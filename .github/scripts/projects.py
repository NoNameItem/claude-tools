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


def get_project_from_path(path: str) -> str | None:
    """
    Extract the package or plugin name from a repository-relative path.
    
    Parameters:
        path (str): Path relative to the repository root.
    
    Returns:
        The project name (the second path component) if the path starts with "packages/" or "plugins/", `None` otherwise.
    """
    if path.startswith("packages/"):
        parts = path.split("/")
        return parts[1] if len(parts) > 1 else None
    if path.startswith("plugins/"):
        parts = path.split("/")
        return parts[1] if len(parts) > 1 else None
    return None


def is_repo_level_path(path: str) -> bool:
    """
    Determine whether the given path refers to a repository-level file (not inside any project).
    
    Parameters:
        path (str): File path relative to the repository root.
    
    Returns:
        `true` if the path is repository-level (does not belong to any package or plugin), `false` otherwise.
    """
    return get_project_from_path(path) is None


def _parse_python_versions(pyproject_path: Path) -> list[str]:
    """
    Extract Python `X.Y` version strings from a package's pyproject.toml classifiers.
    
    Parameters:
        pyproject_path (Path): Path to the project's pyproject.toml file.
    
    Returns:
        list[str]: Discovered Python versions (e.g., ["3.11", "3.12"]).
    
    Raises:
        ValueError: If no Python classifiers of the form
            "Programming Language :: Python :: X.Y" are present; the exception
            message contains guidance and the package/file context.
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
    """
    Discover projects defined in the repository according to the [tool.ci] configuration in pyproject.toml.
    
    Parameters:
        repo_root (Path): Path to repository root.
    
    Returns:
        dict[str, ProjectInfo]: Mapping from project name to its ProjectInfo (name, path, kind, python_versions).
    
    Raises:
        ValueError: If two projects share the same name (scope collision) or if a package is missing Python classifiers required to determine supported versions.
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

                python_versions = _get_python_versions(project_dir, kind)

                projects[name] = ProjectInfo(
                    name=name,
                    path=f"{dir_name}/{name}",
                    kind=kind,
                    python_versions=python_versions,
                )

    return projects


def _get_python_versions(project_dir: Path, kind: str) -> list[str]:
    """
    Determine the Python versions declared for a project.
    
    For projects of kind "package", returns the Python versions declared in the project's pyproject.toml classifiers.
    For non-package kinds or when pyproject.toml is missing, returns an empty list.
    
    Parameters:
        project_dir (Path): Path to the project directory.
        kind (str): Project kind (e.g., "package", "plugin").
    
    Returns:
        list[str]: Python version strings extracted from classifiers (e.g., "3.10"), or an empty list if none are declared.
    """
    if kind != "package":
        return []

    pyproject = project_dir / "pyproject.toml"
    if not pyproject.exists():
        return []

    return _parse_python_versions(pyproject)