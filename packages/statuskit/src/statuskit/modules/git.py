"""Git module for statuskit."""

import subprocess

from statuskit.modules.base import BaseModule

_GIT_TIMEOUT = 2  # seconds


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
