"""Tests for bd-tree.py."""

# ruff: noqa: INP001, S101

import importlib.util
from pathlib import Path

# Import bd-tree.py as module (hyphenated filename)
_spec = importlib.util.spec_from_file_location("bd_tree", Path(__file__).parent / "bd-tree.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

Task = _mod.Task
parse_graphs = _mod.parse_graphs
build_tree = _mod.build_tree
find_task_by_id = _mod.find_task_by_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_task(task_id: str, **kwargs) -> Task:
    """Create a Task with sensible defaults."""
    defaults = {
        "title": task_id,
        "status": "open",
        "priority": 2,
        "issue_type": "task",
    }
    defaults.update(kwargs)
    return Task(id=task_id, **defaults)


def issue(
    task_id: str,
    title: str = "",
    status: str = "open",
    priority: int = 2,
    issue_type: str = "task",
    labels: list[str] | None = None,
) -> dict:
    """Create an issue dict for graph JSON."""
    return {
        "id": task_id,
        "title": title or task_id,
        "status": status,
        "priority": priority,
        "issue_type": issue_type,
        "labels": labels or [],
    }


def dep(child_id: str, parent_id: str) -> dict:
    """Create a parent-child dependency dict."""
    return {"type": "parent-child", "issue_id": child_id, "depends_on_id": parent_id}


def make_graph(issues: list[dict], deps: list[dict] | None = None) -> list[dict]:
    """Create a graph JSON structure (list with one graph entry)."""
    return [{"Issues": issues, "Dependencies": deps or []}]


# ===========================================================================
# find_task_by_id tests
# ===========================================================================


class TestFindTaskById:
    def test_exact_match(self):
        tasks = {"claude-tools-5dl": make_task("claude-tools-5dl")}
        result = find_task_by_id(tasks, "claude-tools-5dl")
        assert result is not None
        assert result.id == "claude-tools-5dl"

    def test_suffix_match(self):
        tasks = {"claude-tools-5dl": make_task("claude-tools-5dl")}
        result = find_task_by_id(tasks, "5dl")
        assert result is not None
        assert result.id == "claude-tools-5dl"

    def test_not_found(self):
        tasks = {"claude-tools-5dl": make_task("claude-tools-5dl")}
        result = find_task_by_id(tasks, "xyz")
        assert result is None

    def test_suffix_requires_dash_prefix(self):
        """'5dl' should NOT match 'claude-tools-a5dl' (no dash before '5dl')."""
        tasks = {"claude-tools-a5dl": make_task("claude-tools-a5dl")}
        result = find_task_by_id(tasks, "5dl")
        assert result is None

    def test_exact_match_priority_over_suffix(self):
        """If both exact and suffix match exist, exact wins."""
        tasks = {
            "5dl": make_task("5dl"),
            "claude-tools-5dl": make_task("claude-tools-5dl"),
        }
        result = find_task_by_id(tasks, "5dl")
        assert result is not None
        assert result.id == "5dl"


# ===========================================================================
# build_tree with root_id tests
# ===========================================================================


class TestBuildTreeRootId:
    def _parse(self, issues, deps=None):
        """Parse a graph and return tasks dict."""
        return parse_graphs(make_graph(issues, deps))

    def test_root_id_shows_subtree(self):
        """Only the root task and its children appear, not other roots."""
        tasks = self._parse(
            [
                issue("proj-aaa", title="Root A"),
                issue("proj-bbb", title="Root B"),
                issue("proj-ccc", title="Child of A"),
            ],
            [dep("proj-ccc", "proj-aaa")],
        )
        lines = build_tree(tasks, root_id="proj-aaa")
        text = "\n".join(lines)
        assert "Root A" in text
        assert "Child of A" in text
        assert "Root B" not in text

    def test_root_id_suffix_match(self):
        """Suffix match works for root_id."""
        tasks = self._parse([issue("proj-aaa", title="Root A")])
        lines = build_tree(tasks, root_id="aaa")
        assert any("Root A" in line for line in lines)

    def test_root_id_not_found_shows_full_tree_with_warning(self):
        """When root_id not found, show warning + full tree."""
        tasks = self._parse([issue("proj-aaa", title="Root A")])
        lines = build_tree(tasks, root_id="nonexistent")
        text = "\n".join(lines)
        assert "not found" in text.lower()
        assert "nonexistent" in text
        assert "Root A" in text

    def test_root_task_becomes_root_1(self):
        """The selected root task's first line starts with '1.'."""
        tasks = self._parse(
            [
                issue("proj-aaa", title="Root A"),
                issue("proj-bbb", title="Root B"),
            ],
        )
        # Even though proj-bbb would be 2nd normally, with --root it becomes 1.
        lines = build_tree(tasks, root_id="proj-bbb")
        assert lines[0].startswith("1.")

    def test_root_no_children_shows_just_task(self):
        """A root with no children shows just the single task line."""
        tasks = self._parse([issue("proj-aaa", title="Lonely")])
        lines = build_tree(tasks, root_id="proj-aaa")
        assert len(lines) == 1
        assert "Lonely" in lines[0]
