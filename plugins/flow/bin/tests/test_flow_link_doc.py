"""Tests for flow-link-doc."""

# ruff: noqa: INP001

import json

from conftest import run_helper


def _desc(description):
    return json.dumps([{"id": "claude-tools-uaj", "description": description}])


def test_append_when_absent(fake_bd):
    fake_bd.set_show(_desc("Some body text."))
    r = run_helper("flow-link-doc", "claude-tools-uaj", "Git", "feature/x", env=fake_bd.env)
    assert r.returncode == 0
    assert fake_bd.captured_description() == "Some body text.\n\nGit: feature/x"


def test_replace_when_present(fake_bd):
    fake_bd.set_show(_desc("Body.\n\nGit: feature/old"))
    run_helper("flow-link-doc", "claude-tools-uaj", "Git", "feature/new", env=fake_bd.env)
    assert fake_bd.captured_description() == "Body.\n\nGit: feature/new"


def test_remove_with_empty_value(fake_bd):
    fake_bd.set_show(_desc("Body.\n\nPlan: docs/superpowers/plans/p.md"))
    run_helper("flow-link-doc", "claude-tools-uaj", "Plan", "", env=fake_bd.env)
    assert fake_bd.captured_description() == "Body."


def test_invalid_key_exits_1(fake_bd):
    fake_bd.set_show(_desc("Body."))
    r = run_helper("flow-link-doc", "claude-tools-uaj", "Bogus", "v", env=fake_bd.env)
    assert r.returncode == 1
    assert fake_bd.captured_description() is None  # no bd update happened
