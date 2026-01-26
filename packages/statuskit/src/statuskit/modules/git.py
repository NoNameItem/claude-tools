"""Git module for statuskit."""

import subprocess

from statuskit.modules.base import BaseModule

_GIT_TIMEOUT = 2  # seconds
_EXPECTED_COUNT_PARTS = 2  # ahead\tbehind format
_MIN_STATUS_LINE_LEN = 2  # "XY filename" format minimum


class GitModule(BaseModule):
    """Display git branch, status, and location."""

    name = "git"
    description = "Git branch, status, and location"

    def __init__(self, ctx, config: dict):
        super().__init__(ctx, config)
        self.commit_age_format = config.get("commit_age_format", "relative")

    def render(self) -> str | None:
        """Render git status output."""
        return None

    def _run_git(self, *args: str) -> str | None:
        """Run git command and return output.

        Args:
            *args: Git command arguments (without 'git' prefix)

        Returns:
            Command output stripped, or None on failure/timeout
        """
        cmd = ["git", "--no-optional-locks", *args]
        try:
            result = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
                check=False,
            )
            if result.returncode != 0:
                return None
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            return None

    def _get_branch(self) -> str | None:
        """Get current branch name or short hash for detached HEAD.

        Returns:
            Branch name, short commit hash, or None if not a git repo
        """
        branch = self._run_git("branch", "--show-current")
        if branch is None:
            return None
        if branch == "":
            # Detached HEAD - get short hash
            return self._run_git("rev-parse", "--short", "HEAD")
        return branch

    def _get_remote_status(self) -> tuple[str, int]:  # noqa: PLR0911
        """Get remote tracking status.

        Returns:
            Tuple of (status, count) where status is one of:
            - "ahead": local has N commits not on remote
            - "behind": remote has N commits not on local
            - "diverged": both have commits, count is total
            - "synced": local and remote are identical
            - "no_upstream": no tracking branch configured
        """
        # Check if upstream exists
        upstream = self._run_git("rev-parse", "--abbrev-ref", "@{upstream}")
        if upstream is None:
            return ("no_upstream", 0)

        # Get ahead/behind counts
        counts = self._run_git("rev-list", "--left-right", "--count", "HEAD...@{upstream}")
        if counts is None:
            return ("no_upstream", 0)

        parts = counts.split("\t")
        if len(parts) != _EXPECTED_COUNT_PARTS:
            return ("no_upstream", 0)

        ahead = int(parts[0])
        behind = int(parts[1])

        if ahead > 0 and behind > 0:
            return ("diverged", ahead + behind)
        if ahead > 0:
            return ("ahead", ahead)
        if behind > 0:
            return ("behind", behind)
        return ("synced", 0)

    def _get_changes(self) -> dict[str, int]:
        """Get working directory change counts.

        Returns:
            Dict with keys: staged, modified, untracked
        """
        result = {"staged": 0, "modified": 0, "untracked": 0}

        status = self._run_git("status", "--porcelain")
        if status is None or status == "":
            return result

        for line in status.split("\n"):
            if not line or len(line) < _MIN_STATUS_LINE_LEN:
                continue

            index_status = line[0]
            worktree_status = line[1]

            # Untracked files
            if index_status == "?" and worktree_status == "?":
                result["untracked"] += 1
            # Staged changes (index has changes)
            elif index_status in "AMDRC":
                result["staged"] += 1
                # File can be both staged and modified
                if worktree_status in "MD":
                    result["modified"] += 1
            # Unstaged modifications only
            elif worktree_status in "MD":
                result["modified"] += 1

        return result

    def _get_last_commit(self) -> tuple[str, str] | None:
        """Get last commit hash and relative age.

        Returns:
            Tuple of (short_hash, relative_age) or None if no commits
        """
        output = self._run_git("log", "-1", "--format=%h %ar")
        if output is None:
            return None

        parts = output.split(" ", 1)
        if len(parts) != _EXPECTED_COUNT_PARTS:
            return None

        return (parts[0], parts[1])

    def _format_commit_age(self, age_str: str) -> str:
        """Format commit age according to config.

        Args:
            age_str: Relative age string from git (e.g., "2 hours ago")

        Returns:
            Formatted age string
        """
        if self.commit_age_format == "relative":
            return age_str

        if self.commit_age_format == "compact":
            # Parse "N unit ago" format
            parts = age_str.split()
            if len(parts) >= _EXPECTED_COUNT_PARTS:
                num = parts[0]
                unit = parts[1]
                unit_map = {
                    "second": "s",
                    "seconds": "s",
                    "minute": "m",
                    "minutes": "m",
                    "hour": "h",
                    "hours": "h",
                    "day": "d",
                    "days": "d",
                    "week": "w",
                    "weeks": "w",
                    "month": "mo",
                    "months": "mo",
                    "year": "y",
                    "years": "y",
                }
                suffix = unit_map.get(unit, unit[0])
                return f"{num}{suffix}"

        return age_str
