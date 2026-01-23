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


def validate_plugin(plugin_path: Path, repo_root: Path) -> PluginValidationResult:
    """Validate complete plugin structure.

    Args:
        plugin_path: Path to plugin directory.
        repo_root: Path to repository root.

    Returns:
        PluginValidationResult with all validation results.
    """
    # Validate plugin.json
    json_result, plugin_data = validate_plugin_json(plugin_path)
    if not json_result.success or plugin_data is None:
        return json_result

    result = PluginValidationResult()
    result.merge(json_result)

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


def validate_components(_plugin_path: Path, _plugin_json: dict) -> PluginValidationResult:
    """Validate component directories and files exist."""
    # Placeholder - implemented in Task 4
    return PluginValidationResult()


def validate_name_uniqueness(_plugin_path: Path, _plugin_json: dict) -> PluginValidationResult:
    """Validate no name collisions between components."""
    # Placeholder - implemented in Task 5
    return PluginValidationResult()


def validate_marketplace_registration(
    _plugin_path: Path, _plugin_json: dict, _repo_root: Path
) -> PluginValidationResult:
    """Validate plugin is registered in marketplace."""
    # Placeholder - implemented in Task 6
    return PluginValidationResult()


def main() -> int:  # noqa: PLR0911, PLR0912
    """Main entry point."""
    if len(sys.argv) < 2:  # noqa: PLR2004
        print("Usage: python -m scripts.validate_plugin <plugin-path>", file=sys.stderr)
        return 10

    plugin_path = Path(sys.argv[1])
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
        result = validate_plugin(plugin_path, repo_root)
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
