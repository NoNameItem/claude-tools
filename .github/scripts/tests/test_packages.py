"""Tests for package discovery module."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..packages import (
    discover_packages,
    get_package_from_path,
    is_repo_level_path,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestGetPackageFromPath:
    """Tests for get_package_from_path function."""

    def test_package_path(self) -> None:
        """Should extract package name from packages/* path."""
        assert get_package_from_path("packages/statuskit/src/foo.py") == "statuskit"

    def test_plugin_path(self) -> None:
        """Should extract plugin name from plugins/* path."""
        assert get_package_from_path("plugins/flow/skills/start.md") == "flow"

    def test_repo_level_path(self) -> None:
        """Should return None for repo-level paths."""
        assert get_package_from_path("README.md") is None
        assert get_package_from_path(".github/workflows/ci.yml") is None
        assert get_package_from_path("docs/design.md") is None

    def test_root_pyproject(self) -> None:
        """Should return None for root pyproject.toml."""
        assert get_package_from_path("pyproject.toml") is None

    def test_package_pyproject(self) -> None:
        """Should extract package from package's pyproject.toml."""
        assert get_package_from_path("packages/statuskit/pyproject.toml") == "statuskit"


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


class TestDiscoverPackages:
    """Tests for discover_packages function."""

    def test_discovers_packages(self, temp_repo: Path) -> None:
        """Should discover packages from packages/ directory."""
        packages = discover_packages(temp_repo)

        assert "statuskit" in packages
        assert packages["statuskit"].name == "statuskit"
        assert packages["statuskit"].path == "packages/statuskit"
        assert packages["statuskit"].kind == "package"

    def test_discovers_plugins(self, temp_repo: Path) -> None:
        """Should discover plugins from plugins/ directory."""
        packages = discover_packages(temp_repo)

        assert "flow" in packages
        assert packages["flow"].name == "flow"
        assert packages["flow"].path == "plugins/flow"
        assert packages["flow"].kind == "plugin"

    def test_detects_collision(self, temp_repo: Path) -> None:
        """Should raise error if same name in packages/ and plugins/."""
        # Create collision: plugins/statuskit
        collision_dir = temp_repo / "plugins" / "statuskit"
        collision_dir.mkdir(parents=True)
        (collision_dir / "plugin.json").write_text("{}")

        with pytest.raises(ValueError, match="Scope collision"):
            discover_packages(temp_repo)

    def test_parses_python_versions(self, temp_repo: Path) -> None:
        """Should parse Python versions from classifiers."""
        packages = discover_packages(temp_repo)

        assert packages["statuskit"].python_versions == ["3.11", "3.12"]

    def test_missing_classifiers(self, temp_repo: Path) -> None:
        """Should raise error if package has no Python classifiers."""
        # Create package without classifiers
        no_classifiers_dir = temp_repo / "packages" / "noclassifiers"
        no_classifiers_dir.mkdir(parents=True)
        (no_classifiers_dir / "pyproject.toml").write_text("""\
[project]
name = "noclassifiers"
version = "0.1.0"
""")

        with pytest.raises(ValueError, match="Missing Python version classifiers"):
            discover_packages(temp_repo)
