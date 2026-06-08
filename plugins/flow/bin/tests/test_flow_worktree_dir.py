"""Tests for flow-worktree-dir."""

# ruff: noqa: INP001

from conftest import run_helper


def test_slashes_become_hyphens():
    r = run_helper("flow-worktree-dir", "feature/claude-tools-uaj-bin-helpers")
    assert r.returncode == 0
    assert r.stdout.strip() == ".worktrees/feature-claude-tools-uaj-bin-helpers"


def test_no_arg_exits_nonzero():
    assert run_helper("flow-worktree-dir").returncode != 0
