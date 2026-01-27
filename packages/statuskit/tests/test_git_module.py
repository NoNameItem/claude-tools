"""Tests for statuskit.modules.git."""

import subprocess
from unittest.mock import patch

from statuskit.modules.git import GitModule

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

    def test_format_commit_age_relative(self, make_render_context):
        """_format_commit_age keeps relative format as-is."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"commit_age_format": "relative"})

        result = mod._format_commit_age("2 hours ago")
        assert result == "2 hours ago"

    def test_format_commit_age_compact(self, make_render_context):
        """_format_commit_age converts to compact format."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"commit_age_format": "compact"})

        assert mod._format_commit_age("2 hours ago") == "2h"
        assert mod._format_commit_age("5 minutes ago") == "5m"
        assert mod._format_commit_age("3 days ago") == "3d"
        assert mod._format_commit_age("2 weeks ago") == "2w"
        assert mod._format_commit_age("4 months ago") == "4mo"
        assert mod._format_commit_age("1 year ago") == "1y"
        assert mod._format_commit_age("10 seconds ago") == "10s"

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
        """render returns None when not in git repo."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        with patch.object(mod, "_get_branch") as mock_branch:
            mock_branch.return_value = None
            result = mod.render()

        assert result is None

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
        ):
            mock_loc.return_value = {"project": "project", "worktree": None, "subfolder": None}
            mock_branch.return_value = "main"

            result = mod.render()

        assert result is None
