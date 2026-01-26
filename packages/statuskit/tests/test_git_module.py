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
