"""Tests for ConsoleUI."""


class TestConsoleUI:
    """Tests for ConsoleUI class."""

    def test_confirm_yes(self, monkeypatch):
        """confirm returns True for 'y' input."""
        from statuskit.setup.ui import ConsoleUI

        monkeypatch.setattr("builtins.input", lambda _: "y")
        ui = ConsoleUI()

        assert ui.confirm("Continue?") is True

    def test_confirm_no(self, monkeypatch):
        """confirm returns False for 'n' input."""
        from statuskit.setup.ui import ConsoleUI

        monkeypatch.setattr("builtins.input", lambda _: "n")
        ui = ConsoleUI()

        assert ui.confirm("Continue?") is False

    def test_confirm_empty_default_no(self, monkeypatch):
        """confirm returns False for empty input (default no)."""
        from statuskit.setup.ui import ConsoleUI

        monkeypatch.setattr("builtins.input", lambda _: "")
        ui = ConsoleUI()

        assert ui.confirm("Continue?") is False

    def test_choose_returns_index(self, monkeypatch):
        """choose returns selected option index."""
        from statuskit.setup.ui import ConsoleUI

        monkeypatch.setattr("builtins.input", lambda _: "2")
        ui = ConsoleUI()

        result = ui.choose("Select:", ["Option A", "Option B", "Cancel"])

        assert result == 1  # 0-based index for "2"
