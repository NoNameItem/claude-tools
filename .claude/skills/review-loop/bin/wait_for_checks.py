#!/usr/bin/env python3
"""Block until the whole check pipeline for an exact PR head SHA is terminal.

Contract:
    wait_for_checks.py <PR> <HEAD_SHA>

Polls `gh` until every check for HEAD_SHA has settled, using the two review
gates as guaranteed-present anchors so it never concludes on a not-yet-started
(empty) check set:

  - Anchor 1  claude-review : check-run `claude-review` exists and is `completed`.
  - Anchor 2  review-gate   : commit status `review-gate` exists and its state is
                              terminal (success | failure | error).
  - Rest       : every other check-run is `completed` AND the combined commit
                 status state is not `pending`.

On success prints one line per signal (`<name/context> <conclusion/state>`) and
exits 0. On timeout exits 2 so the caller can ask the user instead of hanging.

Only stdlib + the authenticated `gh` CLI are used. WAIT_INTERVAL (default 30s)
and WAIT_TIMEOUT (default 900s) are env-overridable (tests set them small). PR
is accepted for contract symmetry; the wait keys only on HEAD_SHA.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ANCHOR_CHECK_RUN = "claude-review"
ANCHOR_STATUS = "review-gate"
TERMINAL_STATUS_STATES = {"success", "failure", "error"}
EXPECTED_ARGC = 2


# `gh` is the trusted, project-required CLI (this skill's whole contract is built on
# it); args passed to it are fixed literals/SHAs, never external/attacker input.


def _gh_json(args: list[str]) -> dict:
    out = subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603, S607
    return json.loads(out) if out else {}


def _repo() -> str:
    args = ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603


def _snapshot(repo: str, sha: str) -> tuple[list[dict], list[dict], str]:
    runs = _gh_json(["api", f"repos/{repo}/commits/{sha}/check-runs?per_page=100"])
    check_runs = runs.get("check_runs", []) if isinstance(runs, dict) else []
    status = _gh_json(["api", f"repos/{repo}/commits/{sha}/status"])
    statuses = status.get("statuses", []) if isinstance(status, dict) else []
    combined = status.get("state", "pending") if isinstance(status, dict) else "pending"
    return check_runs, statuses, combined


def _pipeline_terminal(check_runs: list[dict], statuses: list[dict], combined: str) -> bool:
    claude = next((r for r in check_runs if r.get("name") == ANCHOR_CHECK_RUN), None)
    if claude is None or claude.get("status") != "completed":
        return False
    gate = next((s for s in statuses if s.get("context") == ANCHOR_STATUS), None)
    if gate is None or gate.get("state") not in TERMINAL_STATUS_STATES:
        return False
    if any(r.get("status") != "completed" for r in check_runs):
        return False
    return combined != "pending"


def _emit(check_runs: list[dict], statuses: list[dict]) -> None:
    for r in check_runs:
        print(f"{r.get('name')} {r.get('conclusion')}")
    for s in statuses:
        print(f"{s.get('context')} {s.get('state')}")


def main(argv: list[str]) -> int:
    if len(argv) != EXPECTED_ARGC:
        sys.stderr.write("usage: wait_for_checks.py <PR> <HEAD_SHA>\n")
        return 2
    _pr, sha = argv
    interval = float(os.environ.get("WAIT_INTERVAL", "30"))
    timeout = float(os.environ.get("WAIT_TIMEOUT", "900"))
    repo = _repo()
    deadline = time.monotonic() + timeout
    while True:
        check_runs, statuses, combined = _snapshot(repo, sha)
        if _pipeline_terminal(check_runs, statuses, combined):
            _emit(check_runs, statuses)
            return 0
        if time.monotonic() >= deadline:
            sys.stderr.write(f"timeout: pipeline for {sha} not terminal after {timeout:.0f}s\n")
            return 2
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
