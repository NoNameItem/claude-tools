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


def write_codex_manifest(plugin: Path, **overrides: object) -> None:
    """Create a Codex manifest with valid default metadata."""
    payload: dict[str, object] = {
        "name": "test-plugin",
        "version": "1.0.0",
        "skills": "./skills/",
        "hooks": "./hooks/codex-hooks.json",
    }
    payload.update(overrides)
    target = plugin / ".codex-plugin"
    target.mkdir(exist_ok=True)
    (target / "plugin.json").write_text(json.dumps(payload))


def test_required_codex_manifest_is_missing(temp_plugin: Path) -> None:
    """Should fail when a required Codex manifest is missing."""
    from ..validate_plugin import validate_codex_manifest

    result = validate_codex_manifest(
        temp_plugin,
        {"name": "test-plugin", "version": "1.0.0"},
        required=True,
    )
    assert result.errors == ["Codex plugin.json not found at .codex-plugin/plugin.json"]


def test_codex_manifest_must_match_name_and_version(temp_plugin: Path) -> None:
    """Should fail when Codex and Claude metadata differ."""
    from ..validate_plugin import validate_codex_manifest

    write_codex_manifest(temp_plugin, name="other", version="2.0.0")
    result = validate_codex_manifest(
        temp_plugin,
        {"name": "test-plugin", "version": "1.0.0"},
        required=True,
    )
    assert "Codex manifest name 'other' does not match Claude manifest name 'test-plugin'" in result.errors
    assert "Codex manifest version '2.0.0' does not match Claude manifest version '1.0.0'" in result.errors


def test_codex_manifest_paths_must_exist(temp_plugin: Path) -> None:
    """Should fail when a declared Codex component path is missing."""
    from ..validate_plugin import validate_codex_manifest

    write_codex_manifest(temp_plugin)
    result = validate_codex_manifest(
        temp_plugin,
        {"name": "test-plugin", "version": "1.0.0"},
        required=True,
    )
    assert "Codex manifest path does not exist: ./hooks/codex-hooks.json" in result.errors


def test_codex_manifest_path_must_not_traverse_outside_plugin(temp_plugin: Path) -> None:
    """Should reject a parent traversal even when its target exists."""
    from ..validate_plugin import validate_codex_manifest

    (temp_plugin.parent / "outside").mkdir()
    write_codex_manifest(temp_plugin, skills="./../outside", hooks=[])

    result = validate_codex_manifest(
        temp_plugin,
        {"name": "test-plugin", "version": "1.0.0"},
        required=True,
    )

    assert "Codex manifest path escapes plugin directory: ./../outside" in result.errors


def test_codex_manifest_path_must_not_be_absolute_after_prefix_strip(temp_plugin: Path) -> None:
    """Should reject a path that becomes absolute after removing './'."""
    from ..validate_plugin import validate_codex_manifest

    write_codex_manifest(temp_plugin, skills=".//tmp", hooks=[])

    result = validate_codex_manifest(
        temp_plugin,
        {"name": "test-plugin", "version": "1.0.0"},
        required=True,
    )

    assert "Codex manifest path escapes plugin directory: .//tmp" in result.errors


def test_codex_manifest_symlink_must_not_escape_plugin(temp_plugin: Path) -> None:
    """Should reject an existing in-plugin symlink whose target is outside."""
    from ..validate_plugin import validate_codex_manifest

    outside = temp_plugin.parents[1] / "outside"
    outside.mkdir()
    (temp_plugin / "outside-link").symlink_to(outside, target_is_directory=True)
    write_codex_manifest(temp_plugin, skills="./outside-link", hooks=[])

    result = validate_codex_manifest(
        temp_plugin,
        {"name": "test-plugin", "version": "1.0.0"},
        required=True,
    )

    assert "Codex manifest path escapes plugin directory: ./outside-link" in result.errors


CLAUDE_METADATA = {"name": "test-plugin", "version": "1.0.0"}


def test_codex_apps_accepts_single_existing_path(temp_plugin: Path) -> None:
    """Should accept `apps` as a single path to an existing file."""
    from ..validate_plugin import validate_codex_manifest

    (temp_plugin / "flow.app.json").write_text("{}")
    write_codex_manifest(temp_plugin, skills=[], hooks=[], apps="./flow.app.json")

    result = validate_codex_manifest(temp_plugin, CLAUDE_METADATA, required=True)

    assert result.errors == []


def test_codex_apps_rejects_a_list(temp_plugin: Path) -> None:
    """Codex allows only a single path string for `apps`."""
    from ..validate_plugin import validate_codex_manifest

    (temp_plugin / "flow.app.json").write_text("{}")
    write_codex_manifest(temp_plugin, skills=[], hooks=[], apps=["./flow.app.json"])

    result = validate_codex_manifest(temp_plugin, CLAUDE_METADATA, required=True)

    assert "Codex manifest field 'apps' must be a single path string" in result.errors


def test_codex_apps_path_must_exist(temp_plugin: Path) -> None:
    """Should fail when `apps` points at a missing file."""
    from ..validate_plugin import validate_codex_manifest

    write_codex_manifest(temp_plugin, skills=[], hooks=[], apps="./missing.app.json")

    result = validate_codex_manifest(temp_plugin, CLAUDE_METADATA, required=True)

    assert "Codex manifest path does not exist: ./missing.app.json" in result.errors


def test_codex_hooks_accepts_inline_object(temp_plugin: Path) -> None:
    """Codex allows an inline hook object instead of a path."""
    from ..validate_plugin import validate_codex_manifest

    write_codex_manifest(temp_plugin, skills=[], hooks={"SessionStart": [{"command": "echo hi"}]})

    result = validate_codex_manifest(temp_plugin, CLAUDE_METADATA, required=True)

    assert result.errors == []


def test_codex_hooks_accepts_inline_object_list(temp_plugin: Path) -> None:
    """Codex allows a list of inline hook objects."""
    from ..validate_plugin import validate_codex_manifest

    write_codex_manifest(temp_plugin, skills=[], hooks=[{"SessionStart": []}, {"PreToolUse": []}])

    result = validate_codex_manifest(temp_plugin, CLAUDE_METADATA, required=True)

    assert result.errors == []


def test_codex_hooks_rejects_mixed_list(temp_plugin: Path) -> None:
    """A list mixing paths and inline objects is not a Codex shape."""
    from ..validate_plugin import validate_codex_manifest

    write_codex_manifest(temp_plugin, skills=[], hooks=["./hooks/codex-hooks.json", {"SessionStart": []}])

    result = validate_codex_manifest(temp_plugin, CLAUDE_METADATA, required=True)

    assert any("Codex manifest field 'hooks' must be" in error for error in result.errors)


def test_codex_mcp_servers_accepts_inline_object(temp_plugin: Path) -> None:
    """Codex allows an inline mcpServers object."""
    from ..validate_plugin import validate_codex_manifest

    write_codex_manifest(temp_plugin, skills=[], hooks=[], mcpServers={"beads": {"command": "bd"}})

    result = validate_codex_manifest(temp_plugin, CLAUDE_METADATA, required=True)

    assert result.errors == []


def test_codex_mcp_servers_path_is_validated(temp_plugin: Path) -> None:
    """A string mcpServers value is still validated as a path."""
    from ..validate_plugin import validate_codex_manifest

    write_codex_manifest(temp_plugin, skills=[], hooks=[], mcpServers="./missing-mcp.json")

    result = validate_codex_manifest(temp_plugin, CLAUDE_METADATA, required=True)

    assert "Codex manifest path does not exist: ./missing-mcp.json" in result.errors


def test_codex_mcp_servers_rejects_a_list(temp_plugin: Path) -> None:
    """Codex has no list form for mcpServers."""
    from ..validate_plugin import validate_codex_manifest

    write_codex_manifest(temp_plugin, skills=[], hooks=[], mcpServers=["./mcp.json"])

    result = validate_codex_manifest(temp_plugin, CLAUDE_METADATA, required=True)

    assert "Codex manifest field 'mcpServers' must be a path or an inline object" in result.errors


def test_codex_ignores_non_codex_fields(temp_plugin: Path) -> None:
    """`agents` is not a Codex field, so it must not produce a path error."""
    from ..validate_plugin import validate_codex_manifest

    write_codex_manifest(temp_plugin, skills=[], hooks=[], agents="./missing-agents")

    result = validate_codex_manifest(temp_plugin, CLAUDE_METADATA, required=True)

    assert result.errors == []


def test_optional_codex_manifest_absence_is_allowed(temp_plugin: Path, temp_marketplace: Path) -> None:
    """Should keep Codex support optional when no Codex manifest exists."""
    from ..validate_plugin import validate_plugin

    result = validate_plugin(temp_plugin, temp_marketplace)

    assert result.success is True
    assert result.errors == []


def test_optional_invalid_codex_manifest_fails(temp_plugin: Path, temp_marketplace: Path) -> None:
    """Should validate a Codex manifest whenever one is present."""
    from ..validate_plugin import validate_plugin

    target = temp_plugin / ".codex-plugin"
    target.mkdir()
    (target / "plugin.json").write_text("{not valid JSON")

    result = validate_plugin(temp_plugin, temp_marketplace)

    assert result.success is False
    assert any("Invalid Codex plugin.json" in error for error in result.errors)


def test_main_without_plugin_path_returns_script_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Should preserve the historical return-code contract for missing CLI input."""
    from ..validate_plugin import main

    monkeypatch.setattr("sys.argv", ["validate_plugin.py"])

    assert main() == 10
    assert "usage:" in capsys.readouterr().err.lower()


def test_main_requires_codex_manifest_when_flag_is_set(
    temp_plugin: Path,
    temp_marketplace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Should pass --require-codex-manifest through main to validation."""
    from ..validate_plugin import main

    (temp_marketplace / ".git").mkdir()
    monkeypatch.setattr(
        "sys.argv",
        ["validate_plugin.py", "--require-codex-manifest", str(temp_plugin)],
    )

    assert main() == 1
    assert "Codex plugin.json not found at .codex-plugin/plugin.json" in capsys.readouterr().out


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
        """Should validate skills at custom path."""
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
        """Should fail when same name in skills and commands."""
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

    def test_object_source_valid(self, tmp_path: Path) -> None:
        """Should pass for a tag-pinned git-subdir object source."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "obj-ok"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "obj-ok", "version": "2.1.0"}')

        mp = tmp_path / ".claude-plugin"
        mp.mkdir(exist_ok=True)
        (mp / "marketplace.json").write_text(
            json.dumps(
                {
                    "plugins": [
                        {
                            "name": "obj-ok",
                            "source": {
                                "source": "git-subdir",
                                "url": "NoNameItem/claude-tools",
                                "path": "plugins/obj-ok",
                                "ref": "obj-ok-2.1.0",
                            },
                        }
                    ]
                }
            )
        )

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is True
        assert result.errors == []

    def test_object_source_wrong_path(self, tmp_path: Path) -> None:
        """Should fail when object source.path points elsewhere."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "obj-path"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "obj-path"}')

        mp = tmp_path / ".claude-plugin"
        mp.mkdir(exist_ok=True)
        (mp / "marketplace.json").write_text(
            json.dumps(
                {
                    "plugins": [
                        {
                            "name": "obj-path",
                            "source": {
                                "source": "git-subdir",
                                "url": "NoNameItem/claude-tools",
                                "path": "plugins/somewhere-else",
                                "ref": "obj-path-1.0.0",
                            },
                        }
                    ]
                }
            )
        )

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("does not point at" in e for e in result.errors)

    def test_object_source_missing_ref(self, tmp_path: Path) -> None:
        """Should fail when a git-subdir object source has no ref."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "obj-ref"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "obj-ref"}')

        mp = tmp_path / ".claude-plugin"
        mp.mkdir(exist_ok=True)
        (mp / "marketplace.json").write_text(
            json.dumps(
                {
                    "plugins": [
                        {
                            "name": "obj-ref",
                            "source": {
                                "source": "git-subdir",
                                "url": "NoNameItem/claude-tools",
                                "path": "plugins/obj-ref",
                            },
                        }
                    ]
                }
            )
        )

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("ref" in e.lower() for e in result.errors)

    def test_object_source_wrong_type(self, tmp_path: Path) -> None:
        """Should fail when object source type is not git-subdir."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "obj-type"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "obj-type"}')

        mp = tmp_path / ".claude-plugin"
        mp.mkdir(exist_ok=True)
        (mp / "marketplace.json").write_text(
            json.dumps(
                {
                    "plugins": [
                        {
                            "name": "obj-type",
                            "source": {
                                "source": "github",
                                "url": "NoNameItem/claude-tools",
                                "path": "plugins/obj-type",
                                "ref": "obj-type-1.0.0",
                            },
                        }
                    ]
                }
            )
        )

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("git-subdir" in e for e in result.errors)

    def test_object_source_unsupported_value(self, tmp_path: Path) -> None:
        """Should fail when a matching entry has a non-string, non-object source."""
        from ..validate_plugin import validate_plugin

        plugin_dir = tmp_path / "plugins" / "obj-bad"
        plugin_dir.mkdir(parents=True)
        claude_plugin = plugin_dir / ".claude-plugin"
        claude_plugin.mkdir()
        (claude_plugin / "plugin.json").write_text('{"name": "obj-bad"}')

        mp = tmp_path / ".claude-plugin"
        mp.mkdir(exist_ok=True)
        (mp / "marketplace.json").write_text(json.dumps({"plugins": [{"name": "obj-bad", "source": 42}]}))

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("unsupported source value" in e for e in result.errors)
