#!/usr/bin/env python3
"""Validate commits and PRs for conventional commit format and single-package rule.

Usage:
    python validate.py --hook              # Pre-commit: validate staged files
    python validate.py --pr                # CI: validate PR title + files
    python validate.py --commits <before> <after>  # CI: validate commit range

Environment variables (for --pr mode):
    PR_TITLE: Pull request title
    BASE_REF: Base branch name
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class ValidationError(IntEnum):
    """Exit codes for validation errors."""

    SUCCESS = 0
    INVALID_FORMAT = 1
    SCOPE_MISMATCH = 2
    MULTIPLE_PACKAGES = 3
    SCOPE_COLLISION = 4
    SCRIPT_ERROR = 10


MIN_ARGS = 2
COMMITS_ARGS = 4


@dataclass
class ValidationResult:
    """Result of validation."""

    success: bool
    error: ValidationError | None = None
    message: str = ""


def _get_packages_from_files(
    files: list[str],
) -> tuple[set[str], list[str]]:
    """Extract packages and repo-level files from file list."""
    from .packages import get_package_from_path, is_repo_level_path  # type: ignore[unresolved-import]

    packages: set[str] = set()
    repo_level_files: list[str] = []

    for f in files:
        pkg = get_package_from_path(f)
        if pkg:
            packages.add(pkg)
        elif is_repo_level_path(f):
            repo_level_files.append(f)

    return packages, repo_level_files


def validate_pr(
    pr_title: str,
    changed_files: list[str],
    repo_root: Path,
) -> ValidationResult:
    """Validate PR title and changed files."""
    from .commits import parse_commit_message  # type: ignore[unresolved-import]
    from .packages import discover_packages  # type: ignore[unresolved-import]

    # Check for scope collision first
    try:
        discover_packages(repo_root)
    except ValueError as e:
        if "collision" in str(e).lower():
            return ValidationResult(
                success=False,
                error=ValidationError.SCOPE_COLLISION,
                message=str(e),
            )
        raise

    # Parse PR title
    commit_info = parse_commit_message(pr_title)
    if commit_info is None:
        return ValidationResult(
            success=False,
            error=ValidationError.INVALID_FORMAT,
            message=(
                f"Invalid conventional commit format\n\n  Expected: type(scope): description\n  Got:      {pr_title}"
            ),
        )

    # Extract packages from changed files
    packages, _ = _get_packages_from_files(changed_files)

    # Check multiple packages
    if len(packages) > 1:
        return ValidationResult(
            success=False,
            error=ValidationError.MULTIPLE_PACKAGES,
            message=f"Multiple packages changed: {', '.join(sorted(packages))}",
        )

    # Check scope matches
    if packages:
        expected_scope = next(iter(packages))
        if commit_info.scope != expected_scope:
            return ValidationResult(
                success=False,
                error=ValidationError.SCOPE_MISMATCH,
                message=f"Scope '{commit_info.scope}' doesn't match changed package: {expected_scope}",
            )
    elif commit_info.scope:
        return ValidationResult(
            success=False,
            error=ValidationError.SCOPE_MISMATCH,
            message=f"Scope '{commit_info.scope}' but no package files changed",
        )

    return ValidationResult(
        success=True,
        message=f"✓ PR title valid: {pr_title}",
    )


def validate_commit(sha: str, repo_root: Path) -> ValidationResult:
    """Validate a single commit."""
    from .commits import parse_commit_message  # type: ignore[unresolved-import]

    msg = subprocess.check_output(
        ["git", "log", "-1", "--format=%s", sha],  # noqa: S607
        cwd=repo_root,
        text=True,
    ).strip()

    files_output = subprocess.check_output(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha],  # noqa: S607
        cwd=repo_root,
        text=True,
    ).strip()
    changed_files = [f for f in files_output.split("\n") if f]

    commit_info = parse_commit_message(msg)
    if commit_info is None:
        if msg.lower().startswith("merge"):
            return ValidationResult(
                success=False,
                error=ValidationError.INVALID_FORMAT,
                message=f"Merge commits not allowed: {msg}",
            )
        return ValidationResult(
            success=False,
            error=ValidationError.INVALID_FORMAT,
            message=f"Invalid format: {msg}",
        )

    packages, _ = _get_packages_from_files(changed_files)

    if len(packages) > 1:
        return ValidationResult(
            success=False,
            error=ValidationError.MULTIPLE_PACKAGES,
            message=f"Commit changes multiple packages: {sorted(packages)}",
        )

    if packages:
        expected_scope = next(iter(packages))
        if commit_info.scope != expected_scope:
            return ValidationResult(
                success=False,
                error=ValidationError.SCOPE_MISMATCH,
                message=f"Scope '{commit_info.scope}' doesn't match: {expected_scope}",
            )
    elif commit_info.scope and commit_info.scope not in ("ci", "deps", "docs"):
        return ValidationResult(
            success=False,
            error=ValidationError.SCOPE_MISMATCH,
            message=f"Scope '{commit_info.scope}' but no package files changed",
        )

    return ValidationResult(success=True)


def validate_staged_files(
    staged_files: list[str],
) -> ValidationResult:
    """Validate staged files for single-package rule."""
    packages, _ = _get_packages_from_files(staged_files)

    if len(packages) > 1:
        return ValidationResult(
            success=False,
            error=ValidationError.MULTIPLE_PACKAGES,
            message=f"Multiple packages in one commit: {sorted(packages)}",
        )

    if packages:
        return ValidationResult(success=True, message=f"✓ Single package: {next(iter(packages))}")

    return ValidationResult(success=True, message="✓ Repo-level changes only")


def _get_staged_files(repo_root: Path) -> list[str]:
    """Get list of staged files from git."""
    output = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only"],  # noqa: S607
        cwd=repo_root,
        text=True,
    )
    return [f for f in output.strip().split("\n") if f]


def _get_changed_files_pr(base_ref: str, repo_root: Path) -> list[str]:
    """Get list of changed files in PR compared to base branch."""
    output = subprocess.check_output(
        ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD"],  # noqa: S607
        cwd=repo_root,
        text=True,
    )
    return [f for f in output.strip().split("\n") if f]


def _get_commits_in_range(before: str, after: str, repo_root: Path) -> list[str]:
    """Get list of commit SHAs in range."""
    output = subprocess.check_output(
        ["git", "rev-list", f"{before}..{after}"],  # noqa: S607
        cwd=repo_root,
        text=True,
    )
    return [c for c in output.strip().split("\n") if c]


def main() -> int:  # noqa: PLR0911, PLR0912
    """Main entry point."""
    from pathlib import Path

    repo_root = Path.cwd()

    if len(sys.argv) < MIN_ARGS:
        print("Usage: validate.py --hook | --pr | --commits <before> <after>")
        return ValidationError.SCRIPT_ERROR

    mode = sys.argv[1]

    try:
        if mode == "--hook":
            staged_files = _get_staged_files(repo_root)
            if not staged_files:
                print("✓ No staged files")
                return ValidationError.SUCCESS
            result = validate_staged_files(staged_files)

        elif mode == "--pr":
            pr_title = os.environ.get("PR_TITLE", "")
            base_ref = os.environ.get("BASE_REF", "main")
            if not pr_title:
                print("Error: PR_TITLE environment variable not set")
                return ValidationError.SCRIPT_ERROR
            changed_files = _get_changed_files_pr(base_ref, repo_root)
            result = validate_pr(pr_title, changed_files, repo_root)

        elif mode == "--commits":
            if len(sys.argv) < COMMITS_ARGS:
                print("Usage: validate.py --commits <before> <after>")
                return ValidationError.SCRIPT_ERROR
            before, after = sys.argv[2], sys.argv[3]
            commits = _get_commits_in_range(before, after, repo_root)
            if not commits:
                print("✓ No commits to validate")
                return ValidationError.SUCCESS

            errors: list[str] = []
            for sha in commits:
                r = validate_commit(sha, repo_root)
                if not r.success:
                    errors.append(f"❌ {sha[:8]}: {r.message}")

            if errors:
                print("Commit validation errors:\n" + "\n".join(errors))
                return ValidationError.INVALID_FORMAT

            print(f"✓ All {len(commits)} commit(s) valid")
            return ValidationError.SUCCESS

        else:
            print(f"Unknown mode: {mode}")
            return ValidationError.SCRIPT_ERROR

        if result.success:
            print(result.message)
            return ValidationError.SUCCESS
        print(f"✗ {result.message}")
        return result.error or ValidationError.SCRIPT_ERROR

    except subprocess.CalledProcessError as e:
        print(f"Git error: {e}")
        return ValidationError.SCRIPT_ERROR
    except Exception as e:
        print(f"Error: {e}")
        return ValidationError.SCRIPT_ERROR


if __name__ == "__main__":
    sys.exit(main())
