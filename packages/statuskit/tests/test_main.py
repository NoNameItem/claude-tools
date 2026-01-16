"""Tests for statuskit entry point."""

import json
from unittest.mock import MagicMock, patch

from statuskit import main


def test_main_tty_shows_usage(capsys):
    """main shows usage when stdin is tty."""
    with patch("sys.stdin.isatty", return_value=True):
        main()

    captured = capsys.readouterr()
    assert "statuskit:" in captured.out
    assert "stdin" in captured.out


def test_main_parses_json_and_renders(capsys):
    """main parses JSON and renders output."""
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


def test_main_invalid_json_silent(capsys):
    """main silently exits on invalid JSON (non-debug)."""
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False

    with patch("sys.stdin", mock_stdin), patch("json.load", side_effect=json.JSONDecodeError("", "", 0)):
        main()

    captured = capsys.readouterr()
    assert captured.out == ""


def test_main_empty_json_no_output(capsys):
    """main produces no output for empty JSON."""
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False

    with patch("sys.stdin", mock_stdin), patch("json.load", return_value={}):
        main()

    captured = capsys.readouterr()
    assert captured.out == ""
