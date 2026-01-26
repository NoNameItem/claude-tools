"""Shared fixtures for validation scripts tests."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo with packages/plugins structure.

    Structure created:
    - packages/statuskit/pyproject.toml (with Python classifiers)
    - packages/statuskit/src/statuskit/__init__.py
    - plugins/flow/.claude-plugin/plugin.json
    - README.md (repo-level file)
    - pyproject.toml (with [tool.ci] config)
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    # Init git
    subprocess.run(
        ["git", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
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

    # Create root pyproject.toml with [tool.repo] config
    (repo / "pyproject.toml").write_text("""\
[project]
name = "test-repo"
version = "0.1.0"

[tool.repo]
tooling_files = ["pyproject.toml", "uv.lock"]

[tool.repo.project-types.python]
paths = ["packages"]
publish = ["pypi"]

[tool.repo.project-types.claude-code-plugin]
paths = ["plugins"]
publish = []
""")

    # Create packages/statuskit structure
    statuskit_dir = repo / "packages" / "statuskit"
    statuskit_src = statuskit_dir / "src" / "statuskit"
    statuskit_src.mkdir(parents=True)

    (statuskit_dir / "pyproject.toml").write_text("""\
[project]
name = "statuskit"
version = "0.1.0"
classifiers = [
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
""")
    (statuskit_src / "__init__.py").write_text('__version__ = "0.1.0"\n')

    # Create plugins/flow structure
    flow_dir = repo / "plugins" / "flow"
    flow_plugin_dir = flow_dir / ".claude-plugin"
    flow_plugin_dir.mkdir(parents=True)
    (flow_plugin_dir / "plugin.json").write_text('{"name": "flow", "version": "1.0.0"}\n')

    # Create repo-level file
    (repo / "README.md").write_text("# Test Repo\n")

    # Initial commit
    subprocess.run(
        ["git", "add", "."],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: initial commit"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    return repo


@pytest.fixture
def temp_repo_with_another_package(temp_repo: Path) -> Path:
    """Extend temp_repo with another package for multi-package tests."""
    another_dir = temp_repo / "packages" / "another"
    another_src = another_dir / "src" / "another"
    another_src.mkdir(parents=True)

    (another_dir / "pyproject.toml").write_text("""\
[project]
name = "another"
version = "0.1.0"
classifiers = [
    "Programming Language :: Python :: 3.11",
]
""")
    (another_src / "__init__.py").write_text('__version__ = "0.1.0"\n')

    subprocess.run(
        ["git", "add", "."],
        cwd=temp_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: add another package"],
        cwd=temp_repo,
        check=True,
        capture_output=True,
    )

    return temp_repo
