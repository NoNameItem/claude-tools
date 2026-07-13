"""Tests for flow-review-collect (deterministic Phase-2 collector)."""

# ruff: noqa: INP001  # bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

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
    assert doc["comments"] == []


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
    assert c["side"] == "LEFT"
    assert c["snippet"] is None


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
    assert c["side"] == "RIGHT"
    assert c["snippet"] is not None
    assert "l5" in c["snippet"]["text"]


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
