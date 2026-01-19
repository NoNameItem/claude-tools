"""Tests for setup commands."""

import json
from pathlib import Path


class TestCheckInstallation:
    """Tests for check_installation function."""

    def test_no_installation(self, tmp_path, monkeypatch):
        """Shows not installed for all scopes."""
        from statuskit.setup.commands import check_installation

        # Create directories first
        (tmp_path / "project").mkdir(parents=True)
        (tmp_path / "home").mkdir(parents=True)

        # Mock home to tmp_path
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        monkeypatch.chdir(tmp_path / "project")

        result = check_installation()

        assert "User:" in result
        assert "Not installed" in result
        assert "Project:" in result
        assert "Local:" in result

    def test_user_installed(self, tmp_path, monkeypatch):
        """Shows installed for user scope."""
        from statuskit.setup.commands import check_installation

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "settings.json").write_text(json.dumps({"statusLine": {"command": "statuskit"}}))

        # Create project directory first
        (tmp_path / "project").mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(tmp_path / "project")

        result = check_installation()

        assert "User:" in result
        assert "Installed" in result

    def test_project_installed(self, tmp_path, monkeypatch):
        """Shows installed for project scope."""
        from statuskit.setup.commands import check_installation

        project = tmp_path / "project"
        (project / ".claude").mkdir(parents=True)
        (project / ".claude" / "settings.json").write_text(json.dumps({"statusLine": {"command": "statuskit"}}))

        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        monkeypatch.chdir(project)

        result = check_installation()

        assert "Project:" in result
        assert "Installed" in result


class TestInstallHook:
    """Tests for install_hook function."""

    def test_installs_to_user_scope(self, tmp_path, monkeypatch):
        """Installs hook to user scope."""
        from statuskit.setup.commands import install_hook
        from statuskit.setup.paths import Scope

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: home)

        result = install_hook(Scope.USER, force=False, ui=None)

        assert result.success is True
        settings = json.loads((home / ".claude" / "settings.json").read_text())
        assert settings["statusLine"]["command"] == "statuskit"

    def test_creates_config_file(self, tmp_path, monkeypatch):
        """Creates statuskit.toml alongside hook."""
        from statuskit.setup.commands import install_hook
        from statuskit.setup.paths import Scope

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: home)

        install_hook(Scope.USER, force=False, ui=None)

        config_path = home / ".claude" / "statuskit.toml"
        assert config_path.exists()

    def test_already_installed_returns_early(self, tmp_path, monkeypatch):
        """Returns early if already installed."""
        from statuskit.setup.commands import install_hook
        from statuskit.setup.paths import Scope

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "settings.json").write_text(json.dumps({"statusLine": {"command": "statuskit"}}))

        monkeypatch.setattr(Path, "home", lambda: home)

        result = install_hook(Scope.USER, force=False, ui=None)

        assert result.already_installed is True

    def test_foreign_hook_with_force_creates_backup(self, tmp_path, monkeypatch):
        """Creates backup when overwriting foreign hook with --force."""
        from statuskit.setup.commands import install_hook
        from statuskit.setup.paths import Scope

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "settings.json").write_text(json.dumps({"statusLine": {"command": "other-script"}}))

        monkeypatch.setattr(Path, "home", lambda: home)

        result = install_hook(Scope.USER, force=True, ui=None)

        assert result.success is True
        assert result.backup_created is True
        assert (home / ".claude" / "settings.json.bak").exists()
