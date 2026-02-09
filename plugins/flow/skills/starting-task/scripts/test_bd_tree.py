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
get_type_emoji = _mod.get_type_emoji
find_min_priority = _mod.find_min_priority
format_task_line = _mod.format_task_line


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
# get_type_emoji tests
# ===========================================================================


class TestGetTypeEmoji:
    def test_epic(self):
        assert get_type_emoji("epic") == "📦"

    def test_feature(self):
        assert get_type_emoji("feature") == "🚀"

    def test_bug(self):
        assert get_type_emoji("bug") == "❌"

    def test_task(self):
        assert get_type_emoji("task") == "📋"

    def test_chore(self):
        assert get_type_emoji("chore") == "⚙️"

    def test_unknown_type_fallback(self):
        assert get_type_emoji("milestone") == "❔"

    def test_case_insensitive(self):
        assert get_type_emoji("Epic") == "📦"
        assert get_type_emoji("BUG") == "❌"


# ===========================================================================
# find_min_priority tests
# ===========================================================================


class TestFindMinPriority:
    """Test constants for priority values."""

    LOWEST_PRIORITY = 1
    MIN_PRIORITY = 2
    HIGH_PRIORITY = 3

    def test_mixed_priorities(self):
        """Min priority among visible tasks."""
        tasks = {
            "t1": make_task("t1", priority=self.LOWEST_PRIORITY, status="open"),
            "t2": make_task("t2", priority=self.MIN_PRIORITY, status="open"),
            "t3": make_task("t3", priority=self.HIGH_PRIORITY, status="open"),
        }
        assert find_min_priority(tasks) == self.LOWEST_PRIORITY

    def test_ignores_closed(self):
        """Closed tasks don't count."""
        tasks = {
            "t1": make_task("t1", priority=1, status="closed"),
            "t2": make_task("t2", priority=2, status="open"),
            "t3": make_task("t3", priority=3, status="open"),
        }
        assert find_min_priority(tasks) == self.MIN_PRIORITY

    def test_ignores_blocked(self):
        """Blocked tasks don't count."""
        blocked = make_task("t1", priority=1, status="open")
        blocked.is_blocked = True
        tasks = {
            "t1": blocked,
            "t2": make_task("t2", priority=3, status="open"),
        }
        assert find_min_priority(tasks) == self.HIGH_PRIORITY

    def test_all_same_priority(self):
        """All tasks same priority → that priority is min."""
        tasks = {
            "t1": make_task("t1", priority=2, status="open"),
            "t2": make_task("t2", priority=2, status="open"),
        }
        assert find_min_priority(tasks) == self.MIN_PRIORITY

    def test_no_visible_tasks(self):
        """No visible tasks → return None (no bolding)."""
        tasks = {
            "t1": make_task("t1", priority=1, status="closed"),
        }
        assert find_min_priority(tasks) is None

    def test_empty_dict(self):
        """Empty tasks dict → return None."""
        assert find_min_priority({}) is None


# ===========================================================================
# format_task_line tests
# ===========================================================================


class TestFormatTaskLine:
    def test_emoji_prepended(self):
        """Emoji appears before type letter bracket."""
        task = make_task("test-1", issue_type="bug", priority=2, status="open")
        line = format_task_line(task, prefix="", number="1", is_root=True, min_priority=1)
        assert "❌ [B]" in line

    def test_feature_emoji(self):
        task = make_task("test-1", issue_type="feature", priority=2, status="open")
        line = format_task_line(task, prefix="", number="1", is_root=True, min_priority=1)
        assert "🚀 [F]" in line

    def test_epic_emoji(self):
        task = make_task("test-1", issue_type="epic", priority=1, status="open")
        line = format_task_line(task, prefix="", number="1", is_root=True, min_priority=1)
        assert "📦 [E]" in line

    def test_bold_when_min_priority(self):
        """Task with min priority gets **bold** wrapping."""
        task = make_task("test-1", issue_type="feature", priority=1, status="open")
        line = format_task_line(task, prefix="", number="1", is_root=True, min_priority=1)
        assert line.startswith("**")
        assert line.endswith("**")

    def test_no_bold_when_not_min_priority(self):
        """Task above min priority has no bold."""
        task = make_task("test-1", issue_type="feature", priority=2, status="open")
        line = format_task_line(task, prefix="", number="1", is_root=True, min_priority=1)
        assert not line.startswith("**")

    def test_bold_with_labels(self):
        """Bold wraps entire line including labels."""
        task = make_task("test-1", issue_type="epic", priority=1, status="open", labels=["flow"])
        line = format_task_line(task, prefix="", number="1", is_root=True, min_priority=1)
        assert line.startswith("**")
        assert line.endswith("**")
        assert "#flow" in line

    def test_no_bold_when_min_priority_none(self):
        """When min_priority is None, nothing is bolded."""
        task = make_task("test-1", issue_type="feature", priority=1, status="open")
        line = format_task_line(task, prefix="", number="1", is_root=True, min_priority=None)
        assert not line.startswith("**")

    def test_unknown_type_gets_fallback_emoji(self):
        """Unknown type gets ❔ emoji."""
        task = make_task("test-1", issue_type="milestone", priority=2, status="open")
        line = format_task_line(task, prefix="", number="1", is_root=True, min_priority=1)
        assert "❔" in line

    def test_child_numbering_preserved(self):
        """Child tasks (non-root) don't get trailing dot."""
        task = make_task("test-1", issue_type="task", priority=2, status="open")
        line = format_task_line(task, prefix="├─ ", number="1.1", is_root=False, min_priority=1)
        assert "├─ 1.1 📋 [T]" in line

    def test_prefix_with_bold(self):
        """Bold wrapping does NOT include the tree prefix."""
        task = make_task("test-1", issue_type="bug", priority=1, status="open")
        line = format_task_line(task, prefix="├─ ", number="1.1", is_root=False, min_priority=1)
        # Prefix should be outside bold: "├─ **1.1 ❌ [B] ...**"
        assert line.startswith("├─ **")


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
        """The selected root task's first line contains '1.' numbering."""
        tasks = self._parse(
            [
                issue("proj-aaa", title="Root A"),
                issue("proj-bbb", title="Root B"),
            ],
        )
        # Even though proj-bbb would be 2nd normally, with --root it becomes 1.
        # Bold wrapping may prepend **, so check for "1." presence
        lines = build_tree(tasks, root_id="proj-bbb")
        assert "1." in lines[0]
        assert "Root B" in lines[0]

    def test_root_no_children_shows_just_task(self):
        """A root with no children shows just the single task line."""
        tasks = self._parse([issue("proj-aaa", title="Lonely")])
        lines = build_tree(tasks, root_id="proj-aaa")
        assert len(lines) == 1
        assert "Lonely" in lines[0]


# ===========================================================================
# Tree emoji and bold integration tests
# ===========================================================================


class TestTreeEmojiAndBold:
    """Integration tests for emoji and bold in full tree output."""

    def _parse(self, issues, deps=None):
        return parse_graphs(make_graph(issues, deps))

    def test_emoji_in_tree_output(self):
        """Full tree output includes emoji for each task type."""
        tasks = self._parse(
            [
                issue("proj-aaa", title="Epic Task", issue_type="epic", priority=1),
                issue("proj-bbb", title="Bug Fix", issue_type="bug", priority=2),
            ]
        )
        lines = build_tree(tasks)
        text = "\n".join(lines)
        assert "📦 [E]" in text
        assert "❌ [B]" in text

    def test_bold_only_min_priority(self):
        """Only tasks with minimum priority get bold."""
        tasks = self._parse(
            [
                issue("proj-aaa", title="High", issue_type="feature", priority=1),
                issue("proj-bbb", title="Medium", issue_type="task", priority=2),
            ]
        )
        lines = build_tree(tasks)
        # P1 task should be bold, P2 should not
        high_line = next(line for line in lines if "High" in line)
        med_line = next(line for line in lines if "Medium" in line)
        assert "**" in high_line
        assert "**" not in med_line

    def test_all_same_priority_all_bold(self):
        """When all tasks same priority, all get bold."""
        tasks = self._parse(
            [
                issue("proj-aaa", title="Task A", priority=2),
                issue("proj-bbb", title="Task B", priority=2),
            ]
        )
        lines = build_tree(tasks)
        for line in lines:
            if line.strip():  # skip blank separator lines
                assert "**" in line

    def test_bold_with_children(self):
        """Bold works correctly in parent-child tree."""
        tasks = self._parse(
            [
                issue("proj-parent", title="Parent", issue_type="epic", priority=1),
                issue("proj-child", title="Child", issue_type="bug", priority=2),
            ],
            [dep("proj-child", "proj-parent")],
        )
        lines = build_tree(tasks)
        parent_line = next(line for line in lines if "Parent" in line)
        child_line = next(line for line in lines if "Child" in line)
        assert "**" in parent_line  # P1 is min
        assert "**" not in child_line  # P2 is not min

    def test_tree_connectors_outside_bold(self):
        """Tree connectors (├─, └─) are outside bold markers."""
        tasks = self._parse(
            [
                issue("proj-parent", title="Parent", issue_type="epic", priority=1),
                issue("proj-child", title="Child", issue_type="bug", priority=1),
            ],
            [dep("proj-child", "proj-parent")],
        )
        lines = build_tree(tasks)
        child_line = next(line for line in lines if "Child" in line)
        # Connector should be before bold: "└─ **1.1 ..."
        assert child_line.startswith(("└─ **", "├─ **"))

    def test_root_subtree_uses_own_min_priority(self):
        """When --root is used, min_priority is calculated from visible subtree."""
        tasks = self._parse(
            [
                issue("proj-parent", title="Parent", issue_type="epic", priority=1),
                issue("proj-child1", title="Child1", issue_type="feature", priority=2),
                issue("proj-child2", title="Child2", issue_type="bug", priority=3),
                issue("proj-other", title="Other", issue_type="task", priority=1),
            ],
            [
                dep("proj-child1", "proj-parent"),
                dep("proj-child2", "proj-parent"),
            ],
        )
        # When viewing subtree of parent, min_priority should be 1 (parent itself)
        lines = build_tree(tasks, root_id="proj-parent")
        parent_line = next(line for line in lines if "Parent" in line)
        child1_line = next(line for line in lines if "Child1" in line)
        assert "**" in parent_line  # P1 is min
        assert "**" not in child1_line  # P2 is not min
