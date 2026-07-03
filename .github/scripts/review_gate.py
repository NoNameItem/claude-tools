#!/usr/bin/env python3
"""Decide whether Codex has freshly reviewed the current head of a PR (review-gate logic).

Pure decision function extracted from review-gate.yml so the freshness rule is unit-testable.
The workflow fetches Codex's reviews and reactions via `gh api`, pipes them in as JSON on
stdin, passes the head SHA and an event-appropriate freshness cutoff as CLI args, and this
script prints `pass` or `wait`.

The workflow computes the cutoff per event: the push / base-change time (`pull_request.
updated_at`) for content-change events, and the head commit's committer date for
`ready_for_review` (where `updated_at` is the later ready-toggle time). `reopened` is not a
gate trigger at all. Requiring *both* evidence kinds to beat that cutoff — a SHA-pinned
review@head or a Codex 👍 — is what closes the stale-👍 / stale-review holes (Codex #96
C1/C3/C4): a bare 👍 or an old review that predates the current head/base is rejected.

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
        cutoff: ISO-8601 UTC "Z" timestamp; evidence must be strictly newer. Timestamps are
            compared as strings (GitHub emits fixed-format UTC "Z" timestamps that order
            lexicographically, as the original shell implementation compared them).
        head_sha: The PR head commit SHA (the findings path is pinned to it).
        reviews: Codex PR reviews: {"user": {"login": ...}, "commit_id": ..., "submitted_at": ...}.
        reactions: PR reactions: {"user": {"login": ...}, "content": ..., "created_at": ...}.
    """
    fresh_review = any(
        r.get("user", {}).get("login") == CODEX_BOT
        and r.get("commit_id") == head_sha
        and r.get("submitted_at", "") > cutoff
        for r in reviews
    )
    fresh_thumb = any(
        r.get("user", {}).get("login") == CODEX_BOT and r.get("content") == "+1" and r.get("created_at", "") > cutoff
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
