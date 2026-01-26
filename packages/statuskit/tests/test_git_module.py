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
