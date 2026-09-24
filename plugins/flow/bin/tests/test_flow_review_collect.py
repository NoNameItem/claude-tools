"""Tests for flow-review-collect (deterministic Phase-2 collector)."""

# bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

import importlib.util
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest
from conftest import run_helper

BIN = Path(__file__).parent.parent
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

_HELPER = BIN / "flow-review-collect"
_spec = importlib.util.spec_from_file_location(
    "flow_review_collect_mod", _HELPER, loader=SourceFileLoader("flow_review_collect_mod", str(_HELPER))
)
assert _spec is not None
assert _spec.loader is not None
flow_review_collect_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(flow_review_collect_mod)


def _out(r):
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_github_single_inline_comment(fake_gh_api, monkeypatch):
    fake_gh_api.set("repo", "acme/widgets")
    fake_gh_api.set("user", "me\n")
    fake_gh_api.set(
        "pr_view", json.dumps({"number": 7, "title": "T", "headRefName": "feat/x", "url": "https://gh/pr/7"})
    )
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {
                    "id": 111,
                    "in_reply_to_id": None,
                    "user": {"login": "alice"},
                    "path": "a.py",
                    "line": 42,
                    "start_line": None,
                    "original_line": 42,
                    "original_start_line": None,
                    "body": "Prefer a constant.",
                    "diff_hunk": "@@ -40,3 +40,3 @@\n x\n y\n z",
                },
            ]
        ),
    )
    fake_gh_api.set("reviews", "[]")
    env = fake_gh_api.env()
    r = run_helper("flow-review-collect", "7", "--platform", "github", env=env)
    doc = _out(r)
    assert doc["platform"] == "github"
    assert doc["unit"] == {"number": 7, "branch": "feat/x", "url": "https://gh/pr/7"}
    assert doc["me"] == "me"
    assert doc["counts"] == {"total": 1, "already_replied": 0, "resolved": 0, "actionable": 1}
    c = doc["comments"][0]
    assert c["ref"] == "U1"
    assert c["user"] == "alice"
    assert c["is_bot"] is False
    assert c["path"] == "a.py"
    assert c["line"] == 42
    assert c["comment_id"] == 111
    assert c["discussion_id"] is None
    assert c["diff_hunk"].startswith("@@ -40,3")
    assert c["outdated"] is False
    assert c["already_replied"] is False
    # Resolve side-query succeeded (default fake router returns an empty-but-known set) and
    # this comment id is not in it → a real False, not the "unknown" None.
    assert c["resolved"] is False


def test_github_outdated_uses_original_line(fake_gh_api):
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {
                    "id": 5,
                    "user": {"login": "bob"},
                    "path": "a.py",
                    "line": None,
                    "start_line": None,
                    "original_line": 88,
                    "original_start_line": 80,
                    "body": "x",
                    "diff_hunk": "@@",
                },
            ]
        ),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    c = doc["comments"][0]
    assert c["outdated"] is True
    assert c["line"] == 88  # historical anchor, never bare null
    assert c["start_line"] == 80  # historical anchor, never bare null


def test_github_resolved_thread_present_with_flag(fake_gh_api):
    """A resolved GitHub thread is now REPORTED (not dropped), carrying resolved: true, and
    excluded from `counts["actionable"]` — dropping it made "absent" ambiguous between
    "filtered" and "deleted", which prevented reconcile from telling a settled thread from a
    gone one."""
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {"id": 9, "user": {"login": "bob"}, "path": "a.py", "line": 3, "body": "y", "diff_hunk": "@@"},
            ]
        ),
    )
    fake_gh_api.set(
        "review_threads",
        json.dumps(
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [{"isResolved": True, "comments": {"nodes": [{"fullDatabaseId": "9"}]}}],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            }
                        }
                    }
                }
            }
        ),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    assert len(doc["comments"]) == 1
    c = doc["comments"][0]
    assert c["comment_id"] == 9
    assert c["resolved"] is True
    assert doc["counts"]["total"] == 1
    assert doc["counts"]["resolved"] == 1
    assert doc["counts"]["actionable"] == 0


def test_github_already_replied_and_bot_ref(fake_gh_api):
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {
                    "id": 1,
                    "user": {"login": "coderabbitai[bot]", "type": "Bot"},
                    "path": "a.py",
                    "line": 3,
                    "body": "z",
                    "diff_hunk": "@@",
                },
                {"id": 2, "in_reply_to_id": 1, "user": {"login": "me"}, "body": "done"},
            ]
        ),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    c = doc["comments"][0]
    assert c["ref"] == "C1"
    assert c["is_bot"] is True
    assert c["already_replied"] is True
    assert doc["counts"]["already_replied"] == 1
    assert doc["counts"]["actionable"] == 0


def _gh_minimal(fake_gh_api):
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))


def test_github_is_bot_is_the_account_type_not_the_login(fake_gh_api):
    """`is_bot` gates a destructive call (resolving a thread), so it is the platform's answer —
    `user.type` — never a guess from the login. A person whose login ends in `-bot` is a person;
    an App whose login carries no bot-looking token is still a bot."""
    _gh_minimal(fake_gh_api)
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {"id": 1, "user": {"login": "release-bot", "type": "User"}, "path": "a.py", "line": 3, "body": "h"},
                {"id": 2, "user": {"login": "renovate", "type": "Bot"}, "path": "b.py", "line": 4, "body": "b"},
                {"id": 3, "user": {"login": "coderabbitai[bot]"}, "path": "c.py", "line": 5, "body": "no type"},
            ]
        ),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    by_user = {c["user"]: c for c in doc["comments"]}
    assert by_user["release-bot"]["is_bot"] is False
    assert by_user["release-bot"]["ref"].startswith("U")
    assert by_user["renovate"]["is_bot"] is True
    assert by_user["renovate"]["ref"].startswith("C")
    # No `type` at all → not a bot: the safe direction for the resolve gate.
    assert by_user["coderabbitai[bot]"]["is_bot"] is False


def test_github_thread_replies_and_summaries_take_is_bot_from_the_account_type(fake_gh_api):
    _gh_minimal(fake_gh_api)
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {"id": 1, "user": {"login": "codex[bot]", "type": "Bot"}, "path": "a.py", "line": 3, "body": "z"},
                {"id": 2, "in_reply_to_id": 1, "user": {"login": "ann-bot", "type": "User"}, "body": "hm"},
                {"id": 3, "in_reply_to_id": 1, "user": {"login": "helper", "type": "Bot"}, "body": "ok"},
            ]
        ),
    )
    fake_gh_api.set(
        "reviews",
        json.dumps(
            [
                {"id": 7, "user": {"login": "walker", "type": "Bot"}, "body": "walkthrough", "state": "COMMENTED"},
                {"id": 8, "user": {"login": "x_bot", "type": "User"}, "body": "LGTM", "state": "APPROVED"},
            ]
        ),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    inline = next(c for c in doc["comments"] if c["comment_id"] == 1)
    assert [(r["user"], r["is_bot"]) for r in inline["thread"]] == [("ann-bot", False), ("helper", True)]
    summaries = [c for c in doc["comments"] if c["kind"] == "summary"]
    # The bot walkthrough is a summary item; the human APPROVED body is not actionable — which it
    # would have been had the `x_bot` login made it a "bot".
    assert [(s["user"], s["is_bot"]) for s in summaries] == [("walker", True)]


def gl_graphql_page(discussions, *, has_next=False, cursor=None):
    """One page of the collector's / gate's GitLab GraphQL discussions walk. `discussions` is a
    list of (discussion id, resolved, [(username, bot, system), ...])."""
    nodes = [
        {
            "id": f"gid://gitlab/Discussion/{did}",
            "resolved": resolved,
            "notes": {
                "pageInfo": {"hasNextPage": False},
                "nodes": [{"system": system, "author": {"username": u, "bot": bot}} for u, bot, system in notes],
            },
        }
        for did, resolved, notes in discussions
    ]
    return json.dumps(
        {
            "data": {
                "project": {
                    "mergeRequest": {
                        "discussions": {"nodes": nodes, "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}}
                    }
                }
            }
        }
    )


def _gl_minimal(fake_glab_api, discussions):
    fake_glab_api.set("project", "g/p")
    fake_glab_api.set("user", json.dumps({"username": "me"}))
    fake_glab_api.set("mr_view", json.dumps({"iid": 4, "source_branch": "mb", "web_url": "wu", "state": "opened"}))
    fake_glab_api.set("discussions", json.dumps(discussions))


def _gl_note(did, username, body="n"):
    return {"id": did, "notes": [{"system": False, "author": {"username": username}, "body": body}]}


def test_gitlab_is_bot_comes_from_graphql_not_the_login(fake_glab_api):
    """GitLab REST notes carry no account type, so the collector asks GraphQL (`UserCore.bot`).
    Token bots are named `project_<N>_bot_<hash>` — no `_bot` suffix, so the old heuristic missed
    every one — and `gitlab-bot` on gitlab.com is a regular account the heuristic called a bot."""
    access_bot = "project_278964_bot_89f97e2c57b0b54a"
    _gl_minimal(fake_glab_api, [_gl_note("d1", access_bot), _gl_note("d2", "gitlab-bot"), _gl_note("d3", "carol")])
    fake_glab_api.set(
        "graphql",
        gl_graphql_page([("d1", False, [(access_bot, True, False)]), ("d2", False, [("gitlab-bot", False, False)])]),
    )
    doc = _out(run_helper("flow-review-collect", "4", "--platform", "gitlab", env=fake_glab_api.env()))
    by_user = {c["user"]: c for c in doc["comments"]}
    assert by_user[access_bot]["is_bot"] is True
    assert by_user[access_bot]["ref"] == "C1"
    assert by_user["gitlab-bot"]["is_bot"] is False
    # An author GraphQL never mentioned defaults to not-a-bot.
    assert by_user["carol"]["is_bot"] is False


def test_gitlab_is_bot_map_follows_graphql_pagination(fake_glab_api):
    _gl_minimal(fake_glab_api, [_gl_note("d1", "alpha"), _gl_note("d2", "beta")])
    fake_glab_api.set("graphql", gl_graphql_page([("d1", False, [("alpha", True, False)])], has_next=True, cursor="c1"))
    fake_glab_api.set("graphql_page2", gl_graphql_page([("d2", False, [("beta", True, False)])]))
    doc = _out(run_helper("flow-review-collect", "4", "--platform", "gitlab", env=fake_glab_api.env()))
    assert {c["user"]: c["is_bot"] for c in doc["comments"]} == {"alpha": True, "beta": True}


def test_gitlab_thread_replies_take_is_bot_from_graphql(fake_glab_api):
    disc = {
        "id": "d1",
        "notes": [
            {"system": False, "author": {"username": "rb"}, "body": "root"},
            {"system": False, "author": {"username": "project_9_bot_ab12"}, "body": "bot reply"},
            {"system": False, "author": {"username": "me"}, "body": "our reply"},
        ],
    }
    _gl_minimal(fake_glab_api, [disc])
    fake_glab_api.set(
        "graphql", gl_graphql_page([("d1", False, [("rb", True, False), ("project_9_bot_ab12", True, False)])])
    )
    doc = _out(run_helper("flow-review-collect", "4", "--platform", "gitlab", env=fake_glab_api.env()))
    thread = doc["comments"][0]["thread"]
    assert [(r["user"], r["is_bot"]) for r in thread] == [("project_9_bot_ab12", True), ("me", False)]


def test_gitlab_graphql_failure_degrades_every_author_to_not_a_bot(fake_glab_api):
    """A self-hosted schema that rejects the query, or a transient failure, must not abort the
    round: "not a bot" is the safe direction for the only destructive consumer (nothing gets
    resolved), and the live resolve gate re-checks the account type anyway. It is not silent."""
    _gl_minimal(fake_glab_api, [_gl_note("d1", "project_9_bot_ab12")])
    fake_glab_api.set("graphql_fail", "glab: Field 'bot' doesn't exist on type 'UserCore'\n")
    r = run_helper("flow-review-collect", "4", "--platform", "gitlab", env=fake_glab_api.env())
    doc = _out(r)
    assert doc["comments"][0]["is_bot"] is False
    assert "account type" in r.stderr
    assert "not a bot" in r.stderr


def test_no_login_heuristic_survives():
    """The name-based guess is gone for good — its only callers now read the account type."""
    assert not hasattr(flow_review_collect_mod, "is_bot")


def test_github_multipage_comments_both_pages_included(fake_gh_api):
    """C68 regression: a multi-page `/comments` response.

    Real `gh api --paginate` (no `--slurp`) emits each page as its own back-to-back
    top-level JSON array (`[...][...]`), which makes a bare `json.loads` raise
    `json.JSONDecodeError: Extra data`. The `__pages__` fixture below drives the fake gh
    to reproduce that exact shape. Pre-fix, `gh_collect` crashes (non-zero exit) before
    producing any doc; post-fix (`paginate=True, slurp=True` + flatten) items from BOTH
    pages must show up — in particular the page-2-only comment id.
    """
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    page1 = [
        {"id": 201, "user": {"login": "alice"}, "path": "a.py", "line": 3, "body": "p1 comment", "diff_hunk": "@@"},
    ]
    page2 = [
        {"id": 202, "user": {"login": "bob"}, "path": "b.py", "line": 9, "body": "p2 comment", "diff_hunk": "@@"},
    ]
    fake_gh_api.set("comments", json.dumps({"__pages__": [page1, page2]}))
    fake_gh_api.set("reviews", "[]")
    r = run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env())
    doc = _out(r)
    ids = {c["comment_id"] for c in doc["comments"]}
    assert 201 in ids
    assert 202 in ids  # page-2-only item — dropped/crashed pre-fix


def test_github_multipage_reviews_both_pages_included(fake_gh_api):
    """C68 regression, `/reviews` endpoint: same multi-page shape as the comments test."""
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set("comments", "[]")
    page1 = [{"id": 301, "user": {"login": "coderabbitai[bot]", "type": "Bot"}, "body": "review page 1"}]
    page2 = [{"id": 302, "user": {"login": "coderabbitai[bot]", "type": "Bot"}, "body": "review page 2"}]
    fake_gh_api.set("reviews", json.dumps({"__pages__": [page1, page2]}))
    r = run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env())
    doc = _out(r)
    ids = {c["summary_id"] for c in doc["comments"]}
    assert 301 in ids
    assert 302 in ids  # page-2-only item — dropped/crashed pre-fix


def test_gitlab_inline_and_general(fake_glab_api):
    fake_glab_api.set("project", "grp/proj")
    fake_glab_api.set("user", json.dumps({"username": "me"}))
    fake_glab_api.set("mr_view", json.dumps({"iid": 4, "source_branch": "mb", "web_url": "wu"}))
    fake_glab_api.set(
        "discussions",
        json.dumps(
            [
                {
                    "id": "d1",
                    "notes": [
                        {
                            "system": False,
                            "author": {"username": "carol"},
                            "body": "inline note",
                            "position": {"new_path": "a.py", "new_line": 12, "old_line": None},
                            "resolvable": True,
                            "resolved": False,
                        }
                    ],
                },
                {
                    "id": "d2",
                    "notes": [
                        {
                            "system": False,
                            "author": {"username": "coderabbit"},
                            "body": "walkthrough",
                            "resolvable": False,
                        }
                    ],
                },
                {
                    "id": "d3",
                    "notes": [{"system": True, "author": {"username": "x"}, "body": "changed the description"}],
                },
            ]
        ),
    )
    fake_glab_api.set("graphql", gl_graphql_page([("d2", False, [("coderabbit", True, False)])]))
    r = run_helper("flow-review-collect", "4", "--platform", "gitlab", env=fake_glab_api.env())
    doc = _out(r)
    assert doc["platform"] == "gitlab"
    assert doc["unit"] == {"number": 4, "branch": "mb", "url": "wu"}
    refs = {c["ref"]: c for c in doc["comments"]}
    assert refs["U1"]["path"] == "a.py"
    assert refs["U1"]["line"] == 12
    assert refs["U1"]["discussion_id"] == "d1"
    assert refs["U1"]["comment_id"] is None
    assert refs["C1"]["path"] == "(summary)"
    assert refs["C1"]["is_bot"] is True  # general bot note
    assert all(c["body"] != "changed the description" for c in doc["comments"])  # system dropped


def test_gitlab_resolved_thread_present_with_flag(fake_glab_api):
    """A resolved GitLab discussion is now REPORTED (not dropped), carrying resolved: true, and
    excluded from `counts["actionable"]` — same rationale as the GitHub side, but GitLab ships
    resolution inline with the discussion so the flag is always a real bool, never None."""
    fake_glab_api.set("project", "g/p")
    fake_glab_api.set("user", json.dumps({"username": "me"}))
    fake_glab_api.set("mr_view", json.dumps({"iid": 1, "source_branch": "b", "web_url": "u"}))
    fake_glab_api.set(
        "discussions",
        json.dumps(
            [
                {
                    "id": "d1",
                    "notes": [
                        {
                            "system": False,
                            "author": {"username": "carol"},
                            "body": "n",
                            "position": {"new_path": "a.py", "new_line": 5},
                            "resolvable": True,
                            "resolved": True,
                        }
                    ],
                },
            ]
        ),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "gitlab", env=fake_glab_api.env()))
    assert len(doc["comments"]) == 1
    c = doc["comments"][0]
    assert c["discussion_id"] == "d1"
    assert c["resolved"] is True
    assert doc["counts"]["total"] == 1
    assert doc["counts"]["resolved"] == 1
    assert doc["counts"]["actionable"] == 0


def test_gitlab_outdated_note_anchors_to_old_line(fake_glab_api):
    """An outdated inline note (new_line null, old_line set, no line_range) keeps a historical
    anchor — never a bare null (mirrors the GitHub original_line fallback)."""
    fake_glab_api.set("project", "g/p")
    fake_glab_api.set("user", json.dumps({"username": "me"}))
    fake_glab_api.set("mr_view", json.dumps({"iid": 1, "source_branch": "b", "web_url": "u"}))
    fake_glab_api.set(
        "discussions",
        json.dumps(
            [
                {
                    "id": "d1",
                    "notes": [
                        {
                            "system": False,
                            "author": {"username": "carol"},
                            "body": "was here",
                            "position": {
                                "new_path": "a.py",
                                "old_path": "a.py",
                                "new_line": None,
                                "old_line": 9,
                            },
                            "resolvable": True,
                            "resolved": False,
                        }
                    ],
                },
            ]
        ),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "gitlab", env=fake_glab_api.env()))
    c = doc["comments"][0]
    assert c["outdated"] is True
    assert c["line"] == 9  # historical anchor, never bare null
    assert c["path"] == "a.py"


def test_github_bot_summary_from_review_body(fake_gh_api):
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set("comments", "[]")
    fake_gh_api.set(
        "reviews",
        json.dumps(
            [
                {
                    "id": 55,
                    "user": {"login": "coderabbitai[bot]", "type": "Bot"},
                    "body": "Consider adding retry logic.",
                },
            ]
        ),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    c = doc["comments"][0]
    assert c["ref"] == "C1"
    assert c["path"] == "(summary)"
    assert c["summary_id"] == 55
    assert c["comment_id"] is None
    assert c["diff_hunk"] is None
    assert c["snippet"] is None
    assert "retry" in c["body"]


def test_github_unresolved_inline_comment_resolved_false(fake_gh_api):
    """An unresolved GitHub inline comment carries `resolved: False` — a real bool, not None —
    when the resolve side-query succeeds. Comment id 9 is deliberately absent from the
    resolved-threads response (which resolves a DIFFERENT id, 999) so the False here is a
    genuine "known and not resolved", not a default/degraded value."""
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {"id": 9, "user": {"login": "bob"}, "path": "a.py", "line": 3, "body": "y", "diff_hunk": "@@"},
            ]
        ),
    )
    fake_gh_api.set(
        "review_threads",
        json.dumps(
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [{"isResolved": True, "comments": {"nodes": [{"fullDatabaseId": "999"}]}}],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            }
                        }
                    }
                }
            }
        ),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    c = doc["comments"][0]
    assert c["resolved"] is False
    assert doc["counts"]["resolved"] == 0
    assert doc["counts"]["actionable"] == 1


def test_github_review_body_summary_resolved_is_none(fake_gh_api):
    """A review-body summary item is not a thread, so it has no resolution state at all — it
    must carry `resolved: None` even though the resolve side-query itself succeeded (and even
    resolved an unrelated thread), unlike inline comments which get a real bool in that case."""
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set("comments", "[]")
    fake_gh_api.set(
        "reviews",
        json.dumps(
            [
                {
                    "id": 55,
                    "user": {"login": "coderabbitai[bot]", "type": "Bot"},
                    "body": "Consider adding retry logic.",
                },
            ]
        ),
    )
    fake_gh_api.set(
        "review_threads",
        json.dumps(
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [{"isResolved": True, "comments": {"nodes": [{"fullDatabaseId": "1"}]}}],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            }
                        }
                    }
                }
            }
        ),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    c = doc["comments"][0]
    assert c["resolved"] is None
    assert doc["counts"]["resolved"] == 0
    assert doc["counts"]["actionable"] == 1  # unresolvable → not settled, stays actionable


def test_github_human_changes_requested_summary_included(fake_gh_api):
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set("comments", "[]")
    fake_gh_api.set(
        "reviews",
        json.dumps([{"id": 77, "user": {"login": "alice"}, "state": "CHANGES_REQUESTED", "body": "Please add tests."}]),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    assert len(doc["comments"]) == 1
    c = doc["comments"][0]
    assert c["ref"] == "U1"  # human → U-ref, not C-ref
    assert c["is_bot"] is False
    assert c["path"] == "(summary)"
    assert c["summary_id"] == 77
    assert "add tests" in c["body"]


def test_github_human_commented_summary_included(fake_gh_api):
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set("comments", "[]")
    fake_gh_api.set(
        "reviews",
        json.dumps([{"id": 79, "user": {"login": "carol"}, "state": "COMMENTED", "body": "Consider edge cases."}]),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    assert len(doc["comments"]) == 1
    c = doc["comments"][0]
    assert c["ref"] == "U1"
    assert c["is_bot"] is False
    assert c["summary_id"] == 79


def test_github_human_approved_lgtm_summary_dropped(fake_gh_api):
    # An APPROVED "LGTM" body is noise, not actionable — the state gate must drop it.
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set("comments", "[]")
    fake_gh_api.set(
        "reviews",
        json.dumps([{"id": 78, "user": {"login": "bob"}, "state": "APPROVED", "body": "LGTM"}]),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    assert doc["comments"] == []


m = flow_review_collect_mod


class TestSnippet:
    def test_lang_for_known_and_unknown(self):
        assert m.lang_for("a/b.py") == "python"
        assert m.lang_for("x.unknownext") == ""

    def test_read_window_clamps_top_of_file(self, tmp_path, monkeypatch):
        (tmp_path / "a.py").write_text("l1\nl2\nl3\nl4\nl5\n")
        monkeypatch.chdir(tmp_path)  # snippets read repo-relative paths under cwd
        # comment on line 1: start-4 = -3 → clamp to 1; window [1, 1+4]
        snip = m.build_snippet("a.py", 1, 1)
        assert snip["lang"] == "python"
        assert snip["text"] == "l1\nl2\nl3\nl4\nl5"  # lines 1..5 (end+4 capped at EOF)

    def test_read_window_mid_file(self, tmp_path, monkeypatch):
        (tmp_path / "a.py").write_text("\n".join(f"l{i}" for i in range(1, 21)) + "\n")
        monkeypatch.chdir(tmp_path)
        snip = m.build_snippet("a.py", 10, 10)  # window [6, 14]
        assert snip["text"].splitlines()[0] == "l6"
        assert snip["text"].splitlines()[-1] == "l14"

    def test_missing_file_degrades_to_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert m.build_snippet("nope.py", 3, 3) is None

    def test_symlink_outside_repo_refused(self, tmp_path, monkeypatch):
        """A reviewer-controlled path that is a symlink OUT of the tree must not be read.

        A PR can add `evil.py -> /etc/passwd`; without the guard build_snippet would copy the
        target's contents verbatim into the card/metadata (arbitrary local file read).
        """
        secret = tmp_path / "secret.txt"
        secret.write_text("TOPSECRET\nline2\n")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "evil.py").symlink_to(secret)
        monkeypatch.chdir(repo)
        assert m.build_snippet("evil.py", 1, 1) is None

    def test_parent_traversal_refused(self, tmp_path, monkeypatch):
        """A `..` path that escapes the working tree must not be read."""
        (tmp_path / "outside.py").write_text("secret\n")
        repo = tmp_path / "repo"
        repo.mkdir()
        monkeypatch.chdir(repo)
        assert m.build_snippet("../outside.py", 1, 1) is None

    def test_symlink_loop_degrades_to_none(self, tmp_path, monkeypatch):
        """A symlink loop at the commented path must degrade to None, not abort the run.

        `Path.resolve()` raises RuntimeError (NOT OSError) on a symlink loop such as
        `loop -> loop`. The path is reviewer-controlled, so a single crafted PR file would
        otherwise crash the whole collection — violating the "per-file reads never fail the
        whole run" contract that build_snippet's docstring promises.
        """
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "loop").symlink_to(repo / "loop")  # self-referential symlink → resolution loop
        monkeypatch.chdir(repo)
        assert m.build_snippet("loop", 1, 1) is None

    def test_resolve_runtimeerror_degrades_to_none(self, tmp_path, monkeypatch):
        """Path.resolve() raises RuntimeError (NOT OSError) on a symlink loop under Python
        3.9/3.10; build_snippet must degrade to None there too. The runtime Python may be
        3.11+ (where the loop surfaces later as OSError on read), so simulate the 3.9/3.10
        raise directly — the flow bin/ helpers support 3.9+ (see test_py39_compat).
        """
        (tmp_path / "a.py").write_text("l1\n")

        def boom(self, *args, **kwargs):
            msg = "Symlink loop"
            raise RuntimeError(msg)

        monkeypatch.setattr(Path, "resolve", boom)
        # root passed explicitly so _repo_root() (which also resolves) is bypassed — this
        # isolates the resolve() on the reviewer-controlled target path.
        assert m.build_snippet("a.py", 1, 1, root=tmp_path) is None

    def test_snippet_resolves_from_repo_root_when_run_from_subdir(self, git_repo, monkeypatch):
        # API paths are repo-root-relative; when run from a subdirectory the snippet must
        # still resolve against the repo root, not cwd.
        (git_repo / "pkg").mkdir()
        (git_repo / "pkg" / "mod.py").write_text("\n".join(f"l{i}" for i in range(1, 11)) + "\n")
        sub = git_repo / "sub"
        sub.mkdir()
        monkeypatch.chdir(sub)  # launched from a subdirectory of the repo
        snip = m.build_snippet("pkg/mod.py", 5, 5)
        assert snip is not None
        assert "l5" in snip["text"]

    def test_escape_from_repo_root_refused_from_subdir(self, git_repo, monkeypatch):
        # root is the repo top-level; a path climbing out of the repo is refused even
        # when build_snippet is called from a subdirectory of that repo.
        (git_repo.parent / "secret.txt").write_text("TOPSECRET\n")
        sub = git_repo / "sub"
        sub.mkdir()
        monkeypatch.chdir(sub)
        assert m.build_snippet("../secret.txt", 1, 1) is None


class TestThinHunk:
    def test_thin_hunk_is_thin(self):
        assert m.hunk_is_thin("@@ -1 +1 @@\n line") is True  # 1 body line
        assert m.hunk_is_thin(None) is True
        assert m.hunk_is_thin("") is True

    def test_fat_hunk_is_not_thin(self):
        assert m.hunk_is_thin("@@ -1,5 +1,5 @@\n a\n b\n c\n d\n e") is False


class TestGlLines:
    def test_old_line_range_preserved(self):
        """A multiline comment on removed lines: line_range has only old_line endpoints
        (no new_line). The range must be preserved, not collapsed to a single anchor."""
        position = {
            "line_range": {
                "start": {"old_line": 10, "new_line": None},
                "end": {"old_line": 14, "new_line": None},
            },
            "new_line": None,
            "old_line": None,
        }
        assert m._gl_lines(position) == (10, 14, True)

    def test_new_line_range_preserved(self):
        """Control: a new_line range (comment on current lines) is unaffected."""
        position = {
            "line_range": {
                "start": {"old_line": None, "new_line": 20},
                "end": {"old_line": None, "new_line": 25},
            },
            "new_line": 25,
            "old_line": None,
        }
        assert m._gl_lines(position) == (20, 25, False)


def test_github_thin_hunk_gets_snippet(fake_gh_api, git_repo):
    (git_repo / "a.py").write_text("\n".join(f"l{i}" for i in range(1, 11)) + "\n")
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {
                    "id": 1,
                    "user": {"login": "alice"},
                    "path": "a.py",
                    "line": 5,
                    "body": "x",
                    "diff_hunk": "@@ -5 +5 @@\n l5",  # 1 body line → thin
                },
            ]
        ),
    )
    fake_gh_api.set("reviews", "[]")
    r = run_helper("flow-review-collect", "1", "--platform", "github", cwd=git_repo, env=fake_gh_api.env())
    c = _out(r)["comments"][0]
    assert c["snippet"]["lang"] == "python"
    assert "l5" in c["snippet"]["text"]  # window [1,9]
    assert "l1" in c["snippet"]["text"]


def test_github_fat_hunk_no_snippet(fake_gh_api, git_repo):
    (git_repo / "a.py").write_text("\n".join(f"l{i}" for i in range(1, 11)) + "\n")
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {
                    "id": 1,
                    "user": {"login": "alice"},
                    "path": "a.py",
                    "line": 5,
                    "body": "x",
                    "diff_hunk": "@@ -3,5 +3,5 @@\n l3\n l4\n l5\n l6\n l7",  # 5 lines → fat
                },
            ]
        ),
    )
    fake_gh_api.set("reviews", "[]")
    r = run_helper("flow-review-collect", "1", "--platform", "github", cwd=git_repo, env=fake_gh_api.env())
    assert _out(r)["comments"][0]["snippet"] is None


def test_gitlab_reconstructs_snippet(fake_glab_api, git_repo):
    (git_repo / "a.py").write_text("\n".join(f"l{i}" for i in range(1, 11)) + "\n")
    fake_glab_api.set("project", "g/p")
    fake_glab_api.set("user", json.dumps({"username": "me"}))
    fake_glab_api.set("mr_view", json.dumps({"iid": 1, "source_branch": "b", "web_url": "u"}))
    fake_glab_api.set(
        "discussions",
        json.dumps(
            [
                {
                    "id": "d1",
                    "notes": [
                        {
                            "system": False,
                            "author": {"username": "carol"},
                            "body": "n",
                            "position": {"new_path": "a.py", "new_line": 5},
                            "resolvable": True,
                            "resolved": False,
                        }
                    ],
                },
            ]
        ),
    )
    r = run_helper("flow-review-collect", "1", "--platform", "gitlab", cwd=git_repo, env=fake_glab_api.env())
    c = _out(r)["comments"][0]
    assert c["snippet"]["text"].count("\n") >= 1
    assert "l5" in c["snippet"]["text"]


def test_outdated_gets_no_snippet(fake_gh_api, git_repo):
    (git_repo / "a.py").write_text("l1\nl2\n")
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {
                    "id": 1,
                    "user": {"login": "alice"},
                    "path": "a.py",
                    "line": None,
                    "original_line": 99,
                    "body": "x",
                    "diff_hunk": "@@",
                },
            ]
        ),
    )
    fake_gh_api.set("reviews", "[]")
    r = run_helper("flow-review-collect", "1", "--platform", "github", cwd=git_repo, env=fake_gh_api.env())
    assert _out(r)["comments"][0]["snippet"] is None


def test_github_left_side_no_snippet(fake_gh_api, git_repo):
    """A comment on a deleted line (side=LEFT) must NOT get a current-tree snippet: `line` is
    an old-side line number, so reading the current tree there would show unrelated code. The
    historical diff_hunk stays the anchor instead."""
    (git_repo / "a.py").write_text("\n".join(f"l{i}" for i in range(1, 11)) + "\n")
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {
                    "id": 1,
                    "user": {"login": "alice"},
                    "path": "a.py",
                    "line": 5,
                    "side": "LEFT",
                    "body": "x",
                    "diff_hunk": "@@ -5 +5 @@\n l5",  # thin hunk — would normally get a snippet
                },
            ]
        ),
    )
    fake_gh_api.set("reviews", "[]")
    r = run_helper("flow-review-collect", "1", "--platform", "github", cwd=git_repo, env=fake_gh_api.env())
    c = _out(r)["comments"][0]
    assert c["snippet"] is None  # the actual bug this fix addresses — assert FIRST
    assert c["side"] == "LEFT"  # schema check — second


def test_github_right_side_still_gets_snippet(fake_gh_api, git_repo):
    """Control: a RIGHT-side (current-line) comment with a thin hunk still gets a snippet."""
    (git_repo / "a.py").write_text("\n".join(f"l{i}" for i in range(1, 11)) + "\n")
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {
                    "id": 1,
                    "user": {"login": "alice"},
                    "path": "a.py",
                    "line": 5,
                    "side": "RIGHT",
                    "body": "x",
                    "diff_hunk": "@@ -5 +5 @@\n l5",  # thin hunk
                },
            ]
        ),
    )
    fake_gh_api.set("reviews", "[]")
    r = run_helper("flow-review-collect", "1", "--platform", "github", cwd=git_repo, env=fake_gh_api.env())
    c = _out(r)["comments"][0]
    assert c["snippet"] is not None  # behavioral assertion — FIRST
    assert "l5" in c["snippet"]["text"]
    assert c["side"] == "RIGHT"  # schema check — second


def test_github_mixed_side_start_left_no_snippet(fake_gh_api, git_repo):
    """A mixed multi-line comment (side=RIGHT, start_side=LEFT) starts on a deleted (old-side)
    line, so start_line is an old-side number and a current-tree window would mix coordinate
    systems. Either endpoint on the old side must skip the snippet."""
    (git_repo / "a.py").write_text("\n".join(f"l{i}" for i in range(1, 11)) + "\n")
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {
                    "id": 1,
                    "user": {"login": "alice"},
                    "path": "a.py",
                    "line": 5,
                    "side": "RIGHT",
                    "start_line": 3,
                    "start_side": "LEFT",
                    "body": "x",
                    "diff_hunk": "@@ -3,3 +5 @@\n l5",  # thin hunk — would normally get a snippet
                },
            ]
        ),
    )
    fake_gh_api.set("reviews", "[]")
    r = run_helper("flow-review-collect", "1", "--platform", "github", cwd=git_repo, env=fake_gh_api.env())
    c = _out(r)["comments"][0]
    assert c["snippet"] is None  # behavioral assertion — FIRST
    assert c["side"] == "RIGHT"
    assert c["start_side"] == "LEFT"


def test_github_closed_pr_aborts(fake_gh_api):
    """A closed/merged PR must abort collection, not silently gather stale threads."""
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u", "state": "CLOSED"}))
    r = run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env())
    assert r.returncode != 0
    assert "not open" in r.stderr.lower()


def test_gitlab_merged_mr_aborts(fake_glab_api):
    """A merged MR must abort collection."""
    fake_glab_api.set("project", "g/p")
    fake_glab_api.set("user", json.dumps({"username": "me"}))
    fake_glab_api.set("mr_view", json.dumps({"iid": 1, "source_branch": "b", "web_url": "u", "state": "merged"}))
    r = run_helper("flow-review-collect", "1", "--platform", "gitlab", env=fake_glab_api.env())
    assert r.returncode != 0
    assert "not open" in r.stderr.lower()


def test_gitlab_me_parsed_from_json(fake_glab_api):
    """`glab api user` returns JSON (glab has no `-q` flag); username is parsed in Python."""
    fake_glab_api.set("project", "g/p")
    fake_glab_api.set("user", json.dumps({"username": "alice"}))
    fake_glab_api.set("mr_view", json.dumps({"iid": 1, "source_branch": "b", "web_url": "u", "state": "opened"}))
    fake_glab_api.set("discussions", "[]")
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "gitlab", env=fake_glab_api.env()))
    assert doc["me"] == "alice"


def test_github_thread_replies_carry_id_created_at_and_is_bot(fake_gh_api):
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {
                    "id": 10,
                    "in_reply_to_id": None,
                    "user": {"login": "alice"},
                    "path": "a.py",
                    "line": 3,
                    "start_line": None,
                    "original_line": 3,
                    "original_start_line": None,
                    "body": "root",
                    "diff_hunk": "@@ -1,4 +1,4 @@\n a\n b\n c\n d",
                },
                {
                    "id": 11,
                    "in_reply_to_id": 10,
                    "user": {"login": "coderabbitai[bot]", "type": "Bot"},
                    "body": "reply",
                    "created_at": "2026-07-20T10:00:00Z",
                },
            ]
        ),
    )
    fake_gh_api.set("reviews", "[]")
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    reply = doc["comments"][0]["thread"][0]
    assert reply["user"] == "coderabbitai[bot]"
    assert reply["body"] == "reply"
    assert reply["id"] == 11
    assert reply["created_at"] == "2026-07-20T10:00:00Z"
    assert reply["is_bot"] is True


def test_github_kind_inline_file_and_summary(fake_gh_api):
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {
                    "id": 1,
                    "user": {"login": "alice"},
                    "path": "a.py",
                    "line": 3,
                    "start_line": None,
                    "original_line": 3,
                    "original_start_line": None,
                    "body": "inline",
                    "diff_hunk": "@@ -1,4 +1,4 @@\n a\n b\n c\n d",
                },
                {
                    "id": 2,
                    "user": {"login": "alice"},
                    "path": "b.py",
                    "subject_type": "file",
                    "line": None,
                    "start_line": None,
                    "original_line": None,
                    "original_start_line": None,
                    "body": "file-level",
                    "diff_hunk": None,
                },
            ]
        ),
    )
    fake_gh_api.set(
        "reviews", json.dumps([{"id": 900, "user": {"login": "coderabbitai", "type": "Bot"}, "body": "walkthrough"}])
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    kinds = {c["body"]: c["kind"] for c in doc["comments"]}
    assert kinds == {"inline": "inline", "file-level": "file", "walkthrough": "summary"}


def test_gitlab_kind_and_thread_reply_fields(fake_glab_api):
    fake_glab_api.set("project", "g/p")
    fake_glab_api.set("user", json.dumps({"username": "me"}))
    fake_glab_api.set("mr_view", json.dumps({"iid": 7, "source_branch": "b", "web_url": "u", "state": "opened"}))
    fake_glab_api.set(
        "discussions",
        json.dumps(
            [
                {
                    "id": "d1",
                    "notes": [
                        {
                            "id": 1,
                            "author": {"username": "alice"},
                            "body": "root",
                            "position": {"new_path": "a.py", "new_line": 5},
                        },
                        {
                            "id": 2,
                            "author": {"username": "project_1_bot"},
                            "body": "reply",
                            "created_at": "2026-07-20T10:00:00Z",
                        },
                    ],
                },
                {"id": "d2", "notes": [{"id": 3, "author": {"username": "bob"}, "body": "general"}]},
            ]
        ),
    )
    fake_glab_api.set(
        "graphql", gl_graphql_page([("d1", False, [("alice", False, False), ("project_1_bot", True, False)])])
    )
    doc = _out(run_helper("flow-review-collect", "7", "--platform", "gitlab", env=fake_glab_api.env()))
    by_body = {c["body"]: c for c in doc["comments"]}
    assert by_body["root"]["kind"] == "inline"
    assert by_body["general"]["kind"] == "summary"
    reply = by_body["root"]["thread"][0]
    assert reply["id"] == 2
    assert reply["created_at"] == "2026-07-20T10:00:00Z"
    assert reply["is_bot"] is True


def test_gitlab_kind_file_via_position_type(fake_glab_api):
    """`gl_kind` mirrors `gh_kind`'s file-level detection: a GitLab discussion whose position
    has `position_type: "file"` (and no line endpoints) is `kind: "file"`, not `inline` — this
    is the bug the new helper fixes (previously a bare `"inline" if position else "summary"`
    mislabelled it, sending Phase 3 down the branch that derives a ±20-line window from null
    coordinates). A positioned discussion WITH a real line stays `inline`, and no position at
    all stays `summary` — driven end-to-end through `gl_collect` in the file's existing style."""
    fake_glab_api.set("project", "g/p")
    fake_glab_api.set("user", json.dumps({"username": "me"}))
    fake_glab_api.set("mr_view", json.dumps({"iid": 1, "source_branch": "b", "web_url": "u"}))
    fake_glab_api.set(
        "discussions",
        json.dumps(
            [
                {
                    "id": "d1",
                    "notes": [
                        {
                            "system": False,
                            "author": {"username": "carol"},
                            "body": "file-comment",
                            "position": {
                                "new_path": "a.py",
                                "position_type": "file",
                                "new_line": None,
                                "old_line": None,
                            },
                        }
                    ],
                },
                {
                    "id": "d2",
                    "notes": [
                        {
                            "system": False,
                            "author": {"username": "carol"},
                            "body": "inline-comment",
                            "position": {"new_path": "a.py", "new_line": 5, "old_line": None},
                        }
                    ],
                },
                {
                    "id": "d3",
                    "notes": [{"system": False, "author": {"username": "carol"}, "body": "summary-comment"}],
                },
            ]
        ),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "gitlab", env=fake_glab_api.env()))
    kinds = {c["body"]: c["kind"] for c in doc["comments"]}
    assert kinds == {"file-comment": "file", "inline-comment": "inline", "summary-comment": "summary"}


def test_gitlab_kind_file_via_null_line_endpoints_backup(fake_glab_api):
    """Backup condition in `gl_kind`: a positioned discussion with no `position_type` key at
    all, but both line endpoints (`start_line`, `line`) None, also yields `kind: "file"` — the
    explicit `position_type` check is not the only way a file-level comment can show up."""
    fake_glab_api.set("project", "g/p")
    fake_glab_api.set("user", json.dumps({"username": "me"}))
    fake_glab_api.set("mr_view", json.dumps({"iid": 1, "source_branch": "b", "web_url": "u"}))
    fake_glab_api.set(
        "discussions",
        json.dumps(
            [
                {
                    "id": "d1",
                    "notes": [
                        {
                            "system": False,
                            "author": {"username": "carol"},
                            "body": "no-endpoints",
                            "position": {"new_path": "a.py", "new_line": None, "old_line": None},
                        }
                    ],
                },
            ]
        ),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "gitlab", env=fake_glab_api.env()))
    c = doc["comments"][0]
    assert c["kind"] == "file"


def test_counts_mix_of_resolved_already_replied_and_plain(fake_gh_api):
    """`counts` fixture mixing a resolved item, an already-replied item, and a plain item:
    `total` counts all three, `already_replied`/`resolved` each count exactly their own item,
    and `actionable` is neither — i.e. only the plain one, not `total - already_replied` as it
    used to be (that old formula would have wrongly counted the resolved item as actionable)."""
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {
                    "id": 1,
                    "user": {"login": "alice"},
                    "path": "a.py",
                    "line": 1,
                    "body": "resolved-one",
                    "diff_hunk": "@@",
                },
                {
                    "id": 2,
                    "user": {"login": "bob"},
                    "path": "a.py",
                    "line": 2,
                    "body": "already-replied-one",
                    "diff_hunk": "@@",
                },
                {"id": 3, "in_reply_to_id": 2, "user": {"login": "me"}, "body": "done"},
                {
                    "id": 4,
                    "user": {"login": "carol"},
                    "path": "a.py",
                    "line": 3,
                    "body": "plain-one",
                    "diff_hunk": "@@",
                },
            ]
        ),
    )
    fake_gh_api.set(
        "review_threads",
        json.dumps(
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [{"isResolved": True, "comments": {"nodes": [{"fullDatabaseId": "1"}]}}],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            }
                        }
                    }
                }
            }
        ),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    assert doc["counts"] == {"total": 3, "already_replied": 1, "resolved": 1, "actionable": 1}
    by_body = {c["body"]: c for c in doc["comments"]}
    assert by_body["resolved-one"]["resolved"] is True
    assert by_body["already-replied-one"]["already_replied"] is True
    assert by_body["plain-one"]["resolved"] is False
    assert by_body["plain-one"]["already_replied"] is False


# --- collector aborts instead of degrading (elf.39 task 6) -----------------------------
#
# These monkeypatch `_git.run`/`_git.api_run` directly rather than going through
# `fake_gh_api` (a real subprocess `gh` on PATH): `main()`/`gh_collect()` need to raise a
# Python `_git.ApiUnavailableError`, and a subprocess boundary can't carry that. The router
# below mirrors `_GH_ROUTER` in conftest.py (same endpoint dispatch: pr view / repo view /
# user / comments / reviews / graphql) but as a plain callable, and it forwards any non
# `gh`/`glab` argv (the `git` calls `_repo_root`/`detect_platform` make) to the real
# `_git.run` so those keep working unmocked.
#
# `_patch_gh` is the single install point for every test below: besides `run`/`api_run`, it
# stubs `_git._auth_hosts` to `[]`. `detect_platform(override, remote_host, _auth_hosts("gh"),
# _auth_hosts("glab"))` evaluates BOTH `_auth_hosts` calls eagerly as call arguments even when
# `override` (`--platform`) wins and their result is discarded — and `_auth_hosts` calls
# `subprocess.run(["gh"/"glab", "auth", "status"], ...)` directly, bypassing `_git.run`/
# `_git.api_run` entirely, so neither stub above can intercept it. Left unpatched, every
# `main()`-level test here would spawn a real `gh auth status` / `glab auth status` process.

_REAL_GIT_RUN = flow_review_collect_mod._git.run


def _patch_gh(monkeypatch, _git, *, run=None, api_run=None):
    """Install `run`/`api_run` stand-ins on `_git` and stub `_auth_hosts` to `[]` so
    `detect_platform` never spawns a real `gh`/`glab auth status` subprocess (see block
    comment above)."""
    if run is not None:
        monkeypatch.setattr(_git, "run", run)
    if api_run is not None:
        monkeypatch.setattr(_git, "api_run", api_run)
    monkeypatch.setattr(_git, "_auth_hosts", lambda cli: [])


def _gh_endpoint(argv):
    """Classify a `gh`/`glab` argv the way `_GH_ROUTER` does, but on the argv `_git.run`/
    `_git.api_run` actually receive (program name included, unlike a subprocess's own
    `sys.argv[1:]`)."""
    rest = argv[1:]
    if rest[:2] == ["pr", "view"]:
        return "pr_view"
    if rest[:2] == ["repo", "view"]:
        return "repo_view"
    if rest[:1] == ["api"]:
        tail = rest[1:]
        if "user" in tail:
            return "user"
        i = 0
        while i < len(tail):
            tok = tail[i]
            if tok in ("--paginate", "--slurp"):
                i += 1
                continue
            if tok in ("-q", "-f", "-F"):
                i += 2
                continue
            return tok
        return ""
    return ""


def _graphql_page(resolved_root_ids):
    nodes = [{"isResolved": True, "comments": {"nodes": [{"fullDatabaseId": rid}]}} for rid in resolved_root_ids]
    return json.dumps(
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}
                    }
                }
            }
        }
    )


def github_api_stub(*, resolved_root_ids=None, comments=None, reviews=None, fail_at=None, fail_with=None):
    """In-process stand-in for `_git.run`/`_git.api_run` that drives a full `gh_collect`:
    canned `pr view` / `repo view` / `user`, one inline comment by default, and a resolution
    GraphQL page reporting `resolved_root_ids` as resolved.

    `fail_at` names one endpoint key (`"pr_view"`, `"repo_view"`, `"user"`, `"comments"`,
    `"reviews"`, or `"graphql"`) to raise `fail_with` for instead of answering — every other
    endpoint still answers normally, so a test can pin down exactly which call fails.
    """
    resolved_root_ids = resolved_root_ids or set()
    if comments is None:
        comments = [{"id": 1, "user": {"login": "bob"}, "path": "a.py", "line": 3, "body": "y", "diff_hunk": "@@"}]
    if reviews is None:
        reviews = []
    # `gh_collect` always passes `slurp=True`, which wraps every page into one outer array
    # (`--slurp`'s contract) — a single-page fixture is `[comments]`, not `comments`.
    responses = {
        "pr_view": json.dumps({"number": 118, "headRefName": "b", "url": "u", "state": "OPEN"}),
        "repo_view": "o/r",
        "user": "me",
        "comments": json.dumps([comments]),
        "reviews": json.dumps([reviews]),
        "graphql": _graphql_page(resolved_root_ids),
    }

    def _fake(argv, **kwargs):
        if not argv or argv[0] not in ("gh", "glab"):
            return _REAL_GIT_RUN(argv, **kwargs)
        ep = _gh_endpoint(argv)
        key = next((k for k in ("comments", "reviews") if ep.endswith(f"/{k}")), ep)
        if fail_at is not None and key == fail_at:
            raise fail_with
        return responses.get(key, "{}")

    return _fake


def paginating_api_with_null_cursor():
    """Stand-in for `_git.api_run` that answers the resolution GraphQL query with a page
    carrying `hasNextPage: true` and a null `endCursor` — a page the caller cannot follow."""

    def _fake(argv, **kwargs):
        return json.dumps(
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [],
                                "pageInfo": {"hasNextPage": True, "endCursor": None},
                            }
                        }
                    }
                }
            }
        )

    return _fake


def test_it_exits_4_when_the_resolution_query_cannot_be_answered(monkeypatch, capsys):
    """Degrading used to mean "resolution unknown", which forced a three-valued flag through the
    whole ledger and let one GraphQL hiccup reopen every settled thread. Aborting keeps the model
    two-valued; the round simply did not happen, so no row changed.

    `pr view` / `repo view` / `user` / `comments` / `reviews` all answer normally — only the
    resolution GraphQL call fails — so this pins the failure to the resolution query
    specifically, not to "some API call, any API call"."""
    _git = flow_review_collect_mod._git
    stub = github_api_stub(fail_at="graphql", fail_with=_git.ApiUnavailableError("boom", permanent=False))
    _patch_gh(monkeypatch, _git, run=stub, api_run=stub)
    assert flow_review_collect_mod.main(["118", "--platform", "github"]) == 4
    assert "try again" in capsys.readouterr().err.lower()


def test_it_exits_4_and_names_the_cause_when_the_resolution_query_failure_is_permanent(monkeypatch, capsys):
    """Same shape as above, but the resolution query fails permanently (bad auth / unsupported
    schema field) — `main` must name the cause instead of suggesting a retry."""
    _git = flow_review_collect_mod._git
    stub = github_api_stub(fail_at="graphql", fail_with=_git.ApiUnavailableError("401 Bad credentials", permanent=True))
    _patch_gh(monkeypatch, _git, run=stub, api_run=stub)
    assert flow_review_collect_mod.main(["118", "--platform", "github"]) == 4
    err = capsys.readouterr().err
    assert "401" in err
    assert "authenticated" in err.lower() or "unsupported" in err.lower()


def test_a_partial_resolution_page_aborts_instead_of_reporting_unknown(monkeypatch):
    """`hasNextPage: true` with a null `endCursor` cannot be followed. The pages already read are
    a PARTIAL answer, and a partial answer is indistinguishable from "those threads are not
    resolved" — which would reopen settled rows."""
    _git = flow_review_collect_mod._git
    _patch_gh(monkeypatch, _git, api_run=paginating_api_with_null_cursor())
    with pytest.raises(_git.ApiUnavailableError):
        flow_review_collect_mod.gh_review_threads("o/r", 118)


def test_resolved_is_always_a_bool_for_a_threaded_item(monkeypatch):
    _git = flow_review_collect_mod._git
    stub = github_api_stub(resolved_root_ids={"1"})
    _patch_gh(monkeypatch, _git, run=stub, api_run=stub)
    payload = flow_review_collect_mod.gh_collect("118")
    inline = [c for c in payload["comments"] if c["comment_id"] is not None]
    assert inline, "the stub must produce at least one inline comment"
    assert all(isinstance(c["resolved"], bool) for c in inline)


# --- unit-resolution reads go through the retry wrapper, not bare `_git.run` (whole-branch
# review, Important 2) -----------------------------------------------------------------------
#
# `gh pr view` / `glab mr view` / `gh repo view` / `glab repo view` are the FIRST network calls
# of every round. Before this fix they called `_git.run` directly: a real CLI failure raised a
# bare `subprocess.CalledProcessError`/`TimeoutExpired`, which is neither retried (no
# `_git.api_run` in the chain) nor caught by `main`'s `except _git.ApiUnavailableError` — so a
# transient 502 crashed with a raw traceback and exit 1 instead of the documented exit-4
# message. These tests patch only `_git.run` (leaving the real `_git.api_run` in place) so the
# retry/convert logic actually runs, and assert each of the four call sites now raises
# `_git.ApiUnavailableError` instead of the raw subprocess exception.


def _permanent_failure(argv, **kwargs):
    """Stand-in for `_git.run` that always fails with a permanent-signature stderr (401), so
    `_git.api_run` (left real) raises immediately with no retry sleep — keeps the test fast."""
    raise subprocess.CalledProcessError(1, argv, stderr="401 Bad credentials")


def test_gh_resolve_unit_routes_pr_view_through_the_retry_wrapper(monkeypatch):
    _git = flow_review_collect_mod._git
    monkeypatch.setattr(_git, "run", _permanent_failure)
    with pytest.raises(_git.ApiUnavailableError):
        flow_review_collect_mod.gh_resolve_unit("118")


def test_gl_resolve_unit_routes_mr_view_through_the_retry_wrapper(monkeypatch):
    _git = flow_review_collect_mod._git
    monkeypatch.setattr(_git, "run", _permanent_failure)
    with pytest.raises(_git.ApiUnavailableError):
        flow_review_collect_mod.gl_resolve_unit("4")


def test_resolve_repo_routes_gh_repo_view_through_the_retry_wrapper(monkeypatch):
    _git = flow_review_collect_mod._git
    monkeypatch.setattr(_git, "run", _permanent_failure)
    with pytest.raises(_git.ApiUnavailableError):
        flow_review_collect_mod._resolve_repo()


def test_resolve_project_routes_glab_repo_view_through_the_retry_wrapper(monkeypatch):
    _git = flow_review_collect_mod._git
    monkeypatch.setattr(_git, "run", _permanent_failure)
    with pytest.raises(_git.ApiUnavailableError):
        flow_review_collect_mod._resolve_project()


def test_pr_view_failure_exits_4_end_to_end_instead_of_crashing(monkeypatch, capsys):
    """End-to-end through `main`: before this fix, a real `gh pr view` failure was an unhandled
    `subprocess.CalledProcessError` — this pins the documented exit-4 behavior for the FIRST
    network call of a round, not just the resolution GraphQL query the pre-existing tests
    above cover."""
    _git = flow_review_collect_mod._git
    monkeypatch.setattr(_git, "run", _permanent_failure)
    monkeypatch.setattr(_git, "_auth_hosts", lambda cli: [])
    assert flow_review_collect_mod.main(["118", "--platform", "github"]) == 4
    err = capsys.readouterr().err
    assert "401" in err
    assert "authenticated" in err.lower() or "unsupported" in err.lower()


def test_mr_view_failure_exits_4_end_to_end_instead_of_crashing(monkeypatch, capsys):
    _git = flow_review_collect_mod._git
    monkeypatch.setattr(_git, "run", _permanent_failure)
    monkeypatch.setattr(_git, "_auth_hosts", lambda cli: [])
    assert flow_review_collect_mod.main(["4", "--platform", "gitlab"]) == 4
    err = capsys.readouterr().err
    assert "401" in err


def _threads_page(nodes):
    """One `reviewThreads` GraphQL page, already wrapped in its data envelope."""
    return json.dumps(
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}
                    }
                }
            }
        }
    )


def _gh_inline_fixture(fake_gh_api, threads_nodes):
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set(
        "comments",
        json.dumps(
            [
                {
                    "id": 9,
                    "in_reply_to_id": None,
                    "user": {"login": "codex[bot]", "type": "Bot"},
                    "path": "a.py",
                    "line": 42,
                    "start_line": None,
                    "original_line": 42,
                    "original_start_line": None,
                    "body": "finding",
                    "diff_hunk": "@@ -40,4 +40,4 @@\n w\n x\n y\n z",
                }
            ]
        ),
    )
    fake_gh_api.set("reviews", "[]")
    fake_gh_api.set("review_threads", _threads_page(threads_nodes))


def test_github_inline_comment_carries_the_thread_node_id(fake_gh_api):
    """`resolve_id` is the GraphQL node id — the only value `resolveReviewThread` accepts. It is
    NOT `comment_id` (the reply target), and the two must stay distinguishable."""
    _gh_inline_fixture(
        fake_gh_api,
        [{"id": "PRRT_kwABC", "isResolved": False, "comments": {"nodes": [{"fullDatabaseId": "9"}]}}],
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    c = doc["comments"][0]
    assert c["comment_id"] == 9
    assert c["resolve_id"] == "PRRT_kwABC"
    assert c["resolved"] is False


def test_github_resolved_state_and_node_id_come_from_one_walk(fake_gh_api):
    """The resolution flag and the resolve target are two answers from the same query — a
    resolved thread must report both, or one of the two walks would have to be added back."""
    _gh_inline_fixture(
        fake_gh_api,
        [{"id": "PRRT_kwABC", "isResolved": True, "comments": {"nodes": [{"fullDatabaseId": "9"}]}}],
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    c = doc["comments"][0]
    assert c["resolved"] is True
    assert c["resolve_id"] == "PRRT_kwABC"


def test_github_thread_without_a_node_id_degrades_to_null(fake_gh_api):
    """A malformed node costs that one thread its resolve target, never the whole run."""
    _gh_inline_fixture(
        fake_gh_api,
        [{"isResolved": False, "comments": {"nodes": [{"fullDatabaseId": "9"}]}}],
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    assert doc["comments"][0]["resolve_id"] is None


def test_github_review_body_summary_has_no_resolve_target(fake_gh_api):
    """A review body is not a thread: nothing to resolve, so the field is null by construction."""
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set("comments", "[]")
    fake_gh_api.set(
        "reviews",
        json.dumps(
            [{"id": 500, "user": {"login": "codex[bot]", "type": "Bot"}, "body": "### Review", "state": "COMMENTED"}]
        ),
    )
    doc = _out(run_helper("flow-review-collect", "1", "--platform", "github", env=fake_gh_api.env()))
    c = doc["comments"][0]
    assert c["kind"] == "summary"
    assert c["resolve_id"] is None


def test_gitlab_discussion_resolves_by_its_discussion_id(fake_glab_api):
    """GitLab's PUT key is the discussion id, so `resolve_id` mirrors `discussion_id` — one
    field the skill can read on either platform without branching."""
    fake_glab_api.set("project", "g/r")
    fake_glab_api.set("user", json.dumps({"username": "me"}))
    fake_glab_api.set("mr_view", json.dumps({"iid": 3, "source_branch": "b", "web_url": "u", "state": "opened"}))
    fake_glab_api.set(
        "discussions",
        json.dumps(
            [
                {
                    "id": "abc123",
                    "notes": [
                        {
                            "id": 1,
                            "system": False,
                            "author": {"username": "codex_bot"},
                            "body": "finding",
                            "resolvable": True,
                            "resolved": False,
                            "position": {"new_path": "a.py", "new_line": 5, "position_type": "text"},
                        }
                    ],
                }
            ]
        ),
    )
    doc = _out(run_helper("flow-review-collect", "3", "--platform", "gitlab", env=fake_glab_api.env()))
    c = doc["comments"][0]
    assert c["discussion_id"] == "abc123"
    assert c["resolve_id"] == "abc123"


def test_gitlab_non_resolvable_discussion_has_no_resolve_target(fake_glab_api):
    """A GitLab general MR note (an individual note, `resolvable: false` — exactly the shape a
    review bot's summary takes on GitLab) has no resolvable note, so there is nothing
    `PUT .../discussions/{id}` can resolve. `resolve_id` must degrade to null while
    `discussion_id` — the reply target — still carries the discussion id."""
    fake_glab_api.set("project", "g/r")
    fake_glab_api.set("user", json.dumps({"username": "me"}))
    fake_glab_api.set("mr_view", json.dumps({"iid": 3, "source_branch": "b", "web_url": "u", "state": "opened"}))
    fake_glab_api.set(
        "discussions",
        json.dumps(
            [
                {
                    "id": "d9",
                    "notes": [
                        {
                            "id": 1,
                            "system": False,
                            "author": {"username": "codex_bot"},
                            "body": "walkthrough",
                            "resolvable": False,
                        }
                    ],
                }
            ]
        ),
    )
    doc = _out(run_helper("flow-review-collect", "3", "--platform", "gitlab", env=fake_glab_api.env()))
    c = doc["comments"][0]
    assert c["discussion_id"] == "d9"
    assert c["resolve_id"] is None
