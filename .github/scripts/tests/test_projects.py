"""Tests for project discovery module."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..projects import (
    discover_projects,
    get_project_from_path,
    is_repo_level_path,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestGetProjectFromPath:
    """Tests for get_project_from_path function."""

    def test_package_path(self) -> None:
        """Should extract package name from packages/* path."""
        assert get_project_from_path("packages/statuskit/src/foo.py") == "statuskit"

    def test_plugin_path(self) -> None:
        """Should extract plugin name from plugins/* path."""
        assert get_project_from_path("plugins/flow/skills/start.md") == "flow"

    def test_repo_level_path(self) -> None:
        """Should return None for repo-level paths."""
        assert get_project_from_path("README.md") is None
        assert get_project_from_path(".github/workflows/ci.yml") is None
        assert get_project_from_path("docs/design.md") is None

    def test_root_pyproject(self) -> None:
        """Should return None for root pyproject.toml."""
        assert get_project_from_path("pyproject.toml") is None

    def test_package_pyproject(self) -> None:
        """Should extract package from package's pyproject.toml."""
        assert get_project_from_path("packages/statuskit/pyproject.toml") == "statuskit"


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


class TestDiscoverProjects:
    """Tests for discover_projects function."""

    def test_discovers_packages(self, temp_repo: Path) -> None:
        """Should discover packages from packages/ directory."""
        projects = discover_projects(temp_repo)

        assert "statuskit" in projects
        assert projects["statuskit"].name == "statuskit"
        assert projects["statuskit"].path == "packages/statuskit"
        assert projects["statuskit"].kind == "python"

    def test_discovers_plugins(self, temp_repo: Path) -> None:
        """Should discover plugins from plugins/ directory."""
        projects = discover_projects(temp_repo)

        assert "flow" in projects
        assert projects["flow"].name == "flow"
        assert projects["flow"].path == "plugins/flow"
        assert projects["flow"].kind == "claude-code-plugin"

    def test_detects_collision(self, temp_repo: Path) -> None:
        """Should raise error if same name in packages/ and plugins/."""
        # Create collision: plugins/statuskit
        collision_dir = temp_repo / "plugins" / "statuskit"
        collision_dir.mkdir(parents=True)
        (collision_dir / "plugin.json").write_text("{}")

        with pytest.raises(ValueError, match="Scope collision"):
            discover_projects(temp_repo)

    def test_parses_python_versions(self, temp_repo: Path) -> None:
        """Should parse Python versions from classifiers."""
        projects = discover_projects(temp_repo)

        assert projects["statuskit"].python_versions == ["3.11", "3.12"]

    def test_missing_classifiers(self, temp_repo: Path) -> None:
        """Should return empty python_versions if no classifiers."""
        # Create package without classifiers
        no_classifiers_dir = temp_repo / "packages" / "noclassifiers"
        no_classifiers_dir.mkdir(parents=True)
        (no_classifiers_dir / "pyproject.toml").write_text("""\
[project]
name = "noclassifiers"
version = "0.1.0"
""")

        projects = discover_projects(temp_repo)
        assert "noclassifiers" in projects
        assert projects["noclassifiers"].python_versions == []


class TestRepoConfig:
    """Tests for [tool.repo] config loading."""

    def test_get_repo_config_reads_toml(self, temp_repo: Path) -> None:
        """Should read [tool.repo] from pyproject.toml."""
        from ..projects import get_repo_config

        (temp_repo / "pyproject.toml").write_text("""\
[project]
name = "test"

[tool.repo]
tooling_files = ["pyproject.toml", "uv.lock"]

[tool.repo.project-types.python]
paths = ["packages"]
publish = ["pypi"]

[tool.repo.project-types.claude-code-plugin]
paths = ["plugins"]
publish = []
""")
        config = get_repo_config(temp_repo)
        assert config.tooling_files == ["pyproject.toml", "uv.lock"]
        assert "python" in config.project_types
        assert config.project_types["python"].paths == ["packages"]
        assert config.project_types["python"].publish == ["pypi"]
        assert "claude-code-plugin" in config.project_types
        assert config.project_types["claude-code-plugin"].publish == []

    def test_get_repo_config_missing_raises(self, temp_repo: Path) -> None:
        """Should raise error if [tool.repo] is missing."""
        from ..projects import get_repo_config

        (temp_repo / "pyproject.toml").write_text("""\
[project]
name = "test"
""")
        with pytest.raises(ValueError, match=r"Missing \[tool.repo\]"):
            get_repo_config(temp_repo)

    def test_project_type_kind_mapping(self, temp_repo: Path) -> None:
        """Should map project type name to kind in ProjectInfo."""
        projects = discover_projects(temp_repo)
        assert projects["statuskit"].kind == "python"
        assert projects["flow"].kind == "claude-code-plugin"


class TestCIConfig:
    """Tests for CI config loading (legacy compatibility)."""

    def test_get_ci_config_reads_toml(self, temp_repo: Path) -> None:
        """Should read [tool.repo] from pyproject.toml via legacy wrapper."""
        from ..projects import get_ci_config

        config = get_ci_config(temp_repo)
        assert config.tooling_files == ["pyproject.toml", "uv.lock"]
        assert config.project_types == {
            "python": ["packages"],
            "claude-code-plugin": ["plugins"],
        }

    def test_get_ci_config_missing_raises(self, temp_repo: Path) -> None:
        """Should raise error if [tool.repo] is missing."""
        from ..projects import get_ci_config

        (temp_repo / "pyproject.toml").write_text("""\
[project]
name = "test"
""")
        with pytest.raises(ValueError, match=r"Missing \[tool.repo\]"):
            get_ci_config(temp_repo)


class TestDiscoverProjectsConfigDriven:
    """Tests for config-driven project discovery."""

    def test_discovers_from_config(self, temp_repo: Path) -> None:
        """Should discover projects based on [tool.repo.project-types]."""
        projects = discover_projects(temp_repo)
        assert "statuskit" in projects
        assert "flow" in projects

    def test_custom_project_type(self, temp_repo: Path) -> None:
        """Should support custom project types from config."""
        # Create custom dir
        custom_dir = temp_repo / "custom-projects" / "myproject"
        custom_dir.mkdir(parents=True)
        (custom_dir / "config.json").write_text("{}")

        (temp_repo / "pyproject.toml").write_text("""\
[project]
name = "test"

[tool.repo]
tooling_files = []

[tool.repo.project-types.python]
paths = ["packages"]
publish = ["pypi"]

[tool.repo.project-types.claude-code-plugin]
paths = ["plugins"]
publish = []

[tool.repo.project-types.custom]
paths = ["custom-projects"]
publish = []
""")
        projects = discover_projects(temp_repo)
        assert "myproject" in projects
        assert projects["myproject"].kind == "custom"
