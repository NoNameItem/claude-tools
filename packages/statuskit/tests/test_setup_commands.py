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
