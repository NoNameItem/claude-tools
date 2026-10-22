#!/usr/bin/env python3
"""Decide whether Codex has freshly reviewed the current head of a PR (review-gate logic).

Pure decision function extracted from the gate workflow so the freshness rule is unit-testable.
The workflow fetches Codex's reviews, reactions and issue comments via `gh api`, pipes them in as
JSON on stdin, and passes the head SHA plus a freshness cutoff as CLI args; this script prints
`pass` or `wait` (with a breakdown of Codex activity on stderr), or, at the deadline, the timeout
report.

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

Every poll also explains itself: `codex_activity` lists what Codex did after the cutoff and
whether each item counts, from the same predicates `decide` uses, and `timeout_report` turns that
into the deadline error — "Codex was silent" and "Codex was active but left nothing the gate
accepts" read differently, so the next change in how Codex signals is visible in the log.

Usage:
    echo '{"reviews": [...], "reactions": [...], "comments": [...]}' | python review_gate.py decide \
        --cutoff 2026-07-01T10:00:00Z --head-sha abc123
    echo '{...same payload...}' | python review_gate.py timeout-report \
        --cutoff 2026-07-01T10:00:00Z --head-sha abc123 --minutes 25
    python review_gate.py parse-marker --description="comment:42@2026-07-01T10:00:00Z"
    python review_gate.py format-marker --comment-id 42 --cutoff 2026-07-01T10:00:00Z

Output:
    decide          stdout: `pass` — Codex has freshly reviewed the current head (gate may open)
                            `wait` — not yet (the workflow keeps polling until this or the deadline)
                    stderr: a one-line breakdown of Codex activity since the cutoff
    timeout-report  the lines to print at the deadline; the last one is the `::error::` annotation
    parse-marker    {} for an absent/malformed marker, else {"comment_id": int, "cutoff": str}
    format-marker   the commit-status description to record

See docs/superpowers/specs/2026-08-01-notification-triggers-design.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass

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
        cutoff: ISO-8601 UTC "Z" timestamp (when the gate asked Codex for this head — the
            `codex-nudge` marker); evidence must be strictly newer. Timestamps are compared as
            strings — GitHub emits fixed-format UTC "Z" timestamps that order lexicographically.
            A missing/`null` timestamp is coerced to "" (sorts before any real timestamp) so a
            pending review can't raise a TypeError.
        head_sha: The PR head commit SHA (a review is pinned to it, a receipt by prefix).
        reviews: Codex PR reviews: {"user": {"login": ...}, "commit_id": ..., "submitted_at": ...}.
        reactions: PR reactions: {"user": {"login": ...}, "content": ..., "created_at": ...}.
        comments: PR issue comments: {"id": ..., "user": {"login": ...}, "created_at": ...,
            "updated_at": ..., "body": ...}; only a `codex-review-receipt:v1` for head counts.
    """
    fresh_review = any(_counts_review(r, cutoff, head_sha) for r in reviews)
    fresh_thumb = any(_counts_thumb(r, cutoff) for r in reactions)
    fresh_receipt = any(_counts_receipt(c, cutoff, head_sha) for c in comments or [])
    return "pass" if fresh_review or fresh_thumb or fresh_receipt else "wait"


@dataclass(frozen=True)
class Activity:
    """One Codex-authored item seen after the cutoff — a line of the breakdown."""

    channel: str  # "review" | "reaction" | "comment"
    at: str  # the timestamp that put the item after the cutoff
    detail: str  # id, markers, SHAs and why the item did or did not count
    accepted: bool  # the item's own `_counts_*` verdict — never a second copy of the rule


# Every `<!-- codex-… -->` marker, known or not, named in full up to the next space or `-->`: an
# unknown one is exactly what the breakdown is for, so `…:v1-beta` must not read as `…:v1`.
_ANY_MARKER = re.compile(r"<!--\s*(codex-[^\s>]+?)(?=\s|-->)")
# Diagnostics only: the `Reviewed commit` value whatever its shape, to say it is unreadable.
_ANY_REVIEWED_COMMIT = re.compile(r"\*\*Reviewed commit:\*\*\s*`(?P<value>[^`\n]*)`")
_REVIEW_STATE = re.compile(r"<!--\s*codex-review-state:v1\s*(?P<json>\{.*?\})\s*-->", re.DOTALL)
_SHORT_SHA = 10


def _review_state(body: str) -> str | None:
    """Return "<sha> <status>" from the summary comment's `codex-review-state:v1`, if it parses."""
    match = _REVIEW_STATE.search(body)
    if not match:
        return None
    try:
        state = json.loads(match.group("json"))
    except json.JSONDecodeError:
        return None
    code_review = state.get("code_review") if isinstance(state, dict) else None
    if not isinstance(code_review, dict):
        return None
    sha, status = code_review.get("commit_sha"), code_review.get("status")
    if not isinstance(sha, str) or not isinstance(status, str):
        return None
    return f"{sha[:_SHORT_SHA]} {status}"


def _receipt_note(sha: str, head_sha: str, accepted: bool) -> str:
    if accepted:
        return "head ✓"
    if len(sha) < _MIN_SHA_PREFIX:
        return "too short"
    if not head_sha.startswith(sha):
        return "not head"
    return "too old"


def _unread_receipt_note(body: str, markers: list[str]) -> str | None:
    """Why a receipt-looking comment yielded no reviewed commit, or None if it is not one."""
    if _RECEIPT_MARKER.search(body):
        line = _ANY_REVIEWED_COMMIT.search(body)
        return f"unrecognised Reviewed commit `{line.group('value')}`" if line else "no Reviewed commit line"
    if any(marker.startswith("codex-review-receipt") for marker in markers):
        return "not a v1 receipt"
    return None


def _comment_detail(comment: dict, cutoff: str, head_sha: str, accepted: bool) -> str:
    body = comment.get("body") or ""
    markers = _ANY_MARKER.findall(body)
    parts = [f"{comment.get('id')}", ", ".join(markers) or "no codex marker"]
    sha = receipt_sha(body)
    if sha is not None:
        parts.append(f"reviewed {sha} ({_receipt_note(sha, head_sha, accepted)})")
    elif (note := _unread_receipt_note(body, markers)) is not None:
        parts.append(note)
    state = _review_state(body)
    if state is not None:
        parts.append(f"state {state}")
    if (comment.get("created_at") or "") <= cutoff:
        parts.append("edited")
    return " ".join(parts)


def codex_activity(
    cutoff: str,
    head_sha: str,
    reviews: list[dict],
    reactions: list[dict],
    comments: list[dict],
) -> list[Activity]:
    """List what Codex did after the cutoff, in channel order: reviews, reactions, comments.

    A comment counts as activity when it was created *or* edited after the cutoff — the summary
    comment is only ever edited — but `accepted` is the same rule `decide` applies.
    """
    activity: list[Activity] = []
    for review in reviews:
        submitted = review.get("submitted_at") or ""
        if _codex_login(review) and submitted > cutoff:
            accepted = _counts_review(review, cutoff, head_sha)
            commit = (review.get("commit_id") or "?")[:_SHORT_SHA]
            detail = f"{commit} ({'head ✓' if accepted else 'not head'})"
            activity.append(Activity("review", submitted, detail, accepted))
    for reaction in reactions:
        created = reaction.get("created_at") or ""
        if _codex_login(reaction) and created > cutoff:
            accepted = _counts_thumb(reaction, cutoff)
            detail = f"{reaction.get('content')}{' ✓' if accepted else ''}"
            activity.append(Activity("reaction", created, detail, accepted))
    for comment in comments:
        created, updated = comment.get("created_at") or "", comment.get("updated_at") or ""
        if _codex_login(comment) and (created > cutoff or updated > cutoff):
            accepted = _counts_receipt(comment, cutoff, head_sha)
            at = created if created > cutoff else updated
            activity.append(Activity("comment", at, _comment_detail(comment, cutoff, head_sha, accepted), accepted))
    return activity


def format_breakdown(cutoff: str, activity: list[Activity]) -> str:
    """One log line per poll: what each channel showed since the cutoff."""
    sections = []
    for channel, label in (("review", "reviews"), ("reaction", "reactions"), ("comment", "comments")):
        items = [f"{a.detail} at {a.at}" for a in activity if a.channel == channel]
        sections.append(f"{label}: {'; '.join(items) if items else 'none'}")
    return f"Codex since {cutoff}: " + " · ".join(sections)


_RERUN_HINT = "Re-run this job once Codex finishes — the codex-nudge marker means it will not be asked twice."


def timeout_report(cutoff: str, head_sha: str, minutes: int, activity: list[Activity]) -> list[str]:
    """The lines to print at the deadline; the last one is the single-line `::error::` annotation.

    "Codex was silent" and "Codex was active but left nothing the gate accepts" are different
    failures — the second one is what a change in Codex's signalling looks like.
    """
    if not activity:
        return [f"::error::Codex has not reviewed {head_sha} within {minutes} min. {_RERUN_HINT}"]
    return [
        f"Codex was active on this PR after the nudge ({cutoff}) but left nothing the gate accepts"
        f" as a review of {head_sha}:",
        *(f"  - {a.channel} {a.detail} at {a.at}" for a in activity),
        f"::error::Codex was active but left no review of {head_sha} that the gate recognises within"
        f" {minutes} min — its signalling may have changed, see the Codex activity listed above. {_RERUN_HINT}",
    ]


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
    """CLI entry point: four modes over one module of gate knowledge."""
    parser = argparse.ArgumentParser(description="review-gate decision and marker bookkeeping")
    sub = parser.add_subparsers(dest="command", required=True)

    decide_parser = sub.add_parser(
        "decide", help="Read reviews/reactions/comments JSON from stdin, print pass/wait (breakdown on stderr)."
    )
    decide_parser.add_argument("--cutoff", required=True)
    decide_parser.add_argument("--head-sha", required=True)

    report_parser = sub.add_parser("timeout-report", help="Read the same JSON from stdin, print the deadline error.")
    report_parser.add_argument("--cutoff", required=True)
    report_parser.add_argument("--head-sha", required=True)
    report_parser.add_argument("--minutes", required=True, type=int)

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
    reviews, reactions = payload.get("reviews", []), payload.get("reactions", [])
    comments = payload.get("comments", [])
    activity = codex_activity(args.cutoff, args.head_sha, reviews, reactions, comments)

    if args.command == "timeout-report":
        print("\n".join(timeout_report(args.cutoff, args.head_sha, args.minutes, activity)))
        return 0

    # stdout carries the verdict and nothing else: the workflow compares it to the exact string
    # `pass`, so the breakdown goes to stderr — which lands in the Actions log all the same.
    print(format_breakdown(args.cutoff, activity), file=sys.stderr)
    print(decide(args.cutoff, args.head_sha, reviews, reactions, comments))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
