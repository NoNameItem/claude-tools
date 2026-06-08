"""Tests for flow-find-doc."""

# ruff: noqa: INP001

import os

from conftest import run_helper


def _touch(path, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    os.utime(path, (mtime, mtime))


def test_design_picks_newest_across_both_dirs(tmp_path):
    _touch(tmp_path / "docs/superpowers/specs/a.md", 100)
    _touch(tmp_path / "docs/plans/b.md", 200)  # newer, in the legacy dir
    r = run_helper("flow-find-doc", "design", cwd=tmp_path)
    assert r.returncode == 0
    assert r.stdout.strip() == "docs/plans/b.md"


def test_plan_searches_plans_dirs_not_specs(tmp_path):
    _touch(tmp_path / "docs/superpowers/specs/spec.md", 999)  # should be ignored for 'plan'
    _touch(tmp_path / "docs/superpowers/plans/p.md", 100)
    r = run_helper("flow-find-doc", "plan", cwd=tmp_path)
    assert r.stdout.strip() == "docs/superpowers/plans/p.md"


def test_no_docs_prints_nothing_exit_0(tmp_path):
    r = run_helper("flow-find-doc", "design", cwd=tmp_path)
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_bad_kind_exits_nonzero(tmp_path):
    r = run_helper("flow-find-doc", "bogus", cwd=tmp_path)
    assert r.returncode != 0
