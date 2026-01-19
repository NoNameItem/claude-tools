"""Tests for statuskit.core.config."""

from pathlib import Path

from statuskit.core.config import Config, load_config


def test_config_defaults():
    """Config has sensible defaults."""
    cfg = Config()

    assert cfg.debug is False
    assert cfg.modules == ["model", "git", "beads", "quota"]
    assert cfg.module_configs == {}


def test_config_get_module_config_missing():
    """get_module_config returns empty dict for missing module."""
    cfg = Config()
    assert cfg.get_module_config("model") == {}


def test_config_get_module_config_present():
    """get_module_config returns module config when present."""
    cfg = Config(module_configs={"model": {"show_duration": False}})
    assert cfg.get_module_config("model") == {"show_duration": False}


def test_load_config_no_file(tmp_path: Path, monkeypatch):
    """load_config returns defaults when config file missing."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.chdir(tmp_path)

    cfg = load_config()

    assert cfg.debug is False
    assert cfg.modules == ["model", "git", "beads", "quota"]


def test_load_config_with_file(tmp_path: Path, monkeypatch):
    """load_config parses TOML file."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    config_file = home / ".claude" / "statuskit.toml"
    config_file.write_text("""
debug = true
modules = ["model", "quota"]

[model]
show_duration = false
context_format = "bar"
""")

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(tmp_path)

    cfg = load_config()

    assert cfg.debug is True
    assert cfg.modules == ["model", "quota"]
    assert cfg.get_module_config("model") == {
        "show_duration": False,
        "context_format": "bar",
    }


def test_load_config_invalid_toml(tmp_path: Path, capsys, monkeypatch):
    """load_config shows error and returns defaults for invalid TOML."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    config_file = home / ".claude" / "statuskit.toml"
    config_file.write_text("invalid toml [[[")

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(tmp_path)

    cfg = load_config()

    # Should return defaults
    assert cfg.debug is False
    # Should print error
    captured = capsys.readouterr()
    assert "[!] Config error" in captured.out


class TestLoadConfigHierarchy:
    """Tests for hierarchical config loading."""

    def test_local_takes_priority(self, tmp_path, monkeypatch):
        """Local config overrides project and user."""
        home = tmp_path / "home"
        project = tmp_path / "project"

        # User config
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "statuskit.toml").write_text('modules = ["model"]')

        # Project config
        (project / ".claude").mkdir(parents=True)
        (project / ".claude" / "statuskit.toml").write_text('modules = ["git"]')

        # Local config
        (project / ".claude" / "statuskit.local.toml").write_text('modules = ["quota"]')

        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(project)

        config = load_config()

        assert config.modules == ["quota"]

    def test_project_takes_priority_over_user(self, tmp_path, monkeypatch):
        """Project config overrides user."""
        home = tmp_path / "home"
        project = tmp_path / "project"

        # User config
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "statuskit.toml").write_text('modules = ["model"]')

        # Project config
        (project / ".claude").mkdir(parents=True)
        (project / ".claude" / "statuskit.toml").write_text('modules = ["git"]')

        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(project)

        config = load_config()

        assert config.modules == ["git"]

    def test_user_used_when_no_project(self, tmp_path, monkeypatch):
        """User config used when no project config."""
        home = tmp_path / "home"
        project = tmp_path / "project"

        # User config only
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "statuskit.toml").write_text('modules = ["model"]')

        project.mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(project)

        config = load_config()

        assert config.modules == ["model"]
