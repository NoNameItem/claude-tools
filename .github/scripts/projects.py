"""Project discovery for monorepo validation."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class ProjectInfo:
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


def get_project_from_path(path: str) -> str | None:
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
    return get_project_from_path(path) is None


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
        msg = (
            f"Missing Python version classifiers\n\n"
            f"  Package: {pyproject_path.parent.name}\n"
            f"  File: {pyproject_path}\n\n"
            f"  Add classifiers like:\n"
            f"    classifiers = [\n"
            f'        "Programming Language :: Python :: 3.11",\n'
            f'        "Programming Language :: Python :: 3.12",\n'
            f"    ]"
        )
        raise ValueError(msg)

    return versions


def discover_projects(repo_root: Path) -> dict[str, ProjectInfo]:
    """Discover all packages and plugins in the repository.

    Args:
        repo_root: Path to repository root.

    Returns:
        Dict mapping package/plugin name to ProjectInfo.

    Raises:
        ValueError: If scope collision detected or missing classifiers.
    """
    projects: dict[str, ProjectInfo] = {}

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

            projects[name] = ProjectInfo(
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
            if name in projects:
                msg = (
                    f"Scope collision detected\n\n"
                    f"  Name '{name}' exists in both:\n"
                    f"    - packages/{name}/\n"
                    f"    - plugins/{name}/\n\n"
                    f"  Rename one to ensure unique scope names."
                )
                raise ValueError(msg)

            projects[name] = ProjectInfo(
                name=name,
                path=f"plugins/{name}",
                kind="plugin",
                python_versions=[],  # Plugins don't have Python versions
            )

    return projects
