#!/usr/bin/env python3
"""Decide whether Codex has reviewed the current head of a PR (review-gate logic).

Pure decision function extracted from review-gate.yml so the freshness/cutoff rules are
unit-testable. The workflow fetches Codex's reviews and reactions via `gh api`, pipes them in
as JSON on stdin, passes the triggering event's fields as CLI args, and this script prints
`pass` or `wait`.

Usage:
    echo '{"reviews": [...], "reactions": [...]}' | python review_gate.py \
        --event-action synchronize --updated-at 2026-07-01T10:00:00Z \
        --head-sha abc123 [--base-changed]

Output:
    `pass`  — Codex has reviewed the current head (gate may open)
    `wait`  — not yet (the workflow keeps polling until this or the deadline)

See docs/superpowers/specs/2026-07-01-harden-review-gate-design.md.
"""

from __future__ import annotations

import argparse
import json
import sys

CODEX_BOT = "chatgpt-codex-connector[bot]"

# Events that change what Codex must review -> the freshness cutoff advances.
CONTENT_CHANGE_ACTIONS = frozenset({"opened", "synchronize"})


def decide(
    event_action: str,
    is_base_change: bool,
    updated_at: str,
    head_sha: str,
    reviews: list[dict],
    reactions: list[dict],
) -> str:
    """Return "pass" if Codex has reviewed the current head, else "wait".

    Args:
        event_action: The pull_request(_target) action (opened, synchronize,
            ready_for_review, edited). `reopened` is intentionally NOT a gate trigger — see
            the non-content note below.
        is_base_change: True when action == "edited" and the PR base ref changed.
        updated_at: The event's pull_request.updated_at (ISO-8601 UTC "Z"). The freshness
            cutoff on content-change events.
        head_sha: The PR head commit SHA.
        reviews: Codex PR reviews: {"user": {"login": ...}, "commit_id": ..., "submitted_at": ...}.
        reactions: PR reactions: {"user": {"login": ...}, "content": ..., "created_at": ...}.

    Timestamps are compared as strings; GitHub emits fixed-format UTC "Z" timestamps that
    order lexicographically (the previous shell implementation compared them the same way).
    """
    content_change = event_action in CONTENT_CHANGE_ACTIONS or (event_action == "edited" and is_base_change)

    reviews_at_head = [
        r for r in reviews if r.get("user", {}).get("login") == CODEX_BOT and r.get("commit_id") == head_sha
    ]
    thumbs = [r for r in reactions if r.get("user", {}).get("login") == CODEX_BOT and r.get("content") == "+1"]

    if content_change:
        # Cutoff = updated_at (push or base-change time). Evidence must be strictly newer.
        fresh_review = any(r.get("submitted_at", "") > updated_at for r in reviews_at_head)
        fresh_thumb = any(r.get("created_at", "") > updated_at for r in thumbs)
        return "pass" if fresh_review or fresh_thumb else "wait"

    # Non-content-change event (ready_for_review): no new content, so any existing evidence for
    # the current head is still valid — a draft's head SHA can't change invisibly (pushes to a
    # draft fire `synchronize`), so a bare 👍 here is genuinely for this head.
    #
    # `reopened` is deliberately absent from the gate's triggers: on reopen the head SHA's prior
    # check result simply persists (no re-run), which both keeps a valid green (fixing the
    # non-push false-block) AND prevents a reopen from laundering stale evidence into a fresh
    # green after a base change or a while-closed push (Codex #96 C1/C3). If `reopened` were ever
    # routed here it would take this same non-content branch; the workflow just never sends it.
    # (edited-without-base also never reaches this script — the workflow `if:` filters it out.)
    return "pass" if reviews_at_head or thumbs else "wait"


def main() -> int:
    """CLI entry point: read reviews/reactions JSON from stdin, print pass/wait."""
    parser = argparse.ArgumentParser(description="review-gate decision")
    parser.add_argument("--event-action", required=True)
    parser.add_argument("--updated-at", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--base-changed", action="store_true")
    args = parser.parse_args()

    payload = json.load(sys.stdin)
    result = decide(
        event_action=args.event_action,
        is_base_change=args.base_changed,
        updated_at=args.updated_at,
        head_sha=args.head_sha,
        reviews=payload.get("reviews", []),
        reactions=payload.get("reactions", []),
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
