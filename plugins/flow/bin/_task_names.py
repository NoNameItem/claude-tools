"""Shared naming helpers for flow-branch-for and flow-worktree-dir: title slug and bd issue lookup."""

from __future__ import annotations

import json
import re
import subprocess

MAX_WORDS = 5


class TaskLookupError(Exception):
    """A task could not be read; `code` is the helper exit code (1 = not found, 2 = bd error)."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def slugify(title: str) -> str:
    words = [w for w in re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-").split("-") if w]
    return "-".join(words[:MAX_WORDS])


def read_issue(bd: str, task_id: str) -> dict:
    result = subprocess.run([bd, "show", task_id, "--json"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise TaskLookupError(result.stderr.strip(), 2)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        msg = "malformed bd json"
        raise TaskLookupError(msg, 2) from None
    issue = (data[0] if data else None) if isinstance(data, list) else data
    if not issue:
        msg = f"task not found: {task_id}"
        raise TaskLookupError(msg, 1)
    return issue
