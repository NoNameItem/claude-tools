"""Tests for bd-continue.py."""

# ruff: noqa: INP001, S101, PLR2004

import importlib.util
from pathlib import Path

# Import bd-continue.py as module (hyphenated filename)
_spec = importlib.util.spec_from_file_location("bd_continue", Path(__file__).parent / "bd-continue.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

find_leaf_in_progress = _mod.find_leaf_in_progress
format_task_line = _mod.format_task_line
parse_graphs = _mod.parse_graphs


def issue(
    task_id: str,
    title: str = "",
    status: str = "open",
    priority: int = 2,
    issue_type: str = "task",
    labels: list[str] | None = None,
    owner: str = "",
) -> dict:
    """Create an issue dict for graph JSON."""
    return {
        "id": task_id,
        "title": title or task_id,
        "status": status,
        "priority": priority,
        "issue_type": issue_type,
        "labels": labels or [],
        "owner": owner,
    }


def dep(child_id: str, parent_id: str) -> dict:
    """Create a parent-child dependency dict."""
    return {"type": "parent-child", "issue_id": child_id, "depends_on_id": parent_id}


def make_graph(issues: list[dict], deps: list[dict] | None = None) -> list[dict]:
    """Create a graph JSON structure."""
    return [{"Issues": issues, "Dependencies": deps or []}]


class TestFindLeafInProgress:
    def test_single_in_progress_task(self):
        """A single in_progress task with no children is a leaf."""
        tasks = parse_graphs(
            make_graph(
                [
                    issue("t-1", title="Task 1", status="in_progress", owner="alice"),
                ]
            )
        )
        result = find_leaf_in_progress(tasks, owner=None)
        assert len(result) == 1
        assert result[0].id == "t-1"

    def test_filters_non_in_progress(self):
        """Only in_progress tasks are returned."""
        tasks = parse_graphs(
            make_graph(
                [
                    issue("t-1", title="Open task", status="open"),
                    issue("t-2", title="In progress", status="in_progress"),
                    issue("t-3", title="Closed task", status="closed"),
                ]
            )
        )
        result = find_leaf_in_progress(tasks, owner=None)
        assert len(result) == 1
        assert result[0].id == "t-2"

    def test_parent_not_leaf_when_child_in_progress(self):
        """A parent is NOT a leaf if any child is in_progress."""
        tasks = parse_graphs(
            make_graph(
                [
                    issue("parent", title="Parent", status="in_progress", owner="alice"),
                    issue("child", title="Child", status="in_progress", owner="alice"),
                ],
                [dep("child", "parent")],
            )
        )
        result = find_leaf_in_progress(tasks, owner=None)
        assert len(result) == 1
        assert result[0].id == "child"

    def test_parent_is_leaf_when_children_not_in_progress(self):
        """A parent IS a leaf if no children are in_progress."""
        tasks = parse_graphs(
            make_graph(
                [
                    issue("parent", title="Parent", status="in_progress"),
                    issue("child", title="Child", status="open"),
                ],
                [dep("child", "parent")],
            )
        )
        result = find_leaf_in_progress(tasks, owner=None)
        assert len(result) == 1
        assert result[0].id == "parent"

    def test_filter_by_owner(self):
        """Only tasks matching owner are returned."""
        tasks = parse_graphs(
            make_graph(
                [
                    issue("t-1", status="in_progress", owner="alice"),
                    issue("t-2", status="in_progress", owner="bob"),
                ]
            )
        )
        result = find_leaf_in_progress(tasks, owner="alice")
        assert len(result) == 1
        assert result[0].id == "t-1"

    def test_owner_none_returns_all(self):
        """owner=None returns all in_progress leaf tasks."""
        tasks = parse_graphs(
            make_graph(
                [
                    issue("t-1", status="in_progress", owner="alice"),
                    issue("t-2", status="in_progress", owner="bob"),
                ]
            )
        )
        result = find_leaf_in_progress(tasks, owner=None)
        assert len(result) == 2

    def test_deep_hierarchy_finds_deepest_leaf(self):
        """In a chain grandparent→parent→child, only the deepest in_progress is leaf."""
        tasks = parse_graphs(
            make_graph(
                [
                    issue("gp", status="in_progress"),
                    issue("p", status="in_progress"),
                    issue("c", status="in_progress"),
                ],
                [dep("p", "gp"), dep("c", "p")],
            )
        )
        result = find_leaf_in_progress(tasks, owner=None)
        assert len(result) == 1
        assert result[0].id == "c"

    def test_no_in_progress_returns_empty(self):
        """No in_progress tasks → empty list."""
        tasks = parse_graphs(
            make_graph(
                [
                    issue("t-1", status="open"),
                    issue("t-2", status="closed"),
                ]
            )
        )
        result = find_leaf_in_progress(tasks, owner=None)
        assert len(result) == 0

    def test_sorted_by_priority(self):
        """Results are sorted by priority (lowest number first)."""
        tasks = parse_graphs(
            make_graph(
                [
                    issue("t-low", status="in_progress", priority=3),
                    issue("t-high", status="in_progress", priority=1),
                    issue("t-med", status="in_progress", priority=2),
                ]
            )
        )
        result = find_leaf_in_progress(tasks, owner=None)
        assert [t.id for t in result] == ["t-high", "t-med", "t-low"]


class TestFormatTaskLine:
    def test_basic_format(self):
        """Format includes all fields separated by pipes."""
        tasks = parse_graphs(
            make_graph(
                [
                    issue(
                        "t-1", title="My Task", status="in_progress", priority=2, issue_type="feature", labels=["flow"]
                    ),
                ]
            )
        )
        line = format_task_line(tasks["t-1"])
        assert line == "t-1|feature|My Task|P2|flow"

    def test_no_labels(self):
        """Empty labels → empty last field."""
        tasks = parse_graphs(
            make_graph(
                [
                    issue("t-1", title="Task", status="in_progress", labels=[]),
                ]
            )
        )
        line = format_task_line(tasks["t-1"])
        assert line == "t-1|task|Task|P2|"

    def test_multiple_labels_uses_first(self):
        """Multiple labels → only first label in output."""
        tasks = parse_graphs(
            make_graph(
                [
                    issue("t-1", title="Task", status="in_progress", labels=["flow", "statuskit"]),
                ]
            )
        )
        line = format_task_line(tasks["t-1"])
        assert line == "t-1|task|Task|P2|flow"
