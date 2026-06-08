"""Tests for flow-branch-for."""

# ruff: noqa: INP001

from conftest import run_helper


def _issue(issue_type, title):
    import json

    return json.dumps([{"id": "claude-tools-uaj", "issue_type": issue_type, "title": title}])


def test_task_type_maps_to_feature(fake_bd):
    fake_bd.set_show(_issue("task", "Extract repeated bash snippets from flow skills"))
    r = run_helper("flow-branch-for", "claude-tools-uaj", env=fake_bd.env)
    assert r.returncode == 0
    assert r.stdout.strip() == "feature/claude-tools-uaj-extract-repeated-bash-snippets-from"


def test_bug_type_maps_to_fix(fake_bd):
    fake_bd.set_show(_issue("bug", "Login error!"))
    r = run_helper("flow-branch-for", "claude-tools-uaj", env=fake_bd.env)
    assert r.stdout.strip() == "fix/claude-tools-uaj-login-error"


def test_chore_type_maps_to_chore(fake_bd):
    fake_bd.set_show(_issue("chore", "Update deps"))
    r = run_helper("flow-branch-for", "claude-tools-uaj", env=fake_bd.env)
    assert r.stdout.strip() == "chore/claude-tools-uaj-update-deps"


def test_unknown_type_defaults_to_feature_with_warning(fake_bd):
    fake_bd.set_show(_issue("molecule", "Weird thing"))
    r = run_helper("flow-branch-for", "claude-tools-uaj", env=fake_bd.env)
    assert r.stdout.strip() == "feature/claude-tools-uaj-weird-thing"
    assert "molecule" in r.stderr
