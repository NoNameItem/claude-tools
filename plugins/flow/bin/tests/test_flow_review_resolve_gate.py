"""Tests for flow-review-resolve-gate (the live check right before Phase 5.7 resolves a thread).

Exit 0 = resolve, 3 = the live thread forbids it, 4 = it could not be verified. Every path that is
not a positive, complete answer must refuse — the call it guards closes someone's finding.
"""

# bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

import json

from conftest import run_helper

THREAD_ID = "PRRT_kwDOabc"


def _meta(tmp_path, platform, *, me="me", number=7):
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps({"platform": platform, "unit": {"number": number, "branch": "b", "url": "u"}, "me": me}))
    return path


def _verdict(r):
    return json.loads(r.stdout)


# ---- GitHub ------------------------------------------------------------------


def gh_node(authors, *, resolved=False, has_next=False, typename="PullRequestReviewThread"):
    """A `node(id:)` answer. `authors` is a list of (login, __typename) — or None for a deleted
    account, which GitHub reports as a null author."""
    nodes = [{"author": None if a is None else {"login": a[0], "__typename": a[1]}} for a in authors]
    return json.dumps(
        {
            "data": {
                "node": {
                    "__typename": typename,
                    "isResolved": resolved,
                    "comments": {"pageInfo": {"hasNextPage": has_next}, "nodes": nodes},
                }
            }
        }
    )


def _gh_gate(fake_gh_api, tmp_path, node_json, *, me="me"):
    fake_gh_api.set("thread_node", node_json)
    meta = _meta(tmp_path, "github", me=me)
    return run_helper("flow-review-resolve-gate", "--meta", str(meta), "--resolve-id", THREAD_ID, env=fake_gh_api.env())


def test_github_bot_thread_with_only_our_reply_resolves(fake_gh_api, tmp_path):
    r = _gh_gate(fake_gh_api, tmp_path, gh_node([("chatgpt-codex-connector", "Bot"), ("me", "User")]))
    assert r.returncode == 0, r.stderr
    assert _verdict(r)["resolve"] is True


def test_github_another_bot_answering_does_not_block(fake_gh_api, tmp_path):
    """A conversational bot (CodeRabbit) answering our reply is still a bot thread."""
    r = _gh_gate(fake_gh_api, tmp_path, gh_node([("coderabbitai", "Bot"), ("me", "User"), ("coderabbitai", "Bot")]))
    assert r.returncode == 0, r.stderr


def test_github_human_reply_after_the_snapshot_blocks(fake_gh_api, tmp_path):
    """The Codex finding itself: a person replied while cards were triaged. The live read sees
    it; the Phase-2 snapshot did not."""
    r = _gh_gate(fake_gh_api, tmp_path, gh_node([("codex", "Bot"), ("me", "User"), ("alice", "User")]))
    assert r.returncode == 3
    v = _verdict(r)
    assert v["resolve"] is False
    assert "alice" in v["reason"]


def test_github_human_whose_login_looks_like_a_bot_blocks(fake_gh_api, tmp_path):
    r = _gh_gate(fake_gh_api, tmp_path, gh_node([("codex", "Bot"), ("release-bot", "User")]))
    assert r.returncode == 3


def test_github_human_opener_blocks(fake_gh_api, tmp_path):
    r = _gh_gate(fake_gh_api, tmp_path, gh_node([("renovate-bot", "User"), ("me", "User")]))
    assert r.returncode == 3


def test_github_thread_we_opened_ourselves_is_not_a_bot_thread(fake_gh_api, tmp_path):
    r = _gh_gate(fake_gh_api, tmp_path, gh_node([("me", "User")]))
    assert r.returncode == 3


def test_github_deleted_author_counts_as_a_human(fake_gh_api, tmp_path):
    r = _gh_gate(fake_gh_api, tmp_path, gh_node([("codex", "Bot"), None]))
    assert r.returncode == 3
    r = _gh_gate(fake_gh_api, tmp_path, gh_node([None, ("me", "User")]))
    assert r.returncode == 3


def test_github_already_resolved_thread_is_left_alone(fake_gh_api, tmp_path):
    r = _gh_gate(fake_gh_api, tmp_path, gh_node([("codex", "Bot"), ("me", "User")], resolved=True))
    assert r.returncode == 3
    assert "resolved" in _verdict(r)["reason"]


def test_github_a_thread_longer_than_one_page_is_never_judged(fake_gh_api, tmp_path):
    r = _gh_gate(fake_gh_api, tmp_path, gh_node([("codex", "Bot"), ("me", "User")], has_next=True))
    assert r.returncode == 4
    assert _verdict(r)["resolve"] is False


def test_github_missing_node_cannot_be_verified(fake_gh_api, tmp_path):
    r = _gh_gate(fake_gh_api, tmp_path, json.dumps({"data": {"node": None}}))
    assert r.returncode == 4
    r = _gh_gate(fake_gh_api, tmp_path, gh_node([("codex", "Bot")], typename="IssueComment"))
    assert r.returncode == 4


def test_github_api_failure_refuses_and_says_why(fake_gh_api, tmp_path):
    fake_gh_api.set("thread_node_fail", "gh: HTTP 401: Bad credentials\n")
    r = _gh_gate(fake_gh_api, tmp_path, gh_node([("codex", "Bot"), ("me", "User")]))
    assert r.returncode == 4
    assert _verdict(r)["resolve"] is False
    assert r.stderr.strip()


def test_unreadable_metadata_refuses(fake_gh_api, tmp_path):
    r = run_helper(
        "flow-review-resolve-gate",
        "--meta",
        str(tmp_path / "missing.json"),
        "--resolve-id",
        THREAD_ID,
        env=fake_gh_api.env(),
    )
    assert r.returncode == 4
    assert _verdict(r)["resolve"] is False


# ---- GitLab ------------------------------------------------------------------

DISC = "6a9c1750b37d"


def gl_page(discussions, *, has_next=False, cursor=None):
    """One discussions page. `discussions` is a list of (id, resolved, notes, notes_has_next),
    each note a (username, bot, system) — or None for a deleted author."""
    nodes = []
    for did, resolved, notes, notes_has_next in discussions:
        rendered = []
        for n in notes:
            if n[0] is None:
                rendered.append({"system": n[2], "author": None})
            else:
                rendered.append({"system": n[2], "author": {"username": n[0], "bot": n[1]}})
        nodes.append(
            {
                "id": f"gid://gitlab/Discussion/{did}",
                "resolved": resolved,
                "notes": {"pageInfo": {"hasNextPage": notes_has_next}, "nodes": rendered},
            }
        )
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


def _gl_gate(fake_glab_api, tmp_path, page, *, page2=None, resolve_id=DISC):
    fake_glab_api.set("project", "grp/sub/proj")
    fake_glab_api.set("graphql", page)
    if page2 is not None:
        fake_glab_api.set("graphql_page2", page2)
    meta = _meta(tmp_path, "gitlab")
    return run_helper(
        "flow-review-resolve-gate", "--meta", str(meta), "--resolve-id", resolve_id, env=fake_glab_api.env()
    )


BOT_ROOT = ("project_278964_bot_89f97e2c", True, False)
OUR_REPLY = ("me", False, False)


def test_gitlab_bot_discussion_with_only_our_reply_resolves(fake_glab_api, tmp_path):
    r = _gl_gate(fake_glab_api, tmp_path, gl_page([(DISC, False, [BOT_ROOT, OUR_REPLY], False)]))
    assert r.returncode == 0, r.stderr
    assert _verdict(r)["resolve"] is True


def test_gitlab_human_reply_blocks(fake_glab_api, tmp_path):
    r = _gl_gate(
        fake_glab_api, tmp_path, gl_page([(DISC, False, [BOT_ROOT, OUR_REPLY, ("carol", False, False)], False)])
    )
    assert r.returncode == 3
    assert "carol" in _verdict(r)["reason"]


def test_gitlab_regular_account_named_like_a_bot_is_a_human(fake_glab_api, tmp_path):
    """`gitlab-bot` on gitlab.com is a regular account (`bot: false`)."""
    r = _gl_gate(fake_glab_api, tmp_path, gl_page([(DISC, False, [("gitlab-bot", False, False), OUR_REPLY], False)]))
    assert r.returncode == 3


def test_gitlab_system_notes_are_not_anyone_speaking(fake_glab_api, tmp_path):
    notes = [BOT_ROOT, ("carol", False, True), OUR_REPLY]
    r = _gl_gate(fake_glab_api, tmp_path, gl_page([(DISC, False, notes, False)]))
    assert r.returncode == 0, r.stderr


def test_gitlab_deleted_author_counts_as_a_human(fake_glab_api, tmp_path):
    r = _gl_gate(fake_glab_api, tmp_path, gl_page([(DISC, False, [BOT_ROOT, (None, False, False)], False)]))
    assert r.returncode == 3


def test_gitlab_already_resolved_discussion_is_left_alone(fake_glab_api, tmp_path):
    r = _gl_gate(fake_glab_api, tmp_path, gl_page([(DISC, True, [BOT_ROOT, OUR_REPLY], False)]))
    assert r.returncode == 3


def test_gitlab_finds_the_discussion_on_a_later_page(fake_glab_api, tmp_path):
    first = gl_page([("other", False, [("carol", False, False)], False)], has_next=True, cursor="c1")
    second = gl_page([(DISC, False, [BOT_ROOT, OUR_REPLY], False)])
    r = _gl_gate(fake_glab_api, tmp_path, first, page2=second)
    assert r.returncode == 0, r.stderr


def test_gitlab_discussion_not_found_cannot_be_verified(fake_glab_api, tmp_path):
    r = _gl_gate(fake_glab_api, tmp_path, gl_page([("other", False, [BOT_ROOT], False)]))
    assert r.returncode == 4


def test_gitlab_a_discussion_longer_than_one_page_is_never_judged(fake_glab_api, tmp_path):
    r = _gl_gate(fake_glab_api, tmp_path, gl_page([(DISC, False, [BOT_ROOT, OUR_REPLY], True)]))
    assert r.returncode == 4


def test_gitlab_graphql_failure_refuses(fake_glab_api, tmp_path):
    fake_glab_api.set("graphql_fail", "glab: Field 'bot' doesn't exist on type 'UserCore'\n")
    r = _gl_gate(fake_glab_api, tmp_path, gl_page([(DISC, False, [BOT_ROOT, OUR_REPLY], False)]))
    assert r.returncode == 4
    assert _verdict(r)["resolve"] is False
    assert r.stderr.strip()
