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
