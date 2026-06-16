"""Tests for flow-find-worktree."""

# ruff: noqa: INP001

import subprocess
from pathlib import Path

from conftest import run_helper

_ENV = {"PATH": "/usr/bin:/bin"}


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, env=_ENV)


def _add_worktree(repo, branch, dirname):
    wt_dir = repo.parent / dirname
    subprocess.run(["git", "worktree", "add", str(wt_dir), "-b", branch], cwd=repo, check=True, env=_ENV)
    return wt_dir


def test_worktree_on_matching_branch_prints_path(git_repo):
    wt_dir = _add_worktree(git_repo, "feature/claude-tools-uaj-in-wt", "wt-match")
    r = run_helper("flow-find-worktree", "claude-tools-uaj", cwd=git_repo)
    assert r.returncode == 0
    assert Path(r.stdout.strip()).resolve() == wt_dir.resolve()


def test_subtask_worktree_not_matched_by_parent_id(git_repo):
    _add_worktree(git_repo, "feature/claude-tools-uaj.9-sub", "wt-subtask")
    r = run_helper("flow-find-worktree", "claude-tools-uaj", cwd=git_repo)
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_docs_type_worktree_matched(git_repo):
    wt_dir = _add_worktree(git_repo, "docs/claude-tools-uaj-notes", "wt-docs")
    r = run_helper("flow-find-worktree", "claude-tools-uaj", cwd=git_repo)
    assert r.returncode == 0
    assert Path(r.stdout.strip()).resolve() == wt_dir.resolve()


def test_no_matching_worktree_prints_nothing(git_repo):
    r = run_helper("flow-find-worktree", "claude-tools-uaj", cwd=git_repo)
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_local_branch_without_worktree_not_printed(git_repo):
    _git(git_repo, "branch", "feature/claude-tools-uaj-local-only")
    r = run_helper("flow-find-worktree", "claude-tools-uaj", cwd=git_repo)
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_worktree_git_failure_exits_2(tmp_path):
    """A `git worktree list` failure must surface (exit 2), not look like 'no worktree'."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git_shim = fake_bin / "git"
    git_shim.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "worktree" ]; then\n'
        '  echo "fatal: simulated worktree failure" >&2\n'
        "  exit 1\n"
        "fi\n"
        "exit 0\n"
    )
    git_shim.chmod(0o755)
    env = {"PATH": f"{fake_bin}:/usr/bin:/bin"}
    r = run_helper("flow-find-worktree", "claude-tools-uaj", env=env)
    assert r.returncode == 2
    assert "simulated worktree failure" in r.stderr


def test_multiple_matching_worktrees_printed_sorted(git_repo):
    wt_b = _add_worktree(git_repo, "feature/claude-tools-uaj-bbb", "wt-bbb")
    wt_a = _add_worktree(git_repo, "fix/claude-tools-uaj-aaa", "wt-aaa")
    r = run_helper("flow-find-worktree", "claude-tools-uaj", cwd=git_repo)
    assert r.returncode == 0
    out = r.stdout.splitlines()
    assert len(out) == 2
    resolved = [str(Path(p).resolve()) for p in out]
    assert resolved == sorted([str(wt_a.resolve()), str(wt_b.resolve())])
