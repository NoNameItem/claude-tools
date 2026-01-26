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
