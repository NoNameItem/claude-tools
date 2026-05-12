#!/usr/bin/env python3
"""Publish per-project CI badges to the badges-data branch.

Reads the current GitHub Actions workflow run's job list, aggregates
conclusions per project (extracted from job names by trailing-parens
convention), and writes shields.io endpoint JSON files to ``--output-dir``.

Usage:
    publish_badges.py --output-dir <path> [--repo <owner/repo>] [--run-id <id>]

Environment variables:
    GITHUB_TOKEN       Required. PAT or workflow token with actions:read.
    GITHUB_REPOSITORY  Default for --repo when not provided.
    GITHUB_RUN_ID      Default for --run-id when not provided.

Exit codes:
    0  success (zero files written is still success)
    1  API error, parse error, missing required env, or pagination cap hit
"""

from __future__ import annotations

import re

# Anchored at end. Group 1 is the project; an optional ", suffix" (e.g.
# python version in the test matrix) is allowed but discarded.
_PROJECT_PATTERN = re.compile(r"\((?P<project>[\w][\w-]*)(?:, [^)]+)?\)$")


def extract_project_name(job_name: str) -> str | None:
    """Extract project name from a job name.

    Matches names of the form ``"<prefix> (<project>)"`` or
    ``"<prefix> (<project>, <suffix>)"``. Project must start with a
    word character and may contain word chars and hyphens.

    Args:
        job_name: The GitHub Actions job ``name`` field.

    Returns:
        The project slug, or ``None`` if the name has no recognizable
        trailing project group.
    """
    match = _PROJECT_PATTERN.search(job_name)
    return match.group("project") if match else None


# Conclusions that count as a real positive signal.
_SUCCESS_CONCLUSIONS = frozenset({"success"})

# Conclusions that contribute no signal (don't downgrade, don't upgrade).
_NEUTRAL_CONCLUSIONS = frozenset({"skipped"})


def aggregate_status(conclusions: list[str | None]) -> tuple[str, str] | None:
    """Aggregate per-job conclusions into a single (message, color) tuple.

    Rules:
        * All success (optionally mixed with skipped) -> ("passing", "brightgreen")
        * Any non-success / non-skipped conclusion       -> ("failing", "red")
        * All skipped, or empty input                    -> None (caller skips write)

    Args:
        conclusions: A list of GitHub ``conclusion`` strings for one project.
            ``None`` and unknown values are treated conservatively as failing.

    Returns:
        ``(message, color)`` for shields.io, or ``None`` if there is no
        signal (caller MUST NOT touch the badge file in that case).
    """
    saw_signal = False
    for c in conclusions:
        if c in _NEUTRAL_CONCLUSIONS:
            continue
        if c in _SUCCESS_CONCLUSIONS:
            saw_signal = True
            continue
        # Anything else (failure, cancelled, timed_out, neutral, action_required,
        # stale, unexpected strings, or None) is conservatively a failure.
        return ("failing", "red")

    if not saw_signal:
        return None
    return ("passing", "brightgreen")
