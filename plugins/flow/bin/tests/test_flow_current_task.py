"""Tests for flow-current-task."""

# ruff: noqa: INP001

import json
import subprocess

from conftest import run_helper


def _checkout(repo, branch):
    subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=repo, check=True, env={"PATH": "/usr/bin:/bin"})


def test_match_mode_true_for_own_branch(git_repo):
    _checkout(git_repo, "feature/claude-tools-uaj-bin-helpers")
    assert run_helper("flow-current-task", "claude-tools-uaj", cwd=git_repo).returncode == 0


def test_match_mode_rejects_subtask_false_positive(git_repo):
    _checkout(git_repo, "feature/claude-tools-5dl.9-task-selection")
    # the parent id must NOT match a subtask branch (the latent bug we fix)
    assert run_helper("flow-current-task", "claude-tools-5dl", cwd=git_repo).returncode == 1
    # the exact subtask id matches
    assert run_helper("flow-current-task", "claude-tools-5dl.9", cwd=git_repo).returncode == 0


def test_match_mode_false_on_master(git_repo):
    assert run_helper("flow-current-task", "claude-tools-uaj", cwd=git_repo).returncode == 1


def test_extract_mode_uses_project_prefix(git_repo, fake_bd):
    _checkout(git_repo, "feature/claude-tools-c7b-git-module")
    fake_bd.set_show(json.dumps([{"id": "claude-tools-5dl"}]))  # bd list -> prefix claude-tools
    r = run_helper("flow-current-task", cwd=git_repo, env={**fake_bd.env, "PATH": "/usr/bin:/bin"})
    assert r.returncode == 0
    assert r.stdout.strip() == "claude-tools-c7b"


def test_extract_mode_empty_off_task_branch(git_repo, fake_bd):
    fake_bd.set_show(json.dumps([{"id": "claude-tools-5dl"}]))
    r = run_helper("flow-current-task", cwd=git_repo, env={**fake_bd.env, "PATH": "/usr/bin:/bin"})
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_match_mode_docs_branch(git_repo):
    _checkout(git_repo, "docs/claude-tools-abc-readme")
    assert run_helper("flow-current-task", "claude-tools-abc", cwd=git_repo).returncode == 0
