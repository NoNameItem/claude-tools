"""Integration tests for git module with real git commands.

These tests run against the actual git repository.
Skip with: pytest -m "not integration"
"""

import pytest
from statuskit.modules.git import GitModule

from .factories import make_input_data, make_model_data


@pytest.mark.integration
class TestGitModuleIntegration:
    """Integration tests for GitModule."""

    def test_render_in_real_repo(self, make_render_context):
        """GitModule renders output in actual git repo."""
        data = make_input_data(
            model=make_model_data(),
            workspace={"current_dir": ".", "project_dir": "."},
        )
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        result = mod.render()

        # Should return something since we're in a git repo
        assert result is not None
        # Should have at least one line
        assert len(result) > 0

    def test_branch_detection_real(self, make_render_context):
        """_get_branch returns actual branch name."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        branch = mod._get_branch()

        # Should return something
        assert branch is not None
        assert len(branch) > 0

    def test_changes_detection_real(self, make_render_context):
        """_get_changes returns valid counts."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        changes = mod._get_changes()

        # Should return dict with expected keys
        assert "staged" in changes
        assert "modified" in changes
        assert "untracked" in changes
        # Values should be non-negative
        assert all(v >= 0 for v in changes.values())
