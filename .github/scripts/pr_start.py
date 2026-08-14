#!/usr/bin/env python3
"""Decide whether a push on a PR announces itself, and build that announcement.

Two questions, both answered from the `pr-notify-anchor` commit status and nothing else:

* Does the *previous* head's thread still owe a reply? (`msg:<id>` without ` replied` on
  `github.event.before` — its run announced a push and was superseded before anything answered.)
  Then close it with a *Superseded by …* reply, which is the whole of `claude-tools-5vg.16`.
* Does *this* head already have a start message? Then this is a re-run or a reopen; stay silent.

Keeping this out of shell is what makes the count threshold, the character budget and the
rewritten-history wording testable without a network — the same reason `pr_summary.py` exists.

Usage:
    python3 pr_start.py plan --action=synchronize --head-marker="" --before-marker="msg:99"
    python3 pr_start.py spec --head-sha=… --title=… --url=… --footer=… [--rewritten-history]
        < compare.json

Output (stdout):
    plan  {"send_start": bool, "supersede_message_id": int|null, "reason": str}
    spec  the notify spec consumed by .github/actions/telegram-notify
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass

# `msg:<id>` optionally followed by ` replied`, written by pr.yml's notify-start and appended to
# by _reusable-pr-summary.yml once the thread has been answered.
_MARKER = re.compile(r"\bmsg:(?P<id>\d+)(?P<replied>\s+replied)?")

# Up to five commits are shown expanded; beyond that the block arrives collapsed, because a
# notification is a summary and a 40-commit list is a diff.
_MAX_EXPANDED_COMMITS = 5

# Same budgets, and for the same reason, as release_notes.py: Telegram's `sendRichMessage` allows
# 32768 rendered characters and 500 blocks, and the rest of this message (heading, verdict,
# footer) has to fit under the same cap.
_TEXT_BUDGET = 30000
_ELEMENT_BUDGET = 400

_SHORT_SHA = 7


@dataclass(frozen=True)
class Marker:
    """The parsed `pr-notify-anchor` description."""

    message_id: int | None
    replied: bool


@dataclass(frozen=True)
class StartPlan:
    """What notify-start should do for this event."""

    send_start: bool
    supersede_message_id: int | None
    reason: str


def parse_marker(description: str | None) -> Marker:
    """Parse a `pr-notify-anchor` description.

    A missing, empty or corrupt marker yields ``Marker(None, False)`` rather than raising: a
    bookkeeping typo must never cost a notification.
    """
    match = _MARKER.search(description or "")
    if not match:
        return Marker(message_id=None, replied=False)
    return Marker(message_id=int(match.group("id")), replied=bool(match.group("replied")))


def plan(action: str, head_marker: str, before_marker: str) -> StartPlan:
    """Decide the start-side behaviour for one `pull_request` event.

    Args:
        action: `github.event.action` — only `synchronize` carries a meaningful `before`.
        head_marker: the `pr-notify-anchor` description on the current head SHA.
        before_marker: the same status on `github.event.before` (empty for other actions).
    """
    previous = parse_marker(before_marker)
    supersede = (
        previous.message_id if action == "synchronize" and previous.message_id and not previous.replied else None
    )

    current = parse_marker(head_marker)
    if current.message_id is not None:
        return StartPlan(send_start=False, supersede_message_id=supersede, reason="already-announced")
    return StartPlan(send_start=True, supersede_message_id=supersede, reason="announce")


def _commit_items(commits: list[dict]) -> tuple[list[list[dict]], int]:
    """Render the commit list within budget.

    Returns the item segments and how many commits were dropped. Assembly stops at an element
    boundary — never mid-item — so the rendered markup can't end inside a tag.
    """
    items: list[list[dict]] = []
    visible = 0
    # Two elements are reserved up front: the `<ul>` container, and the possible "… more" item.
    elements = 2

    for index, commit in enumerate(commits):
        sha = str(commit.get("sha") or "")[:_SHORT_SHA]
        subject = str(commit.get("subject") or "")
        if visible + len(sha) + 1 + len(subject) > _TEXT_BUDGET or elements + 1 > _ELEMENT_BUDGET:
            return items, len(commits) - index
        items.append([{"text": sha, "code": True}, {"text": f" {subject}"}])
        visible += len(sha) + 1 + len(subject)
        elements += 1

    return items, 0


def build_spec(
    head_sha: str,
    commits: list[dict],
    rewritten_history: bool,
    title: str,
    url: str,
    footer: str,
) -> dict:
    """Assemble the *checks running* notification for a push."""
    items, dropped = _commit_items(commits)
    if dropped:
        items.append([{"text": f"… and {dropped} more commits"}])

    verdict: list[dict] = [
        {"text": "New commit "},
        {"text": head_sha[:_SHORT_SHA], "code": True},
        {"text": ", checks running"},
    ]
    if rewritten_history:
        # The anchor commit vanished in a rebase (or this is the first push), so the list was
        # built from the base — say so rather than implying these commits are new.
        verdict.append({"text": " · history rewritten, commits listed from the base"})

    blocks: list[dict] = []
    if items:
        blocks.append(
            {
                "type": "list",
                "title": f"Commits: {len(commits)}",
                "open": len(commits) <= _MAX_EXPANDED_COMMITS,
                "items": items,
            }
        )

    return {
        "status": "started",
        "title": title,
        "verdict": verdict,
        "blocks": blocks,
        "footer": footer,
        "buttons": [{"text": "Pull request", "url": url}],
        "silent": True,
        "reply_to": None,
    }


def main() -> int:
    """CLI entrypoint. Always returns 0 — silence is a normal outcome."""
    parser = argparse.ArgumentParser(description="Plan and build the PR start notification.")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_parser = sub.add_parser("plan", help="Decide whether to announce, and what to supersede.")
    plan_parser.add_argument("--action", required=True)
    plan_parser.add_argument("--head-marker", default="")
    plan_parser.add_argument("--before-marker", default="")

    spec_parser = sub.add_parser("spec", help="Build the notify spec from a commit list on stdin.")
    spec_parser.add_argument("--head-sha", required=True)
    spec_parser.add_argument("--title", required=True)
    spec_parser.add_argument("--url", required=True)
    spec_parser.add_argument("--footer", required=True)
    spec_parser.add_argument("--rewritten-history", action="store_true")

    args = parser.parse_args()

    if args.command == "plan":
        decision = plan(args.action, args.head_marker, args.before_marker)
        print(
            json.dumps(
                {
                    "send_start": decision.send_start,
                    "supersede_message_id": decision.supersede_message_id,
                    "reason": decision.reason,
                }
            )
        )
        return 0

    payload = json.load(sys.stdin)
    spec = build_spec(
        head_sha=args.head_sha,
        commits=payload.get("commits", []),
        rewritten_history=args.rewritten_history,
        title=args.title,
        url=args.url,
        footer=args.footer,
    )
    print(json.dumps(spec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
