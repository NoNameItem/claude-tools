# Validation Scripts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create Python scripts for commit validation and change detection in monorepo CI/CD.

**Architecture:** Two standalone scripts (`validate.py` and `detect_changes.py`) with shared utilities for package discovery. TDD approach with pytest fixtures using temporary git repos.

**Tech Stack:** Python 3.11+, pytest, subprocess (git commands), tomllib (Python version parsing)

---

## Task 1: Create Test Infrastructure

**Files:**
- Create: `.github/scripts/__init__.py`
- Create: `.github/scripts/tests/__init__.py`
- Create: `.github/scripts/tests/conftest.py`

**Step 1: Create directory structure**

```bash
mkdir -p .github/scripts/tests
```

**Step 2: Create empty `__init__.py` files**

Create `.github/scripts/__init__.py`:
```python
```

Create `.github/scripts/tests/__init__.py`:
```python
```

**Step 3: Write conftest.py with temp_repo fixture**

Create `.github/scripts/tests/conftest.py`:
```python
"""Shared fixtures for validation scripts tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def temp_repo(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary git repo with packages/plugins structure.

    Structure created:
    - packages/statuskit/pyproject.toml (with Python classifiers)
    - packages/statuskit/src/statuskit/__init__.py
    - plugins/flow/.claude-plugin/plugin.json
    - README.md (repo-level file)
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    # Init git
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Create packages/statuskit structure
    statuskit_dir = repo / "packages" / "statuskit"
    statuskit_src = statuskit_dir / "src" / "statuskit"
    statuskit_src.mkdir(parents=True)

    (statuskit_dir / "pyproject.toml").write_text('''\
[project]
name = "statuskit"
version = "0.1.0"
classifiers = [
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
''')
    (statuskit_src / "__init__.py").write_text('__version__ = "0.1.0"\n')

    # Create plugins/flow structure
    flow_dir = repo / "plugins" / "flow"
    flow_plugin_dir = flow_dir / ".claude-plugin"
    flow_plugin_dir.mkdir(parents=True)
    (flow_plugin_dir / "plugin.json").write_text('{"name": "flow", "version": "1.0.0"}\n')

    # Create repo-level file
    (repo / "README.md").write_text("# Test Repo\n")

    # Initial commit
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: initial commit"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    yield repo


@pytest.fixture
def temp_repo_with_another_package(temp_repo: Path) -> Path:
    """Extend temp_repo with another package for multi-package tests."""
    another_dir = temp_repo / "packages" / "another"
    another_src = another_dir / "src" / "another"
    another_src.mkdir(parents=True)

    (another_dir / "pyproject.toml").write_text('''\
[project]
name = "another"
version = "0.1.0"
classifiers = [
    "Programming Language :: Python :: 3.11",
]
''')
    (another_src / "__init__.py").write_text('__version__ = "0.1.0"\n')

    subprocess.run(["git", "add", "."], cwd=temp_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: add another package"],
        cwd=temp_repo,
        check=True,
        capture_output=True,
    )

    return temp_repo
```

**Step 4: Run tests to verify fixture works**

Run: `uv run pytest .github/scripts/tests/conftest.py -v --collect-only`
Expected: Collection should succeed (no tests yet, but fixture loads)

**Step 5: Commit**

```bash
git add .github/scripts/
git commit -m "ci: add test infrastructure for validation scripts"
```

---

## Task 2: Implement Package Discovery

**Files:**
- Create: `.github/scripts/packages.py`
- Create: `.github/scripts/tests/test_packages.py`

**Step 1: Write failing tests for package discovery**

Create `.github/scripts/tests/test_packages.py`:
```python
"""Tests for package discovery module."""

from __future__ import annotations

from pathlib import Path

import pytest

from ..packages import (
    PackageInfo,
    discover_packages,
    get_package_from_path,
    is_repo_level_path,
)


class TestGetPackageFromPath:
    """Tests for get_package_from_path function."""

    def test_package_path(self) -> None:
        """Should extract package name from packages/* path."""
        assert get_package_from_path("packages/statuskit/src/foo.py") == "statuskit"

    def test_plugin_path(self) -> None:
        """Should extract plugin name from plugins/* path."""
        assert get_package_from_path("plugins/flow/skills/start.md") == "flow"

    def test_repo_level_path(self) -> None:
        """Should return None for repo-level paths."""
        assert get_package_from_path("README.md") is None
        assert get_package_from_path(".github/workflows/ci.yml") is None
        assert get_package_from_path("docs/design.md") is None

    def test_root_pyproject(self) -> None:
        """Should return None for root pyproject.toml."""
        assert get_package_from_path("pyproject.toml") is None

    def test_package_pyproject(self) -> None:
        """Should extract package from package's pyproject.toml."""
        assert get_package_from_path("packages/statuskit/pyproject.toml") == "statuskit"


class TestIsRepoLevelPath:
    """Tests for is_repo_level_path function."""

    def test_github_dir(self) -> None:
        """Should return True for .github/* paths."""
        assert is_repo_level_path(".github/workflows/ci.yml") is True

    def test_docs_dir(self) -> None:
        """Should return True for docs/* paths."""
        assert is_repo_level_path("docs/design.md") is True

    def test_root_md(self) -> None:
        """Should return True for root .md files."""
        assert is_repo_level_path("README.md") is True
        assert is_repo_level_path("CONTRIBUTING.md") is True

    def test_root_config_files(self) -> None:
        """Should return True for root config files."""
        assert is_repo_level_path("pyproject.toml") is True
        assert is_repo_level_path("uv.lock") is True
        assert is_repo_level_path(".gitignore") is True

    def test_package_path(self) -> None:
        """Should return False for package paths."""
        assert is_repo_level_path("packages/statuskit/src/foo.py") is False

    def test_plugin_path(self) -> None:
        """Should return False for plugin paths."""
        assert is_repo_level_path("plugins/flow/skills/start.md") is False


class TestDiscoverPackages:
    """Tests for discover_packages function."""

    def test_discovers_packages(self, temp_repo: Path) -> None:
        """Should discover packages from packages/ directory."""
        packages = discover_packages(temp_repo)

        assert "statuskit" in packages
        assert packages["statuskit"].name == "statuskit"
        assert packages["statuskit"].path == "packages/statuskit"
        assert packages["statuskit"].kind == "package"

    def test_discovers_plugins(self, temp_repo: Path) -> None:
        """Should discover plugins from plugins/ directory."""
        packages = discover_packages(temp_repo)

        assert "flow" in packages
        assert packages["flow"].name == "flow"
        assert packages["flow"].path == "plugins/flow"
        assert packages["flow"].kind == "plugin"

    def test_detects_collision(self, temp_repo: Path) -> None:
        """Should raise error if same name in packages/ and plugins/."""
        # Create collision: plugins/statuskit
        collision_dir = temp_repo / "plugins" / "statuskit"
        collision_dir.mkdir(parents=True)
        (collision_dir / "plugin.json").write_text("{}")

        with pytest.raises(ValueError, match="Scope collision"):
            discover_packages(temp_repo)

    def test_parses_python_versions(self, temp_repo: Path) -> None:
        """Should parse Python versions from classifiers."""
        packages = discover_packages(temp_repo)

        assert packages["statuskit"].python_versions == ["3.11", "3.12"]

    def test_missing_classifiers(self, temp_repo: Path) -> None:
        """Should raise error if package has no Python classifiers."""
        # Create package without classifiers
        no_classifiers_dir = temp_repo / "packages" / "noclassifiers"
        no_classifiers_dir.mkdir(parents=True)
        (no_classifiers_dir / "pyproject.toml").write_text('''\
[project]
name = "noclassifiers"
version = "0.1.0"
''')

        with pytest.raises(ValueError, match="Missing Python version classifiers"):
            discover_packages(temp_repo)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest .github/scripts/tests/test_packages.py -v`
Expected: FAIL with "ModuleNotFoundError" or "cannot import"

**Step 3: Write minimal implementation**

Create `.github/scripts/packages.py`:
```python
"""Package discovery for monorepo validation."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PackageInfo:
    """Information about a package or plugin."""

    name: str
    path: str
    kind: str  # "package" or "plugin"
    python_versions: list[str]


# Patterns for repo-level paths (don't require scope)
REPO_LEVEL_PATTERNS = [
    r"^\.github/",
    r"^docs/",
    r"^[^/]+\.md$",  # *.md in root
    r"^pyproject\.toml$",
    r"^uv\.lock$",
    r"^\.[^/]+$",  # dotfiles in root
]


def get_package_from_path(path: str) -> str | None:
    """Extract package/plugin name from file path.

    Args:
        path: File path relative to repo root.

    Returns:
        Package/plugin name or None if repo-level path.
    """
    if path.startswith("packages/"):
        parts = path.split("/")
        return parts[1] if len(parts) > 1 else None
    if path.startswith("plugins/"):
        parts = path.split("/")
        return parts[1] if len(parts) > 1 else None
    return None


def is_repo_level_path(path: str) -> bool:
    """Check if path is a repo-level file (not in package/plugin).

    Args:
        path: File path relative to repo root.

    Returns:
        True if repo-level, False otherwise.
    """
    for pattern in REPO_LEVEL_PATTERNS:
        if re.match(pattern, path):
            return True
    # Also true if not in packages/ or plugins/
    return get_package_from_path(path) is None


def _parse_python_versions(pyproject_path: Path) -> list[str]:
    """Parse Python versions from pyproject.toml classifiers.

    Args:
        pyproject_path: Path to pyproject.toml file.

    Returns:
        List of Python versions (e.g., ["3.11", "3.12"]).

    Raises:
        ValueError: If no Python classifiers found.
    """
    content = pyproject_path.read_text()
    data = tomllib.loads(content)

    classifiers = data.get("project", {}).get("classifiers", [])

    versions = []
    pattern = re.compile(r"Programming Language :: Python :: (\d+\.\d+)")

    for classifier in classifiers:
        match = pattern.match(classifier)
        if match:
            versions.append(match.group(1))

    if not versions:
        raise ValueError(
            f"Missing Python version classifiers\n\n"
            f"  Package: {pyproject_path.parent.name}\n"
            f"  File: {pyproject_path}\n\n"
            f"  Add classifiers like:\n"
            f'    classifiers = [\n'
            f'        "Programming Language :: Python :: 3.11",\n'
            f'        "Programming Language :: Python :: 3.12",\n'
            f'    ]'
        )

    return versions


def discover_packages(repo_root: Path) -> dict[str, PackageInfo]:
    """Discover all packages and plugins in the repository.

    Args:
        repo_root: Path to repository root.

    Returns:
        Dict mapping package/plugin name to PackageInfo.

    Raises:
        ValueError: If scope collision detected or missing classifiers.
    """
    packages: dict[str, PackageInfo] = {}

    # Discover packages
    packages_dir = repo_root / "packages"
    if packages_dir.exists():
        for pkg_dir in packages_dir.iterdir():
            if not pkg_dir.is_dir():
                continue

            name = pkg_dir.name
            pyproject = pkg_dir / "pyproject.toml"

            if not pyproject.exists():
                continue

            python_versions = _parse_python_versions(pyproject)

            packages[name] = PackageInfo(
                name=name,
                path=f"packages/{name}",
                kind="package",
                python_versions=python_versions,
            )

    # Discover plugins
    plugins_dir = repo_root / "plugins"
    if plugins_dir.exists():
        for plugin_dir in plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue

            name = plugin_dir.name

            # Check for collision
            if name in packages:
                raise ValueError(
                    f"Scope collision detected\n\n"
                    f"  Name '{name}' exists in both:\n"
                    f"    - packages/{name}/\n"
                    f"    - plugins/{name}/\n\n"
                    f"  Rename one to ensure unique scope names."
                )

            packages[name] = PackageInfo(
                name=name,
                path=f"plugins/{name}",
                kind="plugin",
                python_versions=[],  # Plugins don't have Python versions
            )

    return packages
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest .github/scripts/tests/test_packages.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add .github/scripts/packages.py .github/scripts/tests/test_packages.py
git commit -m "ci: add package discovery module"
```

---

## Task 3: Implement Conventional Commit Parser

**Files:**
- Create: `.github/scripts/commits.py`
- Create: `.github/scripts/tests/test_commits.py`

**Step 1: Write failing tests for commit parsing**

Create `.github/scripts/tests/test_commits.py`:
```python
"""Tests for conventional commit parsing."""

from __future__ import annotations

import pytest

from ..commits import CommitInfo, parse_commit_message


class TestParseCommitMessage:
    """Tests for parse_commit_message function."""

    def test_basic_format(self) -> None:
        """Should parse basic conventional commit."""
        result = parse_commit_message("feat(statuskit): add git module")

        assert result is not None
        assert result.type == "feat"
        assert result.scope == "statuskit"
        assert result.description == "add git module"
        assert result.breaking is False

    def test_without_scope(self) -> None:
        """Should parse commit without scope."""
        result = parse_commit_message("docs: update README")

        assert result is not None
        assert result.type == "docs"
        assert result.scope is None
        assert result.description == "update README"

    def test_breaking_with_bang(self) -> None:
        """Should detect breaking change with ! marker."""
        result = parse_commit_message("feat(api)!: change response format")

        assert result is not None
        assert result.breaking is True

    def test_all_valid_types(self) -> None:
        """Should accept all valid commit types."""
        valid_types = [
            "feat", "fix", "docs", "style", "refactor",
            "test", "chore", "ci", "revert", "build", "perf",
        ]

        for commit_type in valid_types:
            result = parse_commit_message(f"{commit_type}: description")
            assert result is not None, f"Type '{commit_type}' should be valid"
            assert result.type == commit_type

    def test_case_insensitive(self) -> None:
        """Should handle case variations."""
        result = parse_commit_message("FEAT(statuskit): add feature")

        assert result is not None
        assert result.type == "feat"  # Normalized to lowercase

    def test_invalid_format(self) -> None:
        """Should return None for invalid format."""
        invalid_messages = [
            "add new feature",
            "feature: without type",
            "feat add module",  # Missing colon
            ": empty type",
            "",
        ]

        for msg in invalid_messages:
            assert parse_commit_message(msg) is None, f"'{msg}' should be invalid"

    def test_merge_commit(self) -> None:
        """Should return None for merge commits."""
        result = parse_commit_message("Merge branch 'feature/x' into main")
        assert result is None

    def test_revert_github_format(self) -> None:
        """Should return None for GitHub's revert format (not conventional)."""
        result = parse_commit_message('Revert "feat(statuskit): add feature"')
        assert result is None

    def test_revert_conventional_format(self) -> None:
        """Should accept conventional revert format."""
        result = parse_commit_message("revert(statuskit): add feature")

        assert result is not None
        assert result.type == "revert"
        assert result.scope == "statuskit"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest .github/scripts/tests/test_commits.py -v`
Expected: FAIL with "ModuleNotFoundError" or "cannot import"

**Step 3: Write minimal implementation**

Create `.github/scripts/commits.py`:
```python
"""Conventional commit parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class CommitInfo:
    """Parsed conventional commit information."""

    type: str
    scope: str | None
    description: str
    breaking: bool


# Valid conventional commit types
VALID_TYPES = frozenset([
    "feat", "fix", "docs", "style", "refactor",
    "test", "chore", "ci", "revert", "build", "perf",
])

# Regex for conventional commit format
COMMIT_PATTERN = re.compile(
    r"^(?P<type>[a-z]+)"
    r"(?:\((?P<scope>[a-z][a-z0-9-]*)\))?"
    r"(?P<breaking>!)?"
    r":\s*(?P<desc>.+)$",
    re.IGNORECASE,
)

# Patterns to reject
MERGE_PATTERN = re.compile(r"^Merge\s+", re.IGNORECASE)
GITHUB_REVERT_PATTERN = re.compile(r'^Revert\s+"', re.IGNORECASE)


def parse_commit_message(message: str) -> CommitInfo | None:
    """Parse a conventional commit message.

    Args:
        message: First line of commit message.

    Returns:
        CommitInfo if valid conventional commit, None otherwise.
    """
    if not message:
        return None

    # Reject merge commits
    if MERGE_PATTERN.match(message):
        return None

    # Reject GitHub's revert format
    if GITHUB_REVERT_PATTERN.match(message):
        return None

    match = COMMIT_PATTERN.match(message)
    if not match:
        return None

    commit_type = match.group("type").lower()

    # Validate type
    if commit_type not in VALID_TYPES:
        return None

    return CommitInfo(
        type=commit_type,
        scope=match.group("scope"),
        description=match.group("desc"),
        breaking=bool(match.group("breaking")),
    )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest .github/scripts/tests/test_commits.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add .github/scripts/commits.py .github/scripts/tests/test_commits.py
git commit -m "ci: add conventional commit parser"
```

---

## Task 4: Implement validate.py Core Logic

**Files:**
- Create: `.github/scripts/validate.py`
- Modify: `.github/scripts/tests/test_validate.py` (create new)

**Step 1: Write failing tests for validation logic**

Create `.github/scripts/tests/test_validate.py`:
```python
"""Tests for validate.py script."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ..validate import (
    ValidationError,
    ValidationResult,
    validate_pr,
    validate_commit,
    validate_staged_files,
)


class TestValidatePR:
    """Tests for PR validation (--pr mode)."""

    def test_valid_single_package(self, temp_repo: Path) -> None:
        """Should pass when PR title scope matches changed package."""
        changed_files = ["packages/statuskit/src/new_module.py"]

        result = validate_pr(
            pr_title="feat(statuskit): add new module",
            changed_files=changed_files,
            repo_root=temp_repo,
        )

        assert result.success is True

    def test_valid_repo_level_no_scope(self, temp_repo: Path) -> None:
        """Should pass for repo-level changes without scope."""
        changed_files = [".github/workflows/ci.yml", "docs/design.md"]

        result = validate_pr(
            pr_title="ci: add CI workflow",
            changed_files=changed_files,
            repo_root=temp_repo,
        )

        assert result.success is True

    def test_invalid_format(self, temp_repo: Path) -> None:
        """Should fail for invalid PR title format."""
        result = validate_pr(
            pr_title="add new feature",
            changed_files=["packages/statuskit/src/foo.py"],
            repo_root=temp_repo,
        )

        assert result.success is False
        assert result.error == ValidationError.INVALID_FORMAT

    def test_scope_mismatch(self, temp_repo: Path) -> None:
        """Should fail when scope doesn't match changed files."""
        changed_files = ["plugins/flow/skills/start.md"]

        result = validate_pr(
            pr_title="feat(statuskit): add feature",
            changed_files=changed_files,
            repo_root=temp_repo,
        )

        assert result.success is False
        assert result.error == ValidationError.SCOPE_MISMATCH

    def test_multiple_packages(
        self, temp_repo_with_another_package: Path
    ) -> None:
        """Should fail when multiple packages changed."""
        changed_files = [
            "packages/statuskit/src/foo.py",
            "packages/another/src/bar.py",
        ]

        result = validate_pr(
            pr_title="feat(statuskit): add feature",
            changed_files=changed_files,
            repo_root=temp_repo_with_another_package,
        )

        assert result.success is False
        assert result.error == ValidationError.MULTIPLE_PACKAGES

    def test_missing_scope_for_package(self, temp_repo: Path) -> None:
        """Should fail when scope missing for package changes."""
        changed_files = ["packages/statuskit/src/foo.py"]

        result = validate_pr(
            pr_title="feat: add feature",  # Missing scope
            changed_files=changed_files,
            repo_root=temp_repo,
        )

        assert result.success is False
        assert result.error == ValidationError.SCOPE_MISMATCH

    def test_mixed_package_and_repo_level(self, temp_repo: Path) -> None:
        """Should use package scope when mixed with repo-level."""
        changed_files = [
            "packages/statuskit/src/foo.py",
            "pyproject.toml",  # Repo-level, should be ignored
            "uv.lock",  # Repo-level, should be ignored
        ]

        result = validate_pr(
            pr_title="feat(statuskit): add dependency",
            changed_files=changed_files,
            repo_root=temp_repo,
        )

        assert result.success is True


class TestValidateCommit:
    """Tests for commit validation (--commits mode)."""

    def test_valid_commit(self, temp_repo: Path) -> None:
        """Should pass for valid commit with matching scope."""
        # Create a test commit
        test_file = temp_repo / "packages" / "statuskit" / "src" / "new.py"
        test_file.write_text("# new file\n")
        subprocess.run(["git", "add", str(test_file)], cwd=temp_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "feat(statuskit): add new file"],
            cwd=temp_repo,
            check=True,
        )

        # Get commit SHA
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_repo,
            text=True,
        ).strip()

        result = validate_commit(sha, repo_root=temp_repo)

        assert result.success is True

    def test_invalid_format(self, temp_repo: Path) -> None:
        """Should fail for invalid commit message format."""
        # Create commit with invalid message
        test_file = temp_repo / "packages" / "statuskit" / "src" / "bad.py"
        test_file.write_text("# bad commit\n")
        subprocess.run(["git", "add", str(test_file)], cwd=temp_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "added new file"],  # Invalid format
            cwd=temp_repo,
            check=True,
        )

        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_repo,
            text=True,
        ).strip()

        result = validate_commit(sha, repo_root=temp_repo)

        assert result.success is False
        assert result.error == ValidationError.INVALID_FORMAT


class TestValidateStagedFiles:
    """Tests for staged files validation (--hook mode)."""

    def test_single_package(self, temp_repo: Path) -> None:
        """Should pass for staged files from one package."""
        staged_files = [
            "packages/statuskit/src/a.py",
            "packages/statuskit/src/b.py",
        ]

        result = validate_staged_files(staged_files, repo_root=temp_repo)

        assert result.success is True

    def test_repo_level_only(self, temp_repo: Path) -> None:
        """Should pass for repo-level files only."""
        staged_files = [
            ".github/workflows/ci.yml",
            "README.md",
        ]

        result = validate_staged_files(staged_files, repo_root=temp_repo)

        assert result.success is True

    def test_multiple_packages(
        self, temp_repo_with_another_package: Path
    ) -> None:
        """Should fail for files from multiple packages."""
        staged_files = [
            "packages/statuskit/src/a.py",
            "packages/another/src/b.py",
        ]

        result = validate_staged_files(
            staged_files, repo_root=temp_repo_with_another_package
        )

        assert result.success is False
        assert result.error == ValidationError.MULTIPLE_PACKAGES
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest .github/scripts/tests/test_validate.py -v`
Expected: FAIL with "ModuleNotFoundError" or "cannot import"

**Step 3: Write validate.py implementation**

Create `.github/scripts/validate.py`:
```python
#!/usr/bin/env python3
"""Validate commits and PRs for conventional commit format and single-package rule.

Usage:
    python validate.py --hook              # Pre-commit: validate staged files
    python validate.py --pr                # CI: validate PR title + files
    python validate.py --commits <before> <after>  # CI: validate commit range

Environment variables (for --pr mode):
    PR_TITLE: Pull request title
    BASE_REF: Base branch name
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from .commits import parse_commit_message
from .packages import discover_packages, get_package_from_path, is_repo_level_path


class ValidationError(IntEnum):
    """Exit codes for validation errors."""

    SUCCESS = 0
    INVALID_FORMAT = 1
    SCOPE_MISMATCH = 2
    MULTIPLE_PACKAGES = 3
    SCOPE_COLLISION = 4
    SCRIPT_ERROR = 10


@dataclass
class ValidationResult:
    """Result of validation."""

    success: bool
    error: ValidationError | None = None
    message: str = ""


def _get_packages_from_files(
    files: list[str],
    repo_root: Path,
) -> tuple[set[str], list[str]]:
    """Extract packages and repo-level files from file list.

    Args:
        files: List of file paths.
        repo_root: Repository root path.

    Returns:
        Tuple of (packages set, repo-level files list).
    """
    packages: set[str] = set()
    repo_level_files: list[str] = []

    for f in files:
        pkg = get_package_from_path(f)
        if pkg:
            packages.add(pkg)
        elif is_repo_level_path(f):
            repo_level_files.append(f)

    return packages, repo_level_files


def validate_pr(
    pr_title: str,
    changed_files: list[str],
    repo_root: Path,
) -> ValidationResult:
    """Validate PR title and changed files.

    Args:
        pr_title: Pull request title.
        changed_files: List of changed file paths.
        repo_root: Repository root path.

    Returns:
        ValidationResult with success status and error details.
    """
    # Check for scope collision first
    try:
        discover_packages(repo_root)
    except ValueError as e:
        if "collision" in str(e).lower():
            return ValidationResult(
                success=False,
                error=ValidationError.SCOPE_COLLISION,
                message=str(e),
            )
        raise

    # Parse PR title
    commit_info = parse_commit_message(pr_title)
    if commit_info is None:
        return ValidationResult(
            success=False,
            error=ValidationError.INVALID_FORMAT,
            message=(
                "Invalid conventional commit format\n\n"
                f"  Expected: type(scope): description\n"
                f"  Got:      {pr_title}\n\n"
                "  Valid types: feat, fix, docs, style, refactor, "
                "test, chore, ci, revert, build, perf\n"
                "  Scope: package name (statuskit, flow) or empty for repo-level"
            ),
        )

    # Extract packages from changed files
    packages, _ = _get_packages_from_files(changed_files, repo_root)

    # Check multiple packages
    if len(packages) > 1:
        return ValidationResult(
            success=False,
            error=ValidationError.MULTIPLE_PACKAGES,
            message=(
                "Multiple packages changed\n\n"
                f"  Changed packages: {', '.join(sorted(packages))}\n\n"
                "  Each PR should modify only one package.\n"
                "  Split into separate PRs for independent versioning."
            ),
        )

    # Check scope matches
    if packages:
        expected_scope = list(packages)[0]
        if commit_info.scope != expected_scope:
            return ValidationResult(
                success=False,
                error=ValidationError.SCOPE_MISMATCH,
                message=(
                    "Scope mismatch\n\n"
                    f"  PR title scope: {commit_info.scope or '(none)'}\n"
                    f"  Changed packages: {expected_scope}\n\n"
                    "  The scope in PR title must match the changed package."
                ),
            )
    elif commit_info.scope:
        # Only repo-level files but scope provided
        return ValidationResult(
            success=False,
            error=ValidationError.SCOPE_MISMATCH,
            message=(
                "Scope mismatch\n\n"
                f"  PR title scope: {commit_info.scope}\n"
                f"  Changed packages: (none, repo-level only)\n\n"
                "  Remove scope for repo-level changes."
            ),
        )

    return ValidationResult(
        success=True,
        message=(
            f"✓ PR title valid: {pr_title}\n"
            f"✓ Changed packages: {', '.join(packages) or '(repo-level)'}\n"
            "✓ Scope matches changed files"
        ),
    )


def validate_commit(sha: str, repo_root: Path) -> ValidationResult:
    """Validate a single commit.

    Args:
        sha: Commit SHA.
        repo_root: Repository root path.

    Returns:
        ValidationResult with success status and error details.
    """
    # Get commit message
    msg = subprocess.check_output(
        ["git", "log", "-1", "--format=%s", sha],
        cwd=repo_root,
        text=True,
    ).strip()

    # Get changed files
    files_output = subprocess.check_output(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha],
        cwd=repo_root,
        text=True,
    ).strip()
    changed_files = [f for f in files_output.split("\n") if f]

    # Parse commit message
    commit_info = parse_commit_message(msg)
    if commit_info is None:
        # Check for merge commit
        if msg.lower().startswith("merge"):
            return ValidationResult(
                success=False,
                error=ValidationError.INVALID_FORMAT,
                message=(
                    "Merge commits not allowed\n\n"
                    f"  Found: {msg}\n\n"
                    "  Use squash merge for pull requests."
                ),
            )
        return ValidationResult(
            success=False,
            error=ValidationError.INVALID_FORMAT,
            message=(
                "Invalid conventional commit format\n\n"
                f"  Expected: type(scope): description\n"
                f"  Got:      {msg}"
            ),
        )

    # Extract packages
    packages, _ = _get_packages_from_files(changed_files, repo_root)

    # Check multiple packages
    if len(packages) > 1:
        return ValidationResult(
            success=False,
            error=ValidationError.MULTIPLE_PACKAGES,
            message=(
                f"Commit changes multiple packages: {sorted(packages)}\n"
                "  Split into separate commits for each package."
            ),
        )

    # Check scope matches
    if packages:
        expected_scope = list(packages)[0]
        if commit_info.scope != expected_scope:
            return ValidationResult(
                success=False,
                error=ValidationError.SCOPE_MISMATCH,
                message=(
                    f"Scope '{commit_info.scope}' doesn't match changed files\n"
                    f"  Changed package: {expected_scope}\n"
                    f"  Use: {commit_info.type}({expected_scope}): ..."
                ),
            )
    elif commit_info.scope and commit_info.scope not in ("ci", "deps", "docs"):
        # Scope provided but no package changed (except allowed repo scopes)
        return ValidationResult(
            success=False,
            error=ValidationError.SCOPE_MISMATCH,
            message=(
                f"Scope '{commit_info.scope}' but no package files changed\n"
                "  Remove scope for repo-level changes."
            ),
        )

    return ValidationResult(success=True)


def validate_staged_files(
    staged_files: list[str],
    repo_root: Path,
) -> ValidationResult:
    """Validate staged files for single-package rule.

    Args:
        staged_files: List of staged file paths.
        repo_root: Repository root path.

    Returns:
        ValidationResult with success status and error details.
    """
    packages, repo_level_files = _get_packages_from_files(staged_files, repo_root)

    if len(packages) > 1:
        # Group files by package for helpful error message
        files_by_pkg: dict[str, list[str]] = {}
        for f in staged_files:
            pkg = get_package_from_path(f)
            if pkg:
                files_by_pkg.setdefault(pkg, []).append(f)

        details = "\n".join(
            f"  - {pkg}: {files[0]}"
            for pkg, files in sorted(files_by_pkg.items())
        )

        return ValidationResult(
            success=False,
            error=ValidationError.MULTIPLE_PACKAGES,
            message=(
                "Multiple packages in one commit\n\n"
                f"  Staged files from multiple packages:\n{details}\n\n"
                "  Create separate commits for each package."
            ),
        )

    if packages:
        pkg = list(packages)[0]
        return ValidationResult(
            success=True,
            message=f"✓ Single package: {pkg}",
        )

    return ValidationResult(
        success=True,
        message="✓ Repo-level changes only",
    )


def _get_staged_files(repo_root: Path) -> list[str]:
    """Get list of staged files from git."""
    output = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo_root,
        text=True,
    )
    return [f for f in output.strip().split("\n") if f]


def _get_changed_files_pr(base_ref: str, repo_root: Path) -> list[str]:
    """Get list of changed files in PR compared to base branch."""
    output = subprocess.check_output(
        ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD"],
        cwd=repo_root,
        text=True,
    )
    return [f for f in output.strip().split("\n") if f]


def _get_commits_in_range(before: str, after: str, repo_root: Path) -> list[str]:
    """Get list of commit SHAs in range."""
    output = subprocess.check_output(
        ["git", "rev-list", f"{before}..{after}"],
        cwd=repo_root,
        text=True,
    )
    return [c for c in output.strip().split("\n") if c]


def main() -> int:
    """Main entry point."""
    repo_root = Path.cwd()

    if len(sys.argv) < 2:
        print("Usage: validate.py --hook | --pr | --commits <before> <after>")
        return ValidationError.SCRIPT_ERROR

    mode = sys.argv[1]

    try:
        if mode == "--hook":
            staged_files = _get_staged_files(repo_root)
            if not staged_files:
                print("✓ No staged files")
                return ValidationError.SUCCESS

            result = validate_staged_files(staged_files, repo_root)

        elif mode == "--pr":
            pr_title = os.environ.get("PR_TITLE", "")
            base_ref = os.environ.get("BASE_REF", "main")

            if not pr_title:
                print("Error: PR_TITLE environment variable not set")
                return ValidationError.SCRIPT_ERROR

            changed_files = _get_changed_files_pr(base_ref, repo_root)
            result = validate_pr(pr_title, changed_files, repo_root)

        elif mode == "--commits":
            if len(sys.argv) < 4:
                print("Usage: validate.py --commits <before> <after>")
                return ValidationError.SCRIPT_ERROR

            before, after = sys.argv[2], sys.argv[3]
            commits = _get_commits_in_range(before, after, repo_root)

            if not commits:
                print("✓ No commits to validate")
                return ValidationError.SUCCESS

            errors: list[str] = []
            for sha in commits:
                result = validate_commit(sha, repo_root)
                if not result.success:
                    msg = subprocess.check_output(
                        ["git", "log", "-1", "--format=%s", sha],
                        cwd=repo_root,
                        text=True,
                    ).strip()
                    errors.append(f"❌ {sha[:8]}: {msg}\n   {result.message}")

            if errors:
                print("Commit validation errors:\n")
                print("\n".join(errors))
                return ValidationError.INVALID_FORMAT

            print(f"✓ All {len(commits)} commit(s) valid")
            return ValidationError.SUCCESS

        else:
            print(f"Unknown mode: {mode}")
            return ValidationError.SCRIPT_ERROR

        # Handle result for --hook and --pr modes
        if result.success:
            print(result.message)
            return ValidationError.SUCCESS
        else:
            print(f"✗ {result.message}")
            return result.error or ValidationError.SCRIPT_ERROR

    except subprocess.CalledProcessError as e:
        print(f"Git error: {e}")
        return ValidationError.SCRIPT_ERROR
    except Exception as e:
        print(f"Error: {e}")
        return ValidationError.SCRIPT_ERROR


if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest .github/scripts/tests/test_validate.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add .github/scripts/validate.py .github/scripts/tests/test_validate.py
git commit -m "ci: add validate.py script"
```

---

## Task 5: Implement detect_changes.py

**Files:**
- Create: `.github/scripts/detect_changes.py`
- Create: `.github/scripts/tests/test_detect_changes.py`

**Step 1: Write failing tests for change detection**

Create `.github/scripts/tests/test_detect_changes.py`:
```python
"""Tests for detect_changes.py script."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ..detect_changes import detect_changes, DetectionResult


class TestDetectChanges:
    """Tests for detect_changes function."""

    def test_single_package(self, temp_repo: Path) -> None:
        """Should detect changes in single package."""
        changed_files = [
            "packages/statuskit/src/new_module.py",
            "packages/statuskit/tests/test_new.py",
        ]

        result = detect_changes(changed_files, repo_root=temp_repo)

        assert result.packages == ["statuskit"]
        assert result.has_packages is True
        assert result.has_repo_level is False

    def test_repo_level_only(self, temp_repo: Path) -> None:
        """Should detect repo-level changes only."""
        changed_files = [
            ".github/workflows/ci.yml",
            "README.md",
        ]

        result = detect_changes(changed_files, repo_root=temp_repo)

        assert result.packages == []
        assert result.has_packages is False
        assert result.has_repo_level is True

    def test_mixed_changes(self, temp_repo: Path) -> None:
        """Should detect both package and repo-level changes."""
        changed_files = [
            "packages/statuskit/src/module.py",
            "pyproject.toml",
        ]

        result = detect_changes(changed_files, repo_root=temp_repo)

        assert result.packages == ["statuskit"]
        assert result.has_packages is True
        assert result.has_repo_level is True

    def test_tooling_changed(self, temp_repo: Path) -> None:
        """Should detect tooling changes (root pyproject.toml without packages)."""
        changed_files = [
            "pyproject.toml",
            "uv.lock",
        ]

        result = detect_changes(changed_files, repo_root=temp_repo)

        assert result.tooling_changed is True
        assert result.has_packages is False

    def test_tooling_not_changed_with_package(self, temp_repo: Path) -> None:
        """Should not flag tooling when package is also changed."""
        changed_files = [
            "packages/statuskit/src/module.py",
            "pyproject.toml",
        ]

        result = detect_changes(changed_files, repo_root=temp_repo)

        assert result.tooling_changed is False

    def test_matrix_generation(self, temp_repo: Path) -> None:
        """Should generate CI matrix with Python versions."""
        changed_files = ["packages/statuskit/src/module.py"]

        result = detect_changes(changed_files, repo_root=temp_repo)

        assert len(result.matrix["include"]) == 2  # 3.11, 3.12

        entry = result.matrix["include"][0]
        assert entry["package"] == "statuskit"
        assert entry["path"] == "packages/statuskit"
        assert entry["python"] in ["3.11", "3.12"]

    def test_all_packages_matrix(self, temp_repo: Path) -> None:
        """Should include all packages in all_packages_matrix."""
        changed_files = ["pyproject.toml"]  # Tooling change

        result = detect_changes(changed_files, repo_root=temp_repo)

        # Should include statuskit even though it wasn't changed
        packages_in_matrix = {
            e["package"] for e in result.all_packages_matrix["include"]
        }
        assert "statuskit" in packages_in_matrix


class TestDetectionResultJson:
    """Tests for JSON output format."""

    def test_json_structure(self, temp_repo: Path) -> None:
        """Should produce valid JSON structure."""
        changed_files = ["packages/statuskit/src/module.py"]

        result = detect_changes(changed_files, repo_root=temp_repo)
        output = result.to_json()
        data = json.loads(output)

        assert "packages" in data
        assert "has_packages" in data
        assert "has_repo_level" in data
        assert "tooling_changed" in data
        assert "matrix" in data
        assert "all_packages_matrix" in data
        assert "include" in data["matrix"]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest .github/scripts/tests/test_detect_changes.py -v`
Expected: FAIL with "ModuleNotFoundError" or "cannot import"

**Step 3: Write detect_changes.py implementation**

Create `.github/scripts/detect_changes.py`:
```python
#!/usr/bin/env python3
"""Detect changed packages for CI matrix generation.

Usage:
    git diff --name-only origin/main..HEAD | python detect_changes.py
    python detect_changes.py --ref origin/main..HEAD

Output:
    JSON with packages, matrix, and flags for CI workflow.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .packages import discover_packages, get_package_from_path, is_repo_level_path


@dataclass
class DetectionResult:
    """Result of change detection."""

    packages: list[str] = field(default_factory=list)
    has_packages: bool = False
    has_repo_level: bool = False
    tooling_changed: bool = False
    matrix: dict = field(default_factory=lambda: {"include": []})
    all_packages_matrix: dict = field(default_factory=lambda: {"include": []})

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps({
            "packages": self.packages,
            "has_packages": self.has_packages,
            "has_repo_level": self.has_repo_level,
            "tooling_changed": self.tooling_changed,
            "matrix": self.matrix,
            "all_packages_matrix": self.all_packages_matrix,
        })


def detect_changes(
    changed_files: list[str],
    repo_root: Path,
) -> DetectionResult:
    """Detect changed packages and generate CI matrix.

    Args:
        changed_files: List of changed file paths.
        repo_root: Repository root path.

    Returns:
        DetectionResult with packages and matrix information.
    """
    result = DetectionResult()

    # Discover all packages
    all_packages = discover_packages(repo_root)

    # Find changed packages
    changed_packages: set[str] = set()
    tooling_files = {"pyproject.toml", "uv.lock"}
    has_tooling_files = False

    for f in changed_files:
        pkg = get_package_from_path(f)
        if pkg:
            changed_packages.add(pkg)
        elif is_repo_level_path(f):
            result.has_repo_level = True
            if f in tooling_files:
                has_tooling_files = True

    # Determine if tooling changed (without package changes)
    result.tooling_changed = has_tooling_files and not changed_packages

    # Build result
    result.packages = sorted(changed_packages)
    result.has_packages = bool(changed_packages)

    # Build matrix for changed packages
    for pkg_name in result.packages:
        pkg_info = all_packages.get(pkg_name)
        if pkg_info and pkg_info.python_versions:
            for py_version in pkg_info.python_versions:
                result.matrix["include"].append({
                    "package": pkg_name,
                    "path": pkg_info.path,
                    "python": py_version,
                })

    # Build all_packages_matrix (for tooling check)
    for pkg_name, pkg_info in sorted(all_packages.items()):
        if pkg_info.kind == "package" and pkg_info.python_versions:
            for py_version in pkg_info.python_versions:
                result.all_packages_matrix["include"].append({
                    "package": pkg_name,
                    "path": pkg_info.path,
                    "python": py_version,
                })

    return result


def _get_changed_files_from_ref(ref: str, repo_root: Path) -> list[str]:
    """Get changed files from git ref range."""
    output = subprocess.check_output(
        ["git", "diff", "--name-only", ref],
        cwd=repo_root,
        text=True,
    )
    return [f for f in output.strip().split("\n") if f]


def main() -> int:
    """Main entry point."""
    repo_root = Path.cwd()

    # Get changed files
    if len(sys.argv) > 1 and sys.argv[1] == "--ref":
        if len(sys.argv) < 3:
            print("Usage: detect_changes.py --ref <git-ref>", file=sys.stderr)
            return 1
        changed_files = _get_changed_files_from_ref(sys.argv[2], repo_root)
    else:
        # Read from stdin
        changed_files = [f for f in sys.stdin.read().strip().split("\n") if f]

    try:
        result = detect_changes(changed_files, repo_root)
        print(result.to_json())
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest .github/scripts/tests/test_detect_changes.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add .github/scripts/detect_changes.py .github/scripts/tests/test_detect_changes.py
git commit -m "ci: add detect_changes.py script"
```

---

## Task 6: Add Pre-commit Hook Configuration

**Files:**
- Modify: `.pre-commit-config.yaml`

**Step 1: Read current pre-commit config**

Already read in exploration phase.

**Step 2: Add single-package-commit hook**

Edit `.pre-commit-config.yaml` to add the hook after existing hooks:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.2
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: local
    hooks:
      - id: ty
        name: ty type check
        entry: uv run ty check .
        language: system
        types: [python]
        pass_filenames: false

      - id: single-package-commit
        name: Check single package per commit
        entry: uv run python .github/scripts/validate.py --hook
        language: system
        always_run: true
        pass_filenames: false

      - id: beads
        name: beads sync
        entry: bd hooks run pre-commit
        language: system
        always_run: true
        pass_filenames: false
```

**Step 3: Test hook locally**

Run: `uv run pre-commit run single-package-commit --all-files`
Expected: Should pass (or show "No staged files")

**Step 4: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "ci: add single-package-commit pre-commit hook"
```

---

## Task 7: Run Full Test Suite

**Files:**
- None (verification only)

**Step 1: Run all tests**

Run: `uv run pytest .github/scripts/tests/ -v`
Expected: All tests PASS

**Step 2: Run lint on new scripts**

Run: `uv run ruff check .github/scripts/`
Expected: No errors

**Step 3: Run format check**

Run: `uv run ruff format --check .github/scripts/`
Expected: Already formatted

**Step 4: Run type check**

Run: `uv run ty check .github/scripts/`
Expected: No type errors

**Step 5: Final commit if any fixes needed**

If any lint/format/type fixes were needed:
```bash
git add .github/scripts/
git commit -m "ci: fix lint/type issues in validation scripts"
```

---

## Summary

| Task | Deliverable | Tests |
|------|-------------|-------|
| 1 | Test infrastructure + conftest.py | Fixture verification |
| 2 | packages.py | 8 tests |
| 3 | commits.py | 10 tests |
| 4 | validate.py | 10 tests |
| 5 | detect_changes.py | 8 tests |
| 6 | Pre-commit hook | Manual verification |
| 7 | Full verification | All tests pass |

**Total: ~36 tests**
