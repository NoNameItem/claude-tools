"""Gitignore handling for local scope setup."""

# ruff: noqa: S603, S607
import subprocess
from pathlib import Path

LOCAL_FILES = [
    ".claude/settings.local.json",
    ".claude/statuskit.local.toml",
]

GITIGNORE_PATTERN = ".claude/*.local.*"


def is_in_git_repo() -> bool:
    """Check if current directory is inside a git repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def is_file_ignored(path: str) -> bool:
    """Check if a file would be ignored by git.

    Uses `git check-ignore` to check against all gitignore rules.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", path],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def ensure_local_files_ignored() -> bool:
    """Ensure local scope files are in .gitignore.

    Returns True if pattern was added, False if already ignored or not in git repo.
    """
    if not is_in_git_repo():
        return False

    # Check if files are already ignored
    all_ignored = all(is_file_ignored(f) for f in LOCAL_FILES)
    if all_ignored:
        return False

    # Add pattern to .gitignore
    gitignore_path = Path(".gitignore")

    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if not content.endswith("\n"):
            content += "\n"
    else:
        content = ""

    content += f"{GITIGNORE_PATTERN}\n"
    gitignore_path.write_text(content)

    return True
