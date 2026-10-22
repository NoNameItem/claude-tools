#!/usr/bin/env python3
"""Decide whether Codex has freshly reviewed the current head of a PR (review-gate logic).

Pure decision function extracted from the gate workflow so the freshness rule is unit-testable.
The workflow fetches Codex's reviews and reactions via `gh api`, pipes them in as JSON on stdin,
and passes the head SHA plus a freshness cutoff as CLI args; this script prints `pass` or `wait`.

The cutoff no longer comes from the event. `_reusable-review-gate.yml` runs on `pull_request`, so
`edited`, `reopened` and a manual re-run all re-execute it for a head SHA that has not changed —
and every one of them advances `pull_request.updated_at`. A cutoff read from the event would
declare the review that already arrived for this very commit "too old" and poll for 25 minutes for
a review nobody is going to write. So the cutoff is written once, by the run that actually asks
Codex, into the `codex-nudge` commit status (`comment:<id>@<cutoff>`), and every later run for the
same SHA reads it back — see `format_nudge_marker` / `parse_nudge_marker`. The cutoff belongs to
the commit, not to the last time somebody touched the PR.

Pass requires *fresh* evidence — a SHA-pinned review@head, a Codex 👍, or a Codex
`codex-review-receipt:v1` comment whose reviewed commit is a ≥7-char prefix of head — each strictly
newer than the cutoff. A missing/`null` timestamp (e.g. a still-pending Codex review, which the API
returns without `submitted_at`) is treated as not-fresh, never a crash.

The receipt exists because Codex's 👍 stopped meaning "this round was clean": Codex now reacts only
once the whole PR is finding-free by its own internal state, so a clean round on a PR it still
considers dirty leaves no review and no 👍 — only the receipt, one new comment per round naming the
reviewed commit. See docs/superpowers/specs/2026-10-22-review-gate-codex-receipt-design.md.

Usage:
    echo '{"reviews": [...], "reactions": [...], "comments": [...]}' | python review_gate.py decide \
        --cutoff 2026-07-01T10:00:00Z --head-sha abc123
    python review_gate.py parse-marker --description="comment:42@2026-07-01T10:00:00Z"
    python review_gate.py format-marker --comment-id 42 --cutoff 2026-07-01T10:00:00Z

Output:
    decide         `pass` — Codex has freshly reviewed the current head (gate may open)
                   `wait` — not yet (the workflow keeps polling until this or the deadline)
    parse-marker   {} for an absent/malformed marker, else {"comment_id": int, "cutoff": str}
    format-marker  the commit-status description to record

See docs/superpowers/specs/2026-08-01-notification-triggers-design.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

CODEX_BOT = "chatgpt-codex-connector[bot]"

# The whole marker, so `codex-review-receipt:v2` (or `:v10`) is not mistaken for v1: a new version
# is a format change to look at, and it shows up in the breakdown rather than opening the gate.
_RECEIPT_MARKER = re.compile(r"<!--\s*codex-review-receipt:v1\s*-->")
_REVIEWED_COMMIT = re.compile(r"\*\*Reviewed commit:\*\*\s*`(?P<sha>[0-9a-f]+)`")
# Codex writes 10 characters; 7 is git's own default abbreviation and the shortest we trust.
_MIN_SHA_PREFIX = 7


def receipt_sha(body: str | None) -> str | None:
    """Return the reviewed commit named by a `codex-review-receipt:v1` comment body, else None."""
    text = body or ""
    if not _RECEIPT_MARKER.search(text):
        return None
    match = _REVIEWED_COMMIT.search(text)
    return match.group("sha") if match else None


def _codex_login(item: dict) -> bool:
    # `or {}`, not a `.get` default: a deleted ("ghost") account comes back as an explicit `null`.
    return (item.get("user") or {}).get("login") == CODEX_BOT


def _counts_review(review: dict, cutoff: str, head_sha: str) -> bool:
    return _codex_login(review) and review.get("commit_id") == head_sha and (review.get("submitted_at") or "") > cutoff


def _counts_thumb(reaction: dict, cutoff: str) -> bool:
    return _codex_login(reaction) and reaction.get("content") == "+1" and (reaction.get("created_at") or "") > cutoff


def _counts_receipt(comment: dict, cutoff: str, head_sha: str) -> bool:
    # `created_at` only: the receipt is a new comment per round, and an edit says nothing about
    # which round it describes.
    sha = receipt_sha(comment.get("body"))
    return (
        _codex_login(comment)
        and sha is not None
        and len(sha) >= _MIN_SHA_PREFIX
        and head_sha.startswith(sha)
        and (comment.get("created_at") or "") > cutoff
    )


def decide(
    cutoff: str,
    head_sha: str,
    reviews: list[dict],
    reactions: list[dict],
    comments: list[dict] | None = None,
) -> str:
    """Return "pass" if Codex reviewed head_sha with evidence newer than cutoff, else "wait".

    Args:
        cutoff: ISO-8601 UTC "Z" timestamp (the head's push time); evidence must be strictly
            newer. Timestamps are compared as strings — GitHub emits fixed-format UTC "Z"
            timestamps that order lexicographically. A missing/`null` timestamp is coerced to
            "" (sorts before any real timestamp) so a pending review can't raise a TypeError.
        head_sha: The PR head commit SHA (the findings path is pinned to it).
        reviews: Codex PR reviews: {"user": {"login": ...}, "commit_id": ..., "submitted_at": ...}.
        reactions: PR reactions: {"user": {"login": ...}, "content": ..., "created_at": ...}.
        comments: PR issue comments: {"id": ..., "user": {"login": ...}, "created_at": ...,
            "updated_at": ..., "body": ...}; only a `codex-review-receipt:v1` for head counts.
    """
    fresh_review = any(_counts_review(r, cutoff, head_sha) for r in reviews)
    fresh_thumb = any(_counts_thumb(r, cutoff) for r in reactions)
    fresh_receipt = any(_counts_receipt(c, cutoff, head_sha) for c in comments or [])
    return "pass" if fresh_review or fresh_thumb or fresh_receipt else "wait"


# `comment:<id>@<cutoff>` — the id lets the gate delete its own nudge once Codex answers, the
# cutoff pins the freshness window to the commit rather than to the event that re-ran the job.
_NUDGE_MARKER = re.compile(r"^comment:(?P<id>\d+)@(?P<cutoff>\S+)$")


def format_nudge_marker(comment_id: int, cutoff: str) -> str:
    """Build the `codex-nudge` commit-status description."""
    return f"comment:{comment_id}@{cutoff}"


def parse_nudge_marker(description: str | None) -> tuple[int, str] | None:
    """Read a `codex-nudge` description back into (comment id, cutoff).

    Returns ``None`` for an absent or malformed marker — which the workflow treats as "we have
    not asked for this SHA yet", so the failure mode is one extra `@codex review` comment, not a
    poll against an invented cutoff.
    """
    match = _NUDGE_MARKER.match((description or "").strip())
    if not match:
        return None
    return int(match.group("id")), match.group("cutoff")


def main() -> int:
    """CLI entry point: three modes over one module of gate knowledge."""
    parser = argparse.ArgumentParser(description="review-gate decision and marker bookkeeping")
    sub = parser.add_subparsers(dest="command", required=True)

    decide_parser = sub.add_parser("decide", help="Read reviews/reactions JSON from stdin, print pass/wait.")
    decide_parser.add_argument("--cutoff", required=True)
    decide_parser.add_argument("--head-sha", required=True)

    parse_parser = sub.add_parser("parse-marker", help="Parse a codex-nudge commit-status description.")
    parse_parser.add_argument("--description", default="")

    format_parser = sub.add_parser("format-marker", help="Build a codex-nudge commit-status description.")
    format_parser.add_argument("--comment-id", required=True, type=int)
    format_parser.add_argument("--cutoff", required=True)

    args = parser.parse_args()

    if args.command == "parse-marker":
        parsed = parse_nudge_marker(args.description)
        print(json.dumps({"comment_id": parsed[0], "cutoff": parsed[1]} if parsed else {}))
        return 0

    if args.command == "format-marker":
        print(format_nudge_marker(args.comment_id, args.cutoff), end="")
        return 0

    payload = json.load(sys.stdin)
    result = decide(
        cutoff=args.cutoff,
        head_sha=args.head_sha,
        reviews=payload.get("reviews", []),
        reactions=payload.get("reactions", []),
        comments=payload.get("comments", []),
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
