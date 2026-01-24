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
class ByTypeResult:
    """Result for a single project type."""

    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    has_changed: bool = False
    has_unchanged: bool = False
    matrix: dict = field(default_factory=lambda: {"include": []})
    unchanged_matrix: dict = field(default_factory=lambda: {"include": []})
    # Flat matrix for test jobs: one entry per (project, python_version)
    test_matrix: dict = field(default_factory=lambda: {"include": []})
    unchanged_test_matrix: dict = field(default_factory=lambda: {"include": []})


@dataclass
class DetectionResult:
    """Result of change detection."""

    by_type: dict[str, ByTypeResult] = field(default_factory=dict)
    total_changed_count: int = 0
    single_project: str | None = None
    single_project_type: str | None = None
    has_repo_level: bool = False
    tooling_changed: bool = False
    changed_files: dict[str, list[str]] = field(default_factory=dict)
    project_types: list[str] = field(default_factory=list)

    # Legacy fields for backward compatibility during migration
    projects: list[str] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)
    has_packages: bool = False
    has_plugins: bool = False
    matrix: dict = field(default_factory=lambda: {"include": []})
    all_packages_matrix: dict = field(default_factory=lambda: {"include": []})

    def to_json(self) -> str:
        """Convert to JSON string."""
        by_type_dict = {}
        for kind, data in self.by_type.items():
            by_type_dict[kind] = {
                "changed": data.changed,
                "unchanged": data.unchanged,
                "has_changed": data.has_changed,
                "has_unchanged": data.has_unchanged,
                "matrix": data.matrix,
                "unchanged_matrix": data.unchanged_matrix,
                "test_matrix": data.test_matrix,
                "unchanged_test_matrix": data.unchanged_test_matrix,
            }

        return json.dumps(
            {
                "by_type": by_type_dict,
                "total_changed_count": self.total_changed_count,
                "single_project": self.single_project,
                "single_project_type": self.single_project_type,
                "has_repo_level": self.has_repo_level,
                "tooling_changed": self.tooling_changed,
                "changed_files": self.changed_files,
                "project_types": self.project_types,
                # Legacy fields
                "projects": self.projects,
                "packages": self.packages,
                "plugins": self.plugins,
                "has_packages": self.has_packages,
                "has_plugins": self.has_plugins,
                "matrix": self.matrix,
                "all_packages_matrix": self.all_packages_matrix,
            }
        )


def detect_changes(  # noqa: PLR0912, PLR0915 - complex due to backward compat
    changed_files: list[str],
    repo_root: Path,
) -> DetectionResult:
    """Detect changed projects and generate CI matrices."""
    try:
        from .projects import (
            discover_projects,
            get_ci_config,
            get_project_from_path,
        )
    except ImportError:
        from projects import (
            discover_projects,
            get_ci_config,
            get_project_from_path,
        )

    config = get_ci_config(repo_root)
    all_projects = discover_projects(repo_root)
    result = DetectionResult()
    result.project_types = list(config.project_types.keys())

    # Initialize by_type for all configured types
    for kind in config.project_types:
        result.by_type[kind] = ByTypeResult()

    # Track changed projects by type
    changed_by_type: dict[str, set[str]] = {k: set() for k in config.project_types}
    all_changed_projects: set[str] = set()

    # Check for tooling files from config
    tooling_files_set = set(config.tooling_files)

    for f in changed_files:
        project_name = get_project_from_path(f)
        if project_name:
            all_changed_projects.add(project_name)
            project_info = all_projects.get(project_name)
            if project_info:
                changed_by_type[project_info.kind].add(project_name)
        else:
            result.has_repo_level = True
            if f in tooling_files_set:
                result.tooling_changed = True

    # If projects changed, tooling_changed should be False (they are tested explicitly)
    if all_changed_projects:
        result.tooling_changed = False

    # Populate by_type results
    for kind, changed_set in changed_by_type.items():
        by_type = result.by_type[kind]
        by_type.changed = sorted(changed_set)
        by_type.has_changed = bool(changed_set)

        # Find unchanged projects of this type
        all_of_type = [p for p in all_projects.values() if p.kind == kind]
        unchanged = [p.name for p in all_of_type if p.name not in changed_set]
        by_type.unchanged = sorted(unchanged)
        by_type.has_unchanged = bool(unchanged)

        # Build matrices
        for proj_name in by_type.changed:
            proj = all_projects.get(proj_name)
            if proj:
                entry: dict[str, str | list[str]] = {
                    "project": proj_name,
                    "path": proj.path,
                }
                if proj.python_versions:
                    entry["python-versions"] = proj.python_versions
                    # Build flat test matrix: one entry per python version
                    for py_ver in proj.python_versions:
                        by_type.test_matrix["include"].append(
                            {
                                "project": proj_name,
                                "path": proj.path,
                                "python": py_ver,
                                "python-versions": proj.python_versions,
                            }
                        )
                by_type.matrix["include"].append(entry)

        for proj_name in by_type.unchanged:
            proj = all_projects.get(proj_name)
            if proj:
                entry = {
                    "project": proj_name,
                    "path": proj.path,
                }
                if proj.python_versions:
                    entry["python-versions"] = proj.python_versions
                    # Build flat unchanged test matrix
                    for py_ver in proj.python_versions:
                        by_type.unchanged_test_matrix["include"].append(
                            {
                                "project": proj_name,
                                "path": proj.path,
                                "python": py_ver,
                                "python-versions": proj.python_versions,
                            }
                        )
                by_type.unchanged_matrix["include"].append(entry)

    # Set single_project fields
    result.total_changed_count = len(all_changed_projects)
    if result.total_changed_count == 1:
        proj_name = next(iter(all_changed_projects))
        result.single_project = proj_name
        proj = all_projects.get(proj_name)
        if proj:
            result.single_project_type = proj.kind

    # Populate legacy fields for backward compatibility
    result.projects = sorted(all_changed_projects)
    result.packages = sorted(changed_by_type.get("package", set()))
    result.plugins = sorted(changed_by_type.get("plugin", set()))
    result.has_packages = bool(result.packages)
    result.has_plugins = bool(result.plugins)

    # Legacy matrix uses "package" key instead of "project"
    result.matrix = {"include": []}
    for pkg_name in result.packages:
        proj = all_projects.get(pkg_name)
        if proj and proj.python_versions:
            result.matrix["include"].append(
                {
                    "package": proj.name,
                    "path": proj.path,
                    "python-versions": proj.python_versions,
                }
            )

    result.all_packages_matrix = {"include": []}
    for proj in all_projects.values():
        if proj.kind == "package" and proj.python_versions:
            result.all_packages_matrix["include"].append(
                {
                    "package": proj.name,
                    "path": proj.path,
                    "python-versions": proj.python_versions,
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
