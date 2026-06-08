"""Tests for flow-find-branches."""

# ruff: noqa: INP001

import subprocess

from conftest import run_helper

_ENV = {"PATH": "/usr/bin:/bin"}


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, env=_ENV)


def test_matches_local_and_excludes_subtask_and_unrelated(git_repo):
    _git(git_repo, "branch", "feature/claude-tools-uaj-bin-helpers")
    _git(git_repo, "branch", "feature/claude-tools-5dl.9-other")  # different id, must not match uaj
    _git(git_repo, "branch", "chore/unrelated-thing")
    r = run_helper("flow-find-branches", "claude-tools-uaj", cwd=git_repo)
    assert r.returncode == 0
    assert "feature/claude-tools-uaj-bin-helpers\tlocal" in r.stdout
    assert "5dl.9" not in r.stdout
    assert "unrelated" not in r.stdout


def test_no_matches_prints_nothing(git_repo):
    r = run_helper("flow-find-branches", "claude-tools-zzz", cwd=git_repo)
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_remote_branch_reported_as_remote(git_repo):
    ref_dir = git_repo / ".git" / "refs" / "remotes" / "origin" / "feature"
    ref_dir.mkdir(parents=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=git_repo, capture_output=True, text=True, check=True, env=_ENV
    ).stdout.strip()
    (ref_dir / "claude-tools-uaj-remote-only").write_text(sha + "\n")
    r = run_helper("flow-find-branches", "claude-tools-uaj", cwd=git_repo)
    assert r.returncode == 0
    assert "feature/claude-tools-uaj-remote-only\tremote" in r.stdout


def test_worktree_branch_takes_precedence_over_local(git_repo):
    branch = "feature/claude-tools-uaj-in-wt"
    wt_dir = git_repo.parent / "wt-test"
    subprocess.run(["git", "worktree", "add", str(wt_dir), "-b", branch], cwd=git_repo, check=True, env=_ENV)
    r = run_helper("flow-find-branches", "claude-tools-uaj", cwd=git_repo)
    assert r.returncode == 0
    assert f"{branch}\tworktree" in r.stdout
    assert f"{branch}\tlocal" not in r.stdout
