"""Git module for statuskit."""

import subprocess

from statuskit.modules.base import BaseModule

_GIT_TIMEOUT = 2  # seconds
_EXPECTED_COUNT_PARTS = 2  # ahead\tbehind format


class GitModule(BaseModule):
    """Display git branch, status, and location."""

    name = "git"
    description = "Git branch, status, and location"

    def __init__(self, ctx, config: dict):
        super().__init__(ctx, config)

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
