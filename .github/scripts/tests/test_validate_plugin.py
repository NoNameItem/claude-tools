"""Tests for validate_plugin.py script."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def temp_plugin(tmp_path: Path) -> Path:
    """
    Create a minimal plugin directory structure for tests.
    
    Creates plugins/test-plugin with a .claude-plugin subdirectory containing a plugin.json
    file with name "test-plugin" and version "1.0.0".
    
    Returns:
        Path: Path to the created plugin directory (plugins/test-plugin).
    """
    plugin_dir = tmp_path / "plugins" / "test-plugin"
    plugin_dir.mkdir(parents=True)
    claude_plugin = plugin_dir / ".claude-plugin"
    claude_plugin.mkdir()
    (claude_plugin / "plugin.json").write_text(json.dumps({"name": "test-plugin", "version": "1.0.0"}))
    return plugin_dir


@pytest.fixture
def temp_marketplace(tmp_path: Path) -> Path:
    """
    Create a minimal marketplace.json under a .claude-plugin directory in the given repository root.
    
    Parameters:
        tmp_path (Path): Path to the repository root (pytest tmp_path fixture).
    
    Returns:
        repo_root (Path): The same tmp_path provided, representing the repository root.
    """
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
        """
        Check that plugin validation fails for a plugin.json with a non-semantic-version `version` field.
        
        Asserts that validation reports failure and that at least one error message contains "must be semver".
        """
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


class TestValidateComponents:
    """Tests for component validation."""

    def test_skill_missing_skill_md(self, tmp_path: Path) -> None:
        """Should fail when skill folder lacks SKILL.md."""
        from ..validate_plugin import validate_plugin

        # Create plugin with skill folder but no SKILL.md
        plugin_dir = tmp_path / "plugins" / "missing-skill-md"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "missing-skill-md"}')

        # Create skill folder without SKILL.md
        skills_dir = plugin_dir / "skills" / "my-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "helper.py").write_text("# helper")

        # Create marketplace
        mp = tmp_path / ".claude-plugin"
        mp.mkdir(exist_ok=True)
        (mp / "marketplace.json").write_text(
            '{"plugins": [{"name": "missing-skill-md", "source": "./plugins/missing-skill-md"}]}'
        )

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("SKILL.md" in e for e in result.errors)

    def test_valid_skill_structure(self, tmp_path: Path) -> None:
        """Should pass for valid skill structure."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "valid-skills"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "valid-skills"}')

        # Create valid skill folder
        skills_dir = plugin_dir / "skills" / "my-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("# My Skill")

        # Create marketplace
        mp = tmp_path / ".claude-plugin"
        mp.mkdir(exist_ok=True)
        (mp / "marketplace.json").write_text(
            '{"plugins": [{"name": "valid-skills", "source": "./plugins/valid-skills"}]}'
        )

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is True

    def test_command_missing_md_extension(self, tmp_path: Path) -> None:
        """Should fail when command file lacks .md extension."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "bad-command"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "bad-command"}')

        # Create commands folder with non-.md file
        commands_dir = plugin_dir / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "my-command.txt").write_text("# Not md")

        # Create marketplace
        mp = tmp_path / ".claude-plugin"
        mp.mkdir(exist_ok=True)
        (mp / "marketplace.json").write_text(
            '{"plugins": [{"name": "bad-command", "source": "./plugins/bad-command"}]}'
        )

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any(".md extension" in e for e in result.errors)

    def test_custom_skills_path(self, tmp_path: Path) -> None:
        """
        Verify that validation fails when a plugin specifies a custom skills path and a skill directory there is missing `SKILL.md`.
        
        The test creates a plugin whose `plugin.json` sets `"skills": "./custom-skills"`, places a skill directory without `SKILL.md` under that custom path, and asserts that validate_plugin reports failure and includes an error mentioning `SKILL.md`.
        """
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "custom-path"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "custom-path", "skills": "./custom-skills"}')

        # Create skill at custom path without SKILL.md
        custom_skills = plugin_dir / "custom-skills" / "my-skill"
        custom_skills.mkdir(parents=True)
        (custom_skills / "helper.py").write_text("# no SKILL.md")

        # Create marketplace
        mp = tmp_path / ".claude-plugin"
        mp.mkdir(exist_ok=True)
        (mp / "marketplace.json").write_text(
            '{"plugins": [{"name": "custom-path", "source": "./plugins/custom-path"}]}'
        )

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("SKILL.md" in e for e in result.errors)


class TestValidateNameUniqueness:
    """Tests for name uniqueness validation."""

    def test_name_collision_skill_command(self, tmp_path: Path) -> None:
        """
        Verifies that validation fails when a plugin defines a skill and a command with the same name.
        
        The test expects validation errors that mention a naming collision and include the conflicting name ("review").
        """
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "name-collision"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "name-collision"}')

        # Create skill named "review"
        skills_dir = plugin_dir / "skills" / "review"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("# Review skill")

        # Create command named "review"
        commands_dir = plugin_dir / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "review.md").write_text("# Review command")

        # Create marketplace
        mp = tmp_path / ".claude-plugin"
        mp.mkdir(exist_ok=True)
        (mp / "marketplace.json").write_text(
            '{"plugins": [{"name": "name-collision", "source": "./plugins/name-collision"}]}'
        )

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("collision" in e.lower() for e in result.errors)
        assert any("review" in e.lower() for e in result.errors)

    def test_no_collision_different_names(self, tmp_path: Path) -> None:
        """Should pass when all component names are unique."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "unique-names"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "unique-names"}')

        # Create skill named "analyze"
        skills_dir = plugin_dir / "skills" / "analyze"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("# Analyze skill")

        # Create command named "report"
        commands_dir = plugin_dir / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "report.md").write_text("# Report command")

        # Create marketplace
        mp = tmp_path / ".claude-plugin"
        mp.mkdir(exist_ok=True)
        (mp / "marketplace.json").write_text(
            '{"plugins": [{"name": "unique-names", "source": "./plugins/unique-names"}]}'
        )

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is True


class TestValidateMarketplace:
    """Tests for marketplace registration validation."""

    def test_not_in_marketplace(self, tmp_path: Path) -> None:
        """Should fail when plugin not registered in marketplace."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "not-registered"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "not-registered"}')

        # Create marketplace without this plugin
        mp = tmp_path / ".claude-plugin"
        mp.mkdir(exist_ok=True)
        (mp / "marketplace.json").write_text('{"plugins": []}')

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("not registered in marketplace" in e for e in result.errors)

    def test_marketplace_name_mismatch(self, tmp_path: Path) -> None:
        """Should fail when marketplace name doesn't match plugin.json."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "name-mismatch"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "name-mismatch"}')

        # Create marketplace with different name
        mp = tmp_path / ".claude-plugin"
        mp.mkdir(exist_ok=True)
        (mp / "marketplace.json").write_text(
            '{"plugins": [{"name": "wrong-name", "source": "./plugins/name-mismatch"}]}'
        )

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("mismatch" in e.lower() for e in result.errors)

    def test_marketplace_source_mismatch(self, tmp_path: Path) -> None:
        """Should fail when marketplace source doesn't match plugin path."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "source-mismatch"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "source-mismatch"}')

        # Create marketplace with wrong source
        mp = tmp_path / ".claude-plugin"
        mp.mkdir(exist_ok=True)
        (mp / "marketplace.json").write_text(
            '{"plugins": [{"name": "source-mismatch", "source": "./plugins/wrong-path"}]}'
        )

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("source mismatch" in e.lower() for e in result.errors)

    def test_missing_marketplace_file(self, tmp_path: Path) -> None:
        """Should fail when marketplace.json doesn't exist."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "no-marketplace"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "no-marketplace"}')

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("marketplace.json" in e for e in result.errors)