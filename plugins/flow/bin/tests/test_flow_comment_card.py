"""Tests for flow-comment-card."""

# ruff: noqa: INP001

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

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
