#!/usr/bin/env python3
"""Validate Claude Code plugin structure.

Usage:
    python -m scripts.validate_plugin <plugin-path>

Exit codes:
    0 - Success
    1 - plugin.json not found or invalid JSON
    2 - Missing required field
    3 - Invalid format (name, version, paths)
    4 - Component structure invalid
    5 - Name collision between components
    6 - Plugin not registered in marketplace
    10 - Script error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Validation patterns
KEBAB_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$")
PATH_FIELDS = ["commands", "agents", "skills", "hooks", "mcpServers", "outputStyles", "lspServers"]


@dataclass
class PluginValidationResult:
    """Result of plugin validation."""

    success: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        """Add an error and mark as failed."""
        self.errors.append(message)
        self.success = False

    def add_warning(self, message: str) -> None:
        """Add a warning."""
        self.warnings.append(message)

    def merge(self, other: PluginValidationResult) -> None:
        """Merge another result into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        if not other.success:
            self.success = False


# noinspection D
def validate_plugin_json(plugin_path: Path) -> tuple[PluginValidationResult, dict | None]:
    """Validate plugin.json exists and has valid structure.

    Returns:
        Tuple of (result, plugin_json_data or None if invalid).
    """
    result = PluginValidationResult()
    plugin_json_path = plugin_path / ".claude-plugin" / "plugin.json"

    # Check file exists
    if not plugin_json_path.exists():
        result.add_error("plugin.json not found at .claude-plugin/plugin.json")
        return result, None

    # Parse JSON
    try:
        content = plugin_json_path.read_text()
        data = json.loads(content)
    except json.JSONDecodeError as e:
        result.add_error(f"Invalid JSON: {e}")
        return result, None

    # Required field: name
    if "name" not in data:
        result.add_error("Missing required field: name")
    elif not KEBAB_CASE_RE.match(data["name"]):
        result.add_error(f"Invalid name format: '{data['name']}' must be kebab-case")

    # Optional field: version (must be semver if present)
    if data.get("version"):
        if not SEMVER_RE.match(data["version"]):
            result.add_error(f"Invalid version format: '{data['version']}' must be semver")

    # Path fields must start with ./
    for field_name in PATH_FIELDS:
        if field_name in data:
            path_value = data[field_name]
            if isinstance(path_value, str) and not path_value.startswith("./"):
                result.add_error(f"Invalid path '{path_value}': must start with ./")

    return result, data if result.success else None


def validate_codex_manifest(
    plugin_path: Path,
    claude_manifest: dict,
    *,
    required: bool,
) -> PluginValidationResult:
    """Validate an optional Codex manifest and its parity with Claude metadata."""
    result = PluginValidationResult()
    path = plugin_path / ".codex-plugin" / "plugin.json"
    if not path.exists():
        if required:
            result.add_error("Codex plugin.json not found at .codex-plugin/plugin.json")
        return result

    try:
        manifest = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        result.add_error(f"Invalid Codex plugin.json: {exc}")
        return result

    if not isinstance(manifest, dict):
        result.add_error("Codex plugin.json must contain a JSON object")
        return result

    for metadata_key in ("name", "version"):
        if manifest.get(metadata_key) != claude_manifest.get(metadata_key):
            result.add_error(
                f"Codex manifest {metadata_key} {manifest.get(metadata_key)!r} does not match "
                f"Claude manifest {metadata_key} {claude_manifest.get(metadata_key)!r}"
            )

    for path_field in PATH_FIELDS:
        values = manifest.get(path_field, [])
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            result.add_error(f"Codex manifest field '{path_field}' must be a path or list of paths")
            continue
        for value in values:
            if not isinstance(value, str) or not value.startswith("./"):
                result.add_error(f"Codex manifest path must start with './': {value!r}")
                continue
            if not (plugin_path / value[2:]).exists():
                result.add_error(f"Codex manifest path does not exist: {value}")
    return result


def validate_plugin(
    plugin_path: Path,
    repo_root: Path,
    *,
    require_codex_manifest: bool = False,
) -> PluginValidationResult:
    """Validate complete plugin structure.

    Args:
        plugin_path: Path to plugin directory.
        repo_root: Path to repository root.
        require_codex_manifest: Whether the plugin must provide a Codex manifest.

    Returns:
        PluginValidationResult with all validation results.
    """
    # Validate plugin.json
    json_result, plugin_data = validate_plugin_json(plugin_path)
    if not json_result.success or plugin_data is None:
        return json_result

    result = PluginValidationResult()
    result.merge(json_result)

    codex_result = validate_codex_manifest(plugin_path, plugin_data, required=require_codex_manifest)
    result.merge(codex_result)

    # Validate components (Task 4)
    components_result = validate_components(plugin_path, plugin_data)
    result.merge(components_result)

    # Validate name uniqueness (Task 5)
    uniqueness_result = validate_name_uniqueness(plugin_path, plugin_data)
    result.merge(uniqueness_result)

    # Validate marketplace registration (Task 6)
    marketplace_result = validate_marketplace_registration(plugin_path, plugin_data, repo_root)
    result.merge(marketplace_result)

    return result


# noinspection D
def validate_components(plugin_path: Path, plugin_json: dict) -> PluginValidationResult:
    """Validate component directories and files exist.

    Checks:
    - skills: Each subfolder must contain SKILL.md
    - commands: Each file must have .md extension
    - agents: Each file must have .md extension
    """
    result = PluginValidationResult()

    # Get paths (custom or default)
    skills_path = plugin_json.get("skills", "./skills")
    commands_path = plugin_json.get("commands", "./commands")
    agents_path = plugin_json.get("agents", "./agents")

    # Normalize paths (remove ./ prefix)
    def normalize_path(p: str) -> str:
        return p[2:] if p.startswith("./") else p

    # Validate skills
    skills_dir = plugin_path / normalize_path(skills_path)
    if skills_dir.exists() and skills_dir.is_dir():
        for skill_folder in skills_dir.iterdir():
            if skill_folder.is_dir():
                skill_md = skill_folder / "SKILL.md"
                if not skill_md.exists():
                    result.add_error(
                        f"Skill '{skill_folder.name}' missing SKILL.md at {skill_folder.relative_to(plugin_path)}"
                    )

    # Validate commands
    commands_dir = plugin_path / normalize_path(commands_path)
    if commands_dir.exists() and commands_dir.is_dir():
        for cmd_file in commands_dir.iterdir():
            if cmd_file.is_file() and not cmd_file.name.endswith(".md"):
                result.add_error(f"Command file '{cmd_file.name}' must have .md extension")

    # Validate agents
    agents_dir = plugin_path / normalize_path(agents_path)
    if agents_dir.exists() and agents_dir.is_dir():
        for agent_file in agents_dir.iterdir():
            if agent_file.is_file() and not agent_file.name.endswith(".md"):
                result.add_error(f"Agent file '{agent_file.name}' must have .md extension")

    return result


def collect_component_names(plugin_path: Path, plugin_json: dict) -> dict[str, list[str]]:
    """Collect component names from all component directories.

    Returns:
        Dict mapping component type to list of names.
        {"skill": ["name1", "name2"], "command": ["name3"], "agent": ["name4"]}
    """
    names: dict[str, list[str]] = {"skill": [], "command": [], "agent": []}

    # Get paths (custom or default)
    skills_path = plugin_json.get("skills", "./skills")
    commands_path = plugin_json.get("commands", "./commands")
    agents_path = plugin_json.get("agents", "./agents")

    def normalize_path(p: str) -> str:
        return p[2:] if p.startswith("./") else p

    # Collect skill names (folder names)
    skills_dir = plugin_path / normalize_path(skills_path)
    if skills_dir.exists() and skills_dir.is_dir():
        for skill_folder in skills_dir.iterdir():
            if skill_folder.is_dir():
                names["skill"].append(skill_folder.name)

    # Collect command names (file names without .md)
    commands_dir = plugin_path / normalize_path(commands_path)
    if commands_dir.exists() and commands_dir.is_dir():
        for cmd_file in commands_dir.iterdir():
            if cmd_file.is_file() and cmd_file.name.endswith(".md"):
                names["command"].append(cmd_file.stem)

    # Collect agent names (file names without .md)
    agents_dir = plugin_path / normalize_path(agents_path)
    if agents_dir.exists() and agents_dir.is_dir():
        for agent_file in agents_dir.iterdir():
            if agent_file.is_file() and agent_file.name.endswith(".md"):
                names["agent"].append(agent_file.stem)

    return names


def validate_name_uniqueness(plugin_path: Path, plugin_json: dict) -> PluginValidationResult:
    """Validate no name collisions between components.

    A name collision occurs when the same name exists in multiple
    component types (e.g., skill and command both named "review").
    """
    result = PluginValidationResult()
    names = collect_component_names(plugin_path, plugin_json)

    # Build name -> component_types mapping
    name_to_types: dict[str, list[str]] = {}
    for component_type, component_names in names.items():
        for name in component_names:
            if name not in name_to_types:
                name_to_types[name] = []
            name_to_types[name].append(component_type)

    # Check for collisions
    for name, types in name_to_types.items():
        if len(types) > 1:
            result.add_error(f"Name collision: '{name}' exists in both {types[0]}s and {types[1]}s")

    return result


def _source_matches(mp_source: object, expected_relative: str) -> tuple[bool, str | None]:
    """Check a marketplace `source` against a plugin's location.

    Accepts the legacy relative-path string ("./plugins/<name>") and the
    tag-pinned git-subdir object form.

    Returns (matches, structural_error):
      - (True, None)   this entry is for this plugin and is well-formed.
      - (False, None)  this entry is NOT for this plugin (no match, no error).
      - (False, msg)   this entry IS for this plugin but is malformed.
    """
    if isinstance(mp_source, str):
        return mp_source == f"./{expected_relative}", None

    if not isinstance(mp_source, dict):
        return False, f"unsupported source value: {mp_source!r}"

    path = mp_source.get("path")
    if not path or path != expected_relative:
        return False, None  # object source for a different plugin

    # Path matches — validate the remaining fields.
    err: str | None = None
    if mp_source.get("source") != "git-subdir":
        err = f"source type must be 'git-subdir', got '{mp_source.get('source')}'"
    elif not mp_source.get("url"):
        err = "git-subdir source missing 'url'"
    elif not mp_source.get("ref"):
        err = "git-subdir source missing 'ref'"

    return err is None, err


def validate_marketplace_registration(plugin_path: Path, plugin_json: dict, repo_root: Path) -> PluginValidationResult:
    """Validate plugin is registered in marketplace.

    Checks:
    - Plugin is listed in .claude-plugin/marketplace.json
    - Name matches between plugin.json and marketplace
    - Source path matches plugin location
    """
    result = PluginValidationResult()
    marketplace_path = repo_root / ".claude-plugin" / "marketplace.json"

    # Check marketplace exists
    if not marketplace_path.exists():
        result.add_error("marketplace.json not found at .claude-plugin/marketplace.json")
        return result

    # Parse marketplace
    try:
        marketplace_data = json.loads(marketplace_path.read_text())
    except json.JSONDecodeError as e:
        result.add_error(f"Invalid marketplace.json: {e}")
        return result

    plugins = marketplace_data.get("plugins", [])
    plugin_name = plugin_json.get("name", "")

    # Expected plugin location relative to repo root, e.g. "plugins/flow".
    try:
        expected_relative = str(plugin_path.relative_to(repo_root))
    except ValueError:
        expected_relative = f"plugins/{plugin_path.name}"

    # Find plugin in marketplace by name (or by source pointing at its location).
    found = False
    for mp_plugin in plugins:
        mp_name = mp_plugin.get("name", "")
        mp_source = mp_plugin.get("source", "")
        source_ok, source_err = _source_matches(mp_source, expected_relative)

        if mp_name == plugin_name:
            found = True
            if source_err is not None:
                result.add_error(f"Marketplace source invalid for '{plugin_name}': {source_err}")
            elif not source_ok:
                result.add_error(f"Marketplace source mismatch: '{mp_name}' does not point at '{expected_relative}'")
            break

        # Entry not matched by name, but its source points at this plugin's location.
        if source_ok:
            found = True
            result.add_error(f"Name mismatch: plugin.json has '{plugin_name}', marketplace has '{mp_name}'")
            break

    if not found:
        result.add_error(f"Plugin '{plugin_name}' not registered in marketplace")

    return result


def main() -> int:  # noqa: PLR0911
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Validate Claude Code plugin structure")
    parser.add_argument(
        "--require-codex-manifest",
        action="store_true",
        help="Require a matching .codex-plugin/plugin.json",
    )
    parser.add_argument("plugin_path", type=Path)
    args = parser.parse_args()

    plugin_path = args.plugin_path
    if not plugin_path.exists():
        print(f"Error: Plugin path does not exist: {plugin_path}", file=sys.stderr)
        return 10

    # Find repo root (look for .git directory)
    repo_root = plugin_path
    while repo_root != repo_root.parent:
        if (repo_root / ".git").exists():
            break
        repo_root = repo_root.parent
    else:
        repo_root = Path.cwd()

    try:
        result = validate_plugin(
            plugin_path,
            repo_root,
            require_codex_manifest=args.require_codex_manifest,
        )
    except Exception as e:
        print(f"Script error: {e}", file=sys.stderr)
        return 10

    if result.warnings:
        for warning in result.warnings:
            print(f"Warning: {warning}")

    if not result.success:
        for error in result.errors:
            print(f"Error: {error}")
        # Determine exit code based on first error type
        first_error = result.errors[0] if result.errors else ""
        if "not found" in first_error or "Invalid JSON" in first_error:
            return 1
        if "Missing required" in first_error:
            return 2
        if "Invalid" in first_error:
            return 3
        return 1

    print(f"Plugin '{plugin_path.name}' is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
