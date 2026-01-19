"""Tests for setup commands."""

# ruff: noqa: S603, S607
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


class TestInstallHookGitignore:
    """Tests for install_hook gitignore handling."""

    def test_adds_gitignore_for_local_scope(self, tmp_path, monkeypatch):
        """Adds gitignore pattern when installing to local scope."""
        import subprocess

        from statuskit.setup.commands import install_hook
        from statuskit.setup.paths import Scope

        project = tmp_path / "project"
        project.mkdir()
        subprocess.run(["git", "init"], cwd=project, capture_output=True, check=False)

        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        monkeypatch.chdir(project)

        result = install_hook(Scope.LOCAL, force=False, ui=None)

        assert result.success is True
        assert result.gitignore_updated is True
        assert ".claude/*.local.*" in (project / ".gitignore").read_text()

    def test_no_gitignore_for_user_scope(self, tmp_path, monkeypatch):
        """Does not modify gitignore for user scope."""
        import subprocess

        from statuskit.setup.commands import install_hook
        from statuskit.setup.paths import Scope

        home = tmp_path / "home"
        project = tmp_path / "project"
        (home / ".claude").mkdir(parents=True)
        project.mkdir()
        subprocess.run(["git", "init"], cwd=project, capture_output=True, check=False)

        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(project)

        result = install_hook(Scope.USER, force=False, ui=None)

        assert result.success is True
        assert result.gitignore_updated is False


class TestRemoveHook:
    """Tests for remove_hook function."""

    def test_removes_our_hook(self, tmp_path, monkeypatch):
        """Removes statuskit hook from settings."""
        from statuskit.setup.commands import remove_hook
        from statuskit.setup.paths import Scope

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "settings.json").write_text(
            json.dumps({"statusLine": {"command": "statuskit"}, "other": "setting"})
        )

        monkeypatch.setattr(Path, "home", lambda: home)

        result = remove_hook(Scope.USER, force=False, ui=None)

        assert result.success is True
        settings = json.loads((home / ".claude" / "settings.json").read_text())
        assert "statusLine" not in settings
        assert settings["other"] == "setting"

    def test_not_installed_returns_early(self, tmp_path, monkeypatch):
        """Returns early if not installed."""
        from statuskit.setup.commands import remove_hook
        from statuskit.setup.paths import Scope

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: home)

        result = remove_hook(Scope.USER, force=False, ui=None)

        assert result.not_installed is True

    def test_foreign_hook_requires_confirmation(self, tmp_path, monkeypatch):
        """Foreign hook requires confirmation or --force."""
        from statuskit.setup.commands import remove_hook
        from statuskit.setup.paths import Scope

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "settings.json").write_text(json.dumps({"statusLine": {"command": "other-script"}}))

        monkeypatch.setattr(Path, "home", lambda: home)

        result = remove_hook(Scope.USER, force=False, ui=None)

        assert result.success is False
        assert "other-script" in result.message
