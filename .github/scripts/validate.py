#!/usr/bin/env python3
"""Validate commits and PRs for conventional commit format and single-package rule.

Usage:
    python validate.py --hook              # Pre-commit: validate staged files
    python validate.py --pr                # CI: validate PR title + files
    python validate.py --commits <before> <after>  # CI: validate commit range

Environment variables (for --pr mode):
    PR_TITLE: Pull request title
    DETECT_RESULT: JSON output from detect_changes.py
"""

from __future__ import annotations

import json
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

# Error titles for job summary
ERROR_TITLES: dict[int, str] = {
    ValidationError.INVALID_FORMAT: "Invalid PR Title Format",
    ValidationError.SCOPE_MISMATCH: "Scope Mismatch",
    ValidationError.MULTIPLE_PACKAGES: "Multiple Projects Changed",
    ValidationError.SCOPE_COLLISION: "Scope Collision",
}


@dataclass
class ValidationResult:
    """Result of validation."""

    success: bool
    error: ValidationError | None = None
    message: str = ""


def _write_job_summary(result: ValidationResult) -> None:
    """Write validation error to GitHub Job Summary."""
    from pathlib import Path

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return

    error_title = ERROR_TITLES.get(result.error or 0, "Validation Error")

    lines = [
        "## :x: PR Validation Failed",
        "",
        f"### {error_title}",
        "",
        f"> {result.message.replace(chr(10), chr(10) + '> ')}",
        "",
    ]

    # Add specific guidance based on error type
    if result.error == ValidationError.INVALID_FORMAT:
        lines.extend(
            [
                "### How to Fix",
                "",
                "Change PR title to conventional commit format:",
                "",
                "```",
                "type(scope): description",
                "```",
                "",
                "| Type | When to use |",
                "|------|-------------|",
                "| `feat` | New feature |",
                "| `fix` | Bug fix |",
                "| `docs` | Documentation only |",
                "| `chore` | Maintenance tasks |",
                "| `refactor` | Code restructuring |",
                "| `test` | Adding tests |",
                "| `ci` | CI/CD changes |",
                "",
                "**Examples:**",
                "- `feat(statuskit): add quota module`",
                "- `fix(flow): handle empty task list`",
                "- `ci: update workflow triggers`",
            ]
        )
    elif result.error == ValidationError.SCOPE_MISMATCH:
        lines.extend(
            [
                "### How to Fix",
                "",
                "The scope in PR title must match the changed project.",
                "",
                "- If you changed files in `packages/statuskit/`, use `(statuskit)`",
                "- If you changed files in `plugins/flow/`, use `(flow)`",
                "- For repo-level changes only, omit the scope (e.g., `ci: update workflow`)",
            ]
        )
    elif result.error == ValidationError.MULTIPLE_PACKAGES:
        lines.extend(
            [
                "### How to Fix",
                "",
                "Each PR should change only one project. Split this PR into separate PRs,",
                "one for each project.",
            ]
        )

    with Path(summary_file).open("a") as f:
        f.write("\n".join(lines) + "\n")


def _write_error_annotation(result: ValidationResult) -> None:
    """Write ::error:: annotation for GitHub Actions."""
    if not os.environ.get("GITHUB_ACTIONS"):
        return

    error_title = ERROR_TITLES.get(result.error or 0, "Validation Error")
    # Extract first line of message for annotation (keep it short)
    short_message = result.message.split("\n")[0]
    # Escape special characters for workflow command
    short_message = short_message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::error title={error_title}::{short_message}")


def _get_projects_from_files(
    files: list[str],
    repo_root: Path,
) -> tuple[set[str], list[str]]:
    """Extract projects and repo-level files from file list."""
    try:
        from .projects import get_project_from_path, is_repo_level_path  # type: ignore[unresolved-import]
    except ImportError:
        from projects import get_project_from_path, is_repo_level_path  # type: ignore[unresolved-import]

    projects: set[str] = set()
    repo_level_files: list[str] = []

    for f in files:
        pkg = get_project_from_path(f, repo_root)
        if pkg:
            projects.add(pkg)
        elif is_repo_level_path(f, repo_root):
            repo_level_files.append(f)

    return projects, repo_level_files


def validate_pr(
    pr_title: str,
    detect_result: dict,
    repo_root: Path,
) -> ValidationResult:
    """Validate PR title using detect result.

    Args:
        pr_title: PR title string.
        detect_result: Output from detect_changes.py (as dict).
        repo_root: Path to repository root.

    Returns:
        ValidationResult.
    """
    try:
        from .commits import parse_commit_message
        from .projects import discover_projects
    except ImportError:
        from commits import parse_commit_message
        from projects import discover_projects

    # Check for scope collision first
    try:
        discover_projects(repo_root)
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

    total_count = detect_result.get("total_changed_count", 0)

    # Check multiple projects
    if total_count > 1:
        all_changed = []
        for kind_data in detect_result.get("by_type", {}).values():
            all_changed.extend(kind_data.get("changed", []))
        return ValidationResult(
            success=False,
            error=ValidationError.MULTIPLE_PACKAGES,
            message=f"PR changes multiple projects: {sorted(all_changed)}",
        )

    # Check scope match
    expected_scope = detect_result.get("single_project")

    if expected_scope:
        if commit_info.scope != expected_scope:
            return ValidationResult(
                success=False,
                error=ValidationError.SCOPE_MISMATCH,
                message=f"Scope mismatch: expected '{expected_scope}', got '{commit_info.scope}'",
            )
    elif commit_info.scope:
        return ValidationResult(
            success=False,
            error=ValidationError.SCOPE_MISMATCH,
            message=f"Scope '{commit_info.scope}' but no project files changed",
        )

    return ValidationResult(
        success=True,
        message=f"✓ PR title valid: {pr_title}",
    )


def validate_commit(sha: str, repo_root: Path) -> ValidationResult:
    """Validate a single commit."""
    try:
        from .commits import parse_commit_message  # type: ignore[unresolved-import]
    except ImportError:
        from commits import parse_commit_message  # type: ignore[unresolved-import]

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

    packages, _ = _get_projects_from_files(changed_files, repo_root)

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
    elif commit_info.scope:
        return ValidationResult(
            success=False,
            error=ValidationError.SCOPE_MISMATCH,
            message=f"Scope '{commit_info.scope}' but no package files changed",
        )

    return ValidationResult(success=True)


def validate_staged_files(
    staged_files: list[str],
    repo_root: Path,
) -> ValidationResult:
    """Validate staged files for single-package rule."""
    packages, _ = _get_projects_from_files(staged_files, repo_root)

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


def _get_commits_in_range(before: str, after: str, repo_root: Path) -> list[str]:
    """Get list of commit SHAs in range."""
    output = subprocess.check_output(
        ["git", "rev-list", f"{before}..{after}"],  # noqa: S607
        cwd=repo_root,
        text=True,
    )
    return [c for c in output.strip().split("\n") if c]


# noinspection D
def main() -> int:  # noqa: PLR0911, PLR0912, PLR0915
    """Main entry point."""
    from pathlib import Path

    # Get repo root from git (works even if cwd is a subdirectory)
    repo_root = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],  # noqa: S607
            text=True,
        ).strip()
    )

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
            result = validate_staged_files(staged_files, repo_root)

        elif mode == "--pr":
            pr_title = os.environ.get("PR_TITLE", "")
            detect_result_json = os.environ.get("DETECT_RESULT")

            if not pr_title:
                print("Error: PR_TITLE environment variable not set")
                return ValidationError.SCRIPT_ERROR

            if not detect_result_json:
                print("Error: DETECT_RESULT environment variable not set")
                return ValidationError.SCRIPT_ERROR

            detect_result = json.loads(detect_result_json)
            result = validate_pr(pr_title, detect_result, repo_root)

            # Write error annotation and job summary on failure
            if not result.success:
                _write_error_annotation(result)
                _write_job_summary(result)

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
            first_error: ValidationResult | None = None
            for sha in commits:
                r = validate_commit(sha, repo_root)
                if not r.success:
                    errors.append(f"❌ {sha[:8]}: {r.message}")
                    if first_error is None:
                        first_error = r

            if errors:
                print("Commit validation errors:\n" + "\n".join(errors))
                return first_error.error if first_error and first_error.error else ValidationError.INVALID_FORMAT

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
