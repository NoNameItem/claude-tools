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
