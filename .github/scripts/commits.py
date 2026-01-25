"""Conventional commit parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class CommitInfo:
    """Parsed conventional commit information."""

    type: str
    scope: str | None
    description: str
    breaking: bool


# Valid conventional commit types
VALID_TYPES = frozenset(
    [
        "feat",
        "fix",
        "docs",
        "style",
        "refactor",
        "test",
        "chore",
        "ci",
        "revert",
        "build",
        "perf",
    ]
)

# Regex for conventional commit format
COMMIT_PATTERN = re.compile(
    r"^(?P<type>[a-z]+)"
    r"(?:\((?P<scope>[a-z][a-z0-9-]*)\))?"
    r"(?P<breaking>!)?"
    r":\s*(?P<desc>.+)$",
    re.IGNORECASE,
)

# Patterns to reject
MERGE_PATTERN = re.compile(r"^Merge\s+", re.IGNORECASE)
GITHUB_REVERT_PATTERN = re.compile(r'^Revert\s+"', re.IGNORECASE)


def parse_commit_message(message: str) -> CommitInfo | None:
    """Parse a conventional commit message.

    Args:
        message: First line of commit message.

    Returns:
        CommitInfo if valid conventional commit, None otherwise.
    """
    if not message:
        return None

    # Reject merge commits
    if MERGE_PATTERN.match(message):
        return None

    # Reject GitHub's revert format
    if GITHUB_REVERT_PATTERN.match(message):
        return None

    match = COMMIT_PATTERN.match(message)
    if not match:
        return None

    commit_type = match.group("type").lower()

    # Validate type
    if commit_type not in VALID_TYPES:
        return None

    return CommitInfo(
        type=commit_type,
        scope=match.group("scope"),
        description=match.group("desc"),
        breaking=bool(match.group("breaking")),
    )
