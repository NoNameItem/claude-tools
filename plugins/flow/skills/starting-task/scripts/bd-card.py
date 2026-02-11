#!/usr/bin/env python3
"""
Render task card from bd show --json output.

Usage:
    bd show <task-id> --json | python3 bd-card.py
"""

import unicodedata


def char_width(ch: str) -> int:
    """Return display width of a character (1 or 2)."""
    w = unicodedata.east_asian_width(ch)
    return 2 if w in ("W", "F") else 1


def str_width(s: str) -> int:
    """Return display width of a string."""
    return sum(char_width(ch) for ch in s)


CARD_WIDTH = 80
CONTENT_WIDTH = 76  # 80 - len("│ ") - len(" │")


def pad_right(s: str, width: int) -> str:
    """Pad string to exact display width with spaces."""
    current = str_width(s)
    if current >= width:
        return s
    return s + " " * (width - current)


def content_line(text: str) -> str:
    """Build a content line: │ <text padded to CONTENT_WIDTH> │"""
    return "│ " + pad_right(text, CONTENT_WIDTH) + " │"


def separator_line() -> str:
    """Build a separator: ├──...──┤"""
    return "├" + "─" * (CARD_WIDTH - 2) + "┤"
