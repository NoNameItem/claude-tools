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
        """
        Record an error message and mark the validation result as unsuccessful.
        
        Parameters:
            message (str): Error message to append to the result's error list.
        """
        self.errors.append(message)
        self.success = False

    def add_warning(self, message: str) -> None:
        """
        Record a warning message in the validation result.
        
        Appends the given message to the `warnings` list without modifying the `success` flag.
        
        Parameters:
            message (str): The warning text to add.
        """
        self.warnings.append(message)

    def merge(self, other: PluginValidationResult) -> None:
        """
        Merge another PluginValidationResult into this result.
        
        Appends the other's errors and warnings and marks this result as unsuccessful if the other.result indicates failure.
        
        Parameters:
            other (PluginValidationResult): Result to merge into this result.
        """
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        if not other.success:
            self.success = False


# noinspection D
def validate_plugin_json(plugin_path: Path) -> tuple[PluginValidationResult, dict | None]:
    """
    Validate the plugin.json file inside the given plugin directory and return structured validation feedback.
    
    Performs existence check, JSON parsing, ensures a required `name` in kebab-case, validates `version` (if present) against semver, and ensures path-like fields start with "./".
    
    Returns:
        tuple: `result` — PluginValidationResult containing collected errors and warnings; `data` — the parsed plugin.json dictionary, or `None` if validation failed.
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
    """
    Validate a plugin directory and return an aggregated validation result.
    
    Runs all validation steps (plugin.json, components, name uniqueness, and marketplace registration)
    and merges their findings into a single PluginValidationResult.
    
    Parameters:
        plugin_path (Path): Path to the plugin directory to validate.
        repo_root (Path): Path to the repository root used to locate marketplace.json and compute expected sources.
    
    Returns:
        PluginValidationResult: Aggregated result containing success flag, errors, and warnings.
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


# noinspection D
def validate_components(plugin_path: Path, plugin_json: dict) -> PluginValidationResult:
    """
    Validate plugin component directories and their required files.
    
    Performs these checks based on the plugin_json paths (defaults: "./skills", "./commands", "./agents"):
    - skills: for each subdirectory, verifies a SKILL.md file exists.
    - commands: verifies every file in the commands directory has a `.md` extension.
    - agents: verifies every file in the agents directory has a `.md` extension.
    
    Parameters:
        plugin_json (dict): Parsed plugin.json whose keys `skills`, `commands`, and `agents` may override the default relative paths.
    
    Returns:
        PluginValidationResult: Aggregated validation result containing errors for missing SKILL.md files or non-`.md` command/agent files; `success` is true if no errors were recorded.
    """
    result = PluginValidationResult()

    # Get paths (custom or default)
    skills_path = plugin_json.get("skills", "./skills")
    commands_path = plugin_json.get("commands", "./commands")
    agents_path = plugin_json.get("agents", "./agents")

    # Normalize paths (remove ./ prefix)
    def normalize_path(p: str) -> str:
        """
        Strip a leading "./" from a path string.
        
        Returns:
            The input string with a leading "./" removed if present, otherwise the original string.
        """
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
    """
    Collect names of skills, commands, and agents from the plugin directory based on paths in plugin_json.
    
    Parameters:
        plugin_path (Path): Root path of the plugin repository containing the component directories.
        plugin_json (dict): Parsed .claude-plugin/plugin.json providing optional keys "skills", "commands", and "agents" which may override default relative paths.
    
    Returns:
        dict[str, list[str]]: Mapping with keys "skill", "command", and "agent" to lists of component names. Skill names are directory names under the skills path; command and agent names are file stems of `.md` files under their respective paths. Paths in plugin_json may use the "./" prefix; defaults are "./skills", "./commands", and "./agents".
    """
    names: dict[str, list[str]] = {"skill": [], "command": [], "agent": []}

    # Get paths (custom or default)
    skills_path = plugin_json.get("skills", "./skills")
    commands_path = plugin_json.get("commands", "./commands")
    agents_path = plugin_json.get("agents", "./agents")

    def normalize_path(p: str) -> str:
        """
        Strip a leading "./" from a path string.
        
        Returns:
            The input string with a leading "./" removed if present, otherwise the original string.
        """
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
    """
    Check for duplicate component names across skills, commands, and agents.
    
    Parameters:
        plugin_path (Path): Path to the plugin root directory used when resolving component locations.
        plugin_json (dict): Parsed plugin.json data used to determine component paths and configuration.
    
    Returns:
        PluginValidationResult: Result containing an error for each name that appears in more than one component type; `success` is false if any collisions are found.
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


def validate_marketplace_registration(plugin_path: Path, plugin_json: dict, repo_root: Path) -> PluginValidationResult:
    """
    Validate that the plugin is registered correctly in the repository marketplace.
    
    Validates that .claude-plugin/marketplace.json exists at the repository root, can be parsed, and contains an entry that corresponds to the plugin. Computes the expected marketplace `source` for the plugin (relative path from repo_root, or `./plugins/<plugin-dir>` if relative computation fails) and checks that either a marketplace entry with the same `name` has a matching `source`, or an entry with the same `source` has a matching `name`. Records errors for a missing marketplace file, invalid JSON, missing registration, source mismatches, or name mismatches.
    
    Returns:
        PluginValidationResult: Aggregated validation outcome with errors for any registration issues and warnings if applicable.
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

    # Calculate expected source path
    try:
        relative_path = plugin_path.relative_to(repo_root)
        expected_source = f"./{relative_path}"
    except ValueError:
        expected_source = f"./plugins/{plugin_path.name}"

    # Find plugin in marketplace by name
    found = False
    for mp_plugin in plugins:
        mp_name = mp_plugin.get("name", "")
        mp_source = mp_plugin.get("source", "")

        # Check if this entry matches our plugin by name
        if mp_name == plugin_name:
            found = True

            # Check source matches
            if mp_source != expected_source:
                result.add_error(f"Marketplace source mismatch: expected '{expected_source}', got '{mp_source}'")
            break

        # Also check by source path (for name mismatch detection)
        if mp_source == expected_source:
            found = True

            # Check name matches
            if mp_name != plugin_name:
                result.add_error(f"Name mismatch: plugin.json has '{plugin_name}', marketplace has '{mp_name}'")
            break

    if not found:
        result.add_error(f"Plugin '{plugin_name}' not registered in marketplace")

    return result


def main() -> int:  # noqa: PLR0911, PLR0912
    """
    Validate a plugin at the filesystem path provided on the command line and emit validation results.
    
    Parses the first command-line argument as the plugin path, locates the repository root (by searching for a .git directory, falling back to the current working directory), runs full plugin validation, prints any warnings or errors, and maps the first error to a process exit code.
    
    Returns:
        int: Exit code indicating result:
            0 — plugin is valid;
            1 — resource not found or generic validation failure (including "not found" or "Invalid JSON" errors);
            2 — missing required field error (contains "Missing required");
            3 — invalid field error (contains "Invalid");
            10 — usage error, missing/invalid CLI arguments, or an internal script error.
    """
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