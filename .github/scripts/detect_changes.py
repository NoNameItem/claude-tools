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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def build_changed_files_map(changed_files: list[str]) -> dict[str, list[str]]:
    """Group changed files by project.

    Returns ALL files without extension filtering.
    Filtering (.py etc.) happens on consumer side (workflow).

    Args:
        changed_files: List of file paths relative to repo root.

    Returns:
        Dict mapping project name to list of files.
        Repo-level files are under "repo" key.
    """
    try:
        from .projects import get_project_from_path
    except ImportError:
        from projects import get_project_from_path

    result: dict[str, list[str]] = {}

    for file_path in changed_files:
        project_name = get_project_from_path(file_path)
        key = project_name if project_name else "repo"

        if key not in result:
            result[key] = []
        result[key].append(file_path)

    return result


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
    changed_files: dict[str, list[str]] = field(default_factory=dict)

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
                "changed_files": self.changed_files,
            }
        )


def detect_changes(
    changed_files: list[str],
    repo_root: Path,
) -> DetectionResult:
    """Detect changed packages and generate CI matrix."""
    try:
        from .projects import (  # type: ignore[unresolved-import]
            discover_projects,
            get_project_from_path,
            is_repo_level_path,
        )
    except ImportError:
        from projects import (  # type: ignore[unresolved-import]
            discover_projects,
            get_project_from_path,
            is_repo_level_path,
        )

    result = DetectionResult()
    all_projects = discover_projects(repo_root)

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

    # Build matrix for changed packages (one entry per package)
    for pkg_name in result.packages:
        pkg_info = all_projects.get(pkg_name)
        if pkg_info and pkg_info.python_versions:
            result.matrix["include"].append(
                {
                    "package": pkg_name,
                    "path": pkg_info.path,
                    "python-versions": pkg_info.python_versions,
                }
            )

    # Build all_packages_matrix (one entry per package)
    for pkg_name, pkg_info in sorted(all_projects.items()):
        if pkg_info.kind == "package" and pkg_info.python_versions:
            result.all_packages_matrix["include"].append(
                {
                    "package": pkg_name,
                    "path": pkg_info.path,
                    "python-versions": pkg_info.python_versions,
                }
            )

    result.changed_files = build_changed_files_map(changed_files)

    return result


def _get_changed_files_from_ref(ref: str, repo_root: Path) -> list[str]:
    """Get changed files from git ref range."""
    output = subprocess.check_output(
        ["git", "diff", "--name-only", ref],  # noqa: S607
        cwd=repo_root,
        text=True,
    )
    return [f for f in output.strip().split("\n") if f]


def main() -> int:
    """Main entry point."""
    from pathlib import Path

    repo_root = Path.cwd()

    if len(sys.argv) > 1 and sys.argv[1] == "--ref":
        if len(sys.argv) < 3:  # noqa: PLR2004
            print("Usage: detect_changes.py --ref <git-ref>", file=sys.stderr)
            return 1
        changed_files = _get_changed_files_from_ref(sys.argv[2], repo_root)
    else:
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
