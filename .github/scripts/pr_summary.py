#!/usr/bin/env python3
"""Decide whether a PR's required checks have settled, and build the Telegram notify spec.

Pure decision function for `_reusable-pr-summary.yml`, mirroring the review_gate.py split:
bash does the I/O (`gh api`), this script decides. The workflow pipes a rollup of the head
SHA's commit statuses and check runs, the required contexts read from the `master` ruleset,
the unresolved-thread count and the reply anchor; the script prints one JSON document saying
whether to send and, if so, exactly what the message contains.

There is exactly ONE producer of the result message now: `pr.yml`'s `pr-summary` job, which sits
on `needs` of every gate. The second call site (review-gate.yml, a separate `pull_request_target`
run that could not observe this one) is gone, and with it the "which verdict was already reported"
record that arbitrated between them — a record that broke three times in review, always by turning
into silence where a reply was owed.

Two `send=False` branches remain load-bearing rather than vestigial:

* `stale-head` — the gate's poll exits within one interval once the PR advances, but it exits
  *successfully*, so this job still runs for a SHA that is no longer the head. This branch is what
  keeps that run silent; the abandoned thread is closed by the new push's *Superseded* reply, not
  by this one. Do not remove it on the grounds that there is only one speaker now: the speaker can
  be speaking for a commit that no longer exists.
* `waiting` — a required context that is `pending` or `missing`. `needs` makes it unreachable for a
  context this workflow produces, but the required list comes from the ruleset, not from the
  workflow: any context the ruleset names and nothing publishes reads as `missing`. That is exactly
  the window between merging this branch and swapping the required context from `review-gate` to
  `Review Gate` (docs/merge-gate-rollout.md, Step 2a), and staying silent through it is correct —
  a verdict computed from a required list we cannot satisfy would be a guess.

Re-notification on thread resolution was designed for this module (a "crossing mode" that spoke
only when the unresolved count crossed zero) and removed unbuilt: GitHub Actions has no
`pull_request_review_thread` trigger, so nothing can call it. See claude-tools-5vg.17.

The one marker that remains is `pr-notify-anchor` (`msg:<id>`, rewritten to `msg:<id> replied`
once this job has answered): it names the newest "checks running" message so the result can reply
into that thread, and its `replied` half tells the next push whether that thread still owes an
answer. Absent — notify-start has not run, or its Telegram send failed — the result is simply sent
standalone.

Usage:
    python3 pr_summary.py --title "…" --url "…" --footer "…" [--checks-url "…"] < payload.json

Output (stdout):
    {"send": bool, "reason": str, "verdict": str, "message_id": int|null, "spec": {…}}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field

# Commit-status states. Anything outside TERMINAL means "still running".
_TERMINAL_STATUS_STATES = frozenset({"success", "failure", "error"})
_GOOD_STATUS_STATES = frozenset({"success"})

# check-run conclusions. A run is terminal once `status == "completed"`; the conclusion then
# decides. `neutral`/`skipped` are green by construction: a skipped reusable-workflow call is
# how a gate job reports "nothing to do here".
_GOOD_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})

# Contexts that only exist for same-repo PRs. Belt-and-braces now: both entry points carry a fork
# guard, so this job does not run for a fork at all — but the required list is read from the
# ruleset, which does require `Review Gate`, and a fork's wrapper deliberately fails.
_SAME_REPO_ONLY = frozenset({"Review Gate"})

_ANCHOR_PATTERN = re.compile(r"\bmsg:(\S+)")

# Icon per resolved state. The validated check-table layout puts the context name in column 1
# and the icon alone, centred, in column 2 — so a state maps to an icon, not to a word.
_STATE_ICONS = {
    "success": "✅",
    "failure": "❌",
    "pending": "⏳",
    "missing": "❔",
}

# Cap the failed-jobs list so a catastrophic run can't produce a 500-block message.
_MAX_FAILED_JOBS = 20


@dataclass(frozen=True)
class CheckState:
    """One required context resolved against the head SHA's rollup."""

    context: str
    state: str  # "success" | "failure" | "pending" | "missing"
    url: str | None = None


@dataclass
class Decision:
    """The aggregator's answer: whether to speak, and what to say."""

    send: bool
    reason: str
    verdict: str = ""
    message_id: int | None = None
    states: list[CheckState] = field(default_factory=list)
    failed_contexts: list[str] = field(default_factory=list)
    failed_jobs: list[str] = field(default_factory=list)
    unresolved_threads: int = 0


def parse_anchor(description: str) -> int | None:
    """Parse the `pr-notify-anchor` commit-status description into a Telegram message id.

    Args:
        description: e.g. ``"msg:4711"`` or ``""``.

    Returns:
        The message id, or ``None`` when the marker is absent or unparsable. A non-integer id
        yields ``None`` rather than raising — a corrupt marker must degrade to "send without a
        reply", never crash the notification.
    """
    match = _ANCHOR_PATTERN.search(description or "")
    if not match or not match.group(1).isdigit():
        return None
    return int(match.group(1))


def _status_state(entry: dict) -> str:
    state = entry.get("state") or ""
    if state not in _TERMINAL_STATUS_STATES:
        return "pending"
    return "success" if state in _GOOD_STATUS_STATES else "failure"


def _check_run_state(entry: dict) -> str:
    if entry.get("status") != "completed":
        return "pending"
    return "success" if entry.get("conclusion") in _GOOD_CONCLUSIONS else "failure"


def _latest(entries: list[dict]) -> dict:
    """Pick the newest attempt for one check-run name.

    The check-runs endpoint defaults to `filter=latest`, and `_reusable-pr-summary.yml` calls it
    without a `filter` param — so on the call path this script actually has, each name already
    arrives as exactly one entry, and this function never actually chooses between attempts. The
    per-name grouping that feeds it (`by_run` in `collect_states` and `_failed_jobs`) is defensive,
    not load-bearing: it exists so this stays correct if the call is ever changed to `filter=all`,
    which surfaces every attempt of a re-run job. This function does not itself guarantee
    de-duplication of anything upstream of it — it only picks the winner among whatever entries
    it is given.

    Ranks a non-terminal (still-running) entry above any completed one, so an in-flight re-run
    supersedes a stale completed attempt rather than losing to it: a queued attempt has no
    `started_at`, so sorting on it alone would rank a queued re-run *below* an older completed
    run. Ties — including between two completed entries — are broken by `id`, which increases
    monotonically, so the newest attempt wins.
    """
    return max(entries, key=lambda e: (e.get("status") != "completed", e.get("id") or 0))


def collect_states(required: list[str], statuses: list[dict], check_runs: list[dict]) -> list[CheckState]:
    """Resolve each required context against the rollup, preserving the required order.

    Commit statuses win over check runs when a name collides. No required context is published as a
    commit status any more — `Review Gate` is a check run like the other three gates — but the
    precedence is kept: `pr-notify-anchor` and `codex-nudge` are statuses, and a future required
    status must not be shadowed by a same-named check run.
    """
    by_status = {entry.get("context"): entry for entry in statuses if entry.get("context")}
    by_run: dict[str, list[dict]] = {}
    for entry in check_runs:
        name = entry.get("name")
        if name:
            by_run.setdefault(name, []).append(entry)

    states: list[CheckState] = []
    for context in required:
        if context in by_status:
            entry = by_status[context]
            states.append(CheckState(context, _status_state(entry), entry.get("target_url")))
        elif context in by_run:
            entry = _latest(by_run[context])
            states.append(CheckState(context, _check_run_state(entry), entry.get("html_url")))
        else:
            states.append(CheckState(context, "missing", None))
    return states


def _failed_jobs(check_runs: list[dict]) -> list[str]:
    """Every check run whose LATEST attempt failed, deduplicated and sorted.

    Not limited to required contexts: the useful part of a failure notification is the child
    job that actually broke (`Python CI / SonarCloud (statuskit)`), not the gate that relayed it.
    Gate jobs are excluded because they are already named in the verdict line.

    The check-runs endpoint's `filter=latest` default (see `_latest`'s docstring) already
    collapses each name to a single entry before this script ever sees it, so on the call path
    this script actually has, a name is judged by its only entry. The `by_run`/`_latest` grouping
    here is defensive for the same reason `_latest` itself is: it keeps a job judged by its
    newest attempt if the caller is ever changed to pass `filter=all` — where a job that failed
    on attempt 1 and passed on re-run must not show up here.
    """
    by_run: dict[str, list[dict]] = {}
    for entry in check_runs:
        name = entry.get("name")
        if name:
            by_run.setdefault(name, []).append(entry)

    names = {
        name
        for name, entries in by_run.items()
        if _check_run_state(_latest(entries)) == "failure" and not name.endswith(" Gate")
    }
    return sorted(names)[:_MAX_FAILED_JOBS]


def decide(payload: dict) -> Decision:
    """Decide whether to notify for this head SHA, and with what verdict.

    Args:
        payload: The rollup document described in this module's docstring.

    Returns:
        A :class:`Decision`. ``send=False`` carries one of two reasons: ``stale-head`` (the PR
        advanced — this is the superseded gate poll) or ``waiting`` (a required context is missing
        or still running).
    """
    head_sha = payload.get("head_sha") or ""
    current = payload.get("current_head_sha") or ""
    message_id = parse_anchor(payload.get("anchor_description", ""))

    # A non-empty mismatch only. An empty `current` means the lookup failed; treating that as
    # "moved" would silence a real notification on a transient API blip.
    if current and head_sha and current != head_sha:
        return Decision(send=False, reason="stale-head", message_id=message_id)

    required = [
        context
        for context in payload.get("required_contexts", [])
        if not (payload.get("is_fork") and context in _SAME_REPO_ONLY)
    ]
    states = collect_states(required, payload.get("statuses", []), payload.get("check_runs", []))

    if any(state.state in {"pending", "missing"} for state in states):
        return Decision(send=False, reason="waiting", message_id=message_id, states=states)

    failed_contexts = [state.context for state in states if state.state == "failure"]
    unresolved = int(payload.get("unresolved_threads") or 0)
    if failed_contexts:
        verdict = "failed"
    elif unresolved > 0:
        verdict = "comments"
    else:
        verdict = "ready"

    # No duplicate check. Reaching this line means every required context is terminal, and that is
    # the single condition for speaking — see the module docstring for why the "which verdict was
    # already reported" record was removed rather than repaired.
    return Decision(
        send=True,
        reason="send",
        verdict=verdict,
        message_id=message_id,
        states=states,
        failed_contexts=failed_contexts,
        failed_jobs=_failed_jobs(payload.get("check_runs", [])) if failed_contexts else [],
        unresolved_threads=unresolved,
    )


def _verdict_segments(decision: Decision) -> list[dict]:
    """The one-line verdict, with bold on exactly the thing that needs attention."""
    if decision.verdict == "failed":
        segments: list[dict] = [{"text": "Checks failed: "}]
        for index, context in enumerate(decision.failed_contexts):
            if index:
                segments.append({"text": ", "})
            segments.append({"text": context, "bold": True})
        return segments
    if decision.verdict == "comments":
        # Count only — locations without the comment text are useless, and quoting the comments
        # in a notification is out of proportion.
        return [{"text": f"All checks passed, unresolved comments: {decision.unresolved_threads}"}]
    return [{"text": "Ready to merge"}]


def build_spec(decision: Decision, title: str, url: str, footer: str, checks_url: str | None) -> dict:
    """Assemble the notify spec (see the plan's shared contract) from a sendable decision."""
    # Bold the name, never the icon: the icon column already carries the colour.
    rows = [
        [
            {"text": state.context, "bold": state.state == "failure"},
            {"text": _STATE_ICONS[state.state], "align": "center"},
        ]
        for state in decision.states
    ]

    # On a failure the table is shown BARE so the red rows are the first thing visible; on a
    # green verdict it collapses behind its own summary.
    failed = decision.verdict == "failed"
    checks_block: dict = {"type": "table", "rows": rows}
    if not failed:
        checks_block["title"] = "All checks passed"
    blocks: list[dict] = [checks_block]
    if decision.failed_jobs:
        blocks.append(
            {
                "type": "list",
                "title": f"Failed jobs: {len(decision.failed_jobs)}",
                "open": True,
                "items": [[{"text": name, "bold": True}] for name in decision.failed_jobs],
            }
        )

    buttons = [{"text": "Pull request", "url": url}]
    if decision.verdict == "failed" and checks_url:
        buttons.append({"text": "Checks", "url": checks_url})

    return {
        "status": decision.verdict,
        "title": title,
        "verdict": _verdict_segments(decision),
        "blocks": blocks,
        "footer": footer,
        "buttons": buttons,
        "silent": False,
        "reply_to": decision.message_id,
    }


def main() -> int:
    """CLI entrypoint. Always returns 0 — a silent decision is a normal outcome."""
    parser = argparse.ArgumentParser(description="Decide the PR notification verdict.")
    parser.add_argument("--title", required=True, help="PR title (the message heading).")
    parser.add_argument("--url", required=True, help="PR html_url (the primary button).")
    parser.add_argument("--footer", required=True, help='Footer line, e.g. "claude-tools · PR 118".')
    parser.add_argument("--checks-url", default=None, help="PR checks tab URL (button on failure).")
    args = parser.parse_args()

    payload = json.load(sys.stdin)
    decision = decide(payload)

    result = {
        "send": decision.send,
        "reason": decision.reason,
        "verdict": decision.verdict,
        "message_id": decision.message_id,
        "spec": build_spec(decision, args.title, args.url, args.footer, args.checks_url) if decision.send else None,
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
