"""Tests for flow-comment-card."""

# ruff: noqa: INP001  # INP001: bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

import importlib.util
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

BIN = Path(__file__).parent.parent
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

# Import the extension-less executable as a module (mirrors test_flow_task_card.py)
_HELPER = Path(__file__).parent.parent / "flow-comment-card"
_spec = importlib.util.spec_from_file_location(
    "flow_comment_card", _HELPER, loader=SourceFileLoader("flow_comment_card", str(_HELPER))
)
assert _spec is not None
assert _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

category_emoji = _mod.category_emoji
format_lines = _mod.format_lines
format_location = _mod.format_location
render_header = _mod.render_header
render_comment = _mod.render_comment
render_code = _mod.render_code
render_take = _mod.render_take
render_card = _mod.render_card
_fence = _mod._fence


def _run(stdin: str):
    return subprocess.run(
        [sys.executable, str(_HELPER)],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


class TestCategoryEmoji:
    def test_correctness_security_logic_are_red(self):
        assert category_emoji("correctness") == "🔴"
        assert category_emoji("security") == "🔴"
        assert category_emoji("logic") == "🔴"

    def test_style_nitpick_are_yellow(self):
        assert category_emoji("style") == "🟡"
        assert category_emoji("nitpick") == "🟡"

    def test_doc_is_blue(self):
        assert category_emoji("doc") == "🔵"

    def test_unknown_and_none_fall_back_to_white(self):
        assert category_emoji("wat") == "⚪"
        assert category_emoji(None) == "⚪"
        assert category_emoji("") == "⚪"


class TestFormatLines:
    def test_range(self):
        assert format_lines(10, 12) == "10-12"

    def test_single_line(self):
        assert format_lines(None, 42) == "42"

    def test_same_start_and_line_collapses_to_single(self):
        assert format_lines(42, 42) == "42"

    def test_only_start_line(self):
        assert format_lines(7, None) == "7"

    def test_no_position(self):
        assert format_lines(None, None) is None


class TestFormatLocation:
    def test_path_with_single_line(self):
        assert format_location({"path": "a/b.py", "line": 42}) == "a/b.py:42"

    def test_path_with_range(self):
        assert format_location({"path": "a/b.py", "start_line": 10, "line": 12}) == "a/b.py:10-12"

    def test_path_without_line(self):
        assert format_location({"path": "a/b.py"}) == "a/b.py"

    def test_no_path_is_summary(self):
        assert format_location({}) == "(summary)"


class TestRenderHeader:
    def test_inline_single_line(self):
        card = {"ref": "C1", "category": "correctness", "path": "a/b.py", "line": 42}
        assert render_header(card) == "### 🔴 C1 · correctness · a/b.py:42"

    def test_range(self):
        card = {"ref": "C2", "category": "style", "path": "a/b.py", "start_line": 10, "line": 12}
        assert render_header(card) == "### 🟡 C2 · style · a/b.py:10-12"

    def test_outdated_marker(self):
        card = {"ref": "C3", "category": "logic", "path": "a/b.py", "line": 5, "outdated": True}
        assert render_header(card) == "### 🔴 C3 · logic · a/b.py:5 ⚠️ outdated"

    def test_summary_no_position(self):
        card = {"ref": "C4", "category": "doc"}
        assert render_header(card) == "### 🔵 C4 · doc · (summary)"

    def test_unknown_category_uses_fallback_emoji_and_none_label(self):
        card = {"ref": "C5", "path": "a/b.py", "line": 1}
        assert render_header(card) == "### ⚪ C5 · none · a/b.py:1"


class TestRenderComment:
    def test_single_body_no_thread(self):
        card = {"author": "alice", "body": "Prefer a constant here."}
        assert render_comment(card) == "> **@alice:** Prefer a constant here."

    def test_body_with_one_reply(self):
        card = {
            "author": "coderabbitai",
            "body": "This crashes on detached HEAD.",
            "thread": [{"user": "you", "body": "already handled?"}],
        }
        assert render_comment(card) == (
            "> **@coderabbitai:** This crashes on detached HEAD.\n> ↳ **@you:** already handled?"
        )

    def test_multiple_replies(self):
        card = {
            "author": "bob",
            "body": "See below.",
            "thread": [
                {"user": "you", "body": "why?"},
                {"user": "bob", "body": "perf."},
            ],
        }
        assert render_comment(card) == ("> **@bob:** See below.\n> ↳ **@you:** why?\n> ↳ **@bob:** perf.")

    def test_multiline_body_each_line_quoted(self):
        card = {"author": "alice", "body": "line one\nline two"}
        assert render_comment(card) == "> **@alice:** line one\n> line two"


class TestRenderCode:
    def test_diff_hunk_is_preferred(self):
        card = {
            "diff_hunk": "@@ -40,7 +40,7 @@\n-    old\n+    new",
            "snippet": {"lang": "python", "text": "ignored"},
        }
        assert render_code(card) == "```diff\n@@ -40,7 +40,7 @@\n-    old\n+    new\n```"

    def test_snippet_when_no_diff_hunk(self):
        card = {"snippet": {"lang": "python", "text": "def f():\n    return 1"}}
        assert render_code(card) == "```python\ndef f():\n    return 1\n```"

    def test_snippet_without_lang(self):
        card = {"snippet": {"text": "plain text"}}
        assert render_code(card) == "```\nplain text\n```"

    def test_no_code_returns_empty_string(self):
        assert render_code({}) == ""
        assert render_code({"diff_hunk": None, "snippet": None}) == ""
        assert render_code({"snippet": {"text": ""}}) == ""

    def test_diff_hunk_with_triple_backtick_widens_fence(self):
        # A bare ``` inside the diff_hunk must not be able to close a 3-backtick
        # fence early; the fence should widen to 4 backticks and the inner ```
        # must survive untouched.
        card = {"diff_hunk": "@@ -1,3 +1,3 @@\n-old\n+```\n+new"}
        result = render_code(card)
        assert result == "````diff\n@@ -1,3 +1,3 @@\n-old\n+```\n+new\n````"

    def test_snippet_with_triple_backtick_widens_fence(self):
        card = {"snippet": {"lang": "markdown", "text": "Some code:\n```\nnested\n```"}}
        result = render_code(card)
        assert result == "````markdown\nSome code:\n```\nnested\n```\n````"

    def test_content_with_four_backtick_run_widens_fence_to_five(self):
        card = {"snippet": {"text": "````"}}
        result = render_code(card)
        assert result == "`````\n````\n`````"


class TestFence:
    def test_no_backticks_returns_three(self):
        assert _fence("") == "```"
        assert _fence("no backticks here") == "```"

    def test_one_triple_backtick_run_returns_four(self):
        assert _fence("```") == "````"
        assert _fence("text\n```\nmore") == "````"

    def test_four_backtick_run_returns_five(self):
        assert _fence("````") == "`````"


class TestRenderTake:
    def test_both_lines(self):
        card = {"thought": "Real crash on detached HEAD.", "suggested": "fix"}
        assert render_take(card) == ("**Thought:** Real crash on detached HEAD.\n**Suggested:** fix")

    def test_thought_only(self):
        assert render_take({"thought": "Informational."}) == "**Thought:** Informational."

    def test_suggested_only(self):
        assert render_take({"suggested": "won't-fix"}) == "**Suggested:** won't-fix"

    def test_neither(self):
        assert render_take({}) == ""


class TestRenderCard:
    def test_full_card_with_diff(self):
        card = {
            "ref": "C1",
            "author": "coderabbitai",
            "body": "This crashes on detached HEAD.",
            "thread": [{"user": "you", "body": "already handled?"}],
            "path": "packages/statuskit/src/git.py",
            "line": 42,
            "category": "correctness",
            "diff_hunk": (
                "@@ -40,7 +40,7 @@\n-    return repo.head.name\n+    return repo.head.name if repo.head else None"
            ),
            "thought": "Real crash on detached HEAD; fix is obvious.",
            "suggested": "fix",
        }
        assert render_card(card) == (
            "### 🔴 C1 · correctness · packages/statuskit/src/git.py:42\n"
            "\n"
            "> **@coderabbitai:** This crashes on detached HEAD.\n"
            "> ↳ **@you:** already handled?\n"
            "\n"
            "```diff\n"
            "@@ -40,7 +40,7 @@\n"
            "-    return repo.head.name\n"
            "+    return repo.head.name if repo.head else None\n"
            "```\n"
            "\n"
            "**Thought:** Real crash on detached HEAD; fix is obvious.\n"
            "**Suggested:** fix"
        )

    def test_summary_card_has_no_code_block(self):
        card = {
            "ref": "C4",
            "author": "coderabbitai",
            "body": "Overall the PR looks good.",
            "category": "doc",
            "thought": "Informational summary; nothing to change.",
            "suggested": "won't-fix",
        }
        assert render_card(card) == (
            "### 🔵 C4 · doc · (summary)\n"
            "\n"
            "> **@coderabbitai:** Overall the PR looks good.\n"
            "\n"
            "**Thought:** Informational summary; nothing to change.\n"
            "**Suggested:** won't-fix"
        )


class TestMain:
    def test_reads_object_from_stdin(self):
        card = {"ref": "C1", "category": "doc", "author": "a", "body": "hi", "thought": "t"}
        result = _run(json.dumps(card))
        assert result.returncode == 0
        assert result.stdout.rstrip("\n") == ("### 🔵 C1 · doc · (summary)\n\n> **@a:** hi\n\n**Thought:** t")

    def test_accepts_single_element_array(self):
        card = {"ref": "C1", "category": "doc", "author": "a", "body": "hi"}
        result = _run(json.dumps([card]))
        assert result.returncode == 0
        assert result.stdout.startswith("### 🔵 C1 · doc · (summary)")

    def test_empty_stdin_errors(self):
        result = _run("")
        assert result.returncode == 1

    def test_empty_object_errors(self):
        # Valid JSON but no comment data -> the "No comment data." path.
        result = _run("{}")
        assert result.returncode == 1

    def test_empty_array_errors(self):
        # Valid JSON but no comment data -> the "No comment data." path.
        result = _run("[]")
        assert result.returncode == 1

    def test_output_is_not_wrapped_in_an_outer_fence(self):
        # The card must NOT be wrapped: it already contains ```-fences.
        card = {"ref": "C1", "category": "doc", "author": "a", "body": "hi"}
        result = _run(json.dumps(card))
        assert not result.stdout.startswith("```")


class TestGoldenCards:
    def test_gitlab_inline_reconstructed_snippet(self):
        card = {
            "ref": "C2",
            "author": "alice",
            "body": "Prefer a constant here.",
            "path": "plugins/flow/bin/flow-sync",
            "start_line": 10,
            "line": 12,
            "category": "style",
            "snippet": {"lang": "python", "text": "TIMEOUT = 30\ndef sync():\n    ..."},
            "thought": "Minor; the literal is used once.",
            "suggested": "won't-fix",
        }
        assert render_card(card) == (
            "### 🟡 C2 · style · plugins/flow/bin/flow-sync:10-12\n"
            "\n"
            "> **@alice:** Prefer a constant here.\n"
            "\n"
            "```python\n"
            "TIMEOUT = 30\n"
            "def sync():\n"
            "    ...\n"
            "```\n"
            "\n"
            "**Thought:** Minor; the literal is used once.\n"
            "**Suggested:** won't-fix"
        )

    def test_outdated_card_keeps_diff_and_marks_warning(self):
        card = {
            "ref": "C3",
            "author": "bob",
            "body": "Off-by-one here.",
            "path": "a/b.py",
            "line": 5,
            "outdated": True,
            "category": "logic",
            "diff_hunk": "@@ -4,3 +4,3 @@\n-    for i in range(n):\n+    for i in range(n + 1):",
            "thought": "Line moved in current code, but the reasoning still holds.",
            "suggested": "follow-up",
        }
        assert render_card(card) == (
            "### 🔴 C3 · logic · a/b.py:5 ⚠️ outdated\n"
            "\n"
            "> **@bob:** Off-by-one here.\n"
            "\n"
            "```diff\n"
            "@@ -4,3 +4,3 @@\n"
            "-    for i in range(n):\n"
            "+    for i in range(n + 1):\n"
            "```\n"
            "\n"
            "**Thought:** Line moved in current code, but the reasoning still holds.\n"
            "**Suggested:** follow-up"
        )

    @pytest.mark.parametrize(
        ("category", "emoji"),
        [
            ("correctness", "🔴"),
            ("security", "🔴"),
            ("logic", "🔴"),
            ("style", "🟡"),
            ("nitpick", "🟡"),
            ("doc", "🔵"),
            ("unknown", "⚪"),
        ],
    )
    def test_category_emoji_in_header(self, category, emoji):
        card = {"ref": "C1", "category": category, "path": "a/b.py", "line": 1}
        label = category if category != "unknown" else "unknown"
        assert render_header(card) == f"### {emoji} C1 · {label} · a/b.py:1"


class TestMergeMode:
    def _files(self, tmp_path, rows, verdict, ref="C1"):
        ledger = {"schema": 1, "unit": {}, "round": 1, "next_ref": {"U": 1, "C": 2}, "rows": rows}
        (tmp_path / "pr-96.json").write_text(json.dumps(ledger))
        (tmp_path / "verdict.json").write_text(json.dumps(verdict))
        return subprocess.run(
            [
                sys.executable,
                str(_HELPER),
                "--ledger",
                str(tmp_path / "pr-96.json"),
                "--ref",
                ref,
                "--verdict",
                str(tmp_path / "verdict.json"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_merges_row_and_verdict(self, tmp_path):
        rows = {
            "77": {
                "ref": "C1",
                "kind": "inline",
                "user": "coderabbitai",
                "path": "a.py",
                "line": 42,
                "body": "crashes",
                "thread": [],
                "diff_hunk": "@@ -40 +40 @@\n x",
                "snippet": None,
            }
        }
        verdict = {"category": "correctness", "thought": "Real crash.", "suggested": "fix"}
        r = self._files(tmp_path, rows, verdict)
        assert r.returncode == 0, r.stderr
        assert r.stdout.startswith("### 🔴 C1 · correctness · a.py:42")
        assert "> **@coderabbitai:** crashes" in r.stdout
        assert "**Suggested:** fix" in r.stdout

    def test_snippet_overrides_diff_hunk(self, tmp_path):
        rows = {
            "77": {
                "ref": "C1",
                "kind": "inline",
                "user": "a",
                "path": "a.py",
                "line": 5,
                "body": "b",
                "thread": [],
                "diff_hunk": "@@ -5 +5 @@\n l5",
                "snippet": {"lang": "python", "text": "l1\nl2\nl5"},
            }
        }
        r = self._files(tmp_path, rows, {"category": "style", "thought": "t", "suggested": "won't-fix"})
        assert "```python" in r.stdout
        assert "l1\nl2\nl5" in r.stdout
        assert "```diff" not in r.stdout

    def test_no_snippet_keeps_diff_hunk(self, tmp_path):
        rows = {
            "77": {
                "ref": "C1",
                "kind": "inline",
                "user": "a",
                "path": "a.py",
                "line": 5,
                "body": "b",
                "thread": [],
                "diff_hunk": "@@ -5,3 +5,3 @@\n a\n b\n c",
                "snippet": None,
            }
        }
        r = self._files(tmp_path, rows, {"category": "logic", "thought": "t", "suggested": "fix"})
        assert "```diff" in r.stdout

    def test_summary_kind_renders_the_summary_location(self, tmp_path):
        rows = {
            "900": {
                "ref": "C1",
                "kind": "summary",
                "user": "coderabbitai",
                "path": "(summary)",
                "line": None,
                "body": "walkthrough",
                "thread": [],
                "diff_hunk": None,
                "snippet": None,
            }
        }
        r = self._files(tmp_path, rows, {"category": "doc", "thought": "t", "suggested": "follow-up"})
        assert "### 🔵 C1 · doc · (summary)" in r.stdout

    def test_thread_replies_still_render(self, tmp_path):
        rows = {
            "77": {
                "ref": "C1",
                "kind": "inline",
                "user": "alice",
                "path": "a.py",
                "line": 5,
                "body": "root",
                "thread": [{"user": "bob", "body": "reply", "id": 78, "created_at": None, "is_bot": False}],
                "diff_hunk": None,
                "snippet": None,
            }
        }
        r = self._files(tmp_path, rows, {"category": "doc", "thought": "t", "suggested": "fix"})
        assert "> ↳ **@bob:** reply" in r.stdout

    def test_missing_ref_errors(self, tmp_path):
        rows = {"77": {"ref": "C1", "user": "a", "body": "b", "thread": []}}
        r = self._files(tmp_path, rows, {"category": "doc", "thought": "t", "suggested": "fix"}, ref="C9")
        assert r.returncode == 1
