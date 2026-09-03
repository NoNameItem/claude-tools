"""Tests for beadboard.cli."""

from unittest.mock import patch

from beadboard.cli import main


def test_main_runs_the_application_once_and_returns_zero():
    """main() is the composition root: it builds the app, runs it, reports success."""
    with patch("beadboard.ui.app.BeadboardApp.run") as run:
        exit_code = main()

    assert exit_code == 0
    assert run.call_count == 1
