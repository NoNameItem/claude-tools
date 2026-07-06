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


def test_replace_preserves_sibling_link(fake_bd):
    fake_bd.set_show(_desc("Body.\n\nDesign: docs/old.md\n\nPlan: docs/p.md"))
    run_helper("flow-link-doc", "claude-tools-uaj", "Design", "docs/new.md", env=fake_bd.env)
    desc = fake_bd.captured_description()
    assert "Design: docs/new.md" in desc
    assert "Plan: docs/p.md" in desc


def test_append_adds_second_line(fake_bd):
    fake_bd.set_show(_desc("Body.\n\nGit: feature/a"))
    r = run_helper("flow-link-doc", "claude-tools-uaj", "Git", "feature/b", "--append", env=fake_bd.env)
    assert r.returncode == 0
    desc = fake_bd.captured_description()
    assert "Git: feature/a" in desc
    assert "Git: feature/b" in desc


def test_append_is_noop_when_value_present(fake_bd):
    fake_bd.set_show(_desc("Body.\n\nGit: feature/a"))
    r = run_helper("flow-link-doc", "claude-tools-uaj", "Git", "feature/a", "--append", env=fake_bd.env)
    assert r.returncode == 0
    assert fake_bd.captured_description() is None  # already recorded → no bd update


def test_append_dedupes_by_value_ignoring_label(fake_bd):
    fake_bd.set_show(_desc("Body.\n\nGit (statuskit): feature/a"))
    r = run_helper(
        "flow-link-doc", "claude-tools-uaj", "Git", "feature/a", "--append", "--label", "flow", env=fake_bd.env
    )
    assert r.returncode == 0
    assert fake_bd.captured_description() is None  # same value, different label → still no-op


def test_label_written_in_parens(fake_bd):
    fake_bd.set_show(_desc("Body."))
    run_helper(
        "flow-link-doc", "claude-tools-uaj", "Git", "feature/x", "--append", "--label", "statuskit", env=fake_bd.env
    )
    assert fake_bd.captured_description() == "Body.\n\nGit (statuskit): feature/x"


def test_replace_latest_replaces_last_matching_line(fake_bd):
    fake_bd.set_show(_desc("Body.\n\nDesign: a.md\n\nDesign: b.md"))
    run_helper("flow-link-doc", "claude-tools-uaj", "Design", "c.md", "--replace-latest", env=fake_bd.env)
    desc = fake_bd.captured_description()
    assert "Design: a.md" in desc  # earlier design kept
    assert "Design: b.md" not in desc  # latest replaced
    assert "Design: c.md" in desc


def test_replace_latest_appends_when_absent(fake_bd):
    fake_bd.set_show(_desc("Body."))
    run_helper("flow-link-doc", "claude-tools-uaj", "Design", "c.md", "--replace-latest", env=fake_bd.env)
    assert fake_bd.captured_description() == "Body.\n\nDesign: c.md"


def test_replace_latest_with_label(fake_bd):
    fake_bd.set_show(_desc("Body.\n\nDesign: a.md"))
    run_helper(
        "flow-link-doc", "claude-tools-uaj", "Design", "b.md", "--replace-latest", "--label", "rework", env=fake_bd.env
    )
    assert fake_bd.captured_description() == "Body.\n\nDesign (rework): b.md"


def test_default_replace_matches_labeled_line(fake_bd):
    fake_bd.set_show(_desc("Body.\n\nPlan (wip): old.md"))
    run_helper("flow-link-doc", "claude-tools-uaj", "Plan", "new.md", env=fake_bd.env)
    assert fake_bd.captured_description() == "Body.\n\nPlan: new.md"


def test_remove_ignores_label(fake_bd):
    fake_bd.set_show(_desc("Body.\n\nPlan (wip): p.md"))
    run_helper("flow-link-doc", "claude-tools-uaj", "Plan", "", env=fake_bd.env)
    assert fake_bd.captured_description() == "Body."


def test_remove_deletes_all_matching_lines(fake_bd):
    fake_bd.set_show(_desc("Body.\n\nGit: feature/a\nGit (flow): feature/b"))
    run_helper("flow-link-doc", "claude-tools-uaj", "Git", "", env=fake_bd.env)
    assert fake_bd.captured_description() == "Body."


def test_append_and_replace_latest_are_mutually_exclusive(fake_bd):
    fake_bd.set_show(_desc("Body."))
    r = run_helper("flow-link-doc", "claude-tools-uaj", "Git", "x", "--append", "--replace-latest", env=fake_bd.env)
    assert r.returncode == 2  # argparse error
    assert fake_bd.captured_description() is None


def test_default_replace_keeps_parens_in_value(fake_bd):
    fake_bd.set_show(_desc("Body.\n\nGit: v1 (old)"))
    run_helper("flow-link-doc", "claude-tools-uaj", "Git", "v2", env=fake_bd.env)
    assert fake_bd.captured_description() == "Body.\n\nGit: v2"


def test_replace_latest_targets_labeled_last_line(fake_bd):
    fake_bd.set_show(_desc("Body.\n\nDesign: a.md\n\nDesign (rework): b.md"))
    run_helper("flow-link-doc", "claude-tools-uaj", "Design", "c.md", "--replace-latest", env=fake_bd.env)
    desc = fake_bd.captured_description()
    assert "Design: a.md" in desc  # earlier unlabeled design kept
    assert "b.md" not in desc  # latest (labeled) replaced
    assert "Design: c.md" in desc
