"""Project discovery for monorepo validation."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 - used at runtime


@dataclass
class CIConfig:
    """CI configuration from pyproject.toml."""

    tooling_files: list[str]
    project_types: dict[str, list[str]]


@dataclass
class ProjectInfo:
    """Information about a package or plugin."""

    name: str
    path: str
    kind: str  # "package" or "plugin"
    python_versions: list[str]


def get_ci_config(repo_root: Path) -> CIConfig:
    """Load CI config from pyproject.toml.

    Args:
        repo_root: Path to repository root.

    Returns:
        CIConfig with tooling_files and project_types.

    Raises:
        ValueError: If [tool.ci] section is missing.
    """
    pyproject_path = repo_root / "pyproject.toml"
    content = pyproject_path.read_text()
    data = tomllib.loads(content)

    ci_config = data.get("tool", {}).get("ci")
    if ci_config is None:
        msg = "Missing [tool.ci] configuration in pyproject.toml"
        raise ValueError(msg)

    return CIConfig(
        tooling_files=ci_config.get("tooling_files", []),
        project_types=ci_config.get("project-types", {}),
    )


def get_project_from_path(path: str, repo_root: Path | None = None) -> str | None:
    """Extract package/plugin name from file path.

    Args:
        path: File path relative to repo root.
        repo_root: Repository root for loading config. If None, uses hardcoded prefixes.

    Returns:
        Package/plugin name or None if repo-level path.
    """
    if repo_root is not None:
        config = get_ci_config(repo_root)
        for prefixes in config.project_types.values():
            for prefix in prefixes:
                if path.startswith(f"{prefix}/"):
                    parts = path.split("/")
                    return parts[1] if len(parts) > 1 else None
        return None

    # Fallback for backwards compatibility (no repo_root provided)
    if path.startswith("packages/"):
        parts = path.split("/")
        return parts[1] if len(parts) > 1 else None
    if path.startswith("plugins/"):
        parts = path.split("/")
        return parts[1] if len(parts) > 1 else None
    return None


def is_repo_level_path(path: str, repo_root: Path | None = None) -> bool:
    """Check if path is a repo-level file (not in any project).

    Args:
        path: File path relative to repo root.
        repo_root: Repository root for loading config.

    Returns:
        True if repo-level (not belonging to any project), False otherwise.
    """
    return get_project_from_path(path, repo_root) is None


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
    """Discover all projects based on [tool.ci] configuration.

    Args:
        repo_root: Path to repository root.

    Returns:
        Dict mapping project name to ProjectInfo.

    Raises:
        ValueError: If scope collision detected or missing classifiers.
    """
    config = get_ci_config(repo_root)
    projects: dict[str, ProjectInfo] = {}

    for kind, dirs in config.project_types.items():
        for dir_name in dirs:
            dir_path = repo_root / dir_name
            if not dir_path.exists():
                continue

            for project_dir in dir_path.iterdir():
                if not project_dir.is_dir():
                    continue

                name = project_dir.name

                # Check for collision
                if name in projects:
                    msg = (
                        f"Scope collision detected\n\n"
                        f"  Name '{name}' exists in multiple locations:\n"
                        f"    - {projects[name].path}/\n"
                        f"    - {dir_name}/{name}/\n\n"
                        f"  Rename one to ensure unique scope names."
                    )
                    raise ValueError(msg)

                python_versions = _get_python_versions(project_dir)

                projects[name] = ProjectInfo(
                    name=name,
                    path=f"{dir_name}/{name}",
                    kind=kind,
                    python_versions=python_versions,
                )

    return projects


def _get_python_versions(project_dir: Path) -> list[str]:
    """Get Python versions for a project.

    Parses from pyproject.toml classifiers if available.
    Returns empty list if no pyproject.toml or no classifiers.
    """
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.exists():
        return []

    try:
        return _parse_python_versions(pyproject)
    except ValueError:
        # No Python classifiers found - not a Python project
        return []
