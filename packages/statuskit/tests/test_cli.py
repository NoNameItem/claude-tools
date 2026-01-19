"""Tests for CLI argument parsing."""

import pytest
from statuskit.cli import create_parser, get_version


def test_version_returns_string():
    """--version returns version string."""
    version = get_version()
    assert isinstance(version, str)
    assert version  # not empty


def test_parser_version_action(capsys):
    """--version prints version and exits."""
    parser = create_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "statuskit" in captured.out.lower() or get_version() in captured.out


def test_help_shows_modules(capsys):
    """--help shows built-in modules list."""
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    captured = capsys.readouterr()
    # Check modules are listed
    assert "model" in captured.out
    assert "git" in captured.out
    assert "beads" in captured.out
    assert "quota" in captured.out
