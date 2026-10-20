"""Tests for config file creation."""

import os
import sys
from pathlib import Path

import pytest

no_permission_bits = pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="permission bits are not enforced (Windows or root)",
)


def _deny(self, *args, **kwargs):
    msg = "denied"
    raise PermissionError(msg)


class TestCreateConfig:
    """Tests for create_config function."""

    def test_creates_default_config(self, tmp_path):
        """Creates statuskit.toml with defaults."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / "statuskit.toml"
        create_config(config_path)

        assert config_path.exists()
        content = config_path.read_text()
        assert '# modules = ["model", "git", "usage_limits"]' in content

    def test_creates_parent_dirs(self, tmp_path):
        """Creates parent directories if needed."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / ".claude" / "statuskit.toml"
        create_config(config_path)

        assert config_path.exists()

    def test_does_not_overwrite_existing(self, tmp_path):
        """Does not overwrite existing config."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / "statuskit.toml"
        config_path.write_text("custom = true")

        create_config(config_path)

        assert config_path.read_text() == "custom = true"

    def test_returns_created_true(self, tmp_path):
        """Returns True when config was created."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / "statuskit.toml"
        result = create_config(config_path)

        assert result is True

    def test_returns_created_false_if_exists(self, tmp_path):
        """Returns False when config already existed."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / "statuskit.toml"
        config_path.write_text("existing = true")

        result = create_config(config_path)

        assert result is False

    def test_create_config_writes_generated_template(self, tmp_path):
        """Writes the template produced by build_config."""
        from statuskit.setup.config import create_config
        from statuskit.setup.config_gen import build_config

        config_path = tmp_path / "statuskit.toml"
        create_config(config_path)

        assert config_path.read_text(encoding="utf-8") == build_config()[0]


class TestInitConfig:
    """Tests for init_config function."""

    def test_creates_missing_file_and_parent_dirs(self, tmp_path):
        from statuskit.setup.config import InitResult, InitStatus, init_config
        from statuskit.setup.config_gen import build_config

        path = tmp_path / ".claude" / "statuskit.toml"

        assert init_config(path, force=False) == InitResult(InitStatus.CREATED)
        assert path.read_text(encoding="utf-8") == build_config()[0]

    def test_refuses_existing_file(self, tmp_path):
        from statuskit.setup.config import InitResult, InitStatus, init_config

        path = tmp_path / "statuskit.toml"
        path.write_text("debug = true\n")

        assert init_config(path, force=False) == InitResult(InitStatus.EXISTS)
        assert path.read_text() == "debug = true\n"

    def test_force_resets_and_backs_up(self, tmp_path):
        from statuskit.setup.config import InitResult, InitStatus, init_config
        from statuskit.setup.config_gen import build_config

        path = tmp_path / "statuskit.toml"
        path.write_text("debug = true\n")
        backup = tmp_path / "statuskit.toml.bak"

        assert init_config(path, force=True) == InitResult(InitStatus.RESET, backup=backup)
        assert backup.read_text() == "debug = true\n"
        assert path.read_text(encoding="utf-8") == build_config()[0]

    def test_write_failure_is_an_error(self, tmp_path, monkeypatch):
        from pathlib import Path

        from statuskit.setup.config import InitStatus, init_config

        def boom(self, *args, **kwargs):
            msg = "denied"
            raise PermissionError(msg)

        monkeypatch.setattr(Path, "write_text", boom)
        path = tmp_path / "statuskit.toml"

        result = init_config(path, force=False)

        assert result.status == InitStatus.ERROR
        assert result.error.startswith("Cannot write")
        assert not path.exists()


class TestSyncConfig:
    """Tests for sync_config function."""

    def test_missing_file_is_created(self, tmp_path):
        from statuskit.setup.config import SyncStatus, sync_config
        from statuskit.setup.config_gen import build_config

        path = tmp_path / ".claude" / "statuskit.toml"

        result = sync_config(path, dry_run=False)

        assert result.status == SyncStatus.CREATED
        assert path.read_text(encoding="utf-8") == build_config()[0]

    def test_missing_file_dry_run_writes_nothing(self, tmp_path):
        from statuskit.setup.config import SyncStatus, sync_config

        path = tmp_path / ".claude" / "statuskit.toml"

        assert sync_config(path, dry_run=True).status == SyncStatus.CREATED
        assert not path.exists()

    def test_up_to_date_file_is_left_alone(self, tmp_path):
        from statuskit.setup.config import SyncStatus, sync_config
        from statuskit.setup.config_gen import build_config

        path = tmp_path / "statuskit.toml"
        path.write_text(build_config()[0], encoding="utf-8", newline="\n")

        result = sync_config(path, dry_run=False)

        assert result.status == SyncStatus.UNCHANGED
        assert not (tmp_path / "statuskit.toml.bak").exists()

    def test_rebuild_keeps_values_reports_removals_and_backs_up(self, tmp_path):
        import tomllib

        from statuskit.setup.config import SyncStatus, sync_config
        from statuskit.setup.config_gen import Removal, build_config

        old = '[model]\ncontext_format = "bar"\nbogus = 1\n'
        path = tmp_path / "statuskit.toml"
        path.write_bytes(old.encode())

        result = sync_config(path, dry_run=False)

        assert result.status == SyncStatus.UPDATED
        assert result.removals == (Removal("model.bogus", "unknown key"),)
        assert (tmp_path / "statuskit.toml.bak").read_bytes() == old.encode()
        assert path.read_text(encoding="utf-8") == build_config(tomllib.loads(old))[0]

    def test_dry_run_reports_but_writes_nothing(self, tmp_path):
        from statuskit.setup.config import SyncStatus, sync_config
        from statuskit.setup.config_gen import Removal

        old = b'[model]\ncontext_format = "bar"\nbogus = 1\n'
        path = tmp_path / "statuskit.toml"
        path.write_bytes(old)

        result = sync_config(path, dry_run=True)

        assert result.status == SyncStatus.UPDATED
        assert result.removals == (Removal("model.bogus", "unknown key"),)
        assert result.backup is None
        assert path.read_bytes() == old
        assert not (tmp_path / "statuskit.toml.bak").exists()

    def test_unparsable_file_is_untouched(self, tmp_path):
        from statuskit.setup.config import SyncStatus, sync_config

        for content in (b"[model\n", b"\xff\xfe"):
            path = tmp_path / "statuskit.toml"
            path.write_bytes(content)

            result = sync_config(path, dry_run=False)

            assert result.status == SyncStatus.ERROR
            assert result.error.startswith("Cannot read")
            assert result.error.endswith("Nothing was changed.")
            assert path.read_bytes() == content
            assert not (tmp_path / "statuskit.toml.bak").exists()

    def test_crlf_file_is_rebuilt_to_lf(self, tmp_path):
        from statuskit.setup.config import SyncStatus, sync_config

        path = tmp_path / "statuskit.toml"
        path.write_bytes(b"debug = true\r\n")

        assert sync_config(path, dry_run=False).status == SyncStatus.UPDATED

        assert b"\r" not in path.read_bytes()
        assert "\ndebug = true\n" in path.read_text(encoding="utf-8")

    def test_bom_file_is_rebuilt_without_bom(self, tmp_path):
        from statuskit.setup.config import SyncStatus, sync_config

        path = tmp_path / "statuskit.toml"
        path.write_bytes(b"\xef\xbb\xbfdebug = true\n")

        assert sync_config(path, dry_run=False).status == SyncStatus.UPDATED

        assert path.read_bytes().startswith(b"# Statuskit")

    def test_empty_file_gets_full_template(self, tmp_path):
        from statuskit.setup.config import SyncStatus, sync_config
        from statuskit.setup.config_gen import build_config

        path = tmp_path / "statuskit.toml"
        path.write_bytes(b"")

        result = sync_config(path, dry_run=False)

        assert result.status == SyncStatus.UPDATED
        assert result.removals == ()
        assert path.read_text(encoding="utf-8") == build_config()[0]

    def test_write_failure_leaves_original_intact(self, tmp_path, monkeypatch):
        from pathlib import Path

        from statuskit.setup.config import SyncStatus, sync_config

        def boom(self, *args, **kwargs):
            msg = "denied"
            raise PermissionError(msg)

        path = tmp_path / "statuskit.toml"
        path.write_bytes(b"bogus = 1\n")
        monkeypatch.setattr(Path, "write_text", boom)

        result = sync_config(path, dry_run=False)

        assert result.status == SyncStatus.ERROR
        assert result.error.startswith("Cannot write")
        assert path.read_bytes() == b"bogus = 1\n"
        assert list(tmp_path.glob("*.tmp")) == []

    def test_replace_failure_cleans_up_tmp(self, tmp_path, monkeypatch):
        from pathlib import Path

        from statuskit.setup.config import SyncStatus, sync_config

        def boom(self, *args, **kwargs):
            msg = "replace failed"
            raise OSError(msg)

        path = tmp_path / "statuskit.toml"
        path.write_bytes(b"bogus = 1\n")
        monkeypatch.setattr(Path, "replace", boom)

        result = sync_config(path, dry_run=False)

        assert result.status == SyncStatus.ERROR
        assert result.error.startswith("Cannot write")
        assert path.read_bytes() == b"bogus = 1\n"
        assert list(tmp_path.glob("*.tmp")) == []

    def test_symlinked_config_stays_a_symlink(self, tmp_path):
        from statuskit.setup.config import SyncStatus, sync_config
        from statuskit.setup.config_gen import build_config

        real = tmp_path / "dotfiles" / "statuskit.toml"
        real.parent.mkdir()
        real.write_text("bogus = 1\n")
        link = tmp_path / ".claude" / "statuskit.toml"
        link.parent.mkdir()
        link.symlink_to(real)

        assert sync_config(link, dry_run=False).status == SyncStatus.UPDATED

        assert link.is_symlink()
        assert real.read_text(encoding="utf-8") == build_config()[0]

    def test_bom_only_difference_is_rebuilt(self, tmp_path):
        from statuskit.setup.config import SyncStatus, sync_config
        from statuskit.setup.config_gen import build_config

        bom = b"\xef\xbb\xbf"
        content = bom + build_config()[0].encode("utf-8")
        path = tmp_path / "statuskit.toml"
        path.write_bytes(content)

        dry = sync_config(path, dry_run=True)
        assert dry.status == SyncStatus.UPDATED
        assert path.read_bytes() == content

        result = sync_config(path, dry_run=False)
        assert result.status == SyncStatus.UPDATED
        assert result.removals == ()
        assert not path.read_bytes().startswith(bom)


class TestUnreadableConfig:
    """F1: an unreadable config is reported as 'Cannot read', never a traceback."""

    def test_sync_permission_error_is_cannot_read(self, tmp_path, monkeypatch):
        from statuskit.setup.config import SyncStatus, sync_config

        path = tmp_path / "statuskit.toml"
        path.write_text("debug = true\n")
        monkeypatch.setattr(Path, "read_bytes", _deny)

        for dry_run in (False, True):
            result = sync_config(path, dry_run=dry_run)
            assert result.status == SyncStatus.ERROR
            assert result.error.startswith("Cannot read")
        assert path.read_text() == "debug = true\n"
        assert not (tmp_path / "statuskit.toml.bak").exists()

    def test_init_permission_error_is_cannot_read(self, tmp_path, monkeypatch):
        from statuskit.setup.config import InitStatus, init_config

        path = tmp_path / "statuskit.toml"
        path.write_text("debug = true\n")
        monkeypatch.setattr(Path, "stat", _deny)

        for force in (False, True):
            result = init_config(path, force=force)
            assert result.status == InitStatus.ERROR
            assert result.error.startswith("Cannot read")
        monkeypatch.undo()
        assert path.read_text() == "debug = true\n"

    @no_permission_bits
    def test_sync_unsearchable_parent_dir(self, tmp_path):
        from statuskit.setup.config import SyncStatus, sync_config

        parent = tmp_path / "locked"
        parent.mkdir()
        path = parent / "statuskit.toml"
        path.write_text("debug = true\n")
        parent.chmod(0o000)
        try:
            result = sync_config(path, dry_run=False)
        finally:
            parent.chmod(0o700)

        assert result.status == SyncStatus.ERROR
        assert result.error.startswith("Cannot read")

    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
    def test_sync_symlink_loop_is_an_error(self, tmp_path):
        from statuskit.setup.config import SyncStatus, sync_config

        link = tmp_path / "statuskit.toml"
        link.symlink_to(link)

        assert sync_config(link, dry_run=False).status == SyncStatus.ERROR


class TestWriteOrderAndModes:
    """F2/F3: backup is taken only once the new content is staged; modes are respected."""

    def test_failed_write_keeps_previous_backup(self, tmp_path, monkeypatch):
        from statuskit.setup.config import SyncStatus, sync_config

        path = tmp_path / "statuskit.toml"
        path.write_text("[git]\nshow_prr = true\n")
        bak = tmp_path / "statuskit.toml.bak"
        bak.write_bytes(b"older backup\n")
        monkeypatch.setattr(Path, "write_text", _deny)

        result = sync_config(path, dry_run=False)

        assert result.status == SyncStatus.ERROR
        assert bak.read_bytes() == b"older backup\n"
        assert not (tmp_path / "statuskit.toml.tmp").exists()

    @no_permission_bits
    def test_read_only_config_is_not_overwritten(self, tmp_path):
        from statuskit.setup.config import SyncStatus, sync_config

        path = tmp_path / "statuskit.toml"
        path.write_text("[git]\nshow_prr = true\n")
        path.chmod(0o444)

        result = sync_config(path, dry_run=False)

        assert result.status == SyncStatus.ERROR
        assert result.error.startswith("Cannot write")
        assert path.read_text() == "[git]\nshow_prr = true\n"
        assert path.stat().st_mode & 0o777 == 0o444
        assert not (tmp_path / "statuskit.toml.bak").exists()

    @no_permission_bits
    def test_private_mode_is_preserved(self, tmp_path):
        from statuskit.setup.config import SyncStatus, sync_config

        path = tmp_path / "statuskit.toml"
        path.write_text("[git]\nshow_prr = true\n")
        path.chmod(0o600)

        assert sync_config(path, dry_run=False).status == SyncStatus.UPDATED
        assert path.stat().st_mode & 0o777 == 0o600
