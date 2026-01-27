"""Tests for statuskit entry point."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from statuskit import main


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
    assert "statuskit" in captured.out.lower() or "0.1.0" in captured.out


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
