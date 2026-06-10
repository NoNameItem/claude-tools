"""Tests for flow-actor."""

# ruff: noqa: INP001

import subprocess

from conftest import run_helper

NO_GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def set_repo_user_name(repo, name):
    subprocess.run(
        ["git", "config", "user.name", name],
        cwd=repo,
        check=True,
        env=NO_GIT_ENV,
    )


def test_bd_actor_takes_precedence(git_repo):
    set_repo_user_name(git_repo, "carol")
    r = run_helper("flow-actor", cwd=git_repo, env={**NO_GIT_ENV, "BD_ACTOR": "alice", "USER": "bob"})
    assert r.returncode == 0
    assert r.stdout.strip() == "alice"


def test_git_user_name_when_no_bd_actor(git_repo):
    set_repo_user_name(git_repo, "carol")
    r = run_helper("flow-actor", cwd=git_repo, env={**NO_GIT_ENV, "USER": "bob"})
    assert r.returncode == 0
    assert r.stdout.strip() == "carol"


def test_user_fallback_when_no_git_name(tmp_path):
    r = run_helper("flow-actor", cwd=tmp_path, env={**NO_GIT_ENV, "USER": "bob"})
    assert r.returncode == 0
    assert r.stdout.strip() == "bob"


def test_blank_bd_actor_falls_through(tmp_path):
    r = run_helper("flow-actor", cwd=tmp_path, env={**NO_GIT_ENV, "BD_ACTOR": "  ", "USER": "bob"})
    assert r.stdout.strip() == "bob"


def test_no_identity_prints_nothing_exits_1(tmp_path):
    r = run_helper("flow-actor", cwd=tmp_path, env=NO_GIT_ENV)
    assert r.returncode == 1
    assert r.stdout == ""
