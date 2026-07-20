"""Lock in parser compatibility with real bd 1.0.5 --json fixtures (Task 1)."""

# ruff: noqa: INP001  # bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

BIN = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


def _load(name, attrs):
    """Import an extension-less helper as a module; return selected attrs."""
    path = BIN / name
    mod_name = name.replace("-", "_")
    spec = importlib.util.spec_from_file_location(mod_name, path, loader=SourceFileLoader(mod_name, str(path)))
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return {a: getattr(mod, a) for a in attrs}


GRAPH = json.loads((FIXTURES / "graph-1.0.5.json").read_text())
SHOW = json.loads((FIXTURES / "show-1.0.5.json").read_text())
SHOW_FEATURE = SHOW[0] if isinstance(SHOW, list) else SHOW


def _by_title(tasks):
    return {t.title: t for t in tasks.values()}


def test_find_leaf_parses_all_six_issues():
    m = _load("flow-find-leaf", ["parse_graphs"])
    titles = {t.title for t in m["parse_graphs"](GRAPH).values()}
    assert {
        "Fixture epic",
        "Fixture feature",
        "Fixture task",
        "Fixture bug",
        "Fixture chore",
        "Fixture decision",
    } <= titles


def test_find_leaf_reads_assignee_and_labels_from_graph():
    m = _load("flow-find-leaf", ["parse_graphs"])
    feature = _by_title(m["parse_graphs"](GRAPH))["Fixture feature"]
    assert feature.assignee == "fixtureuser"
    assert "flow" in feature.labels


def test_find_leaf_captures_parent_child():
    m = _load("flow-find-leaf", ["parse_graphs"])
    by = _by_title(m["parse_graphs"](GRAPH))
    assert by["Fixture feature"].parent_id == by["Fixture epic"].id


def test_find_leaf_renders_decision_from_real_graph():
    m = _load("flow-find-leaf", ["parse_graphs", "format_task_line"])
    decision = _by_title(m["parse_graphs"](GRAPH))["Fixture decision"]
    assert m["format_task_line"](decision, 1).startswith("1. [D]")


def test_task_tree_marks_blocked_from_blocks_edge():
    m = _load("flow-task-tree", ["parse_graphs"])
    by = _by_title(m["parse_graphs"](GRAPH))
    assert by["Fixture task"].is_blocked is True


def test_task_card_renders_show_with_description_and_links():
    m = _load("flow-task-card", ["render_card"])
    rendered = m["render_card"](SHOW_FEATURE)  # render_card returns a single string
    assert "Fixture feature" in rendered  # title
    assert "┌─ Feature " in rendered  # type word in the top border, not the description text
    assert "fx-demo-design.md" in rendered  # Design: link shown in LINKS
    assert "feature/fx-demo-branch" not in rendered  # Git: is intentionally hidden from the card


def test_show_has_fields_branch_for_and_current_task_read():
    assert SHOW_FEATURE["issue_type"] == "feature"
    assert SHOW_FEATURE["title"] == "Fixture feature"
    assert isinstance(SHOW_FEATURE["description"], str)
