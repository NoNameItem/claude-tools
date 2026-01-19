"""Tests for hook detection."""

from statuskit.setup.hooks import is_our_hook


class TestIsOurHook:
    """Tests for is_our_hook function."""

    def test_simple_statuskit(self):
        """Detects simple 'statuskit' command."""
        assert is_our_hook({"command": "statuskit"}) is True

    def test_statuskit_with_path(self):
        """Detects statuskit with full path."""
        assert is_our_hook({"command": "/usr/local/bin/statuskit"}) is True
        assert is_our_hook({"command": "~/.local/bin/statuskit"}) is True

    def test_statuskit_with_flags(self):
        """Detects statuskit with flags."""
        assert is_our_hook({"command": "statuskit --debug"}) is True

    def test_other_command(self):
        """Rejects other commands."""
        assert is_our_hook({"command": "other-script.sh"}) is False
        assert is_our_hook({"command": "/path/to/other"}) is False

    def test_empty_command(self):
        """Handles empty command."""
        assert is_our_hook({"command": ""}) is False
        assert is_our_hook({}) is False

    def test_malformed_command(self):
        """Handles malformed command strings."""
        assert is_our_hook({"command": "statuskit 'unclosed"}) is False

    def test_type_mismatch(self):
        """Only checks command type hooks."""
        assert is_our_hook({"type": "shell", "command": "statuskit"}) is True
        assert is_our_hook({"command": "statuskit"}) is True
