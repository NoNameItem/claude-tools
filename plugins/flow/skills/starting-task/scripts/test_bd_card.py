"""Tests for bd-card.py."""

# ruff: noqa: INP001, S101, PLR2004, RUF003

import importlib.util
from pathlib import Path

# Import bd-card.py as module (hyphenated filename)
_spec = importlib.util.spec_from_file_location("bd_card", Path(__file__).parent / "bd-card.py")
assert _spec is not None
assert _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

char_width = _mod.char_width
str_width = _mod.str_width


class TestCharWidth:
    def test_ascii(self):
        assert char_width("A") == 1

    def test_cyrillic(self):
        assert char_width("Я") == 1

    def test_cjk(self):
        assert char_width("\u4e16") == 2  # 世

    def test_fullwidth_letter(self):
        assert char_width("\uff21") == 2  # Ａ (fullwidth A)


class TestStrWidth:
    def test_ascii(self):
        assert str_width("hello") == 5

    def test_cyrillic(self):
        assert str_width("Привет") == 6

    def test_mixed(self):
        assert str_width("Hello Мир") == 9

    def test_empty(self):
        assert str_width("") == 0

    def test_cjk(self):
        assert str_width("世界") == 4
