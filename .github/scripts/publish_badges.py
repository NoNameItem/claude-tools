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
