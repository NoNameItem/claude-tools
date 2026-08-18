#!/usr/bin/env python3
"""Detect a release-please merge from a push event's commit list.

Only release-please writes `.release-please-manifest.json`, which makes this a semantic signal
rather than a guess at the commit subject.

The test runs over the WHOLE push, not over its head commit: `github.event.commits[].modified` is
already in the event payload (no checkout, no history depth, no git command), and reading only the
head would be wrong under a rebase merge — the flow release PR carries a second commit from
`pin_marketplace_refs.py`, so its head is the pin commit and the manifest is one commit further
back. The repository is squash-only today, which makes that case unreachable; the range test is
used anyway so the detection does not silently depend on a merge policy somebody may widen again.
The payload's 20-commit cap is irrelevant here — a release merge is one or two commits.

Usage:
    printf '%s' "$COMMITS_JSON" | python3 release_merge.py

Output (stdout):
    "true" | "false"
"""

from __future__ import annotations

import json
import sys

_MANIFEST = ".release-please-manifest.json"


def is_release_merge(commits: list[dict]) -> bool:
    """Whether any commit in this push touched the release-please manifest."""
    return any(_MANIFEST in (commit.get("modified") or []) for commit in commits)


def main() -> int:
    """CLI entrypoint. Always returns 0 — both answers are normal."""
    commits = json.load(sys.stdin)
    print("true" if is_release_merge(commits) else "false", end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
