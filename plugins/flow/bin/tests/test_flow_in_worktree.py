"""Tests for flow-in-worktree."""

# ruff: noqa: INP001  # bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

from conftest import run_helper


def test_inside_worktree_exits_0(tmp_path):
    wt = tmp_path / ".worktrees" / "feature-x"
    wt.mkdir(parents=True)
    assert run_helper("flow-in-worktree", cwd=wt).returncode == 0


def test_outside_worktree_exits_1(tmp_path):
    assert run_helper("flow-in-worktree", cwd=tmp_path).returncode == 1
