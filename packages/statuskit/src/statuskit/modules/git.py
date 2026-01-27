"""Git module for statuskit."""

import subprocess
from pathlib import Path

from termcolor import colored

from statuskit.modules.base import BaseModule

_GIT_TIMEOUT = 2  # seconds
_EXPECTED_COUNT_PARTS = 2  # ahead\tbehind format
_MIN_STATUS_LINE_LEN = 2  # "XY filename" format minimum

# Time conversion constants
_MINUTES_PER_HOUR = 60
_MINUTES_PER_DAY = 1440  # 24 * 60
_MINUTES_PER_WEEK = 10080  # 7 * 1440
_MINUTES_PER_MONTH = 43200  # 30 * 1440
_MINUTES_PER_YEAR = 525600  # 365 * 1440

# Git age unit to minutes mapping
_UNIT_TO_MINUTES: dict[str, int] = {
    "second": 0,
    "seconds": 0,
    "minute": 1,
    "minutes": 1,
    "hour": _MINUTES_PER_HOUR,
    "hours": _MINUTES_PER_HOUR,
    "day": _MINUTES_PER_DAY,
    "days": _MINUTES_PER_DAY,
    "week": _MINUTES_PER_WEEK,
    "weeks": _MINUTES_PER_WEEK,
    "month": _MINUTES_PER_MONTH,
    "months": _MINUTES_PER_MONTH,
    "year": _MINUTES_PER_YEAR,
    "years": _MINUTES_PER_YEAR,
}


class GitModule(BaseModule):
    """Display git branch, status, and location."""

    name = "git"
    description = "Git branch, status, and location"

    def __init__(self, ctx, config: dict):
        super().__init__(ctx, config)
        self.commit_age_format = config.get("commit_age_format", "relative")
        self.show_project = config.get("show_project", True)
        self.show_worktree = config.get("show_worktree", True)
        self.show_folder = config.get("show_folder", True)
        self.show_branch = config.get("show_branch", True)
        self.show_remote_status = config.get("show_remote_status", True)
        self.show_changes = config.get("show_changes", True)
        self.show_commit = config.get("show_commit", True)

    def render(self) -> str | None:
        """Render git status output.

        Returns:
            Two-line output (location + status) or None if not a git repo
        """
        # Check if we're in a git repo
        branch = self._get_branch()
        if branch is None:
            return None

        lines = []

        # Line 1: Location
        location = self._get_location()
        if location:
            line1 = self._render_location_line(location)
            if line1:
                lines.append(line1)

        # Line 2: Git status
        remote_status = self._get_remote_status()
        changes = self._get_changes()
        commit = self._get_last_commit()
        if commit:
            commit = (commit[0], self._format_commit_age(commit[1]))

        line2 = self._render_status_line(branch, remote_status, changes, commit)
        if line2:
            lines.append(line2)

        if not lines:
            return None

        return "\n".join(lines)

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

    def _parse_git_age(self, age_str: str) -> int | None:
        """Parse git relative age string to total minutes.

        Args:
            age_str: Relative age string from git (e.g., "2 hours ago")

        Returns:
            Total minutes, or None if parsing fails
        """
        parts = age_str.split()
        if len(parts) < _EXPECTED_COUNT_PARTS:
            return None

        try:
            num = int(parts[0])
        except ValueError:
            return None

        unit = parts[1]
        if unit not in _UNIT_TO_MINUTES:
            return None

        return num * _UNIT_TO_MINUTES[unit]

    def _decompose_minutes(self, total_minutes: int) -> tuple[int, int, int]:
        """Decompose total minutes into days, hours, minutes.

        Args:
            total_minutes: Total number of minutes

        Returns:
            Tuple of (days, hours, minutes)
        """
        days = total_minutes // _MINUTES_PER_DAY
        remaining = total_minutes % _MINUTES_PER_DAY
        hours = remaining // _MINUTES_PER_HOUR
        minutes = remaining % _MINUTES_PER_HOUR
        return (days, hours, minutes)

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

    def _get_location(self) -> dict[str, str | None] | None:
        """Get project, worktree, and subfolder info.

        Returns:
            Dict with keys: project, worktree, subfolder
            or None if not in git repo
        """
        # Get main repo .git path
        git_common_dir = self._run_git("rev-parse", "--git-common-dir")
        if git_common_dir is None:
            return None

        # Get current worktree root
        toplevel = self._run_git("rev-parse", "--show-toplevel")
        if toplevel is None:
            return None

        # Extract project name from main repo path
        git_path = Path(git_common_dir)
        if git_path.name == ".git":
            project_name = git_path.parent.name
        else:
            project_name = git_path.name

        # Detect worktree: .git is a file (not directory) in worktrees
        toplevel_path = Path(toplevel)
        git_file = toplevel_path / ".git"
        is_worktree = git_file.is_file()

        worktree_name = toplevel_path.name if is_worktree else None

        # Get subfolder relative to worktree/repo root
        current_dir = self.data.workspace.current_dir if self.data.workspace else None
        subfolder = None
        if current_dir:
            current_path = Path(current_dir)
            try:
                rel_path = current_path.relative_to(toplevel_path)
                if rel_path != Path():
                    subfolder = str(rel_path)
            except ValueError:
                pass

        return {"project": project_name, "worktree": worktree_name, "subfolder": subfolder}

    def _render_location_line(self, location: dict[str, str | None]) -> str | None:
        """Render the location line (Line 1).

        Args:
            location: Dict with project, worktree, subfolder

        Returns:
            Formatted location string or None if all disabled
        """
        parts = []
        separator = colored(" → ", "dark_grey")

        if self.show_project and location["project"]:
            parts.append(colored(location["project"], "cyan"))

        if self.show_worktree and location["worktree"]:
            worktree_name = colored(location["worktree"], "yellow")
            parts.append(f"🌲 {worktree_name}")

        if self.show_folder and location["subfolder"]:
            parts.append(colored(location["subfolder"], "white"))

        if not parts:
            return None

        return separator.join(parts)

    def _render_remote_status(self, remote_status: tuple[str, int]) -> str | None:
        """Render remote tracking status indicator.

        Args:
            remote_status: Tuple of (status, count)

        Returns:
            Colored status indicator or None
        """
        status_map = {
            "ahead": ("↑{}", "yellow"),
            "behind": ("↓{}", "red"),
            "diverged": ("⇅{}", "red"),
            "synced": ("✓", "green"),
            "no_upstream": ("☁✗", "blue"),
        }
        status, count = remote_status
        if status not in status_map:
            return None
        template, color = status_map[status]
        text = template.format(count) if "{}" in template else template
        return colored(text, color)

    def _render_changes(self, changes: dict[str, int]) -> str | None:
        """Render working directory changes indicator.

        Args:
            changes: Dict with staged, modified, untracked counts

        Returns:
            Bracketed change indicators or None if no changes
        """
        indicators = [
            (changes["staged"], "+", "green"),
            (changes["modified"], "~", "yellow"),
            (changes["untracked"], "?", "cyan"),
        ]
        change_parts = [colored(f"{prefix}{count}", color) for count, prefix, color in indicators if count > 0]
        return "[" + " ".join(change_parts) + "]" if change_parts else None

    def _render_status_line(
        self,
        branch: str,
        remote_status: tuple[str, int],
        changes: dict[str, int],
        commit: tuple[str, str] | None,
    ) -> str | None:
        """Render the status line (Line 2).

        Args:
            branch: Branch name or commit hash
            remote_status: Tuple of (status, count)
            changes: Dict with staged, modified, untracked counts
            commit: Tuple of (hash, age) or None

        Returns:
            Formatted status string or None if all disabled
        """
        parts = []

        if self.show_branch:
            parts.append(colored(branch, "magenta"))

        if self.show_remote_status:
            remote = self._render_remote_status(remote_status)
            if remote:
                parts.append(remote)

        if self.show_changes:
            changes_str = self._render_changes(changes)
            if changes_str:
                parts.append(changes_str)

        if self.show_commit and commit:
            commit_hash, commit_age = commit
            parts.append(colored(f"{commit_hash} {commit_age}", "white", attrs=["dark"]))

        return " ".join(parts) if parts else None
