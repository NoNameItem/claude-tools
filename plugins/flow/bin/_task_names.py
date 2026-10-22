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


def _is_not_found(result: subprocess.CompletedProcess[str]) -> bool:
    """bd >= 1.0 fails a missing id: `{"error": "no issues found matching ..."}` on stdout, the id on stderr."""
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        data = None
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, str) and "no issues found matching" in error:
        return True
    return "no issue found matching" in result.stderr


def read_issue(bd: str, task_id: str) -> dict:
    result = subprocess.run([bd, "show", task_id, "--json"], capture_output=True, text=True, check=False)
    not_found = f"task not found: {task_id}"
    if result.returncode != 0:
        if _is_not_found(result):
            raise TaskLookupError(not_found, 1)
        raise TaskLookupError(result.stderr.strip(), 2)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        msg = "malformed bd json"
        raise TaskLookupError(msg, 2) from None
    issue = (data[0] if data else None) if isinstance(data, list) else data
    if not issue:
        raise TaskLookupError(not_found, 1)
    return issue
