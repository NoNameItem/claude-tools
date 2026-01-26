#!/usr/bin/env python3
"""Resolve publish targets for a release tag.

Usage:
    python resolve_publish.py <release-tag>

Example:
    python resolve_publish.py statuskit-0.2.0

Output:
    JSON with project info and publish targets.
"""

from __future__ import annotations

import json
import re
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def parse_release_tag(tag: str) -> tuple[str, str]:
    """Parse release tag into component and version.

    Args:
        tag: Release tag in format "component-version".

    Returns:
        Tuple of (component, version).

    Raises:
        ValueError: If tag format is invalid.
    """
    # Match: component-version where version starts with digit
    match = re.match(r"^(.+)-(\d.+)$", tag)
    if not match:
        msg = f"Invalid release tag format: {tag}. Expected: component-version"
        raise ValueError(msg)

    return match.group(1), match.group(2)


def resolve_publish(tag: str, repo_root: Path) -> dict:
    """Resolve publish targets for a release tag.

    Args:
        tag: Release tag (e.g., "statuskit-0.2.0").
        repo_root: Repository root path.

    Returns:
        Dict with project_name, project_path, project_type, version, publish_targets.

    Raises:
        ValueError: If component is unknown or config is missing.
    """
    try:
        from .projects import discover_projects, get_repo_config
    except ImportError:
        from projects import discover_projects, get_repo_config

    component, version = parse_release_tag(tag)

    # Find project by name using discover_projects
    projects = discover_projects(repo_root)

    if component not in projects:
        msg = f"Unknown component: {component}. Not found in discovered projects."
        raise ValueError(msg)

    project = projects[component]
    project_type = project.kind

    # Get publish targets from repo config
    repo_config = get_repo_config(repo_root)
    publish_targets = repo_config.project_types[project_type].publish

    return {
        "project_name": component,
        "project_path": project.path,
        "project_type": project_type,
        "version": version,
        "publish_targets": publish_targets,
    }


def main() -> int:
    """Main entry point."""
    from pathlib import Path

    if len(sys.argv) < 2:  # noqa: PLR2004
        print("Usage: resolve_publish.py <release-tag>", file=sys.stderr)
        return 1

    tag = sys.argv[1]
    repo_root = Path.cwd()

    try:
        result = resolve_publish(tag, repo_root)
        print(json.dumps(result))
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
