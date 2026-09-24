"""Tests for statuskit entry point."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from statuskit import main
from statuskit.cli import get_version


def test_main_tty_shows_usage(capsys, monkeypatch):
    """main shows usage when stdin is tty."""
    monkeypatch.setattr(sys, "argv", ["statuskit"])
    with patch("sys.stdin.isatty", return_value=True):
        main()

    captured = capsys.readouterr()
    assert "statuskit:" in captured.out
    assert "stdin" in captured.out


def test_main_parses_json_and_renders(capsys, monkeypatch):
    """main parses JSON and renders output."""
    monkeypatch.setattr(sys, "argv", ["statuskit"])
    input_data = {
        "model": {"display_name": "Opus"},
        "cost": {"total_duration_ms": 60000},
        "context_window": {
            "context_window_size": 200000,
            "current_usage": {
                "input_tokens": 50000,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
    }

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False
    mock_stdin.read.return_value = json.dumps(input_data)

    with patch("sys.stdin", mock_stdin), patch("json.load", return_value=input_data):
        main()

    captured = capsys.readouterr()
    assert "[Opus]" in captured.out


def test_main_invalid_json_silent(capsys, monkeypatch):
    """main silently exits on invalid JSON (non-debug)."""
    from statuskit.core.config import Config

    monkeypatch.setattr(sys, "argv", ["statuskit"])
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False

    # Explicitly set debug=False to ensure silent error handling
    mock_config = Config(modules=["model"], debug=False)

    with (
        patch("sys.stdin", mock_stdin),
        patch("json.load", side_effect=json.JSONDecodeError("", "", 0)),
        patch("statuskit.load_config", return_value=mock_config),
    ):
        main()

    captured = capsys.readouterr()
    assert captured.out == ""


def test_main_empty_json_no_output(capsys, monkeypatch):
    """main produces no output for empty JSON when using JSON-dependent modules only."""
    from statuskit.core.config import Config

    monkeypatch.setattr(sys, "argv", ["statuskit"])
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False

    # Only test model module (JSON-dependent) - git module runs without JSON
    mock_config = Config(modules=["model"])
    with (
        patch("sys.stdin", mock_stdin),
        patch("json.load", return_value={}),
        patch("statuskit.load_config", return_value=mock_config),
    ):
        main()

    captured = capsys.readouterr()
    assert captured.out == ""


def test_main_with_version_flag(capsys, monkeypatch):
    """main() handles --version flag."""
    monkeypatch.setattr(sys, "argv", ["statuskit", "--version"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "statuskit" in captured.out.lower()
    assert get_version() in captured.out


def test_main_setup_check(capsys, monkeypatch, tmp_path):
    """main() handles 'setup --check' command."""
    from pathlib import Path

    # Mock home to tmp_path
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / "home" / ".claude").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(sys, "argv", ["statuskit", "setup", "--check"])

    main()

    captured = capsys.readouterr()
    assert "User:" in captured.out
    assert "Not installed" in captured.out


def test_render_statusline_sets_force_color(monkeypatch):
    """_render_statusline sets FORCE_COLOR=1 when colors enabled."""
    import os

    from statuskit import _render_statusline
    from statuskit.core.config import Config

    monkeypatch.setattr(sys, "argv", ["statuskit"])

    # Remove FORCE_COLOR if present
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False

    input_data = {"model": {"display_name": "Test"}}
    mock_config = Config(modules=["model"], colors=True)

    with (
        patch("sys.stdin", mock_stdin),
        patch("json.load", return_value=input_data),
        patch("statuskit.load_config", return_value=mock_config),
    ):
        _render_statusline()

    assert os.environ.get("FORCE_COLOR") == "1"


def test_render_statusline_respects_colors_false(monkeypatch):
    """_render_statusline does not set FORCE_COLOR when colors=false."""
    import os

    from statuskit import _render_statusline
    from statuskit.core.config import Config

    monkeypatch.setattr(sys, "argv", ["statuskit"])

    # Remove FORCE_COLOR if present
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False

    input_data = {"model": {"display_name": "Test"}}
    mock_config = Config(modules=["model"], colors=False)

    with (
        patch("sys.stdin", mock_stdin),
        patch("json.load", return_value=input_data),
        patch("statuskit.load_config", return_value=mock_config),
    ):
        _render_statusline()

    assert os.environ.get("FORCE_COLOR") is None


def test_main_outputs_ansi_codes_when_colors_enabled(capsys, monkeypatch):
    """main outputs ANSI escape codes when colors=true."""
    from statuskit.core.config import Config
    from termcolor.termcolor import can_colorize

    monkeypatch.setattr(sys, "argv", ["statuskit"])

    # Set FORCE_COLOR before calling main() and clear termcolor's cache
    # termcolor uses @cache on can_colorize(), so we must clear it
    # after setting the env var for the new value to be detected
    monkeypatch.setenv("FORCE_COLOR", "1")
    can_colorize.cache_clear()

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False

    input_data = {
        "model": {"display_name": "Opus"},
        "context_window": {
            "context_window_size": 200000,
            "current_usage": {"input_tokens": 1000},
        },
    }
    mock_config = Config(modules=["model"], colors=True)

    with (
        patch("sys.stdin", mock_stdin),
        patch("json.load", return_value=input_data),
        patch("statuskit.load_config", return_value=mock_config),
    ):
        main()

    captured = capsys.readouterr()
    # ANSI escape sequence starts with \x1b[
    assert "\x1b[" in captured.out, f"Expected ANSI codes in output, got: {captured.out!r}"


# ECMAScript WhiteSpace + LineTerminator: exactly what String.prototype.trim() strips.
_JS_WHITESPACE = (
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)


def _claude_code_statusline(stdout: str) -> str:
    """Reproduce Claude Code's post-processing of statusline output (checked in 2.1.281).

    ``stdout.trim().split("\\n").flatMap((line) => line.trim() || []).join("\\n")``
    """
    lines = stdout.strip(_JS_WHITESPACE).split("\n")
    return "\n".join(stripped for line in lines if (stripped := line.strip(_JS_WHITESPACE)))


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("  └ Fable: 34%", "\u2800 └ Fable: 34%"),
        ("  \x1b[2m└\x1b[0m Fable: 34%", "\u2800 \x1b[2m└\x1b[0m Fable: 34%"),
        (" x", "\u2800x"),
        ("├ Session: 11%", "├ Session: 11%"),
        ("\x1b[2m└\x1b[0m Weekly:  2%", "\x1b[2m└\x1b[0m Weekly:  2%"),
        ("\t└ Fable", "\t└ Fable"),
        ("   ", "   "),
        (
            "Usage:\n└ Weekly:  2%\n  ├ Fable\n  └ Opus",
            "Usage:\n└ Weekly:  2%\n\u2800 ├ Fable\n\u2800 └ Opus",
        ),
    ],
    ids=[
        "two-space-indent",
        "indent-before-ansi-connector",
        "single-space",
        "no-indent",
        "ansi-first",
        "tab-indent",
        "whitespace-only",
        "multiline",
    ],
)
def test_guard_indent(text, want):
    """_guard_indent swaps only an indent's first space for the guard, line by line."""
    from statuskit import _guard_indent

    assert _guard_indent(text) == want


def test_claude_code_trim_strips_plain_indent():
    """The simulated Claude Code trim drops a plain-space indent (the bug being fixed)."""
    stdout = "Usage:\n└ Weekly:  2%\n  \x1b[2m└\x1b[0m Fable: 34%\n"

    assert _claude_code_statusline(stdout) == "Usage:\n└ Weekly:  2%\n\x1b[2m└\x1b[0m Fable: 34%"


def test_guarded_indent_survives_claude_code_trim():
    """A guarded indent keeps its two-column offset through Claude Code's per-line trim()."""
    from statuskit import _guard_indent

    stdout = _guard_indent("Usage:\n└ Weekly:  2%\n  \x1b[2m└\x1b[0m Fable: 34%") + "\n"

    assert _claude_code_statusline(stdout) == "Usage:\n└ Weekly:  2%\n\u2800 \x1b[2m└\x1b[0m Fable: 34%"


def test_render_statusline_guards_indented_lines(capsys):
    """_render_statusline protects a module's indented lines from Claude Code's trim()."""
    from statuskit import _render_statusline
    from statuskit.core.config import Config

    module = MagicMock()
    module.render.return_value = "Usage:\n└ Weekly:  2%\n  └ Fable: 34%"

    with (
        patch("sys.stdin", MagicMock()),
        patch("json.load", return_value={"model": {"display_name": "Test"}}),
        patch("statuskit.load_config", return_value=Config(modules=["model"], colors=False)),
        patch("statuskit.load_modules", return_value=[module]),
    ):
        _render_statusline()

    assert capsys.readouterr().out == "Usage:\n└ Weekly:  2%\n\u2800 └ Fable: 34%\n"
