"""Tests for flow-review-collect (deterministic Phase-2 collector)."""

# ruff: noqa: INP001

import importlib.util
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

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
    assert doc["counts"] == {"total": 1, "already_replied": 0, "actionable": 1}
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


def test_github_resolved_thread_dropped(fake_gh_api):
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
    assert doc["comments"] == []
    assert doc["counts"]["total"] == 0


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
                    "user": {"login": "coderabbitai[bot]"},
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


def test_is_bot_word_boundary():
    is_bot = flow_review_collect_mod.is_bot
    # Bots: explicit [bot] suffix, coderabbit, and -bot/_bot service accounts.
    assert is_bot("dependabot[bot]") is True
    assert is_bot("github-actions[bot]") is True
    assert is_bot("coderabbitai") is True
    assert is_bot("project_9_bot") is True
    assert is_bot("release-bot") is True
    # Humans whose login merely ends in the letters "bot".
    assert is_bot("abbot") is False
    assert is_bot("talbot") is False
    assert is_bot("alice") is False


def test_gh_resolved_ids_degrades_on_gh_failure(monkeypatch):
    """A non-zero `gh api graphql` (CalledProcessError) must yield set(), not a traceback."""

    def boom(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "gh")

    monkeypatch.setattr(flow_review_collect_mod._git, "run", boom)
    assert flow_review_collect_mod.gh_review_thread_resolved_ids("o/r", 1) == set()


def test_github_resolved_pagination_null_cursor_terminates(fake_gh_api):
    """hasNextPage=true with a null endCursor must NOT loop forever; the thread still drops."""
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
                                "pageInfo": {"hasNextPage": True, "endCursor": None},
                            }
                        }
                    }
                }
            }
        ),
    )
    # Run with a hard timeout so a pagination regression fails loudly instead of hanging the suite.
    r = subprocess.run(
        [sys.executable, str(BIN / "flow-review-collect"), "1", "--platform", "github"],
        env=fake_gh_api.env(),
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    doc = _out(r)
    assert doc["comments"] == []
    assert doc["counts"]["total"] == 0


def test_gitlab_inline_and_general(fake_glab_api):
    fake_glab_api.set("project", "grp/proj")
    fake_glab_api.set("user", "me")
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


def test_gitlab_resolved_thread_dropped(fake_glab_api):
    fake_glab_api.set("project", "g/p")
    fake_glab_api.set("user", "me")
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
    assert doc["comments"] == []


def test_github_bot_summary_from_review_body(fake_gh_api):
    fake_gh_api.set("repo", "o/r")
    fake_gh_api.set("user", "me")
    fake_gh_api.set("pr_view", json.dumps({"number": 1, "headRefName": "b", "url": "u"}))
    fake_gh_api.set("comments", "[]")
    fake_gh_api.set(
        "reviews",
        json.dumps(
            [
                {"id": 55, "user": {"login": "coderabbitai[bot]"}, "body": "Consider adding retry logic."},
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
