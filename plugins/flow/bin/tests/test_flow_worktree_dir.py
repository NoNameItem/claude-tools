"""Tests for flow-worktree-dir."""

# bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

import json

from conftest import run_helper


def _issue(task_id, title):
    return json.dumps([{"id": task_id, "issue_type": "task", "title": title}])


def test_strips_issue_prefix(fake_bd):
    fake_bd.set_show(_issue("claude-tools-elf.28", "flow-worktree-dir: shorten generated worktree directory names"))
    fake_bd.set_issue_prefix("claude-tools")
    r = run_helper("flow-worktree-dir", "claude-tools-elf.28", env=fake_bd.env)
    assert r.returncode == 0
    assert r.stdout == ".worktrees/elf.28-flow-worktree-dir-shorten-generated\n"


def test_subtask_id_keeps_dots(fake_bd):
    fake_bd.set_show(_issue("claude-tools-5dl.9.2", "Config template generation and CLI"))
    fake_bd.set_issue_prefix("claude-tools")
    r = run_helper("flow-worktree-dir", "claude-tools-5dl.9.2", env=fake_bd.env)
    assert r.returncode == 0
    assert r.stdout.strip() == ".worktrees/5dl.9.2-config-template-generation-and-cli"


def test_id_without_issue_prefix_keeps_full_id_with_warning(fake_bd):
    fake_bd.set_show(_issue("claude-tools-uaj", "Update deps"))
    fake_bd.set_issue_prefix("other")
    r = run_helper("flow-worktree-dir", "claude-tools-uaj", env=fake_bd.env)
    assert r.returncode == 0
    assert r.stdout.strip() == ".worktrees/claude-tools-uaj-update-deps"
    assert "issue prefix" in r.stderr


def test_unset_issue_prefix_keeps_full_id_with_warning(fake_bd):
    fake_bd.set_show(_issue("claude-tools-uaj", "Update deps"))
    fake_bd.set_issue_prefix("")
    r = run_helper("flow-worktree-dir", "claude-tools-uaj", env=fake_bd.env)
    assert r.returncode == 0
    assert r.stdout.strip() == ".worktrees/claude-tools-uaj-update-deps"
    assert "issue_prefix" in r.stderr


def test_failing_config_keeps_full_id_with_warning(fake_bd):
    fake_bd.set_show(_issue("claude-tools-uaj", "Update deps"))
    fake_bd.set_issue_prefix(None)
    r = run_helper("flow-worktree-dir", "claude-tools-uaj", env=fake_bd.env)
    assert r.returncode == 0
    assert r.stdout.strip() == ".worktrees/claude-tools-uaj-update-deps"
    assert "issue_prefix" in r.stderr


def test_empty_slug_uses_short_id(fake_bd):
    fake_bd.set_show(_issue("claude-tools-uaj", ""))
    fake_bd.set_issue_prefix("claude-tools")
    r = run_helper("flow-worktree-dir", "claude-tools-uaj", env=fake_bd.env)
    assert r.returncode == 0
    assert r.stdout.strip() == ".worktrees/uaj"
    assert "empty slug" in r.stderr


def test_slug_matches_flow_branch_for(fake_bd):
    fake_bd.set_show(_issue("claude-tools-uaj", "Extract repeated bash snippets from flow skills"))
    fake_bd.set_issue_prefix("claude-tools")
    branch = run_helper("flow-branch-for", "claude-tools-uaj", env=fake_bd.env).stdout.strip()
    wt = run_helper("flow-worktree-dir", "claude-tools-uaj", env=fake_bd.env).stdout.strip()
    assert branch.removeprefix("feature/claude-tools-uaj-") == wt.removeprefix(".worktrees/uaj-")
    assert wt == ".worktrees/uaj-extract-repeated-bash-snippets-from"


def test_output_ignores_an_existing_directory(fake_bd, tmp_path):
    (tmp_path / ".worktrees" / "uaj-update-deps").mkdir(parents=True)
    fake_bd.set_show(_issue("claude-tools-uaj", "Update deps"))
    fake_bd.set_issue_prefix("claude-tools")
    r = run_helper("flow-worktree-dir", "claude-tools-uaj", cwd=tmp_path, env=fake_bd.env)
    assert r.returncode == 0
    assert r.stdout.strip() == ".worktrees/uaj-update-deps"


def test_task_not_found_exits_1(fake_bd):
    fake_bd.set_show("[]")
    fake_bd.set_issue_prefix("claude-tools")
    r = run_helper("flow-worktree-dir", "claude-tools-uaj", env=fake_bd.env)
    assert r.returncode == 1
    assert r.stdout == ""


def test_bd_error_exits_2_with_empty_stdout():
    r = run_helper("flow-worktree-dir", "claude-tools-uaj", env={"BD_BIN": "/usr/bin/false", "PATH": "/usr/bin:/bin"})
    assert r.returncode == 2
    assert r.stdout == ""


def test_no_arg_exits_nonzero():
    assert run_helper("flow-worktree-dir").returncode != 0
