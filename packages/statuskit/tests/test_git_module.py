"""Tests for statuskit.modules.git."""

import json
import subprocess
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from statuskit.modules.git import (
    CliResult,
    GitModule,
    PrCache,
    PrCacheDoc,
    PrCacheEntry,
    PrInfo,
    parse_github_pr_list,
    parse_gitlab_mr_list,
    parse_remote_host,
    parse_remote_slug,
)
from termcolor import colored

from .factories import make_input_data, make_model_data


class TestGitModule:
    """Tests for GitModule."""

    def test_run_git_success(self, make_render_context):
        """_run_git returns command output."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="main\n", stderr="")
            result = mod._run_git("branch", "--show-current")

        assert result == "main"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "git"
        assert "--no-optional-locks" in args

    def test_run_git_failure_returns_none(self, make_render_context):
        """_run_git returns None on command failure."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
            result = mod._run_git("branch", "--show-current")

        assert result is None

    def test_run_git_timeout_returns_none(self, make_render_context):
        """_run_git returns None on timeout."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=2)
            result = mod._run_git("status")

        assert result is None

    def test_run_git_invalid_cwd_returns_none(self, make_render_context):
        """_run_git returns None (not raises) when subprocess.run raises OSError.

        A stale/deleted/invalid cwd (e.g. project_dir) makes subprocess.run raise
        FileNotFoundError/NotADirectoryError before git runs; _run_git must swallow
        it like any other git failure so callers can degrade gracefully.
        """
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("[Errno 2] No such file or directory: '/nope'")
            result = mod._run_git("rev-parse", "--git-common-dir", cwd="/nope")

        assert result is None

    def test_render_cwd_fallback_invalid_project_dir_degrades_to_case2(self, make_render_context, force_color):
        """A stale/deleted project_dir must not crash the Case-1 probe — degrade to Case 2."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/work/scratch", "project_dir": "/nonexistent/xyz"},
        )
        mod = GitModule(make_render_context(data), {})

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("[Errno 2] No such file or directory: '/nonexistent/xyz'")
            result = mod._render_cwd_fallback()

        assert result == colored("/work/scratch", "light_magenta")

    def test_run_git_passes_cwd(self, make_render_context):
        """_run_git forwards cwd to subprocess.run."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")
            result = mod._run_git("rev-parse", "--git-common-dir", cwd="/some/repo")

        assert result == "ok"
        assert mock_run.call_args.kwargs["cwd"] == "/some/repo"

    def test_run_git_default_cwd_is_none(self, make_render_context):
        """_run_git defaults cwd to None (process cwd)."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="main\n", stderr="")
            mod._run_git("branch", "--show-current")

        assert mock_run.call_args.kwargs["cwd"] is None

    def test_get_branch_name(self, make_render_context):
        """_get_branch returns current branch name."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = "feature/test"
            result = mod._get_branch()

        assert result == "feature/test"
        mock_git.assert_called_with("branch", "--show-current")

    def test_get_branch_detached_head(self, make_render_context):
        """_get_branch returns short hash for detached HEAD."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            # Empty string means detached HEAD
            mock_git.side_effect = lambda *args: "" if "show-current" in args else "abc1234"
            result = mod._get_branch()

        assert result == "abc1234"

    def test_get_branch_not_git_repo(self, make_render_context):
        """_get_branch returns None when not in git repo."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = None
            result = mod._get_branch()

        assert result is None

    def test_get_remote_status_ahead(self, make_render_context):
        """_get_remote_status returns ahead count."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.side_effect = lambda *args: "origin/main" if "abbrev-ref" in args else "2\t0"
            result = mod._get_remote_status()

        assert result == ("ahead", 2)

    def test_get_remote_status_behind(self, make_render_context):
        """_get_remote_status returns behind count."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.side_effect = lambda *args: "origin/main" if "abbrev-ref" in args else "0\t3"
            result = mod._get_remote_status()

        assert result == ("behind", 3)

    def test_get_remote_status_diverged(self, make_render_context):
        """_get_remote_status returns diverged with total count."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.side_effect = lambda *args: "origin/main" if "abbrev-ref" in args else "2\t3"
            result = mod._get_remote_status()

        assert result == ("diverged", 5)

    def test_get_remote_status_synced(self, make_render_context):
        """_get_remote_status returns synced when no difference."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.side_effect = lambda *args: "origin/main" if "abbrev-ref" in args else "0\t0"
            result = mod._get_remote_status()

        assert result == ("synced", 0)

    def test_get_remote_status_no_upstream(self, make_render_context):
        """_get_remote_status returns no_upstream when no tracking branch."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = None
            result = mod._get_remote_status()

        assert result == ("no_upstream", 0)

    def test_get_changes_all_types(self, make_render_context):
        """_get_changes returns counts for all change types."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        porcelain_output = """A  staged_new.py
M  staged_modified.py
 M unstaged.py
 M another_unstaged.py
?? untracked1.txt
?? untracked2.txt
?? untracked3.txt"""

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = porcelain_output
            result = mod._get_changes()

        assert result == {"staged": 2, "modified": 2, "untracked": 3}

    def test_get_changes_staged_only(self, make_render_context):
        """_get_changes counts staged files."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = "A  new.py\nM  modified.py\nD  deleted.py"
            result = mod._get_changes()

        assert result == {"staged": 3, "modified": 0, "untracked": 0}

    def test_get_changes_modified_only(self, make_render_context):
        """_get_changes counts modified files."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = " M file1.py\n M file2.py"
            result = mod._get_changes()

        assert result == {"staged": 0, "modified": 2, "untracked": 0}

    def test_get_changes_untracked_only(self, make_render_context):
        """_get_changes counts untracked files."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = "?? file1.txt\n?? file2.txt"
            result = mod._get_changes()

        assert result == {"staged": 0, "modified": 0, "untracked": 2}

    def test_get_changes_clean(self, make_render_context):
        """_get_changes returns zeros for clean working directory."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = ""
            result = mod._get_changes()

        assert result == {"staged": 0, "modified": 0, "untracked": 0}

    def test_get_changes_not_git_repo(self, make_render_context):
        """_get_changes returns zeros when not in git repo."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = None
            result = mod._get_changes()

        assert result == {"staged": 0, "modified": 0, "untracked": 0}

    def test_get_last_commit(self, make_render_context):
        """_get_last_commit returns hash and age."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = "abc1234 2 hours ago"
            result = mod._get_last_commit()

        assert result == ("abc1234", "2 hours ago")

    def test_get_last_commit_no_commits(self, make_render_context):
        """_get_last_commit returns None for empty repo."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = None
            result = mod._get_last_commit()

        assert result is None

    def test_format_commit_age_raw(self, make_render_context):
        """_format_commit_age returns git output as-is for raw format."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"commit_age_format": "raw"})

        assert mod._format_commit_age("2 hours ago") == "2 hours ago"
        assert mod._format_commit_age("69 minutes ago") == "69 minutes ago"

    def test_format_commit_age_relative_decomposed(self, make_render_context):
        """_format_commit_age decomposes and uses full names for relative format."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"commit_age_format": "relative"})

        assert mod._format_commit_age("5 minutes ago") == "5 minutes ago"
        assert mod._format_commit_age("69 minutes ago") == "1 hour 9 minutes ago"
        assert mod._format_commit_age("120 minutes ago") == "2 hours ago"
        assert mod._format_commit_age("26 hours ago") == "1 day 2 hours ago"
        assert mod._format_commit_age("3 days ago") == "3 days ago"

    def test_format_commit_age_relative_singular(self, make_render_context):
        """_format_commit_age uses singular forms correctly."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"commit_age_format": "relative"})

        assert mod._format_commit_age("60 minutes ago") == "1 hour ago"
        assert mod._format_commit_age("1 day ago") == "1 day ago"

    def test_format_commit_age_compact_decomposed(self, make_render_context):
        """_format_commit_age decomposes and uses short names for compact format."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"commit_age_format": "compact"})

        assert mod._format_commit_age("5 minutes ago") == "5m"
        assert mod._format_commit_age("69 minutes ago") == "1h 9m"
        assert mod._format_commit_age("120 minutes ago") == "2h"
        assert mod._format_commit_age("26 hours ago") == "1d 2h"
        assert mod._format_commit_age("3 days ago") == "3d"
        assert mod._format_commit_age("1501 minutes ago") == "1d 1h 1m"

    def test_format_commit_age_just_now(self, make_render_context):
        """_format_commit_age returns 'just now' for < 1 minute."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)

        mod_relative = GitModule(ctx, {"commit_age_format": "relative"})
        mod_compact = GitModule(ctx, {"commit_age_format": "compact"})

        assert mod_relative._format_commit_age("30 seconds ago") == "just now"
        assert mod_compact._format_commit_age("30 seconds ago") == "just now"

    def test_format_commit_age_default_is_relative(self, make_render_context):
        """_format_commit_age defaults to relative format."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})  # No format specified

        assert mod._format_commit_age("69 minutes ago") == "1 hour 9 minutes ago"

    def test_format_commit_age_invalid_fallback(self, make_render_context):
        """_format_commit_age returns input as-is for invalid strings."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"commit_age_format": "compact"})

        assert mod._format_commit_age("invalid") == "invalid"
        assert mod._format_commit_age("") == ""

    def test_parse_git_age_seconds(self, make_render_context):
        """_parse_git_age returns 0 for seconds."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("30 seconds ago") == 0
        assert mod._parse_git_age("1 second ago") == 0

    def test_parse_git_age_minutes(self, make_render_context):
        """_parse_git_age converts minutes."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("5 minutes ago") == 5
        assert mod._parse_git_age("1 minute ago") == 1
        assert mod._parse_git_age("69 minutes ago") == 69

    def test_parse_git_age_hours(self, make_render_context):
        """_parse_git_age converts hours to minutes."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("2 hours ago") == 120
        assert mod._parse_git_age("1 hour ago") == 60

    def test_parse_git_age_days(self, make_render_context):
        """_parse_git_age converts days to minutes."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("3 days ago") == 4320  # 3 * 1440
        assert mod._parse_git_age("1 day ago") == 1440

    def test_parse_git_age_weeks(self, make_render_context):
        """_parse_git_age converts weeks to minutes."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("2 weeks ago") == 20160  # 2 * 7 * 1440

    def test_parse_git_age_months(self, make_render_context):
        """_parse_git_age converts months to minutes (30 days)."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("2 months ago") == 86400  # 2 * 30 * 1440

    def test_parse_git_age_years(self, make_render_context):
        """_parse_git_age converts years to minutes (365 days)."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("1 year ago") == 525600  # 365 * 1440

    def test_parse_git_age_invalid(self, make_render_context):
        """_parse_git_age returns None for invalid input."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("invalid") is None
        assert mod._parse_git_age("") is None

    def test_decompose_minutes_only_minutes(self, make_render_context):
        """_decompose_minutes returns only minutes for small values."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._decompose_minutes(5) == (0, 0, 5)
        assert mod._decompose_minutes(59) == (0, 0, 59)

    def test_decompose_minutes_hours_and_minutes(self, make_render_context):
        """_decompose_minutes breaks into hours and minutes."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._decompose_minutes(69) == (0, 1, 9)
        assert mod._decompose_minutes(120) == (0, 2, 0)
        assert mod._decompose_minutes(150) == (0, 2, 30)

    def test_decompose_minutes_days_hours_minutes(self, make_render_context):
        """_decompose_minutes breaks into days, hours, minutes."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._decompose_minutes(1501) == (1, 1, 1)  # 1d 1h 1m
        assert mod._decompose_minutes(1560) == (1, 2, 0)  # 26h = 1d 2h
        assert mod._decompose_minutes(4320) == (3, 0, 0)  # 3 days

    def test_decompose_minutes_zero(self, make_render_context):
        """_decompose_minutes returns zeros for zero input."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._decompose_minutes(0) == (0, 0, 0)

    def test_project_name_from_common_dir_absolute(self, make_render_context):
        """Derives the project name from an absolute .git path."""
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})

        assert mod._project_name_from_common_dir("/home/user/myrepo/.git") == "myrepo"

    def test_project_name_from_common_dir_relative_uses_base(self, make_render_context):
        """Resolves a relative --git-common-dir against the supplied base, not the cwd."""
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})

        # ".git" relative to base → base's own name (not the test process cwd's name).
        assert mod._project_name_from_common_dir(".git", base="/home/user/myrepo") == "myrepo"

    def test_project_name_from_common_dir_bare_repo(self, make_render_context):
        """Uses the directory name when it is not a plain .git dir (bare repo)."""
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})

        assert mod._project_name_from_common_dir("/srv/repos/myrepo.git") == "myrepo.git"

    def test_get_location_regular_repo_root(self, make_render_context):
        """_get_location returns project name for regular repo at root."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/home/user/myproject", "project_dir": "/home/user/myproject"},
        )
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.side_effect = lambda *args: {
                ("rev-parse", "--git-common-dir"): "/home/user/myproject/.git",
                ("rev-parse", "--show-toplevel"): "/home/user/myproject",
            }.get(tuple(args))
            with patch("pathlib.Path.is_file", return_value=False):
                result = mod._get_location()

        assert result == {"project": "myproject", "worktree": None, "subfolder": None}

    def test_get_location_regular_repo_subfolder(self, make_render_context):
        """_get_location returns project and subfolder for regular repo."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/home/user/myproject/src/utils", "project_dir": "/home/user/myproject"},
        )
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.side_effect = lambda *args: {
                ("rev-parse", "--git-common-dir"): "/home/user/myproject/.git",
                ("rev-parse", "--show-toplevel"): "/home/user/myproject",
            }.get(tuple(args))
            with patch("pathlib.Path.is_file", return_value=False):
                result = mod._get_location()

        assert result == {"project": "myproject", "worktree": None, "subfolder": "src/utils"}

    def test_get_location_worktree_root(self, make_render_context):
        """_get_location returns project and worktree name for worktree at root."""
        data = make_input_data(
            model=make_model_data(),
            workspace={
                "current_dir": "/home/user/myproject/.worktrees/feature-branch",
                "project_dir": "/home/user/myproject/.worktrees/feature-branch",
            },
        )
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.side_effect = lambda *args: {
                ("rev-parse", "--git-common-dir"): "/home/user/myproject/.git",
                ("rev-parse", "--show-toplevel"): "/home/user/myproject/.worktrees/feature-branch",
            }.get(tuple(args))
            with patch("pathlib.Path.is_file", return_value=True):
                result = mod._get_location()

        assert result == {"project": "myproject", "worktree": "feature-branch", "subfolder": None}

    def test_get_location_worktree_subfolder(self, make_render_context):
        """_get_location returns all components for worktree with subfolder."""
        data = make_input_data(
            model=make_model_data(),
            workspace={
                "current_dir": "/home/user/myproject/.worktrees/feature-branch/src",
                "project_dir": "/home/user/myproject/.worktrees/feature-branch",
            },
        )
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.side_effect = lambda *args: {
                ("rev-parse", "--git-common-dir"): "/home/user/myproject/.git",
                ("rev-parse", "--show-toplevel"): "/home/user/myproject/.worktrees/feature-branch",
            }.get(tuple(args))
            with patch("pathlib.Path.is_file", return_value=True):
                result = mod._get_location()

        assert result == {"project": "myproject", "worktree": "feature-branch", "subfolder": "src"}

    def test_get_location_not_git_repo(self, make_render_context):
        """_get_location returns None when not in git repo."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = None
            result = mod._get_location()

        assert result is None

    def test_get_location_relative_git_common_dir_root(self, make_render_context, tmp_path, monkeypatch):
        """_get_location handles relative .git path when at repo root.

        Bug: git rev-parse --git-common-dir returns relative path ".git"
        when running from repo root. Path(".git").parent.name returns "."
        instead of the project name.
        """
        # Create a fake project structure
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        git_dir = project_dir / ".git"
        git_dir.mkdir()

        # Change to project directory so relative path works
        monkeypatch.chdir(project_dir)

        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": str(project_dir), "project_dir": str(project_dir)},
        )
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            # Git returns relative path ".git" when at repo root
            mock_git.side_effect = lambda *args: {
                ("rev-parse", "--git-common-dir"): ".git",
                ("rev-parse", "--show-toplevel"): str(project_dir),
            }.get(tuple(args))
            with patch("pathlib.Path.is_file", return_value=False):
                result = mod._get_location()

        assert result is not None
        assert result["project"] == "myproject"

    def test_get_location_relative_git_common_dir_subfolder(self, make_render_context, tmp_path, monkeypatch):
        """_get_location handles relative ../.git path when in subfolder.

        Bug: git rev-parse --git-common-dir returns relative path "../.git"
        when running from a subfolder. Path("../.git").parent.name returns ".."
        instead of the project name.
        """
        # Create a fake project structure
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        git_dir = project_dir / ".git"
        git_dir.mkdir()
        src_dir = project_dir / "src"
        src_dir.mkdir()

        # Change to subfolder so relative path works
        monkeypatch.chdir(src_dir)

        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": str(src_dir), "project_dir": str(project_dir)},
        )
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_run_git") as mock_git:
            # Git returns relative path "../.git" when in subfolder
            mock_git.side_effect = lambda *args: {
                ("rev-parse", "--git-common-dir"): "../.git",
                ("rev-parse", "--show-toplevel"): str(project_dir),
            }.get(tuple(args))
            with patch("pathlib.Path.is_file", return_value=False):
                result = mod._get_location()

        assert result is not None
        assert result["project"] == "myproject"
        assert result["subfolder"] == "src"

    def test_render_location_line_project_only(self, make_render_context):
        """_render_location_line shows just project name."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        location = {"project": "myproject", "worktree": None, "subfolder": None}
        result = mod._render_location_line(location)

        assert result is not None
        assert "myproject" in result
        # Should not have separator when only project
        assert "→" not in result

    def test_render_location_line_with_worktree(self, make_render_context):
        """_render_location_line shows project and worktree."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        location = {"project": "myproject", "worktree": "feature-x", "subfolder": None}
        result = mod._render_location_line(location)

        assert result is not None
        assert "myproject" in result
        assert "→" in result
        assert "feature-x" in result

    def test_render_location_line_with_subfolder(self, make_render_context):
        """_render_location_line shows project and subfolder."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        location = {"project": "myproject", "worktree": None, "subfolder": "src/utils"}
        result = mod._render_location_line(location)

        assert result is not None
        assert "myproject" in result
        assert "→" in result
        assert "src/utils" in result

    def test_render_location_line_subfolder_is_light_magenta(self, make_render_context, force_color):
        """In-repo subfolder renders in light_magenta (unified folder-leaf color)."""
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})

        location = {"project": "myproject", "worktree": None, "subfolder": "src/utils"}
        result = mod._render_location_line(location)

        assert result is not None
        assert colored("src/utils", "light_magenta") in result

    def test_render_location_line_full(self, make_render_context):
        """_render_location_line shows all components."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        location = {"project": "myproject", "worktree": "feature-x", "subfolder": "src"}
        result = mod._render_location_line(location)

        assert result is not None
        assert "myproject" in result
        assert "feature-x" in result
        assert "src" in result
        # Tree icon for worktree
        assert "🌲" in result

    def test_render_location_line_config_disabled(self, make_render_context):
        """_render_location_line respects config flags."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"show_project": False, "show_worktree": True, "show_folder": True})

        location = {"project": "myproject", "worktree": "feature-x", "subfolder": "src"}
        result = mod._render_location_line(location)

        assert result is not None
        assert "myproject" not in result
        assert "feature-x" in result
        assert "src" in result

    def test_render_location_line_all_disabled(self, make_render_context):
        """_render_location_line returns None when all disabled."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"show_project": False, "show_worktree": False, "show_folder": False})

        location = {"project": "myproject", "worktree": "feature-x", "subfolder": "src"}
        result = mod._render_location_line(location)

        assert result is None

    def test_render_status_line_branch_only(self, make_render_context):
        """_render_status_line shows branch name."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"show_remote_status": False, "show_changes": False, "show_commit": False})

        result = mod._render_status_line(
            branch="main",
            remote_status=("synced", 0),
            changes={"staged": 0, "modified": 0, "untracked": 0},
            commit=("abc1234", "2h"),
        )

        assert result is not None
        assert "main" in result

    def test_render_status_line_remote_ahead(self, make_render_context):
        """_render_status_line shows ahead indicator."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"show_changes": False, "show_commit": False})

        result = mod._render_status_line(
            branch="main",
            remote_status=("ahead", 2),
            changes={"staged": 0, "modified": 0, "untracked": 0},
            commit=None,
        )

        assert result is not None
        assert "↑2" in result

    def test_render_status_line_remote_behind(self, make_render_context):
        """_render_status_line shows behind indicator."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"show_changes": False, "show_commit": False})

        result = mod._render_status_line(
            branch="main",
            remote_status=("behind", 3),
            changes={"staged": 0, "modified": 0, "untracked": 0},
            commit=None,
        )

        assert result is not None
        assert "↓3" in result

    def test_render_status_line_remote_diverged(self, make_render_context):
        """_render_status_line shows diverged indicator."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"show_changes": False, "show_commit": False})

        result = mod._render_status_line(
            branch="main",
            remote_status=("diverged", 5),
            changes={"staged": 0, "modified": 0, "untracked": 0},
            commit=None,
        )

        assert result is not None
        assert "⇅5" in result

    def test_render_status_line_remote_synced(self, make_render_context):
        """_render_status_line shows synced indicator."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"show_changes": False, "show_commit": False})

        result = mod._render_status_line(
            branch="main",
            remote_status=("synced", 0),
            changes={"staged": 0, "modified": 0, "untracked": 0},
            commit=None,
        )

        assert result is not None
        assert "✓" in result

    def test_render_status_line_no_upstream(self, make_render_context):
        """_render_status_line shows no upstream indicator."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"show_changes": False, "show_commit": False})

        result = mod._render_status_line(
            branch="main",
            remote_status=("no_upstream", 0),
            changes={"staged": 0, "modified": 0, "untracked": 0},
            commit=None,
        )

        assert result is not None
        assert "☁✗" in result

    def test_render_status_line_changes(self, make_render_context):
        """_render_status_line shows change counts."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"show_remote_status": False, "show_commit": False})

        result = mod._render_status_line(
            branch="main",
            remote_status=("synced", 0),
            changes={"staged": 3, "modified": 2, "untracked": 1},
            commit=None,
        )

        assert result is not None
        assert "+3" in result
        assert "~2" in result
        assert "?1" in result
        assert "[" in result
        assert "]" in result

    def test_render_status_line_changes_partial(self, make_render_context):
        """_render_status_line shows only non-zero changes."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"show_remote_status": False, "show_commit": False})

        result = mod._render_status_line(
            branch="main",
            remote_status=("synced", 0),
            changes={"staged": 0, "modified": 2, "untracked": 0},
            commit=None,
        )

        assert result is not None
        assert "+0" not in result
        assert "~2" in result
        assert "?0" not in result

    def test_render_status_line_changes_clean(self, make_render_context):
        """_render_status_line hides brackets when no changes."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"show_remote_status": False, "show_commit": False})

        result = mod._render_status_line(
            branch="main",
            remote_status=("synced", 0),
            changes={"staged": 0, "modified": 0, "untracked": 0},
            commit=None,
        )

        assert result is not None
        assert "[" not in result

    def test_render_status_line_commit(self, make_render_context):
        """_render_status_line shows commit hash and age."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"show_remote_status": False, "show_changes": False})

        result = mod._render_status_line(
            branch="main",
            remote_status=("synced", 0),
            changes={"staged": 0, "modified": 0, "untracked": 0},
            commit=("abc1234", "2h"),
        )

        assert result is not None
        assert "abc1234" in result
        assert "2h" in result

    def test_render_status_line_full(self, make_render_context):
        """_render_status_line shows all components."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        result = mod._render_status_line(
            branch="feature/test",
            remote_status=("ahead", 2),
            changes={"staged": 1, "modified": 1, "untracked": 1},
            commit=("abc1234", "2h"),
        )

        assert result is not None
        assert "feature/test" in result
        assert "↑2" in result
        assert "+1" in result
        assert "~1" in result
        assert "?1" in result
        assert "abc1234" in result

    def test_render_status_line_all_disabled(self, make_render_context):
        """_render_status_line returns None when all disabled."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(
            ctx, {"show_branch": False, "show_remote_status": False, "show_changes": False, "show_commit": False}
        )

        result = mod._render_status_line(
            branch="main",
            remote_status=("synced", 0),
            changes={"staged": 0, "modified": 0, "untracked": 0},
            commit=("abc1234", "2h"),
        )

        assert result is None

    def test_render_not_git_repo(self, make_render_context):
        """render returns None when not in a git repo and there is no workspace to fall back to."""
        data = make_input_data(model=make_model_data())  # no workspace
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with (
            patch.object(mod, "_get_location") as mock_loc,
            patch.object(mod, "_get_branch") as mock_branch,
        ):
            mock_loc.return_value = None
            mock_branch.return_value = None
            result = mod.render()

        assert result is None

    def test_render_branch_unresolved_location_only(self, make_render_context):
        """When _get_branch() is None but a location resolves, render shows the location line only.

        Reachable when no ref resolves (e.g. an unborn/detached HEAD whose short
        hash also fails). NOTE: a normal fresh `git init` repo does NOT hit this —
        modern git's `branch --show-current` returns the unborn branch name, so
        _get_branch() resolves and render shows two lines.
        """
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/home/user/project", "project_dir": "/home/user/project"},
        )
        mod = GitModule(make_render_context(data), {})

        with (
            patch.object(mod, "_get_location") as mock_loc,
            patch.object(mod, "_get_branch") as mock_branch,
        ):
            mock_loc.return_value = {"project": "project", "worktree": None, "subfolder": None}
            mock_branch.return_value = None
            result = mod.render()

        assert result is not None
        assert "\n" not in result
        assert "project" in result

    def test_render_not_repo_uses_cwd_fallback(self, make_render_context):
        """Not a repo but workspace present → cwd fallback line, no status line."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/work/scratch", "project_dir": "/work/scratch"},
        )
        mod = GitModule(make_render_context(data), {})

        with (
            patch.object(mod, "_get_location") as mock_loc,
            patch.object(mod, "_get_branch") as mock_branch,
        ):
            mock_loc.return_value = None
            mock_branch.return_value = None
            result = mod.render()

        assert result is not None
        assert "\n" not in result
        assert "/work/scratch" in result

    def test_render_two_lines(self, make_render_context):
        """render returns two lines of output."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/home/user/project", "project_dir": "/home/user/project"},
        )
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with (
            patch.object(mod, "_get_location") as mock_loc,
            patch.object(mod, "_get_branch") as mock_branch,
            patch.object(mod, "_get_remote_status") as mock_remote,
            patch.object(mod, "_get_changes") as mock_changes,
            patch.object(mod, "_get_last_commit") as mock_commit,
            patch.object(mod, "_get_pr", return_value=None),
        ):
            mock_loc.return_value = {"project": "project", "worktree": None, "subfolder": None}
            mock_branch.return_value = "main"
            mock_remote.return_value = ("synced", 0)
            mock_changes.return_value = {"staged": 1, "modified": 0, "untracked": 0}
            mock_commit.return_value = ("abc1234", "2 hours ago")

            result = mod.render()

        assert result is not None
        lines = result.split("\n")
        assert len(lines) == 2
        assert "project" in lines[0]
        assert "main" in lines[1]

    def test_render_line1_only(self, make_render_context):
        """render returns one line when line 2 disabled."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/home/user/project", "project_dir": "/home/user/project"},
        )
        ctx = make_render_context(data)
        mod = GitModule(
            ctx,
            {"show_branch": False, "show_remote_status": False, "show_changes": False, "show_commit": False},
        )

        with (
            patch.object(mod, "_get_location") as mock_loc,
            patch.object(mod, "_get_branch") as mock_branch,
            patch.object(mod, "_get_pr", return_value=None),
        ):
            mock_loc.return_value = {"project": "project", "worktree": None, "subfolder": None}
            mock_branch.return_value = "main"

            result = mod.render()

        assert result is not None
        assert "\n" not in result
        assert "project" in result

    def test_render_line2_only(self, make_render_context):
        """render returns one line when line 1 disabled."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"show_project": False, "show_worktree": False, "show_folder": False})

        with (
            patch.object(mod, "_get_location") as mock_loc,
            patch.object(mod, "_get_branch") as mock_branch,
            patch.object(mod, "_get_remote_status") as mock_remote,
            patch.object(mod, "_get_changes") as mock_changes,
            patch.object(mod, "_get_last_commit") as mock_commit,
            patch.object(mod, "_get_pr", return_value=None),
        ):
            mock_loc.return_value = {"project": "project", "worktree": None, "subfolder": None}
            mock_branch.return_value = "main"
            mock_remote.return_value = ("synced", 0)
            mock_changes.return_value = {"staged": 0, "modified": 0, "untracked": 0}
            mock_commit.return_value = ("abc1234", "2h")

            result = mod.render()

        assert result is not None
        assert "\n" not in result
        assert "main" in result

    def test_render_all_disabled(self, make_render_context):
        """render returns None when both lines disabled."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(
            ctx,
            {
                "show_project": False,
                "show_worktree": False,
                "show_folder": False,
                "show_branch": False,
                "show_remote_status": False,
                "show_changes": False,
                "show_commit": False,
            },
        )

        with (
            patch.object(mod, "_get_location") as mock_loc,
            patch.object(mod, "_get_branch") as mock_branch,
            patch.object(mod, "_get_pr", return_value=None),
        ):
            mock_loc.return_value = {"project": "project", "worktree": None, "subfolder": None}
            mock_branch.return_value = "main"

            result = mod.render()

        assert result is None

    def test_shorten_path_under_home(self, make_render_context, monkeypatch):
        """_shorten_path replaces a leading $HOME with ~."""
        monkeypatch.setenv("HOME", "/home/user")
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})

        assert mod._shorten_path("/home/user/projects/x") == "~/projects/x"

    def test_shorten_path_equals_home(self, make_render_context, monkeypatch):
        """_shorten_path returns ~ when path equals $HOME."""
        monkeypatch.setenv("HOME", "/home/user")
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})

        assert mod._shorten_path("/home/user") == "~"

    def test_shorten_path_outside_home(self, make_render_context, monkeypatch):
        """_shorten_path leaves paths outside $HOME unchanged."""
        monkeypatch.setenv("HOME", "/home/user")
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})

        assert mod._shorten_path("/work/scratch") == "/work/scratch"

    def test_shorten_path_home_prefix_not_subdir(self, make_render_context, monkeypatch):
        """_shorten_path does not shorten a sibling that merely shares the prefix."""
        monkeypatch.setenv("HOME", "/home/user")
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})

        assert mod._shorten_path("/home/username") == "/home/username"

    def test_render_cwd_fallback_case2_plain_dir(self, make_render_context, force_color):
        """Case 2: not a repo, project_dir == current_dir → light_magenta path, no probe."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/work/scratch", "project_dir": "/work/scratch"},
        )
        mod = GitModule(make_render_context(data), {})

        with patch.object(mod, "_run_git") as mock_git:
            result = mod._render_cwd_fallback()

        mock_git.assert_not_called()
        assert result == colored("/work/scratch", "light_magenta")

    def test_render_cwd_fallback_case2_empty_project_dir(self, make_render_context, force_color):
        """Case 2: project_dir empty → light_magenta path, no probe."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/work/scratch", "project_dir": ""},
        )
        mod = GitModule(make_render_context(data), {})

        with patch.object(mod, "_run_git") as mock_git:
            result = mod._render_cwd_fallback()

        mock_git.assert_not_called()
        assert result == colored("/work/scratch", "light_magenta")

    def test_render_cwd_fallback_case1_left_repo(self, make_render_context, force_color):
        """Case 1: project_dir is a repo we cd'd out of → project[cyan] → path[red]."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/work/scratch", "project_dir": "/home/user/myrepo"},
        )
        mod = GitModule(make_render_context(data), {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = "/home/user/myrepo/.git"
            result = mod._render_cwd_fallback()

        mock_git.assert_called_once_with("rev-parse", "--git-common-dir", cwd="/home/user/myrepo")
        assert result is not None
        assert colored("myrepo", "cyan") in result
        assert colored("/work/scratch", "red") in result
        assert colored(" → ", "dark_grey") in result
        assert result == colored("myrepo", "cyan") + colored(" → ", "dark_grey") + colored("/work/scratch", "red")

    def test_render_cwd_fallback_case1_relative_common_dir(self, make_render_context, force_color):
        """Case 1: a relative --git-common-dir resolves against project_dir."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/work/scratch", "project_dir": "/home/user/myrepo"},
        )
        mod = GitModule(make_render_context(data), {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = ".git"  # relative to project_dir
            result = mod._render_cwd_fallback()

        assert result is not None
        assert colored("myrepo", "cyan") in result

    def test_render_cwd_fallback_case1_probe_fails_is_case2(self, make_render_context, force_color):
        """project_dir differs but is not a repo (probe → None) → Case 2 rendering."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/work/scratch", "project_dir": "/work/other"},
        )
        mod = GitModule(make_render_context(data), {})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = None  # project_dir not a repo either
            result = mod._render_cwd_fallback()

        assert result == colored("/work/scratch", "light_magenta")

    def test_render_cwd_fallback_no_workspace(self, make_render_context):
        """No workspace → no fallback line."""
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})

        assert mod._render_cwd_fallback() is None

    def test_render_cwd_fallback_empty_current_dir(self, make_render_context):
        """Empty current_dir → no fallback line."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "", "project_dir": ""},
        )
        mod = GitModule(make_render_context(data), {})

        assert mod._render_cwd_fallback() is None

    def test_render_cwd_fallback_case2_folder_disabled(self, make_render_context):
        """Case 2 with show_folder=False → None."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/work/scratch", "project_dir": "/work/scratch"},
        )
        mod = GitModule(make_render_context(data), {"show_folder": False})

        assert mod._render_cwd_fallback() is None

    def test_render_cwd_fallback_case1_project_disabled(self, make_render_context, force_color):
        """Case 1 with show_project=False → red path only (no cyan project, no separator)."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/work/scratch", "project_dir": "/home/user/myrepo"},
        )
        mod = GitModule(make_render_context(data), {"show_project": False})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = "/home/user/myrepo/.git"
            result = mod._render_cwd_fallback()

        assert result is not None
        assert result == colored("/work/scratch", "red")
        assert colored("myrepo", "cyan") not in result
        assert colored(" → ", "dark_grey") not in result

    def test_render_cwd_fallback_case1_folder_disabled(self, make_render_context, force_color):
        """Case 1 with show_folder=False → cyan project only (no red path)."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/work/scratch", "project_dir": "/home/user/myrepo"},
        )
        mod = GitModule(make_render_context(data), {"show_folder": False})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = "/home/user/myrepo/.git"
            result = mod._render_cwd_fallback()

        assert result is not None
        assert result == colored("myrepo", "cyan")
        assert colored("/work/scratch", "red") not in result

    def test_render_cwd_fallback_case1_both_disabled(self, make_render_context):
        """Case 1 with show_project=False and show_folder=False → None (empty parts)."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/work/scratch", "project_dir": "/home/user/myrepo"},
        )
        mod = GitModule(make_render_context(data), {"show_project": False, "show_folder": False})

        with patch.object(mod, "_run_git") as mock_git:
            mock_git.return_value = "/home/user/myrepo/.git"
            result = mod._render_cwd_fallback()

        assert result is None


class TestPrParams:
    """Tests for the PR-related GitParams and the PrInfo value type."""

    def test_pr_params_defaults(self, make_render_context):
        """show_pr/pr_link default on, pr_provider auto, pr_cache_ttl 300."""
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})

        assert mod.params.show_pr is True
        assert mod.params.pr_provider == "auto"
        assert mod.params.pr_link is True
        assert mod.params.pr_cache_ttl == 300

    def test_pr_params_override(self, make_render_context):
        """PR params are configurable from the raw TOML section."""
        mod = GitModule(
            make_render_context(make_input_data(model=make_model_data())),
            {"show_pr": False, "pr_provider": "gitlab", "pr_link": False, "pr_cache_ttl": 60},
        )

        assert mod.params.show_pr is False
        assert mod.params.pr_provider == "gitlab"
        assert mod.params.pr_link is False
        assert mod.params.pr_cache_ttl == 60

    def test_pr_provider_invalid_falls_back_to_default(self, make_render_context):
        """An out-of-choices pr_provider is dropped, default 'auto' applies."""
        mod = GitModule(
            make_render_context(make_input_data(model=make_model_data())),
            {"pr_provider": "bitbucket"},
        )

        assert mod.params.pr_provider == "auto"

    def test_pr_info_holds_fields(self):
        """PrInfo stores provider, number, state, url."""
        info = PrInfo(provider="github", number=42, state="open", url="https://example/pr/42")

        assert info.provider == "github"
        assert info.number == 42
        assert info.state == "open"
        assert info.url == "https://example/pr/42"


class TestParseRemoteHost:
    """Tests for parse_remote_host (SSH scp-form, URL-form, edge cases)."""

    def test_scp_ssh_with_user(self):
        assert parse_remote_host("git@github.com:NoNameItem/claude-tools.git") == "github.com"

    def test_scp_ssh_self_hosted(self):
        assert parse_remote_host("git@gitlab.example.com:group/sub/repo.git") == "gitlab.example.com"

    def test_scp_ssh_without_user(self):
        assert parse_remote_host("github.com:owner/repo.git") == "github.com"

    def test_https(self):
        assert parse_remote_host("https://github.com/owner/repo.git") == "github.com"

    def test_https_with_userinfo_and_port(self):
        assert parse_remote_host("https://user@git.example.com:8443/group/repo.git") == "git.example.com"

    def test_ssh_scheme_with_port(self):
        assert parse_remote_host("ssh://git@gitlab.example.com:2222/group/repo.git") == "gitlab.example.com"

    def test_empty_or_whitespace(self):
        assert parse_remote_host("") is None
        assert parse_remote_host("   ") is None

    def test_unparseable(self):
        assert parse_remote_host("not-a-url") is None

    def test_host_is_lowercased(self):
        assert parse_remote_host("git@GitHub.com:o/r.git") == "github.com"
        assert parse_remote_host("https://GitLab.example.COM/g/r.git") == "gitlab.example.com"


class TestParseRemoteSlug:
    """Tests for parse_remote_slug: scp/https forms, .git stripping, subgroups."""

    def test_scp_form(self):
        assert parse_remote_slug("git@github.com:Org/Repo.git") == "github.com/Org/Repo"

    def test_https_form(self):
        assert parse_remote_slug("https://github.com/Org/Repo") == "github.com/Org/Repo"

    def test_gitlab_subgroup(self):
        assert parse_remote_slug("git@gitlab.com:group/sub/repo.git") == "gitlab.com/group/sub/repo"

    def test_empty_returns_none(self):
        assert parse_remote_slug("") is None

    def test_no_path_returns_none(self):
        assert parse_remote_slug("git@github.com:") is None


class TestParseGithubPrList:
    """Tests for parse_github_pr_list: state mapping, empty, malformed."""

    def test_open_pr(self):
        stdout = '[{"number": 42, "state": "OPEN", "isDraft": false, "title": "t", "url": "u"}]'
        result = parse_github_pr_list(stdout)
        assert result == [PrInfo(provider="github", number=42, state="open", url="u")]

    def test_draft_pr(self):
        stdout = '[{"number": 7, "state": "OPEN", "isDraft": true, "url": "u"}]'
        assert parse_github_pr_list(stdout) == [PrInfo("github", 7, "draft", "u")]

    def test_merged_pr(self):
        stdout = '[{"number": 5, "state": "MERGED", "isDraft": false, "url": "u"}]'
        assert parse_github_pr_list(stdout) == [PrInfo("github", 5, "merged", "u")]

    def test_closed_pr(self):
        stdout = '[{"number": 9, "state": "CLOSED", "isDraft": false, "url": "u"}]'
        assert parse_github_pr_list(stdout) == [PrInfo("github", 9, "closed", "u")]

    def test_empty_list_is_no_pr(self):
        """An empty JSON array is a valid 'no PR' result, not an error."""
        assert parse_github_pr_list("[]") == []

    def test_malformed_json_is_none(self):
        """Non-JSON stdout on a supposedly-ok result is an error signalled by None."""
        assert parse_github_pr_list("not json") is None

    def test_non_list_json_is_none(self):
        assert parse_github_pr_list('{"number": 1}') is None

    def test_unknown_state_row_skipped(self):
        stdout = '[{"number": 1, "state": "WEIRD", "isDraft": false, "url": "u"}]'
        assert parse_github_pr_list(stdout) == []


class TestParseGitlabMrList:
    """Tests for parse_gitlab_mr_list."""

    def test_opened_mr(self):
        stdout = '[{"iid": 42, "state": "opened", "draft": false, "web_url": "u"}]'
        assert parse_gitlab_mr_list(stdout) == [PrInfo("gitlab", 42, "open", "u")]

    def test_draft_mr_via_draft_field(self):
        stdout = '[{"iid": 3, "state": "opened", "draft": true, "web_url": "u"}]'
        assert parse_gitlab_mr_list(stdout) == [PrInfo("gitlab", 3, "draft", "u")]

    def test_draft_mr_via_work_in_progress_fallback(self):
        stdout = '[{"iid": 4, "state": "opened", "work_in_progress": true, "web_url": "u"}]'
        assert parse_gitlab_mr_list(stdout) == [PrInfo("gitlab", 4, "draft", "u")]

    def test_merged_mr(self):
        stdout = '[{"iid": 5, "state": "merged", "web_url": "u"}]'
        assert parse_gitlab_mr_list(stdout) == [PrInfo("gitlab", 5, "merged", "u")]

    def test_locked_maps_to_closed(self):
        stdout = '[{"iid": 6, "state": "locked", "web_url": "u"}]'
        assert parse_gitlab_mr_list(stdout) == [PrInfo("gitlab", 6, "closed", "u")]

    def test_empty_is_no_mr(self):
        assert parse_gitlab_mr_list("[]") == []

    def test_malformed_is_none(self):
        assert parse_gitlab_mr_list("<html>") is None


class TestSelectPr:
    """Tests for _select_pr precedence: open>draft>merged>closed, then highest number."""

    def test_prefers_open_over_merged(self):
        from statuskit.modules.git import _select_pr

        candidates = [PrInfo("github", 1, "merged", "u"), PrInfo("github", 2, "open", "u")]
        assert _select_pr(candidates) == PrInfo("github", 2, "open", "u")

    def test_prefers_draft_over_closed(self):
        from statuskit.modules.git import _select_pr

        candidates = [PrInfo("github", 9, "closed", "u"), PrInfo("github", 3, "draft", "u")]
        assert _select_pr(candidates) == PrInfo("github", 3, "draft", "u")

    def test_ties_broken_by_highest_number(self):
        from statuskit.modules.git import _select_pr

        candidates = [PrInfo("github", 10, "open", "a"), PrInfo("github", 20, "open", "b")]
        assert _select_pr(candidates) == PrInfo("github", 20, "open", "b")

    def test_empty_is_none(self):
        from statuskit.modules.git import _select_pr

        assert _select_pr([]) is None


class TestRunCli:
    """Tests for _run_cli: ok, nonzero, timeout, OSError classification."""

    def _mod(self, make_render_context):
        return GitModule(make_render_context(make_input_data(model=make_model_data())), {})

    def test_ok(self, make_render_context):
        mod = self._mod(make_render_context)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="[]\n", stderr="")
            result = mod._run_cli("github", "pr", "list")
        assert result == CliResult(ok=True, stdout="[]", stderr="", reason=None)
        assert mock_run.call_args[0][0][0] == "gh"

    def test_gitlab_uses_glab_binary(self, make_render_context):
        mod = self._mod(make_render_context)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="[]", stderr="")
            mod._run_cli("gitlab", "mr", "list")
        assert mock_run.call_args[0][0][0] == "glab"

    def test_nonzero_returns_error_reason_from_stderr(self, make_render_context):
        mod = self._mod(make_render_context)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="not authenticated\n"
            )
            result = mod._run_cli("github", "pr", "list")
        assert result.ok is False
        assert result.reason == "not authenticated"

    def test_timeout_returns_timeout_reason(self, make_render_context):
        mod = self._mod(make_render_context)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=3)
            result = mod._run_cli("github", "pr", "list")
        assert result.ok is False
        assert result.reason == "timeout"

    def test_oserror_returns_not_runnable_reason(self, make_render_context):
        mod = self._mod(make_render_context)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("no gh")
            result = mod._run_cli("github", "pr", "list")
        assert result.ok is False
        assert result.reason is not None
        assert "gh" in result.reason


class TestFetchPr:
    """Tests for _fetch_pr: found, no-PR-normal, error, malformed."""

    def _mod(self, make_render_context):
        return GitModule(make_render_context(make_input_data(model=make_model_data())), {})

    def test_github_found(self, make_render_context):
        mod = self._mod(make_render_context)
        cli = CliResult(
            ok=True, stdout='[{"number": 42, "state": "OPEN", "isDraft": false, "url": "u"}]', stderr="", reason=None
        )
        with patch.object(mod, "_run_cli", return_value=cli) as mock_cli:
            info, error = mod._fetch_pr("github", "feature/x")
        assert error is None
        assert info == PrInfo("github", 42, "open", "u")
        # correct gh invocation
        assert mock_cli.call_args[0][0] == "github"
        assert "--head" in mock_cli.call_args[0]
        assert "feature/x" in mock_cli.call_args[0]

    def test_no_pr_is_normal(self, make_render_context):
        """Empty list → (None, None): no PR, not an error."""
        mod = self._mod(make_render_context)
        cli = CliResult(ok=True, stdout="[]", stderr="", reason=None)
        with patch.object(mod, "_run_cli", return_value=cli):
            info, error = mod._fetch_pr("github", "feature/x")
        assert info is None
        assert error is None

    def test_cli_error_propagates_reason(self, make_render_context):
        mod = self._mod(make_render_context)
        cli = CliResult(ok=False, stdout="", stderr="boom", reason="boom")
        with patch.object(mod, "_run_cli", return_value=cli):
            info, error = mod._fetch_pr("github", "feature/x")
        assert info is None
        assert error == "boom"

    def test_malformed_json_is_error(self, make_render_context):
        mod = self._mod(make_render_context)
        cli = CliResult(ok=True, stdout="<html>", stderr="", reason=None)
        with patch.object(mod, "_run_cli", return_value=cli):
            info, error = mod._fetch_pr("github", "feature/x")
        assert info is None
        assert error == "malformed CLI JSON"

    def test_gitlab_requests_all_states(self, make_render_context):
        """glab mr list must pass --all so merged/closed MRs are included, not just open."""
        mod = self._mod(make_render_context)
        cli = CliResult(ok=True, stdout="[]", stderr="", reason=None)
        with patch.object(mod, "_run_cli", return_value=cli) as mock_cli:
            mod._fetch_pr("gitlab", "feature/x")
        assert mock_cli.call_args[0][0] == "gitlab"
        assert "--all" in mock_cli.call_args[0]
        assert "--source-branch" in mock_cli.call_args[0]

    def test_gitlab_uses_source_branch(self, make_render_context):
        mod = self._mod(make_render_context)
        cli = CliResult(
            ok=True, stdout='[{"iid": 7, "state": "opened", "draft": false, "web_url": "u"}]', stderr="", reason=None
        )
        with patch.object(mod, "_run_cli", return_value=cli) as mock_cli:
            info, _error = mod._fetch_pr("gitlab", "feature/x")
        assert info == PrInfo("gitlab", 7, "open", "u")
        assert "--source-branch" in mock_cli.call_args[0]


class TestDetectProvider:
    """Tests for _detect_provider: literal hosts, self-hosted auth, name heuristic, give-up."""

    def _mod(self, make_render_context):
        return GitModule(make_render_context(make_input_data(model=make_model_data())), {})

    def test_github_com_literal_no_subprocess(self, make_render_context):
        mod = self._mod(make_render_context)
        with patch("statuskit.modules.git.shutil.which") as which, patch.object(mod, "_run_cli") as cli:
            assert mod._detect_provider("github.com") == "github"
        which.assert_not_called()
        cli.assert_not_called()

    def test_gitlab_com_literal(self, make_render_context):
        mod = self._mod(make_render_context)
        assert mod._detect_provider("gitlab.com") == "gitlab"

    def test_self_hosted_authed_in_gh_only(self, make_render_context):
        mod = self._mod(make_render_context)
        with (
            patch("statuskit.modules.git.shutil.which", return_value="/bin/x"),
            patch.object(mod, "_host_authenticated", side_effect=lambda p, h: p == "github"),
        ):
            assert mod._detect_provider("git.corp.example") == "github"

    def test_self_hosted_authed_in_glab_only(self, make_render_context):
        mod = self._mod(make_render_context)
        with (
            patch("statuskit.modules.git.shutil.which", return_value="/bin/x"),
            patch.object(mod, "_host_authenticated", side_effect=lambda p, h: p == "gitlab"),
        ):
            assert mod._detect_provider("git.corp.example") == "gitlab"

    def test_self_hosted_authed_in_both_is_ambiguous(self, make_render_context):
        mod = self._mod(make_render_context)
        with (
            patch("statuskit.modules.git.shutil.which", return_value="/bin/x"),
            patch.object(mod, "_host_authenticated", return_value=True),
        ):
            assert mod._detect_provider("git.corp.example") is None

    def test_name_heuristic_when_not_authed(self, make_render_context):
        mod = self._mod(make_render_context)
        with (
            patch("statuskit.modules.git.shutil.which", return_value="/bin/x"),
            patch.object(mod, "_host_authenticated", return_value=False),
        ):
            assert mod._detect_provider("gitlab.corp.example") == "gitlab"
            assert mod._detect_provider("github.corp.example") == "github"

    def test_give_up_unknown_host(self, make_render_context):
        mod = self._mod(make_render_context)
        with (
            patch("statuskit.modules.git.shutil.which", return_value="/bin/x"),
            patch.object(mod, "_host_authenticated", return_value=False),
        ):
            assert mod._detect_provider("scm.corp.example") is None


class TestHostAuthenticated:
    """Tests for _host_authenticated (substring match over combined streams)."""

    def _mod(self, make_render_context):
        return GitModule(make_render_context(make_input_data(model=make_model_data())), {})

    def test_matches_host_in_stdout(self, make_render_context):
        mod = self._mod(make_render_context)
        cli = CliResult(ok=True, stdout="git.corp.example\n  logged in", stderr="", reason=None)
        with patch.object(mod, "_run_cli", return_value=cli):
            assert mod._host_authenticated("github", "git.corp.example") is True

    def test_matches_host_in_stderr(self, make_render_context):
        mod = self._mod(make_render_context)
        cli = CliResult(ok=True, stdout="", stderr="Logged in to git.corp.example", reason=None)
        with patch.object(mod, "_run_cli", return_value=cli):
            assert mod._host_authenticated("gitlab", "git.corp.example") is True

    def test_false_when_cli_failed(self, make_render_context):
        mod = self._mod(make_render_context)
        cli = CliResult(ok=False, stdout="", stderr="not logged in", reason="not logged in")
        with patch.object(mod, "_run_cli", return_value=cli):
            assert mod._host_authenticated("github", "git.corp.example") is False

    def test_false_when_host_absent(self, make_render_context):
        mod = self._mod(make_render_context)
        cli = CliResult(ok=True, stdout="github.com logged in", stderr="", reason=None)
        with patch.object(mod, "_run_cli", return_value=cli):
            assert mod._host_authenticated("github", "git.corp.example") is False


class TestPrCache:
    """Tests for PrCache: round-trip, negative entries, corrupt file, atomic write."""

    def test_load_missing_returns_empty_doc(self, tmp_path):
        cache = PrCache(cache_dir=tmp_path, ttl=300)
        doc = cache.load()
        assert doc.providers == {}
        assert doc.entries == {}

    def test_save_and_load_round_trip(self, tmp_path):
        cache = PrCache(cache_dir=tmp_path, ttl=300)
        now = datetime.now(UTC)
        doc = PrCacheDoc(
            providers={"git.corp.example": "github"},
            entries={"git.corp.example\tmain": PrCacheEntry(PrInfo("github", 42, "open", "u"), now)},
        )
        cache.save(doc)

        loaded = cache.load()
        assert loaded.providers == {"git.corp.example": "github"}
        entry = loaded.entries["git.corp.example\tmain"]
        assert entry.info == PrInfo("github", 42, "open", "u")
        assert entry.last_attempt_at == now

    def test_negative_entry_round_trips(self, tmp_path):
        """A cached 'no PR' (info=None) survives a save/load cycle."""
        cache = PrCache(cache_dir=tmp_path, ttl=300)
        now = datetime.now(UTC)
        doc = PrCacheDoc(providers={}, entries={"h\tb": PrCacheEntry(None, now)})
        cache.save(doc)

        loaded = cache.load()
        assert "h\tb" in loaded.entries
        assert loaded.entries["h\tb"].info is None

    def test_corrupt_file_returns_empty_doc(self, tmp_path):
        cache = PrCache(cache_dir=tmp_path, ttl=300)
        cache.cache_file.write_text("{ not json")
        doc = cache.load()
        assert doc.providers == {}
        assert doc.entries == {}

    def test_load_drops_bad_provider_values(self, tmp_path):
        cache = PrCache(cache_dir=tmp_path, ttl=300)
        cache.cache_file.write_text(json.dumps({"providers": {"h": "bitbucket"}, "entries": {}}))
        assert cache.load().providers == {}

    def test_save_is_atomic_no_partial_file(self, tmp_path):
        """A failed replace leaves no stray temp files behind."""
        cache = PrCache(cache_dir=tmp_path, ttl=300)
        doc = PrCacheDoc(providers={}, entries={})
        with patch("pathlib.Path.replace", side_effect=OSError("boom")):
            cache.save(doc)  # must not raise
        assert list(tmp_path.glob("*.tmp")) == []

    def test_load_wrong_shape_returns_empty_doc(self, tmp_path):
        """Well-formed JSON of the wrong shape degrades to empty, never raises."""
        cache = PrCache(cache_dir=tmp_path, ttl=300)
        wrong_shapes = [
            [1, 2, 3],  # top-level array
            "hello",  # top-level string
            {"entries": ["a", "b"]},  # entries is a list, not a mapping
            {"entries": {"h\tb": "oops"}},  # entry value is a string
            {"entries": {"h\tb": None}},  # entry value is null
            {"providers": ["x"]},  # providers is a list, not a mapping
        ]
        for payload in wrong_shapes:
            cache.cache_file.write_text(json.dumps(payload))
            doc = cache.load()
            assert doc.providers == {}, payload
            assert doc.entries == {}, payload

    def test_load_skips_bad_entry_keeps_good(self, tmp_path):
        """One unparseable entry is dropped; every valid entry and all providers survive."""
        cache = PrCache(cache_dir=tmp_path, ttl=300)
        now = datetime.now(UTC)
        payload = {
            "providers": {"git.corp.example": "github"},
            "entries": {
                "git.corp.example\tmain": {
                    "info": {"provider": "github", "number": 7, "state": "open", "url": "u"},
                    "last_attempt_at": now.isoformat(),
                },
                "git.corp.example\tbad": {"info": None, "last_attempt_at": "not-a-date"},
            },
        }
        cache.cache_file.write_text(json.dumps(payload))

        doc = cache.load()
        assert doc.providers == {"git.corp.example": "github"}
        assert "git.corp.example\tbad" not in doc.entries
        good = doc.entries["git.corp.example\tmain"]
        assert good.info == PrInfo("github", 7, "open", "u")
        assert good.last_attempt_at == now

    def test_load_skips_naive_timestamp_entry(self, tmp_path):
        """A naive last_attempt_at (no tz) is dropped so aware minus naive never raises later."""
        cache = PrCache(cache_dir=tmp_path, ttl=300)
        now = datetime.now(UTC)
        payload = {
            "providers": {},
            "entries": {
                "h\tgood": {
                    "info": {"provider": "github", "number": 7, "state": "open", "url": "u"},
                    "last_attempt_at": now.isoformat(),
                },
                "h\tnaive": {"info": None, "last_attempt_at": "2026-01-01T00:00:00"},
            },
        }
        cache.cache_file.write_text(json.dumps(payload))

        doc = cache.load()
        assert "h\tnaive" not in doc.entries
        good = doc.entries["h\tgood"]
        assert good.info == PrInfo("github", 7, "open", "u")
        assert good.last_attempt_at == now


class TestGitInitAndRemoteHost:
    """Tests for the __init__ cache wiring, debug channel, and _get_remote."""

    def test_cache_built_when_cache_dir_set(self, make_render_context, tmp_path):
        ctx = make_render_context(make_input_data(model=make_model_data()), cache_dir=tmp_path)
        mod = GitModule(ctx, {"pr_cache_ttl": 120})
        assert mod.cache is not None
        assert mod.cache.ttl == 120
        assert mod._debug_messages == []

    def test_cache_none_without_cache_dir(self, make_render_context):
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})
        assert mod.cache is None

    def test_note_debug_appends(self, make_render_context):
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})
        mod._note_debug("hello")
        assert mod._debug_messages == ["hello"]

    def test_get_remote_uses_upstream_remote(self, make_render_context):
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})

        def fake_git(*args):
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return "upstream/main"
            if args == ("remote", "get-url", "upstream"):
                return "git@github.com:o/r.git"
            return None

        with patch.object(mod, "_run_git", side_effect=fake_git):
            assert mod._get_remote() == ("github.com", "github.com/o/r")

    def test_get_remote_falls_back_to_origin(self, make_render_context):
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})

        def fake_git(*args):
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return None
            if args == ("remote", "get-url", "origin"):
                return "https://gitlab.com/g/p.git"
            return None

        with patch.object(mod, "_run_git", side_effect=fake_git):
            assert mod._get_remote() == ("gitlab.com", "gitlab.com/g/p")

    def test_get_remote_none_when_no_remote(self, make_render_context):
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})
        with patch.object(mod, "_run_git", return_value=None):
            assert mod._get_remote() is None


class TestResolveProvider:
    """Tests for _resolve_provider: explicit override, cache reuse, positive caching."""

    def test_explicit_override_wins(self, make_render_context):
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {"pr_provider": "github"})
        doc = PrCacheDoc.empty()
        with patch.object(mod, "_detect_provider") as detect:
            assert mod._resolve_provider("gitlab.com", doc) == "github"
        detect.assert_not_called()

    def test_cached_provider_reused(self, make_render_context):
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})
        doc = PrCacheDoc(providers={"h": "gitlab"}, entries={})
        with patch.object(mod, "_detect_provider") as detect:
            assert mod._resolve_provider("h", doc) == "gitlab"
        detect.assert_not_called()

    def test_positive_detection_is_cached(self, make_render_context):
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})
        doc = PrCacheDoc.empty()
        with patch.object(mod, "_detect_provider", return_value="github"):
            assert mod._resolve_provider("h", doc) == "github"
        assert doc.providers["h"] == "github"

    def test_give_up_not_cached(self, make_render_context):
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {})
        doc = PrCacheDoc.empty()
        with patch.object(mod, "_detect_provider", return_value=None):
            assert mod._resolve_provider("h", doc) is None
        assert "h" not in doc.providers


class TestGetPr:
    """Tests for _get_pr orchestration: gates, throttle, fetch, error fallback."""

    def _mod(self, make_render_context, tmp_path, config=None):
        ctx = make_render_context(make_input_data(model=make_model_data()), cache_dir=tmp_path, debug=True)
        return GitModule(ctx, config or {})

    def test_show_pr_false_skips_silently(self, make_render_context, tmp_path):
        mod = self._mod(make_render_context, tmp_path, {"show_pr": False})
        with patch.object(mod, "_get_remote") as remote:
            assert mod._get_pr("main", ("synced", 0)) is None
        remote.assert_not_called()
        assert mod._debug_messages == []

    def test_local_only_branch_skips(self, make_render_context, tmp_path):
        mod = self._mod(make_render_context, tmp_path)
        with patch.object(mod, "_get_remote") as remote:
            assert mod._get_pr("main", ("no_upstream", 0)) is None
        remote.assert_not_called()

    def test_no_host_degrades_with_debug(self, make_render_context, tmp_path):
        mod = self._mod(make_render_context, tmp_path)
        with patch.object(mod, "_get_remote", return_value=None):
            assert mod._get_pr("main", ("synced", 0)) is None
        assert any("host" in m for m in mod._debug_messages)

    def test_neither_cli_degrades_with_debug(self, make_render_context, tmp_path):
        mod = self._mod(make_render_context, tmp_path)
        with (
            patch.object(mod, "_get_remote", return_value=("github.com", "github.com/o/r")),
            patch("statuskit.modules.git.shutil.which", return_value=None),
        ):
            assert mod._get_pr("main", ("synced", 0)) is None
        assert any("neither gh nor glab" in m for m in mod._debug_messages)

    def test_provider_give_up_degrades_with_debug(self, make_render_context, tmp_path):
        mod = self._mod(make_render_context, tmp_path)
        with (
            patch.object(mod, "_get_remote", return_value=("scm.corp.example", "scm.corp.example/o/r")),
            patch("statuskit.modules.git.shutil.which", return_value="/bin/x"),
            patch.object(mod, "_resolve_provider", return_value=None),
        ):
            assert mod._get_pr("main", ("synced", 0)) is None
        assert any("resolve provider" in m for m in mod._debug_messages)

    def test_missing_resolved_cli_degrades(self, make_render_context, tmp_path):
        """Provider resolves to gitlab but glab is absent → step-5 degrade."""
        mod = self._mod(make_render_context, tmp_path)

        def which(binary):
            return "/bin/gh" if binary == "gh" else None

        with (
            patch.object(mod, "_get_remote", return_value=("gitlab.com", "gitlab.com/o/r")),
            patch("statuskit.modules.git.shutil.which", side_effect=which),
            patch.object(mod, "_resolve_provider", return_value="gitlab"),
        ):
            assert mod._get_pr("main", ("synced", 0)) is None
        assert any("glab not installed" in m for m in mod._debug_messages)

    def test_success_returns_and_caches(self, make_render_context, tmp_path):
        mod = self._mod(make_render_context, tmp_path)
        found = PrInfo("github", 42, "open", "u")
        with (
            patch.object(mod, "_get_remote", return_value=("github.com", "github.com/o/r")),
            patch("statuskit.modules.git.shutil.which", return_value="/bin/gh"),
            patch.object(mod, "_resolve_provider", return_value="github"),
            patch.object(mod, "_fetch_pr", return_value=(found, None)) as fetch,
        ):
            assert mod._get_pr("main", ("synced", 0)) == found
            fetch.assert_called_once()
        # persisted entry
        entry = mod.cache.load().entries["github.com/o/r\tmain"]
        assert entry.info == found

    def test_throttle_reuses_cached_entry(self, make_render_context, tmp_path):
        mod = self._mod(make_render_context, tmp_path, {"pr_cache_ttl": 300})
        cached = PrInfo("github", 42, "open", "u")
        doc = PrCacheDoc(
            providers={"github.com": "github"},
            entries={"github.com/o/r\tmain": PrCacheEntry(cached, datetime.now(UTC))},
        )
        mod.cache.save(doc)
        with (
            patch.object(mod, "_get_remote", return_value=("github.com", "github.com/o/r")),
            patch("statuskit.modules.git.shutil.which", return_value="/bin/gh"),
            patch.object(mod, "_fetch_pr") as fetch,
        ):
            assert mod._get_pr("main", ("synced", 0)) == cached
            fetch.assert_not_called()

    def test_stale_entry_refetched_after_ttl(self, make_render_context, tmp_path):
        mod = self._mod(make_render_context, tmp_path, {"pr_cache_ttl": 300})
        old = PrInfo("github", 1, "open", "u")
        doc = PrCacheDoc(
            providers={"github.com": "github"},
            entries={"github.com/o/r\tmain": PrCacheEntry(old, datetime.now(UTC) - timedelta(seconds=600))},
        )
        mod.cache.save(doc)
        fresh = PrInfo("github", 1, "merged", "u")
        with (
            patch.object(mod, "_get_remote", return_value=("github.com", "github.com/o/r")),
            patch("statuskit.modules.git.shutil.which", return_value="/bin/gh"),
            patch.object(mod, "_fetch_pr", return_value=(fresh, None)) as fetch,
        ):
            assert mod._get_pr("main", ("synced", 0)) == fresh
            fetch.assert_called_once()

    def test_fetch_error_keeps_stale_and_advances_clock(self, make_render_context, tmp_path):
        mod = self._mod(make_render_context, tmp_path, {"pr_cache_ttl": 300})
        stale = PrInfo("github", 1, "open", "u")
        old_ts = datetime.now(UTC) - timedelta(seconds=600)
        doc = PrCacheDoc(
            providers={"github.com": "github"},
            entries={"github.com/o/r\tmain": PrCacheEntry(stale, old_ts)},
        )
        mod.cache.save(doc)
        with (
            patch.object(mod, "_get_remote", return_value=("github.com", "github.com/o/r")),
            patch("statuskit.modules.git.shutil.which", return_value="/bin/gh"),
            patch.object(mod, "_fetch_pr", return_value=(None, "network down")),
        ):
            assert mod._get_pr("main", ("synced", 0)) == stale
        reloaded = mod.cache.load().entries["github.com/o/r\tmain"]
        assert reloaded.info == stale
        assert reloaded.last_attempt_at > old_ts
        assert any("fetch failed" in m for m in mod._debug_messages)

    def test_no_pr_caches_negative(self, make_render_context, tmp_path):
        mod = self._mod(make_render_context, tmp_path)
        with (
            patch.object(mod, "_get_remote", return_value=("github.com", "github.com/o/r")),
            patch("statuskit.modules.git.shutil.which", return_value="/bin/gh"),
            patch.object(mod, "_resolve_provider", return_value="github"),
            patch.object(mod, "_fetch_pr", return_value=(None, None)),
        ):
            assert mod._get_pr("main", ("synced", 0)) is None
        assert "github.com/o/r\tmain" in mod.cache.load().entries

    def test_throttle_hit_does_not_rewrite_cache(self, make_render_context, tmp_path):
        """Throttled hit reuses the cached PrInfo without an atomic cache rewrite."""
        mod = self._mod(make_render_context, tmp_path, {"pr_cache_ttl": 300})
        cached = PrInfo("github", 42, "open", "u")
        doc = PrCacheDoc(
            providers={"github.com": "github"},
            entries={"github.com/o/r\tmain": PrCacheEntry(cached, datetime.now(UTC))},
        )
        mod.cache.save(doc)
        with (
            patch.object(mod, "_get_remote", return_value=("github.com", "github.com/o/r")),
            patch("statuskit.modules.git.shutil.which", return_value="/bin/gh"),
            patch.object(mod, "_fetch_pr") as fetch,
            patch.object(mod.cache, "save") as save_mock,
        ):
            assert mod._get_pr("main", ("synced", 0)) == cached
            fetch.assert_not_called()
            save_mock.assert_not_called()

    def test_first_fetch_error_no_prior_entry(self, make_render_context, tmp_path):
        """Fetch error with no prior entry persists a negative entry and keeps the git line."""
        mod = self._mod(make_render_context, tmp_path)
        with (
            patch.object(mod, "_get_remote", return_value=("github.com", "github.com/o/r")),
            patch("statuskit.modules.git.shutil.which", return_value="/bin/gh"),
            patch.object(mod, "_resolve_provider", return_value="github"),
            patch.object(mod, "_fetch_pr", return_value=(None, "boom")),
        ):
            assert mod._get_pr("main", ("synced", 0)) is None
        assert any("fetch failed" in m for m in mod._debug_messages)
        entry = mod.cache.load().entries["github.com/o/r\tmain"]
        assert entry.info is None
        assert entry.last_attempt_at is not None

    def test_cache_key_scoped_per_repo(self, make_render_context, tmp_path):
        """Same branch name in two repos on one host must not alias cached PRs (C3)."""
        ctx = make_render_context(make_input_data(model=make_model_data()), cache_dir=tmp_path, debug=True)
        mod = GitModule(ctx, {})
        pr_a = PrInfo("github", 1, "open", "a")
        with (
            patch.object(mod, "_get_remote", return_value=("github.com", "github.com/org/a")),
            patch("statuskit.modules.git.shutil.which", return_value="/bin/gh"),
            patch.object(mod, "_resolve_provider", return_value="github"),
            patch.object(mod, "_fetch_pr", return_value=(pr_a, None)),
        ):
            assert mod._get_pr("feature/login", ("synced", 0)) == pr_a
        pr_b = PrInfo("github", 2, "open", "b")
        with (
            patch.object(mod, "_get_remote", return_value=("github.com", "github.com/org/b")),
            patch("statuskit.modules.git.shutil.which", return_value="/bin/gh"),
            patch.object(mod, "_resolve_provider", return_value="github"),
            patch.object(mod, "_fetch_pr", return_value=(pr_b, None)) as fetch_b,
        ):
            assert mod._get_pr("feature/login", ("synced", 0)) == pr_b  # NOT aliased to repo A
            fetch_b.assert_called_once()


class TestRenderPr:
    """Tests for _render_pr: label, sigil, glyph, color, OSC 8 wrapping."""

    def _mod(self, make_render_context, config=None):
        return GitModule(make_render_context(make_input_data(model=make_model_data())), config or {})

    def test_open_github_token(self, make_render_context, force_color):
        mod = self._mod(make_render_context, {"pr_link": False})
        result = mod._render_pr(PrInfo("github", 42, "open", "u"))
        assert result == colored("PR #42 ●", "green")

    def test_draft_gitlab_token(self, make_render_context, force_color):
        mod = self._mod(make_render_context, {"pr_link": False})
        result = mod._render_pr(PrInfo("gitlab", 7, "draft", "u"))
        assert result == colored("MR !7 ○", "yellow")

    def test_merged_and_closed_colors(self, make_render_context, force_color):
        mod = self._mod(make_render_context, {"pr_link": False})
        assert mod._render_pr(PrInfo("github", 1, "merged", "u")) == colored("PR #1 ✓", "magenta")
        assert mod._render_pr(PrInfo("github", 2, "closed", "u")) == colored("PR #2 ✗", "red")

    def test_osc8_wrapping_when_pr_link_on(self, make_render_context, force_color):
        mod = self._mod(make_render_context, {"pr_link": True})
        result = mod._render_pr(PrInfo("github", 42, "open", "https://x/42"))
        token = colored("PR #42 ●", "green")
        assert result == f"\033]8;;https://x/42\a{token}\033]8;;\a"

    def test_no_osc8_when_url_empty(self, make_render_context, force_color):
        mod = self._mod(make_render_context, {"pr_link": True})
        result = mod._render_pr(PrInfo("github", 42, "open", ""))
        assert result == colored("PR #42 ●", "green")

    def test_unknown_state_returns_none(self, make_render_context):
        mod = self._mod(make_render_context)
        assert mod._render_pr(PrInfo("github", 1, "weird", "u")) is None


class TestRenderStatusLineWithPr:
    """PR token sits between branch and remote status."""

    def test_pr_inserted_before_sync(self, make_render_context, force_color):
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {"pr_link": False})
        result = mod._render_status_line(
            branch="main",
            remote_status=("ahead", 2),
            changes={"staged": 0, "modified": 0, "untracked": 0},
            commit=None,
            pr=PrInfo("github", 42, "open", "u"),
        )
        assert result is not None
        assert result.index("PR #42") < result.index("↑2")

    def test_pr_hidden_when_show_pr_false(self, make_render_context):
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {"show_pr": False})
        result = mod._render_status_line(
            branch="main",
            remote_status=("synced", 0),
            changes={"staged": 0, "modified": 0, "untracked": 0},
            commit=None,
            pr=PrInfo("github", 42, "open", "u"),
        )
        assert result is not None
        assert "PR #42" not in result

    def test_unknown_state_pr_omitted_line_intact(self, make_render_context, force_color):
        """An unrenderable PR (unknown state) is silently dropped; the rest of line 2 stays."""
        mod = GitModule(make_render_context(make_input_data(model=make_model_data())), {"pr_link": False})
        result = mod._render_status_line(
            branch="main",
            remote_status=("ahead", 2),
            changes={"staged": 0, "modified": 0, "untracked": 0},
            commit=None,
            pr=PrInfo("github", 1, "weird", "u"),
        )
        assert result is not None
        assert "PR #1" not in result
        assert "main" in result  # branch still rendered
        assert "↑2" in result  # sync indicator still rendered


class TestRenderWithPr:
    """render() wires _get_pr into line 2 and surfaces debug messages."""

    def test_render_includes_pr(self, make_render_context, force_color):
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/home/user/project", "project_dir": "/home/user/project"},
        )
        mod = GitModule(make_render_context(data), {"pr_link": False})
        with (
            patch.object(mod, "_get_location", return_value={"project": "p", "worktree": None, "subfolder": None}),
            patch.object(mod, "_get_branch", return_value="main"),
            patch.object(mod, "_get_remote_status", return_value=("synced", 0)),
            patch.object(mod, "_get_changes", return_value={"staged": 0, "modified": 0, "untracked": 0}),
            patch.object(mod, "_get_last_commit", return_value=None),
            patch.object(mod, "_get_pr", return_value=PrInfo("github", 42, "open", "u")),
        ):
            result = mod.render()
        assert result is not None
        assert "PR #42" in result.split("\n")[1]

    def test_render_appends_debug_messages(self, make_render_context):
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": "/home/user/project", "project_dir": "/home/user/project"},
        )
        mod = GitModule(make_render_context(data, debug=True), {})

        def fake_get_pr(_branch, _remote):
            mod._note_debug("PR: neither gh nor glab installed")

        with (
            patch.object(mod, "_get_location", return_value={"project": "p", "worktree": None, "subfolder": None}),
            patch.object(mod, "_get_branch", return_value="main"),
            patch.object(mod, "_get_remote_status", return_value=("synced", 0)),
            patch.object(mod, "_get_changes", return_value={"staged": 0, "modified": 0, "untracked": 0}),
            patch.object(mod, "_get_last_commit", return_value=None),
            patch.object(mod, "_get_pr", side_effect=fake_get_pr),
        ):
            result = mod.render()
        assert result is not None
        assert "[git] PR: neither gh nor glab installed" in result
