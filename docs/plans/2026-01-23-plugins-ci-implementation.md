# Plugins CI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create GitHub Actions CI workflow for Claude Code plugins with structure validation and Python linting.

**Architecture:** Three-phase approach: (1) refactor terminology packages.py → projects.py, (2) create validate_plugin.py script, (3) create plugins-ci.yml workflow. Each phase is independent and testable.

**Tech Stack:** Python 3.11, pytest, ruff, GitHub Actions

---

## ✅ Task 1: Rename packages.py → projects.py

**Files:**
- Rename: `.github/scripts/packages.py` → `.github/scripts/projects.py`
- Rename: `.github/scripts/tests/test_packages.py` → `.github/scripts/tests/test_projects.py`
- Modify: `.github/scripts/detect_changes.py:54-58`
- Modify: `.github/scripts/validate.py:55-56,77`
- Modify: `.github/scripts/tests/test_projects.py:9-13`

**Step 1: Rename packages.py to projects.py**

```bash
git mv .github/scripts/packages.py .github/scripts/projects.py
```

**Step 2: Update class and function names in projects.py**

Replace in `.github/scripts/projects.py`:
- `PackageInfo` → `ProjectInfo`
- `discover_packages` → `discover_projects`
- `get_package_from_path` → `get_project_from_path`

```python
@dataclass
class ProjectInfo:
    """Information about a package or plugin."""

    name: str
    path: str
    kind: str  # "package" or "plugin"
    python_versions: list[str]
```

```python
def get_project_from_path(path: str) -> str | None:
```

```python
def discover_projects(repo_root: Path) -> dict[str, ProjectInfo]:
```

Also update internal variable names:
- `packages: dict[str, PackageInfo]` → `projects: dict[str, ProjectInfo]`

**Step 3: Update imports in detect_changes.py**

Replace lines 54-58:
```python
    from .projects import (
        discover_projects,
        get_project_from_path,
        is_repo_level_path,
    )
```

Update line 61:
```python
    all_projects = discover_projects(repo_root)
```

Update line 82-83:
```python
        pkg_info = all_projects.get(pkg_name)
```

Update lines 94-95:
```python
    for pkg_name, pkg_info in sorted(all_projects.items()):
```

**Step 4: Update imports in validate.py**

Replace lines 55-56:
```python
    from .projects import get_project_from_path, is_repo_level_path
```

Replace line 77:
```python
    from .projects import discover_projects
```

Update line 81:
```python
        discover_projects(repo_root)
```

**Step 5: Rename function _get_packages_from_files → _get_projects_from_files in validate.py**

Replace function name at line 51 and update docstring:
```python
def _get_projects_from_files(
    files: list[str],
) -> tuple[set[str], list[str]]:
    """Extract projects and repo-level files from file list."""
    from .projects import get_project_from_path, is_repo_level_path
```

Update all calls to this function (lines 103, 166, 197).

**Step 6: Rename test file**

```bash
git mv .github/scripts/tests/test_packages.py .github/scripts/tests/test_projects.py
```

**Step 7: Update imports in test_projects.py**

Replace lines 9-13:
```python
from ..projects import (
    discover_projects,
    get_project_from_path,
    is_repo_level_path,
)
```

Update test method calls to use new function names:
- `discover_packages` → `discover_projects`
- `get_package_from_path` → `get_project_from_path`

**Step 8: Run tests to verify refactoring**

```bash
cd .github && uv run pytest scripts/tests/ -v
```

Expected: All tests pass.

**Step 9: Run linter and formatter**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run ty check .
```

**Step 10: Commit**

```bash
git add .github/scripts/projects.py .github/scripts/tests/test_projects.py .github/scripts/detect_changes.py .github/scripts/validate.py
git commit -m "$(cat <<'EOF'
refactor(ci): rename packages → projects terminology

- Rename packages.py → projects.py
- Rename PackageInfo → ProjectInfo
- Rename discover_packages → discover_projects
- Rename get_package_from_path → get_project_from_path
- Update all imports and usages

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## ✅ Task 2: Add packages/plugins split to detect_changes.py output

**Files:**
- Modify: `.github/scripts/detect_changes.py:25-46,63-78`
- Modify: `.github/scripts/tests/test_detect_changes.py`

**Step 1: Write failing test for new output fields**

Add to `.github/scripts/tests/test_detect_changes.py`:

```python
class TestDetectChangesPlugins:
    """Tests for plugin detection in detect_changes."""

    def test_detects_plugin_changes(self, temp_repo: Path) -> None:
        """Should detect changes in plugin."""
        changed_files = ["plugins/flow/skills/start.md"]
        result = detect_changes(changed_files, repo_root=temp_repo)
        assert result.plugins == ["flow"]
        assert result.has_plugins is True
        assert result.packages == []
        assert result.has_packages is False

    def test_separates_packages_and_plugins(self, temp_repo: Path) -> None:
        """Should separate packages and plugins in output."""
        changed_files = [
            "packages/statuskit/src/module.py",
            "plugins/flow/skills/start.md",
        ]
        result = detect_changes(changed_files, repo_root=temp_repo)
        assert result.projects == ["flow", "statuskit"]
        assert result.packages == ["statuskit"]
        assert result.plugins == ["flow"]
        assert result.has_packages is True
        assert result.has_plugins is True


class TestDetectionResultJsonPlugins:
    """Tests for JSON output with plugin fields."""

    def test_json_has_plugin_fields(self, temp_repo: Path) -> None:
        """Should include plugin fields in JSON output."""
        changed_files = ["plugins/flow/skills/start.md"]
        result = detect_changes(changed_files, repo_root=temp_repo)
        output = result.to_json()
        data = json.loads(output)
        assert "projects" in data
        assert "packages" in data
        assert "plugins" in data
        assert "has_packages" in data
        assert "has_plugins" in data
```

**Step 2: Run test to verify it fails**

```bash
cd .github && uv run pytest scripts/tests/test_detect_changes.py::TestDetectChangesPlugins -v
```

Expected: FAIL (missing attributes).

**Step 3: Update DetectionResult dataclass**

Replace lines 25-34 in `.github/scripts/detect_changes.py`:

```python
@dataclass
class DetectionResult:
    """Result of change detection."""

    projects: list[str] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)
    has_packages: bool = False
    has_plugins: bool = False
    has_repo_level: bool = False
    tooling_changed: bool = False
    matrix: dict = field(default_factory=lambda: {"include": []})
    all_packages_matrix: dict = field(default_factory=lambda: {"include": []})

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(
            {
                "projects": self.projects,
                "packages": self.packages,
                "plugins": self.plugins,
                "has_packages": self.has_packages,
                "has_plugins": self.has_plugins,
                "has_repo_level": self.has_repo_level,
                "tooling_changed": self.tooling_changed,
                "matrix": self.matrix,
                "all_packages_matrix": self.all_packages_matrix,
            }
        )
```

**Step 4: Update detect_changes function logic**

Update the function starting at line 63 to separate packages and plugins:

```python
    changed_projects: set[str] = set()
    changed_packages: set[str] = set()
    changed_plugins: set[str] = set()
    tooling_files = {"pyproject.toml", "uv.lock"}
    has_tooling_files = False

    for f in changed_files:
        project_name = get_project_from_path(f)
        if project_name:
            changed_projects.add(project_name)
            # Determine if package or plugin by path prefix
            if f.startswith("packages/"):
                changed_packages.add(project_name)
            elif f.startswith("plugins/"):
                changed_plugins.add(project_name)
        elif is_repo_level_path(f):
            result.has_repo_level = True
            if f in tooling_files:
                has_tooling_files = True

    result.tooling_changed = has_tooling_files and not changed_packages
    result.projects = sorted(changed_projects)
    result.packages = sorted(changed_packages)
    result.plugins = sorted(changed_plugins)
    result.has_packages = bool(changed_packages)
    result.has_plugins = bool(changed_plugins)
```

**Step 5: Run tests to verify they pass**

```bash
cd .github && uv run pytest scripts/tests/test_detect_changes.py -v
```

Expected: All tests pass.

**Step 6: Run linter and formatter**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run ty check .
```

**Step 7: Commit**

```bash
git add .github/scripts/detect_changes.py .github/scripts/tests/test_detect_changes.py
git commit -m "$(cat <<'EOF'
feat(ci): add packages/plugins split to detect_changes output

- Add projects, packages, plugins fields to DetectionResult
- Add has_packages, has_plugins flags
- Separate package and plugin detection by path prefix

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## ✅ Task 3: Create validate_plugin.py - Core validation

**Files:**
- Create: `.github/scripts/validate_plugin.py`
- Create: `.github/scripts/tests/test_validate_plugin.py`

**Step 1: Write failing tests for plugin.json validation**

Create `.github/scripts/tests/test_validate_plugin.py`:

```python
"""Tests for validate_plugin.py script."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    pass


@pytest.fixture
def temp_plugin(tmp_path: Path) -> Path:
    """Create minimal valid plugin structure."""
    plugin_dir = tmp_path / "plugins" / "test-plugin"
    plugin_dir.mkdir(parents=True)
    claude_plugin = plugin_dir / ".claude-plugin"
    claude_plugin.mkdir()
    (claude_plugin / "plugin.json").write_text(
        json.dumps({"name": "test-plugin", "version": "1.0.0"})
    )
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
        (claude_plugin / "plugin.json").write_text(
            '{"name": "bad-version", "version": "not-semver"}'
        )

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
        (claude_plugin / "plugin.json").write_text(
            '{"name": "bad-path", "skills": "skills/"}'
        )

        result = validate_plugin(plugin_dir, tmp_path)
        assert result.success is False
        assert any("must start with ./" in e for e in result.errors)
```

**Step 2: Run tests to verify they fail**

```bash
cd .github && uv run pytest scripts/tests/test_validate_plugin.py::TestValidatePluginJson -v
```

Expected: FAIL (module not found).

**Step 3: Create validate_plugin.py with PluginValidationResult**

Create `.github/scripts/validate_plugin.py`:

```python
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
    if "version" in data and data["version"]:
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


def validate_components(plugin_path: Path, plugin_json: dict) -> PluginValidationResult:
    """Validate component directories and files exist."""
    # Placeholder - implemented in Task 4
    return PluginValidationResult()


def validate_name_uniqueness(plugin_path: Path, plugin_json: dict) -> PluginValidationResult:
    """Validate no name collisions between components."""
    # Placeholder - implemented in Task 5
    return PluginValidationResult()


def validate_marketplace_registration(
    plugin_path: Path, plugin_json: dict, repo_root: Path
) -> PluginValidationResult:
    """Validate plugin is registered in marketplace."""
    # Placeholder - implemented in Task 6
    return PluginValidationResult()


def main() -> int:
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

    print(f"✓ Plugin '{plugin_path.name}' is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Run tests to verify they pass**

```bash
cd .github && uv run pytest scripts/tests/test_validate_plugin.py::TestValidatePluginJson -v
```

Expected: All tests pass.

**Step 5: Run linter and formatter**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run ty check .
```

**Step 6: Commit**

```bash
git add .github/scripts/validate_plugin.py .github/scripts/tests/test_validate_plugin.py
git commit -m "$(cat <<'EOF'
feat(ci): add validate_plugin.py core validation

- Add PluginValidationResult dataclass
- Implement validate_plugin_json for JSON structure validation
- Validate name (kebab-case), version (semver), paths (./ prefix)
- Add placeholder functions for components, uniqueness, marketplace

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## ✅ Task 4: Add component validation to validate_plugin.py

**Files:**
- Modify: `.github/scripts/validate_plugin.py`
- Modify: `.github/scripts/tests/test_validate_plugin.py`

**Step 1: Write failing tests for component validation**

Add to `.github/scripts/tests/test_validate_plugin.py`:

```python
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
        (claude_plugin / "plugin.json").write_text(
            '{"name": "missing-skill-md"}'
        )

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
        (claude_plugin / "plugin.json").write_text(
            '{"name": "custom-path", "skills": "./custom-skills"}'
        )

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
```

**Step 2: Run tests to verify they fail**

```bash
cd .github && uv run pytest scripts/tests/test_validate_plugin.py::TestValidateComponents -v
```

Expected: FAIL (validation passes when it should fail).

**Step 3: Implement validate_components function**

Replace the placeholder in `.github/scripts/validate_plugin.py`:

```python
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
                result.add_error(
                    f"Command file '{cmd_file.name}' must have .md extension"
                )

    # Validate agents
    agents_dir = plugin_path / normalize_path(agents_path)
    if agents_dir.exists() and agents_dir.is_dir():
        for agent_file in agents_dir.iterdir():
            if agent_file.is_file() and not agent_file.name.endswith(".md"):
                result.add_error(
                    f"Agent file '{agent_file.name}' must have .md extension"
                )

    return result
```

**Step 4: Run tests to verify they pass**

```bash
cd .github && uv run pytest scripts/tests/test_validate_plugin.py::TestValidateComponents -v
```

Expected: All tests pass.

**Step 5: Run linter and formatter**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run ty check .
```

**Step 6: Commit**

```bash
git add .github/scripts/validate_plugin.py .github/scripts/tests/test_validate_plugin.py
git commit -m "$(cat <<'EOF'
feat(ci): add component validation to validate_plugin

- Validate skills folders contain SKILL.md
- Validate commands/agents files have .md extension
- Support custom paths from plugin.json

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## ✅ Task 5: Add name uniqueness validation

**Files:**
- Modify: `.github/scripts/validate_plugin.py`
- Modify: `.github/scripts/tests/test_validate_plugin.py`

**Step 1: Write failing test for name collision**

Add to `.github/scripts/tests/test_validate_plugin.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

```bash
cd .github && uv run pytest scripts/tests/test_validate_plugin.py::TestValidateNameUniqueness -v
```

Expected: FAIL (collision not detected).

**Step 3: Implement validate_name_uniqueness function**

Replace the placeholder in `.github/scripts/validate_plugin.py`:

```python
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
            result.add_error(
                f"Name collision: '{name}' exists in both {types[0]}s and {types[1]}s"
            )

    return result
```

**Step 4: Run tests to verify they pass**

```bash
cd .github && uv run pytest scripts/tests/test_validate_plugin.py::TestValidateNameUniqueness -v
```

Expected: All tests pass.

**Step 5: Run linter and formatter**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run ty check .
```

**Step 6: Commit**

```bash
git add .github/scripts/validate_plugin.py .github/scripts/tests/test_validate_plugin.py
git commit -m "$(cat <<'EOF'
feat(ci): add name uniqueness validation to validate_plugin

- Add collect_component_names helper function
- Detect name collisions between skills, commands, agents
- Report which component types have the collision

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## ✅ Task 6: Add marketplace registration validation

**Files:**
- Modify: `.github/scripts/validate_plugin.py`
- Modify: `.github/scripts/tests/test_validate_plugin.py`

**Step 1: Write failing tests for marketplace validation**

Add to `.github/scripts/tests/test_validate_plugin.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

```bash
cd .github && uv run pytest scripts/tests/test_validate_plugin.py::TestValidateMarketplace -v
```

Expected: FAIL (validation passes).

**Step 3: Implement validate_marketplace_registration function**

Replace the placeholder in `.github/scripts/validate_plugin.py`:

```python
def validate_marketplace_registration(
    plugin_path: Path, plugin_json: dict, repo_root: Path
) -> PluginValidationResult:
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

    # Calculate expected source path
    try:
        relative_path = plugin_path.relative_to(repo_root)
        expected_source = f"./{relative_path}"
    except ValueError:
        expected_source = f"./plugins/{plugin_path.name}"

    # Find plugin in marketplace
    found = False
    for mp_plugin in plugins:
        mp_source = mp_plugin.get("source", "")

        # Check if this entry matches our plugin by source path
        if mp_source == expected_source or mp_source == f"./plugins/{plugin_path.name}":
            found = True

            # Check name matches
            mp_name = mp_plugin.get("name", "")
            if mp_name != plugin_name:
                result.add_error(
                    f"Name mismatch: plugin.json has '{plugin_name}', marketplace has '{mp_name}'"
                )

            # Check source matches exactly
            if mp_source != expected_source:
                result.add_error(
                    f"Marketplace source mismatch: expected '{expected_source}', got '{mp_source}'"
                )
            break

    if not found:
        result.add_error(f"Plugin '{plugin_name}' not registered in marketplace")

    return result
```

**Step 4: Run tests to verify they pass**

```bash
cd .github && uv run pytest scripts/tests/test_validate_plugin.py::TestValidateMarketplace -v
```

Expected: All tests pass.

**Step 5: Run all validate_plugin tests**

```bash
cd .github && uv run pytest scripts/tests/test_validate_plugin.py -v
```

Expected: All tests pass.

**Step 6: Run linter and formatter**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run ty check .
```

**Step 7: Commit**

```bash
git add .github/scripts/validate_plugin.py .github/scripts/tests/test_validate_plugin.py
git commit -m "$(cat <<'EOF'
feat(ci): add marketplace registration validation

- Check plugin is listed in marketplace.json
- Validate name matches between plugin.json and marketplace
- Validate source path matches plugin location

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## ✅ Task 7: Create plugins-ci.yml workflow

**Files:**
- Create: `.github/workflows/plugins-ci.yml`

**Step 1: Create the workflow file**

Create `.github/workflows/plugins-ci.yml`:

```yaml
name: Plugins CI

on:
  pull_request:
    paths: ['plugins/**']
  push:
    branches: [main]
    paths: ['plugins/**']

jobs:
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      plugin: ${{ steps.detect.outputs.plugin }}
      plugin_path: ${{ steps.detect.outputs.plugin_path }}
      has_plugins: ${{ steps.detect.outputs.has_plugins }}
      has_python: ${{ steps.check-python.outputs.has_python }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Detect changes
        id: detect
        run: |
          if [ "${{ github.event_name }}" = "pull_request" ]; then
            REF="origin/${{ github.base_ref }}..HEAD"
          else
            REF="HEAD~1..HEAD"
          fi
          OUTPUT=$(python -m scripts.detect_changes --ref "$REF")
          echo "Output: $OUTPUT"
          PLUGIN=$(echo "$OUTPUT" | jq -r '.plugins[0] // empty')
          echo "plugin=$PLUGIN" >> $GITHUB_OUTPUT
          echo "plugin_path=plugins/$PLUGIN" >> $GITHUB_OUTPUT
          echo "has_plugins=$(echo "$OUTPUT" | jq -r '.has_plugins')" >> $GITHUB_OUTPUT
        working-directory: .github

      - name: Check for Python files
        id: check-python
        if: steps.detect.outputs.has_plugins == 'true'
        run: |
          if find ${{ steps.detect.outputs.plugin_path }} -name "*.py" 2>/dev/null | grep -q .; then
            echo "has_python=true" >> $GITHUB_OUTPUT
          else
            echo "has_python=false" >> $GITHUB_OUTPUT
          fi

  validate-structure:
    needs: detect-changes
    if: needs.detect-changes.outputs.has_plugins == 'true'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Validate plugin structure
        run: |
          python -m scripts.validate_plugin ${{ needs.detect-changes.outputs.plugin_path }}
        working-directory: .github

  lint-scripts:
    needs: detect-changes
    if: needs.detect-changes.outputs.has_plugins == 'true' && needs.detect-changes.outputs.has_python == 'true'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Setup uv
        uses: astral-sh/setup-uv@v4

      - name: Install ruff
        run: uv tool install ruff

      - name: Ruff check
        run: ruff check --config pyproject.toml ${{ needs.detect-changes.outputs.plugin_path }}

      - name: Ruff format check
        run: ruff format --config pyproject.toml --check ${{ needs.detect-changes.outputs.plugin_path }}
```

**Step 2: Validate workflow syntax**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/plugins-ci.yml'))" && echo "YAML valid"
```

Expected: "YAML valid"

**Step 3: Run linter and formatter**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run ty check .
```

**Step 4: Commit**

```bash
git add .github/workflows/plugins-ci.yml
git commit -m "$(cat <<'EOF'
feat(ci): add plugins-ci.yml workflow

- detect-changes job: detect plugin changes, check for Python files
- validate-structure job: run validate_plugin.py
- lint-scripts job: run ruff check/format on Python files

Triggered by changes in plugins/**

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Test workflow locally with act

**Files:**
- None (testing only)

**Step 1: Create test event file**

```bash
cat > /tmp/pr-event.json << 'EOF'
{
  "pull_request": {
    "number": 1,
    "head": {
      "ref": "test-branch",
      "sha": "abc123"
    },
    "base": {
      "ref": "main"
    }
  }
}
EOF
```

**Step 2: Run act with pull_request event**

```bash
act pull_request -W .github/workflows/plugins-ci.yml -e /tmp/pr-event.json --container-architecture linux/amd64 -v 2>&1 | head -100
```

Expected: Workflow runs, may fail on detect-changes if no actual changes in plugins/.

**Step 3: Verify the actual plugin validates**

```bash
cd .github && python -m scripts.validate_plugin ../plugins/flow
```

Expected: "✓ Plugin 'flow' is valid"

**Step 4: Run all tests**

```bash
cd .github && uv run pytest scripts/tests/ -v
```

Expected: All tests pass.

---

## Task 9: Final verification and cleanup

**Files:**
- None (verification only)

**Step 1: Run full test suite**

```bash
cd .github && uv run pytest scripts/tests/ -v --tb=short
```

Expected: All tests pass.

**Step 2: Run linter on all files**

```bash
uv run ruff check . && uv run ruff format --check .
```

Expected: No issues.

**Step 3: Run type checker**

```bash
uv run ty check .
```

Expected: No type errors.

**Step 4: Verify git status is clean**

```bash
git status
```

Expected: Working tree clean (all changes committed).

**Step 5: Review commits**

```bash
git log --oneline -10
```

Expected: 7-8 commits with proper conventional commit format.
