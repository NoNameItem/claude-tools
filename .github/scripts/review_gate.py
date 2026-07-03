#!/usr/bin/env python3
"""Decide whether Codex has freshly reviewed the current head of a PR (review-gate logic).

Pure decision function extracted from review-gate.yml so the freshness rule is unit-testable.
The workflow fetches Codex's reviews and reactions via `gh api`, pipes them in as JSON on
stdin, and passes the head SHA plus a freshness cutoff (the head's push time,
`pull_request.updated_at`) as CLI args; this script prints `pass` or `wait`.

Pass requires *fresh* evidence — a SHA-pinned review@head or a Codex 👍 whose timestamp is
strictly newer than the cutoff. A missing/`null` timestamp (e.g. a still-pending Codex review,
which the API returns without `submitted_at`) is treated as not-fresh, never a crash.

`reopened` is not a gate trigger (a reopen's prior head-SHA status persists). Base-change
re-arm was intentionally dropped — see the spec's §10; a base change is an accepted limitation.

Usage:
    echo '{"reviews": [...], "reactions": [...]}' | python review_gate.py \
        --cutoff 2026-07-01T10:00:00Z --head-sha abc123

Output:
    `pass`  — Codex has freshly reviewed the current head (gate may open)
    `wait`  — not yet (the workflow keeps polling until this or the deadline)

See docs/superpowers/specs/2026-07-01-harden-review-gate-design.md.
"""

from __future__ import annotations

import argparse
import json
import sys

CODEX_BOT = "chatgpt-codex-connector[bot]"


def decide(cutoff: str, head_sha: str, reviews: list[dict], reactions: list[dict]) -> str:
    """Return "pass" if Codex reviewed head_sha with evidence newer than cutoff, else "wait".

    Args:
        cutoff: ISO-8601 UTC "Z" timestamp (the head's push time); evidence must be strictly
            newer. Timestamps are compared as strings — GitHub emits fixed-format UTC "Z"
            timestamps that order lexicographically. A missing/`null` timestamp is coerced to
            "" (sorts before any real timestamp) so a pending review can't raise a TypeError.
        head_sha: The PR head commit SHA (the findings path is pinned to it).
        reviews: Codex PR reviews: {"user": {"login": ...}, "commit_id": ..., "submitted_at": ...}.
        reactions: PR reactions: {"user": {"login": ...}, "content": ..., "created_at": ...}.
    """
    fresh_review = any(
        r.get("user", {}).get("login") == CODEX_BOT
        and r.get("commit_id") == head_sha
        and (r.get("submitted_at") or "") > cutoff
        for r in reviews
    )
    fresh_thumb = any(
        r.get("user", {}).get("login") == CODEX_BOT
        and r.get("content") == "+1"
        and (r.get("created_at") or "") > cutoff
        for r in reactions
    )
    return "pass" if fresh_review or fresh_thumb else "wait"


def main() -> int:
    """CLI entry point: read reviews/reactions JSON from stdin, print pass/wait."""
    parser = argparse.ArgumentParser(description="review-gate decision")
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args()

    payload = json.load(sys.stdin)
    result = decide(
        cutoff=args.cutoff,
        head_sha=args.head_sha,
        reviews=payload.get("reviews", []),
        reactions=payload.get("reactions", []),
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
