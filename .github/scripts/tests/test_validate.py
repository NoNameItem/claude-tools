"""Tests for validate.py script."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from ..validate import (
    ValidationError,
    validate_commit,
    validate_pr,
    validate_staged_files,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestValidatePR:
    """Tests for PR validation (--pr mode)."""

    def test_valid_single_package(self, temp_repo: Path) -> None:
        """Should pass when PR title scope matches changed package."""
        changed_files = ["packages/statuskit/src/new_module.py"]
        result = validate_pr(
            pr_title="feat(statuskit): add new module",
            changed_files=changed_files,
            repo_root=temp_repo,
        )
        assert result.success is True

    def test_valid_repo_level_no_scope(self, temp_repo: Path) -> None:
        """Should pass for repo-level changes without scope."""
        changed_files = [".github/workflows/ci.yml", "docs/design.md"]
        result = validate_pr(
            pr_title="ci: add CI workflow",
            changed_files=changed_files,
            repo_root=temp_repo,
        )
        assert result.success is True

    def test_invalid_format(self, temp_repo: Path) -> None:
        """Should fail for invalid PR title format."""
        result = validate_pr(
            pr_title="add new feature",
            changed_files=["packages/statuskit/src/foo.py"],
            repo_root=temp_repo,
        )
        assert result.success is False
        assert result.error == ValidationError.INVALID_FORMAT

    def test_scope_mismatch(self, temp_repo: Path) -> None:
        """Should fail when scope doesn't match changed files."""
        changed_files = ["plugins/flow/skills/start.md"]
        result = validate_pr(
            pr_title="feat(statuskit): add feature",
            changed_files=changed_files,
            repo_root=temp_repo,
        )
        assert result.success is False
        assert result.error == ValidationError.SCOPE_MISMATCH

    def test_multiple_packages(self, temp_repo_with_another_package: Path) -> None:
        """Should fail when multiple packages changed."""
        changed_files = [
            "packages/statuskit/src/foo.py",
            "packages/another/src/bar.py",
        ]
        result = validate_pr(
            pr_title="feat(statuskit): add feature",
            changed_files=changed_files,
            repo_root=temp_repo_with_another_package,
        )
        assert result.success is False
        assert result.error == ValidationError.MULTIPLE_PACKAGES

    def test_missing_scope_for_package(self, temp_repo: Path) -> None:
        """Should fail when scope missing for package changes."""
        changed_files = ["packages/statuskit/src/foo.py"]
        result = validate_pr(
            pr_title="feat: add feature",
            changed_files=changed_files,
            repo_root=temp_repo,
        )
        assert result.success is False
        assert result.error == ValidationError.SCOPE_MISMATCH

    def test_mixed_package_and_repo_level(self, temp_repo: Path) -> None:
        """Should use package scope when mixed with repo-level."""
        changed_files = [
            "packages/statuskit/src/foo.py",
            "pyproject.toml",
            "uv.lock",
        ]
        result = validate_pr(
            pr_title="feat(statuskit): add dependency",
            changed_files=changed_files,
            repo_root=temp_repo,
        )
        assert result.success is True


class TestValidateCommit:
    """Tests for commit validation (--commits mode)."""

    def test_valid_commit(self, temp_repo: Path) -> None:
        """Should pass for valid commit with matching scope."""
        test_file = temp_repo / "packages" / "statuskit" / "src" / "new.py"
        test_file.write_text("# new file\n")
        subprocess.run(
            ["git", "add", str(test_file)],
            cwd=temp_repo,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "feat(statuskit): add new file"],
            cwd=temp_repo,
            check=True,
        )
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_repo,
            text=True,
        ).strip()
        result = validate_commit(sha, repo_root=temp_repo)
        assert result.success is True

    def test_invalid_format(self, temp_repo: Path) -> None:
        """Should fail for invalid commit message format."""
        test_file = temp_repo / "packages" / "statuskit" / "src" / "bad.py"
        test_file.write_text("# bad commit\n")
        subprocess.run(
            ["git", "add", str(test_file)],
            cwd=temp_repo,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "added new file"],
            cwd=temp_repo,
            check=True,
        )
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_repo,
            text=True,
        ).strip()
        result = validate_commit(sha, repo_root=temp_repo)
        assert result.success is False
        assert result.error == ValidationError.INVALID_FORMAT


class TestValidateStagedFiles:
    """Tests for staged files validation (--hook mode)."""

    def test_single_package(self) -> None:
        """Should pass for staged files from one package."""
        staged_files = [
            "packages/statuskit/src/a.py",
            "packages/statuskit/src/b.py",
        ]
        result = validate_staged_files(staged_files)
        assert result.success is True

    def test_repo_level_only(self) -> None:
        """Should pass for repo-level files only."""
        staged_files = [".github/workflows/ci.yml", "README.md"]
        result = validate_staged_files(staged_files)
        assert result.success is True

    def test_multiple_packages(self) -> None:
        """Should fail for files from multiple packages."""
        staged_files = [
            "packages/statuskit/src/a.py",
            "packages/another/src/b.py",
        ]
        result = validate_staged_files(staged_files)
        assert result.success is False
        assert result.error == ValidationError.MULTIPLE_PACKAGES
