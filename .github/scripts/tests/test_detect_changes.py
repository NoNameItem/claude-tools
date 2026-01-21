"""Tests for detect_changes.py script."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..detect_changes import detect_changes

if TYPE_CHECKING:
    from pathlib import Path


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
        changed_files = [".github/workflows/ci.yml", "README.md"]
        result = detect_changes(changed_files, repo_root=temp_repo)
        assert result.packages == []
        assert result.has_packages is False
        assert result.has_repo_level is True

    def test_mixed_changes(self, temp_repo: Path) -> None:
        """Should detect both package and repo-level changes."""
        changed_files = ["packages/statuskit/src/module.py", "pyproject.toml"]
        result = detect_changes(changed_files, repo_root=temp_repo)
        assert result.packages == ["statuskit"]
        assert result.has_packages is True
        assert result.has_repo_level is True

    def test_tooling_changed(self, temp_repo: Path) -> None:
        """Should detect tooling changes."""
        changed_files = ["pyproject.toml", "uv.lock"]
        result = detect_changes(changed_files, repo_root=temp_repo)
        assert result.tooling_changed is True
        assert result.has_packages is False

    def test_tooling_not_changed_with_package(self, temp_repo: Path) -> None:
        """Should not flag tooling when package is also changed."""
        changed_files = ["packages/statuskit/src/module.py", "pyproject.toml"]
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
        changed_files = ["pyproject.toml"]
        result = detect_changes(changed_files, repo_root=temp_repo)
        packages_in_matrix = {e["package"] for e in result.all_packages_matrix["include"]}
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
