"""Tests for flow-find-leaf."""

# ruff: noqa: INP001  # bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

from conftest import run_helper

_HELPER = Path(__file__).parent.parent / "flow-find-leaf"
_spec = importlib.util.spec_from_file_location(
    "flow_find_leaf", _HELPER, loader=SourceFileLoader("flow_find_leaf", str(_HELPER))
)
if _spec is None or _spec.loader is None:
    msg = "Unable to load flow-find-leaf for tests"
    raise ImportError(msg)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

find_leaf_in_progress = _mod.find_leaf_in_progress
format_task_line = _mod.format_task_line
group_tasks = _mod.group_tasks
parse_graphs = _mod.parse_graphs
render = _mod.render
select_tasks = _mod.select_tasks

NO_GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def issue(
    task_id: str,
    title: str = "",
    status: str = "open",
    priority: int = 2,
    issue_type: str = "task",
    labels: list[str] | None = None,
    assignee: str | None = None,
) -> dict:
    """Create an issue dict for graph JSON. assignee=None mimics JSON null."""
    return {
        "id": task_id,
        "title": title or task_id,
        "status": status,
        "priority": priority,
        "issue_type": issue_type,
        "labels": labels or [],
        "assignee": assignee,
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
        tasks = parse_graphs(make_graph([issue("t-1", title="Task 1", status="in_progress", assignee="alice")]))
        result = find_leaf_in_progress(tasks)
        assert [t.id for t in result] == ["t-1"]

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
        result = find_leaf_in_progress(tasks)
        assert [t.id for t in result] == ["t-2"]

    def test_parent_not_leaf_when_child_in_progress(self):
        """A parent is NOT a leaf if any child is in_progress."""
        tasks = parse_graphs(
            make_graph(
                [
                    issue("parent", status="in_progress"),
                    issue("child", status="in_progress"),
                ],
                [dep("child", "parent")],
            )
        )
        result = find_leaf_in_progress(tasks)
        assert [t.id for t in result] == ["child"]

    def test_parent_is_leaf_when_children_not_in_progress(self):
        """A parent IS a leaf if no children are in_progress."""
        tasks = parse_graphs(
            make_graph(
                [
                    issue("parent", status="in_progress"),
                    issue("child", status="open"),
                ],
                [dep("child", "parent")],
            )
        )
        result = find_leaf_in_progress(tasks)
        assert [t.id for t in result] == ["parent"]

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
        result = find_leaf_in_progress(tasks)
        assert [t.id for t in result] == ["c"]

    def test_no_in_progress_returns_empty(self):
        """No in_progress tasks → empty list."""
        tasks = parse_graphs(make_graph([issue("t-1", status="open"), issue("t-2", status="closed")]))
        assert find_leaf_in_progress(tasks) == []

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
        result = find_leaf_in_progress(tasks)
        assert [t.id for t in result] == ["t-high", "t-med", "t-low"]


class TestParseAssignee:
    def test_json_null_assignee_becomes_empty_string(self):
        """assignee: null in JSON → ''."""
        tasks = parse_graphs(make_graph([issue("t-1", status="in_progress", assignee=None)]))
        assert tasks["t-1"].assignee == ""

    def test_missing_assignee_key_becomes_empty_string(self):
        """Real bd JSON omits assignee when null — key absent → ''."""
        iss = issue("t-1", status="in_progress")
        del iss["assignee"]
        tasks = parse_graphs(make_graph([iss]))
        assert tasks["t-1"].assignee == ""

    def test_assignee_preserved(self):
        tasks = parse_graphs(make_graph([issue("t-1", status="in_progress", assignee="alice")]))
        assert tasks["t-1"].assignee == "alice"


def _leaves(assignee_map: dict[str, str | None]) -> list:
    """Build sorted leaf tasks from {task_id: assignee}."""
    issues = [issue(tid, status="in_progress", assignee=a) for tid, a in assignee_map.items()]
    return find_leaf_in_progress(parse_graphs(make_graph(issues)))


class TestSelectTasks:
    def test_default_keeps_mine_and_unassigned(self):
        tasks = _leaves({"t-mine": "alice", "t-none": None, "t-other": "bob"})
        result = select_tasks(tasks, "alice", show_all=False)
        assert sorted(t.id for t in result) == ["t-mine", "t-none"]

    def test_all_keeps_everything(self):
        tasks = _leaves({"t-mine": "alice", "t-none": None, "t-other": "bob"})
        result = select_tasks(tasks, "alice", show_all=True)
        assert len(result) == 3

    def test_no_actor_keeps_everything(self):
        """Identity unavailable → degrade to --all behavior."""
        tasks = _leaves({"t-mine": "alice", "t-other": "bob"})
        result = select_tasks(tasks, None, show_all=False)
        assert len(result) == 2


class TestGroupTasks:
    def test_group_order_mine_unassigned_others_alphabetical(self):
        tasks = _leaves({"t-z": "zoe", "t-mine": "alice", "t-none": None, "t-b": "bob"})
        groups = group_tasks(tasks, "alice")
        assert [header for header, _ in groups] == [
            "Мои задачи (alice):",
            "Unassigned:",
            "bob:",
            "zoe:",
        ]

    def test_empty_groups_omitted(self):
        tasks = _leaves({"t-mine": "alice"})
        groups = group_tasks(tasks, "alice")
        assert [header for header, _ in groups] == ["Мои задачи (alice):"]

    def test_no_actor_has_no_mine_group(self):
        tasks = _leaves({"t-none": None, "t-b": "bob"})
        groups = group_tasks(tasks, None)
        assert [header for header, _ in groups] == ["Unassigned:", "bob:"]


class TestFormatTaskLine:
    def test_with_label(self):
        tasks = parse_graphs(
            make_graph([issue("t-1", title="My Task", status="in_progress", issue_type="feature", labels=["flow"])])
        )
        assert format_task_line(tasks["t-1"], 3) == "3. [F] My Task (t-1) | P2 | #flow"

    def test_without_label_no_suffix(self):
        tasks = parse_graphs(make_graph([issue("t-1", title="Task", status="in_progress", issue_type="epic")]))
        assert format_task_line(tasks["t-1"], 1) == "1. [E] Task (t-1) | P2"

    def test_type_letters(self):
        for issue_type, letter in [("bug", "B"), ("feature", "F"), ("task", "T"), ("epic", "E"), ("chore", "C")]:
            tasks = parse_graphs(make_graph([issue("t-1", title="X", status="in_progress", issue_type=issue_type)]))
            assert format_task_line(tasks["t-1"], 1).startswith(f"1. [{letter}]")

    def test_multiline_title_collapsed(self):
        tasks = parse_graphs(make_graph([issue("t-1", title="Line one\nline two", status="in_progress")]))
        assert format_task_line(tasks["t-1"], 1) == "1. [T] Line one line two (t-1) | P2"


class TestRender:
    def test_continuous_numbering_across_groups(self):
        tasks = _leaves({"t-a": "alice", "t-none": None, "t-b": "bob"})
        output = render(group_tasks(tasks, "alice"))
        assert output == (
            "Мои задачи (alice):\n"
            "1. [T] t-a (t-a) | P2\n"
            "\n"
            "Unassigned:\n"
            "2. [T] t-none (t-none) | P2\n"
            "\n"
            "bob:\n"
            "3. [T] t-b (t-b) | P2"
        )

    def test_no_tasks_renders_empty(self):
        assert render(group_tasks([], "alice")) == ""


class TestEndToEnd:
    GRAPH = json.dumps(
        make_graph(
            [
                issue("t-mine", title="Mine", status="in_progress", issue_type="bug", assignee="alice"),
                issue("t-none", title="Nobody's", status="in_progress", assignee=None),
                issue("t-bob", title="Bobs", status="in_progress", assignee="bob"),
            ]
        )
    )

    def test_bd_actor_selects_my_and_unassigned(self, tmp_path):
        r = run_helper("flow-find-leaf", cwd=tmp_path, env={**NO_GIT_ENV, "BD_ACTOR": "alice"}, stdin=self.GRAPH)
        assert r.returncode == 0
        assert "Мои задачи (alice):" in r.stdout
        assert "t-mine" in r.stdout
        assert "t-none" in r.stdout
        assert "t-bob" not in r.stdout

    def test_all_flag_shows_everyone(self, tmp_path):
        r = run_helper(
            "flow-find-leaf", "--all", cwd=tmp_path, env={**NO_GIT_ENV, "BD_ACTOR": "alice"}, stdin=self.GRAPH
        )
        assert r.returncode == 0
        assert "t-bob" in r.stdout
        assert r.stdout.index("Мои задачи (alice):") < r.stdout.index("Unassigned:") < r.stdout.index("bob:")

    def test_no_identity_behaves_like_all(self, tmp_path):
        r = run_helper("flow-find-leaf", cwd=tmp_path, env=NO_GIT_ENV, stdin=self.GRAPH)
        assert r.returncode == 0
        assert "t-bob" in r.stdout
        assert "Мои задачи" not in r.stdout

    def test_empty_input_no_output(self, tmp_path):
        r = run_helper("flow-find-leaf", cwd=tmp_path, env={**NO_GIT_ENV, "BD_ACTOR": "alice"}, stdin="[]")
        assert r.returncode == 0
        assert r.stdout == ""


class TestDecisionType:
    def test_decision_letter(self):
        tasks = parse_graphs(make_graph([issue("x", issue_type="decision")]))
        assert format_task_line(tasks["x"], 1).startswith("1. [D]")
