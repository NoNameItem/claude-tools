"""Tests for validate_plugin.py script."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def temp_plugin(tmp_path: Path) -> Path:
    """Create minimal valid plugin structure."""
    plugin_dir = tmp_path / "plugins" / "test-plugin"
    plugin_dir.mkdir(parents=True)
    claude_plugin = plugin_dir / ".claude-plugin"
    claude_plugin.mkdir()
    (claude_plugin / "plugin.json").write_text(json.dumps({"name": "test-plugin", "version": "1.0.0"}))
    return plugin_dir


@pytest.fixture
def temp_marketplace(tmp_path: Path) -> Path:
    """Create marketplace.json in repo root."""
    claude_plugin = tmp_path / ".claude-plugin"
    claude_plugin.mkdir(exist_ok=True)
    marketplace = {
        "name": "test-marketplace",
        "plugins": [
            {
                "name": "test-plugin",
                "source": "./plugins/test-plugin",
            }
        ],
    }
    (claude_plugin / "marketplace.json").write_text(json.dumps(marketplace))
    return tmp_path


class TestValidatePluginJson:
    """Tests for plugin.json validation."""

    def test_valid_plugin(self, temp_plugin: Path, temp_marketplace: Path) -> None:
        """Should pass for valid plugin."""
        from ..validate_plugin import validate_plugin

        result = validate_plugin(temp_plugin, temp_marketplace)
        assert result.success is True
        assert result.errors == []

    def test_missing_plugin_json(self, tmp_path: Path) -> None:
        """Should fail when plugin.json not found."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "no-json"
        plugin_dir.mkdir(parents=True)

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("plugin.json not found" in e for e in result.errors)

    def test_invalid_json(self, tmp_path: Path) -> None:
        """Should fail for invalid JSON."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "bad-json"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text("not valid json {")

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("Invalid JSON" in e for e in result.errors)

    def test_missing_name(self, tmp_path: Path) -> None:
        """Should fail when name field is missing."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "no-name"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"version": "1.0.0"}')

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("Missing required field: name" in e for e in result.errors)

    def test_invalid_name_format(self, tmp_path: Path) -> None:
        """Should fail when name is not kebab-case."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "BadName"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "BadName"}')

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("must be kebab-case" in e for e in result.errors)

    def test_invalid_version(self, tmp_path: Path) -> None:
        """Should fail when version is not semver."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "bad-version"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "bad-version", "version": "not-semver"}')

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("must be semver" in e for e in result.errors)

    def test_invalid_path_format(self, tmp_path: Path) -> None:
        """Should fail when path doesn't start with ./"""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "bad-path"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "bad-path", "skills": "skills/"}')

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("must start with ./" in e for e in result.errors)
