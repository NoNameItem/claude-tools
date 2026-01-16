"""Tests for statuskit.core.config."""

from pathlib import Path
from unittest.mock import patch

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


def test_load_config_no_file(tmp_path: Path):
    """load_config returns defaults when config file missing."""
    with patch("statuskit.core.config.CONFIG_PATH", tmp_path / "nonexistent.toml"):
        cfg = load_config()

    assert cfg.debug is False
    assert cfg.modules == ["model", "git", "beads", "quota"]


def test_load_config_with_file(tmp_path: Path):
    """load_config parses TOML file."""
    config_file = tmp_path / "statuskit.toml"
    config_file.write_text("""
debug = true
modules = ["model", "quota"]

[model]
show_duration = false
context_format = "bar"
""")

    with patch("statuskit.core.config.CONFIG_PATH", config_file):
        cfg = load_config()

    assert cfg.debug is True
    assert cfg.modules == ["model", "quota"]
    assert cfg.get_module_config("model") == {
        "show_duration": False,
        "context_format": "bar",
    }


def test_load_config_invalid_toml(tmp_path: Path, capsys):
    """load_config shows error and returns defaults for invalid TOML."""
    config_file = tmp_path / "statuskit.toml"
    config_file.write_text("invalid toml [[[")

    with patch("statuskit.core.config.CONFIG_PATH", config_file):
        cfg = load_config()

    # Should return defaults
    assert cfg.debug is False
    # Should print error
    captured = capsys.readouterr()
    assert "[!] Config error:" in captured.out
