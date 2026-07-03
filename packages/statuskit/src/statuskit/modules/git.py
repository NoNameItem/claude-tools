"""Git module for statuskit."""

import subprocess
from collections.abc import Mapping
from pathlib import Path

from termcolor import colored

from statuskit.core.schema import param, schema
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

# Age format constant
_JUST_NOW = "just now"

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


@schema
class GitParams:
    commit_age_format: str = param(
        "relative",
        "Commit age display format",
        choices={
            "relative": "full words — e.g. `1 day 2 hours 30 minutes ago`",
            "compact": "abbreviated — e.g. `1d 2h 30m`",
            "raw": "git's own string, unmodified — e.g. `2 hours ago`",
        },
    )
    show_project: bool = param(True, "Show project name")
    show_worktree: bool = param(True, "Show worktree name")
    show_folder: bool = param(True, "Show current subfolder")
    show_branch: bool = param(True, "Show branch name")
    show_remote_status: bool = param(True, "Show remote tracking status")
    show_changes: bool = param(True, "Show working tree change counts")
    show_commit: bool = param(True, "Show last commit hash and age")


class GitModule(BaseModule[GitParams]):
    """Display git branch, status, and location."""

    name = "git"
    description = "Git branch, status, and location"

    def render(self) -> str | None:
        """Render git status output.

        Line 1 (location) is always attempted: inside a repo it shows the
        project / worktree / subfolder; outside a repo it falls back to the
        current directory. Line 2 (git status) renders only when a branch
        resolves.

        Returns:
            One or two lines, or None if there is nothing to show.
        """
        location = self._get_location()  # None ⟺ current_dir is not in a repo
        branch = self._get_branch()  # None even inside a repo (fresh, no commits)

        # Line 1: location — always attempted.
        if location is not None:
            line1 = self._render_location_line(location)
        else:
            line1 = self._render_cwd_fallback()

        # Line 2: git status — only when a branch resolves.
        line2 = None
        if branch is not None:
            remote_status = self._get_remote_status()
            changes = self._get_changes()
            commit = self._get_last_commit()
            if commit:
                commit = (commit[0], self._format_commit_age(commit[1]))
            line2 = self._render_status_line(branch, remote_status, changes, commit)

        lines = [line for line in (line1, line2) if line]
        return "\n".join(lines) if lines else None

    def _run_git(self, *args: str, cwd: str | None = None) -> str | None:
        """Run git command and return output.

        Args:
            *args: Git command arguments (without 'git' prefix)
            cwd: Working directory for the command. Defaults to None (the process
                cwd, which tracks ``current_dir`` — the behaviour the module
                already relies on).

        Returns:
            Command output stripped, or None on failure/timeout
        """
        cmd = ["git", "--no-optional-locks", *args]
        try:
            result = subprocess.run(  # noqa: S603
                cmd,
                cwd=cwd,
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

    def _shorten_path(self, path: str) -> str:
        """Shorten an absolute path by replacing a leading $HOME with ``~``.

        Args:
            path: Absolute filesystem path.

        Returns:
            ``~`` when ``path`` equals $HOME, ``~/...`` when under $HOME,
            otherwise ``path`` unchanged.
        """
        home = str(Path.home())
        if path == home:
            return "~"
        if path.startswith(home + "/"):
            return "~" + path[len(home) :]
        return path

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
        # Raw format: return as-is
        if self.params.commit_age_format == "raw":
            return age_str

        # Parse git output to minutes
        total_minutes = self._parse_git_age(age_str)
        if total_minutes is None:
            return age_str  # Fallback for invalid input

        # Less than 1 minute
        if total_minutes == 0:
            return _JUST_NOW

        # Decompose into d/h/m
        days, hours, minutes = self._decompose_minutes(total_minutes)

        # Format based on config
        if self.params.commit_age_format == "compact":
            return self._format_compact(days, hours, minutes)
        # relative (default)
        return self._format_relative(days, hours, minutes)

    def _format_compact(self, days: int, hours: int, minutes: int) -> str:
        """Format time as compact string (e.g., '1d 2h 30m')."""
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        return " ".join(parts) if parts else _JUST_NOW

    def _format_relative(self, days: int, hours: int, minutes: int) -> str:
        """Format time as relative string (e.g., '1 day 2 hours ago')."""
        parts = []
        if days > 0:
            parts.append(f"{days} day" if days == 1 else f"{days} days")
        if hours > 0:
            parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
        if minutes > 0:
            parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
        return " ".join(parts) + " ago" if parts else _JUST_NOW

    def _project_name_from_common_dir(self, git_common_dir: str, base: str | None = None) -> str:
        """Derive the project name from a ``git rev-parse --git-common-dir`` value.

        Args:
            git_common_dir: Output of ``git rev-parse --git-common-dir``.
            base: Directory to resolve a *relative* ``git_common_dir`` against.
                When None, resolution is relative to the process cwd (the
                behaviour ``_get_location`` relies on).

        Returns:
            The repository directory name (``.git`` maps to its parent name).
        """
        git_path = Path(git_common_dir)
        if base is not None and not git_path.is_absolute():
            git_path = Path(base) / git_path
        git_path = git_path.resolve()
        return git_path.parent.name if git_path.name == ".git" else git_path.name

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

        # Extract project name from main repo path (resolves relative ".git"/"../.git")
        project_name = self._project_name_from_common_dir(git_common_dir)

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

    def _render_location_line(self, location: Mapping[str, str | None]) -> str | None:
        """Render the location line (Line 1).

        Args:
            location: Dict with project, worktree, subfolder

        Returns:
            Formatted location string or None if all disabled
        """
        parts = []
        separator = colored(" → ", "dark_grey")

        if self.params.show_project and location["project"]:
            parts.append(colored(location["project"], "cyan"))

        if self.params.show_worktree and location["worktree"]:
            worktree_name = colored(location["worktree"], "yellow")
            parts.append(f"🌲 {worktree_name}")

        if self.params.show_folder and location["subfolder"]:
            parts.append(colored(location["subfolder"], "light_magenta"))

        if not parts:
            return None

        return separator.join(parts)

    def _render_cwd_fallback(self) -> str | None:
        """Render Line 1 when ``current_dir`` is not inside a git repo.

        Two states (see design doc):

        - Case 1 — the session's ``project_dir`` *is* a repo but we have ``cd``'d
          out of it: ``project``[cyan] → ``current_dir``[red].
        - Case 2 — never in a repo: ``current_dir``[light_magenta].

        Returns:
            The fallback location line, or None when there is no workspace,
            ``current_dir`` is empty, or the relevant segments are disabled.
        """
        workspace = self.data.workspace
        if workspace is None:
            return None

        current_dir = workspace.current_dir
        if not current_dir:
            return None

        project_dir = workspace.project_dir

        # Case 1 detection: project_dir differs from current_dir and is a repo.
        # Skip the probe (→ Case 2) when project_dir is missing or equal to
        # current_dir — we already know current_dir is not a repo.
        project_name = None
        if project_dir and project_dir != current_dir:
            git_common_dir = self._run_git("rev-parse", "--git-common-dir", cwd=project_dir)
            if git_common_dir is not None:
                project_name = self._project_name_from_common_dir(git_common_dir, base=project_dir)

        shortened = self._shorten_path(current_dir)
        separator = colored(" → ", "dark_grey")
        parts = []

        if project_name is not None:
            # Case 1: stepped out of the project repo.
            if self.params.show_project:
                parts.append(colored(project_name, "cyan"))
            if self.params.show_folder:
                parts.append(colored(shortened, "red"))
        # Case 2: plain directory, never in a repo.
        elif self.params.show_folder:
            parts.append(colored(shortened, "light_magenta"))

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

        if self.params.show_branch:
            parts.append(colored(branch, "magenta"))

        if self.params.show_remote_status:
            remote = self._render_remote_status(remote_status)
            if remote:
                parts.append(remote)

        if self.params.show_changes:
            changes_str = self._render_changes(changes)
            if changes_str:
                parts.append(changes_str)

        if self.params.show_commit and commit:
            commit_hash, commit_age = commit
            parts.append(colored(f"{commit_hash} {commit_age}", "white", attrs=["dark"]))

        return " ".join(parts) if parts else None
