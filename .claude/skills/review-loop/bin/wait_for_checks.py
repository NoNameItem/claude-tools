#!/usr/bin/env python3
"""Block until the whole check pipeline for an exact PR head SHA is terminal.

Contract:
    wait_for_checks.py <PR> <HEAD_SHA>

Polls `gh` until every check for HEAD_SHA has settled, using the two review
gates as guaranteed-present anchors so it never concludes on a partial view of
the pipeline (empty, or truncated below total_count):

  - Anchor 1  claude-review : check-run `claude-review` exists and is `completed`.
  - Anchor 2  review-gate   : commit status `review-gate` exists and its state is
                              terminal (success | failure | error).
  - Rest       : the check-runs view is complete (len >= total_count), every
                 check-run is `completed`, AND no commit-status context is still
                 `pending` (checked per-context, not via the combined state, which
                 ranks `failure` above `pending` and would mask a running one).

On success prints one line per signal (`<name/context> <conclusion/state>`) and
exits 0. Exits 2 on timeout (so the caller can ask the user instead of hanging),
1 on a usage error, and 3 when the branch head moved out from under the wait
(see below). A transient `gh`/JSON failure during a poll is treated as "not yet
terminal" and retried until the deadline, never crashing the wait.

Head-moved guard: the wait keys on HEAD_SHA, but once the pipeline for it is
terminal we re-fetch the PR's current head. If the branch advanced during the
wait (an external push, or this repo's periodic master auto-merge into the
branch), HEAD_SHA is stale — returning success would let the caller declare
convergence before the new head's checks/reviews register — so we exit 3 and the
caller re-captures HEAD and re-waits. If that re-fetch can't determine the head
(a transient `gh` failure), it is retried and, if still unknown, we exit 3 as
well rather than assume the head is unchanged. PR is used only for this re-check.

Only stdlib + the authenticated `gh` CLI are used. WAIT_INTERVAL (default 30s)
and WAIT_TIMEOUT (default 1800s / 30 min) are env-overridable (tests set them
small). WAIT_TIMEOUT is coupled to review-gate.yml's TIMEOUT — see
DEFAULT_WAIT_TIMEOUT below.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import NamedTuple

ANCHOR_CHECK_RUN = "claude-review"
ANCHOR_STATUS = "review-gate"
TERMINAL_STATUS_STATES = {"success", "failure", "error"}
EXPECTED_ARGC = 2
EXIT_USAGE = 1
EXIT_TIMEOUT = 2
EXIT_HEAD_MOVED = 3
HEAD_RECHECK_ATTEMPTS = 3  # tries for the final head re-fetch before failing safe

# Poll cadence and ceiling for the whole-pipeline wait. WAIT_INTERVAL / WAIT_TIMEOUT
# env vars override these (tests set them to 0). COUPLING INVARIANT (design §8):
# DEFAULT_WAIT_TIMEOUT MUST stay above review-gate.yml's TIMEOUT (1500s / 25 min)
# plus a margin — otherwise this local wait trips exit-2 (a false timeout) before the
# review-gate commit status settles. If you change one, change the other.
DEFAULT_WAIT_INTERVAL = 30
DEFAULT_WAIT_TIMEOUT = 1800  # 30 min = review-gate TIMEOUT (25 min) + 5 min margin


class Snapshot(NamedTuple):
    check_runs: list[dict]
    statuses: list[dict]
    complete: bool  # the check-runs view is not truncated (len >= total_count)


def _run_gh(args: list[str]) -> str:
    # gh is the trusted, project-required CLI; args are fixed literals/SHAs, never
    # external input. S603 (subprocess) / S607 (partial path) mirror the repo's
    # flow-* helper precedent.
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)  # noqa: S603, S607
    return proc.stdout.strip()


def _gh_pages(endpoint: str) -> list[dict]:
    """Fetch every page of a paginated endpoint. `--paginate --slurp` returns one
    array element per page; return that list of page objects."""
    out = _run_gh(["api", "--paginate", "--slurp", endpoint])
    data = json.loads(out) if out else []
    return data if isinstance(data, list) else [data]


def _repo() -> str:
    return _run_gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])


def _head_moved(pr: str, sha: str, interval: float) -> bool:
    """True when the PR's head is known to differ from `sha`, OR stayed unknown.

    The wait keys on the `sha` captured before polling; if the branch advances
    during the (up to 30-minute) wait — an external push, or this repo's periodic
    master auto-merge into the branch — returning success for the now-stale `sha`
    would let the caller count threads and declare convergence before the new
    head's checks/reviews have registered. So the recheck must fail *safe*: a
    transient `gh` failure is retried (`HEAD_RECHECK_ATTEMPTS`), and if the head is
    still unknown we return True (treated as moved) rather than assume it is
    unchanged — swallowing the error as "unchanged" would defeat this guard exactly
    when the branch may have moved. A confirmed-equal head returns False."""
    for attempt in range(HEAD_RECHECK_ATTEMPTS):
        try:
            current = _run_gh(["pr", "view", pr, "--json", "headRefOid", "-q", ".headRefOid"])
        except subprocess.CalledProcessError:
            if attempt + 1 < HEAD_RECHECK_ATTEMPTS:
                time.sleep(interval)
                continue
            return True  # head unknown after retries -> fail safe (re-wait)
        else:
            return bool(current) and current != sha
    return True


def _snapshot(repo: str, sha: str) -> Snapshot:
    # Fetch ALL check-run pages and merge them so the completeness check below sees
    # the whole set — a head with >100 check-runs would otherwise look permanently
    # truncated (len < total_count) and never go terminal.
    pages = _gh_pages(f"repos/{repo}/commits/{sha}/check-runs?per_page=100")
    check_runs = [cr for pg in pages if isinstance(pg, dict) for cr in pg.get("check_runs", [])]
    total = next(
        (pg["total_count"] for pg in pages if isinstance(pg, dict) and "total_count" in pg),
        len(check_runs),
    )
    # Paginate the combined-status endpoint too and merge every page's `statuses`:
    # `_pipeline_terminal` gates on the per-context states, so a head with >100
    # status contexts would otherwise hide a later-page `pending` context and look
    # terminal early (same failure mode the check-runs pagination above prevents).
    status_pages = _gh_pages(f"repos/{repo}/commits/{sha}/status?per_page=100")
    statuses = [s for pg in status_pages if isinstance(pg, dict) for s in pg.get("statuses", [])]
    return Snapshot(check_runs, statuses, len(check_runs) >= total)


def _pipeline_terminal(snap: Snapshot) -> bool:
    if not snap.complete:
        return False
    claude = next((r for r in snap.check_runs if r.get("name") == ANCHOR_CHECK_RUN), None)
    if claude is None or claude.get("status") != "completed":
        return False
    gate = next((s for s in snap.statuses if s.get("context") == ANCHOR_STATUS), None)
    if gate is None or gate.get("state") not in TERMINAL_STATUS_STATES:
        return False
    if any(r.get("status") != "completed" for r in snap.check_runs):
        return False
    # A context can be `pending` while GitHub's *combined* state is already
    # `failure` (failure ranks above pending), so the combined state alone can't
    # prove every context settled. Gate on the individual contexts: terminal only
    # when none is still pending.
    return not any(s.get("state") == "pending" for s in snap.statuses)


def _emit(snap: Snapshot) -> None:
    for r in snap.check_runs:
        print(f"{r.get('name')} {r.get('conclusion')}")
    for s in snap.statuses:
        print(f"{s.get('context')} {s.get('state')}")


def main(argv: list[str]) -> int:
    if len(argv) != EXPECTED_ARGC:
        sys.stderr.write("usage: wait_for_checks.py <PR> <HEAD_SHA>\n")
        return EXIT_USAGE
    pr, sha = argv
    interval = float(os.environ.get("WAIT_INTERVAL", str(DEFAULT_WAIT_INTERVAL)))
    timeout = float(os.environ.get("WAIT_TIMEOUT", str(DEFAULT_WAIT_TIMEOUT)))
    deadline = time.monotonic() + timeout
    while True:
        # _repo() is inside the retry so a transient `gh` failure here is retried
        # until the deadline (exit 2), never an uncaught crash (which exits 1 —
        # the caller's usage-error code).
        try:
            snap: Snapshot | None = _snapshot(_repo(), sha)
        except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"warning: gh poll failed ({exc}); retrying until deadline\n")
            snap = None
        if snap is not None and _pipeline_terminal(snap):
            # The pipeline for `sha` is terminal, but re-check the PR head first: if the
            # branch advanced while we polled, `sha` is stale and success would be a lie.
            if _head_moved(pr, sha, interval):
                sys.stderr.write(
                    f"head moved: PR #{pr} head is no longer {sha}; caller should re-capture HEAD and re-wait\n"
                )
                return EXIT_HEAD_MOVED
            _emit(snap)
            return 0
        if time.monotonic() >= deadline:
            sys.stderr.write(f"timeout: pipeline for {sha} not terminal after {timeout:.0f}s\n")
            return EXIT_TIMEOUT
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
