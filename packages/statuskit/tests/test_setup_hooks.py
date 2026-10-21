"""Tests for hook detection."""

import json
import re
import sys
from datetime import datetime

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


class TestCreateBackup:
    """Tests for create_backup function."""

    NOW = datetime(2026, 10, 22, 14, 30, 12)

    def test_copies_file_to_timestamped_backup(self, tmp_path):
        """The backup is named after the local time and holds the original bytes."""
        from statuskit.setup.hooks import create_backup

        original = tmp_path / "settings.json"
        original.write_text('{"original": true}')

        result = create_backup(original, now=self.NOW)

        assert result == tmp_path / "settings.json.20261022-143012.bak"
        assert result.read_text() == '{"original": true}'

    def test_default_clock_names_backup_by_current_time(self, tmp_path):
        from statuskit.setup.hooks import create_backup

        original = tmp_path / "settings.json"
        original.write_text("{}")

        result = create_backup(original)

        assert re.fullmatch(r"settings\.json\.\d{8}-\d{6}\.bak", result.name)

    def test_existing_backups_are_never_touched(self, tmp_path):
        """Neither a legacy .bak nor an earlier timestamped backup is overwritten."""
        from statuskit.setup.hooks import create_backup

        original = tmp_path / "settings.json"
        original.write_text('{"new": true}')
        legacy = tmp_path / "settings.json.bak"
        legacy.write_text("legacy")
        earlier = tmp_path / "settings.json.20260101-000000.bak"
        earlier.write_text("earlier")

        result = create_backup(original, now=self.NOW)

        assert legacy.read_text() == "legacy"
        assert earlier.read_text() == "earlier"
        assert result.read_text() == '{"new": true}'

    def test_same_second_gets_counter_suffix(self, tmp_path):
        from statuskit.setup.hooks import create_backup

        original = tmp_path / "settings.json"
        original.write_text("first")
        first = create_backup(original, now=self.NOW)
        original.write_text("second")
        second = create_backup(original, now=self.NOW)
        original.write_text("third")
        third = create_backup(original, now=self.NOW)

        assert [first.name, second.name, third.name] == [
            "settings.json.20261022-143012.bak",
            "settings.json.20261022-143012-1.bak",
            "settings.json.20261022-143012-2.bak",
        ]
        assert [first.read_text(), second.read_text(), third.read_text()] == ["first", "second", "third"]

    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
    def test_symlink_at_backup_name_is_skipped_not_followed(self, tmp_path):
        """A symlink planted at the backup name is neither written through nor replaced."""
        from statuskit.setup.hooks import create_backup

        decoy = tmp_path / "decoy"
        decoy.write_text("decoy")
        original = tmp_path / "settings.json"
        original.write_text('{"new": true}')
        planted = tmp_path / "settings.json.20261022-143012.bak"
        planted.symlink_to(decoy)

        result = create_backup(original, now=self.NOW)

        assert decoy.read_text() == "decoy"
        assert planted.is_symlink()
        assert result == tmp_path / "settings.json.20261022-143012-1.bak"
        assert result.read_text() == '{"new": true}'

    def test_failed_copy_leaves_no_backup(self, tmp_path, monkeypatch):
        """A failing copy raises and removes the partial backup; older backups stay."""
        import shutil

        from statuskit.setup.hooks import create_backup

        original = tmp_path / "settings.json"
        original.write_text('{"new": true}')
        earlier = tmp_path / "settings.json.20260101-000000.bak"
        earlier.write_text("earlier")

        def boom(*args, **kwargs):
            msg = "disk full"
            raise OSError(msg)

        monkeypatch.setattr(shutil, "copyfileobj", boom)

        with pytest.raises(OSError, match="disk full"):
            create_backup(original, now=self.NOW)

        assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json", earlier.name]
        assert earlier.read_text() == "earlier"
