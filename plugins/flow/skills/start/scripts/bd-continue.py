#!/usr/bin/env python3
"""
Find leaf in_progress tasks from bd graph --all --json output.

A task is "leaf" if none of its children are in_progress.

Usage:
    bd graph --all --json | python3 bd-continue.py
    bd graph --all --json | python3 bd-continue.py --all

Output (one task per line, pipe-delimited):
    task-id|issue_type|title|P<priority>|first_label
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field


@dataclass
class Task:
    id: str
    title: str
    status: str
    priority: int
    issue_type: str
    labels: list[str] = field(default_factory=list)
    owner: str = ""
    children: list["Task"] = field(default_factory=list)
    parent_id: str | None = None


def parse_graphs(data: list[dict]) -> dict[str, Task]:
    """Parse all graphs into a flat dict of tasks."""
    tasks: dict[str, Task] = {}
    parent_map: dict[str, str] = {}

    for graph in data:
        for iss in graph.get("Issues") or []:
            task = Task(
                id=iss["id"],
                title=iss["title"],
                status=iss["status"],
                priority=iss.get("priority", 2),
                issue_type=iss.get("issue_type", "task"),
                labels=iss.get("labels", []),
                owner=iss.get("owner", ""),
            )
            tasks[task.id] = task

        for d in graph.get("Dependencies") or []:
            if d["type"] == "parent-child":
                parent_map[d["issue_id"]] = d["depends_on_id"]

    for child_id, parent_id in parent_map.items():
        if child_id in tasks and parent_id in tasks:
            tasks[child_id].parent_id = parent_id
            tasks[parent_id].children.append(tasks[child_id])

    return tasks


def find_leaf_in_progress(tasks: dict[str, Task], *, owner: str | None) -> list[Task]:
    """Find leaf in_progress tasks, optionally filtered by owner.

    A task is "leaf" if none of its children are in_progress.
    """
    result = []
    for task in tasks.values():
        if task.status != "in_progress":
            continue
        if owner is not None and task.owner != owner:
            continue
        # Leaf = no children are in_progress
        has_in_progress_child = any(c.status == "in_progress" for c in task.children)
        if not has_in_progress_child:
            result.append(task)

    return sorted(result, key=lambda t: (t.priority, t.id))


def _sanitize(value: str) -> str:
    """Escape characters that break pipe-delimited output."""
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", "")


def format_task_line(task: Task) -> str:
    """Format task as pipe-delimited line."""
    label = task.labels[0] if task.labels else ""
    return f"{task.id}|{task.issue_type}|{_sanitize(task.title)}|P{task.priority}|{_sanitize(label)}"


def get_git_user() -> str | None:
    """Get current git user.name. Returns None if unavailable."""
    try:
        name = subprocess.check_output(
            ["git", "config", "user.name"],
            text=True,
        ).strip()
        return name or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Find leaf in_progress tasks")
    parser.add_argument("--all", action="store_true", help="Show all users' tasks")
    args = parser.parse_args()

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if not data:
        sys.exit(0)

    tasks = parse_graphs(data)
    owner = None if args.all else get_git_user()
    result = find_leaf_in_progress(tasks, owner=owner)

    for task in result:
        print(format_task_line(task))


if __name__ == "__main__":
    main()
