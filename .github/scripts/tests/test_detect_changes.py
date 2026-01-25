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
        assert len(result.matrix["include"]) == 1
        entry = result.matrix["include"][0]
        assert entry["package"] == "statuskit"
        assert entry["path"] == "packages/statuskit"
        assert entry["python-versions"] == ["3.11", "3.12"]

    def test_matrix_has_python_versions_array(self, temp_repo: Path) -> None:
        """Matrix entry should have python-versions as array."""
        changed_files = ["packages/statuskit/src/module.py"]
        result = detect_changes(changed_files, repo_root=temp_repo)
        assert len(result.matrix["include"]) == 1
        entry = result.matrix["include"][0]
        assert entry["package"] == "statuskit"
        assert entry["path"] == "packages/statuskit"
        assert entry["python-versions"] == ["3.11", "3.12"]
        assert "python" not in entry  # Old field should not exist

    def test_all_packages_matrix(self, temp_repo: Path) -> None:
        """Should include all packages in all_packages_matrix."""
        changed_files = ["pyproject.toml"]
        result = detect_changes(changed_files, repo_root=temp_repo)
        packages_in_matrix = {e["package"] for e in result.all_packages_matrix["include"]}
        assert "statuskit" in packages_in_matrix


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

    def test_json_has_changed_files(self, temp_repo: Path) -> None:
        """Should include changed_files in JSON output."""
        changed_files = ["packages/statuskit/src/module.py"]
        result = detect_changes(changed_files, repo_root=temp_repo)
        output = result.to_json()
        data = json.loads(output)
        assert "changed_files" in data
        assert data["changed_files"] == {"statuskit": ["packages/statuskit/src/module.py"]}


class TestBuildChangedFilesMap:
    """Tests for build_changed_files_map function."""

    def test_single_package(self, temp_repo: Path) -> None:
        """Should group files by package."""
        from ..detect_changes import build_changed_files_map

        files = ["packages/statuskit/src/foo.py", "packages/statuskit/tests/test_foo.py"]
        result = build_changed_files_map(files, temp_repo)
        assert result == {"statuskit": files}

    def test_repo_level_files(self, temp_repo: Path) -> None:
        """Should group repo-level files under 'repo' key."""
        from ..detect_changes import build_changed_files_map

        files = ["pyproject.toml", ".github/scripts/validate.py"]
        result = build_changed_files_map(files, temp_repo)
        assert result == {"repo": files}

    def test_mixed_files(self, temp_repo: Path) -> None:
        """Should separate package and repo-level files."""
        from ..detect_changes import build_changed_files_map

        files = [
            "packages/statuskit/src/foo.py",
            "packages/statuskit/README.md",
            "pyproject.toml",
        ]
        result = build_changed_files_map(files, temp_repo)
        assert result == {
            "statuskit": ["packages/statuskit/src/foo.py", "packages/statuskit/README.md"],
            "repo": ["pyproject.toml"],
        }

    def test_multiple_packages(self, temp_repo_with_another_package: Path) -> None:
        """Should group files by their respective packages."""
        from ..detect_changes import build_changed_files_map

        files = [
            "packages/statuskit/src/foo.py",
            "packages/another/src/bar.py",
        ]
        result = build_changed_files_map(files, temp_repo_with_another_package)
        assert result == {
            "statuskit": ["packages/statuskit/src/foo.py"],
            "another": ["packages/another/src/bar.py"],
        }

    def test_empty_list(self, temp_repo: Path) -> None:
        """Should return empty dict for empty input."""
        from ..detect_changes import build_changed_files_map

        result = build_changed_files_map([], temp_repo)
        assert result == {}


class TestDetectChangesNewStructure:
    """Tests for new detect_changes output structure."""

    def test_by_type_structure(self, temp_repo: Path) -> None:
        """Should output by_type with changed/unchanged per type."""
        changed_files = ["packages/statuskit/src/module.py"]
        result = detect_changes(changed_files, repo_root=temp_repo)

        assert hasattr(result, "by_type")
        assert "package" in result.by_type
        pkg_data = result.by_type["package"]
        assert pkg_data.changed == ["statuskit"]
        assert pkg_data.has_changed is True
        assert pkg_data.matrix is not None

    def test_single_project_field(self, temp_repo: Path) -> None:
        """Should have single_project when exactly one project changed."""
        changed_files = ["packages/statuskit/src/module.py"]
        result = detect_changes(changed_files, repo_root=temp_repo)

        assert result.single_project == "statuskit"
        assert result.single_project_type == "package"
        assert result.total_changed_count == 1

    def test_total_changed_count_multiple(self, temp_repo: Path) -> None:
        """Should count total changed projects across types."""
        changed_files = [
            "packages/statuskit/src/module.py",
            "plugins/flow/skills/start.md",
        ]
        result = detect_changes(changed_files, repo_root=temp_repo)

        assert result.total_changed_count == 2
        assert result.single_project is None
        assert result.single_project_type is None

    def test_tooling_changed_from_config(self, temp_repo: Path) -> None:
        """Should detect tooling changes from config tooling_files."""
        # temp_repo fixture has tooling_files = ["pyproject.toml", "uv.lock"]
        changed_files = ["uv.lock"]
        result = detect_changes(changed_files, repo_root=temp_repo)

        assert result.tooling_changed is True

    def test_unchanged_matrix_when_tooling_changed(self, temp_repo: Path) -> None:
        """Should include unchanged_matrix when tooling changed."""
        changed_files = ["pyproject.toml"]
        result = detect_changes(changed_files, repo_root=temp_repo)

        assert result.tooling_changed is True
        pkg_data = result.by_type["package"]
        assert pkg_data.has_unchanged is True
        assert len(pkg_data.unchanged_matrix["include"]) > 0

    def test_test_matrix_flat_structure(self, temp_repo: Path) -> None:
        """Should have flat test_matrix with one entry per python version."""
        changed_files = ["packages/statuskit/src/module.py"]
        result = detect_changes(changed_files, repo_root=temp_repo)

        pkg_data = result.by_type["package"]
        # temp_repo has Python 3.11 and 3.12
        assert len(pkg_data.test_matrix["include"]) == 2
        entries = pkg_data.test_matrix["include"]
        assert entries[0]["project"] == "statuskit"
        assert entries[0]["python"] == "3.11"
        assert entries[1]["python"] == "3.12"
        # Each entry should have python-versions for coverage upload logic
        assert entries[0]["python-versions"] == ["3.11", "3.12"]
