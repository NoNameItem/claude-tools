"""Tests for hook detection."""

import json

import pytest
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


class TestReadSettings:
    """Tests for read_settings function."""

    def test_read_existing_settings(self, tmp_path):
        """Reads existing settings.json."""
        from statuskit.setup.hooks import read_settings

        settings_path = tmp_path / "settings.json"
        settings_path.write_text('{"foo": "bar"}')

        data = read_settings(settings_path)
        assert data == {"foo": "bar"}

    def test_read_nonexistent_returns_empty(self, tmp_path):
        """Returns empty dict for nonexistent file."""
        from statuskit.setup.hooks import read_settings

        settings_path = tmp_path / "settings.json"

        data = read_settings(settings_path)
        assert data == {}

    def test_read_invalid_json_raises(self, tmp_path):
        """Raises ValueError for invalid JSON."""
        from statuskit.setup.hooks import read_settings

        settings_path = tmp_path / "settings.json"
        settings_path.write_text("not json")

        with pytest.raises(ValueError, match="Invalid JSON"):
            read_settings(settings_path)


class TestWriteSettings:
    """Tests for write_settings function."""

    def test_write_creates_file(self, tmp_path):
        """Creates settings.json with data."""
        from statuskit.setup.hooks import write_settings

        settings_path = tmp_path / "settings.json"
        write_settings(settings_path, {"foo": "bar"})

        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert data == {"foo": "bar"}

    def test_write_creates_parent_dirs(self, tmp_path):
        """Creates parent directories if needed."""
        from statuskit.setup.hooks import write_settings

        settings_path = tmp_path / ".claude" / "settings.json"
        write_settings(settings_path, {"foo": "bar"})

        assert settings_path.exists()

    def test_write_preserves_formatting(self, tmp_path):
        """Writes with indent for readability."""
        from statuskit.setup.hooks import write_settings

        settings_path = tmp_path / "settings.json"
        write_settings(settings_path, {"foo": "bar"})

        content = settings_path.read_text()
        assert "\n" in content  # has newlines (indented)
