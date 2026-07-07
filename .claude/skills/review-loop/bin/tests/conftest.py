"""Local smoke-test harness for the review-loop helper.

Not run in CI (see the plan's decision #2) — run manually with:
    uv run pytest .claude/skills/review-loop/bin/tests
"""

# INP001: this test dir is an implicit namespace package (no __init__.py, matching
# plugins/flow/bin/tests/). Adding __init__.py to satisfy INP001 would change how
# `conftest` is imported by these tests, so the suppression is intentional.
# ruff: noqa: INP001

import subprocess
import sys
from pathlib import Path

import pytest

HELPER = Path(__file__).parent.parent / "wait_for_checks.py"


def run_helper(*args, env=None):
    """Run wait_for_checks.py via the current interpreter; return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.fixture
def fake_gh(tmp_path):
    """Write a fake `gh` on PATH that serves canned check-runs/status fixtures.

    Fixtures live in a state dir as files named `<sha>.check-runs.<phase>.json`
    and `<sha>.status.<phase>.json`, where <phase> is `pending` or `terminal`.
    A `flip_after` int (default 0) makes the fake serve `pending` for the first
    N check-runs polls, then `terminal` — so a test can prove the helper loops.
    """
    state = tmp_path / "gh-state"
    state.mkdir()
    (state / "count").write_text("0")
    (state / "flip_after").write_text("0")
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"STATE = Path({str(state)!r})\n"
        "a = sys.argv[1:]\n"
        "if a[:2] == ['repo', 'view']:\n"
        "    sys.stdout.write('o/r')\n"
        "    sys.exit(0)\n"
        "if a[:2] == ['pr', 'view']:\n"
        # Count every pr-view call (so a test can assert the recheck retried) and,
        # if a test armed `pr_view_fail`, simulate a transient `gh pr view` outage:
        # a positive N fails the next N calls; a negative N fails every call.
        "    calls = int((STATE / 'pr_view_calls').read_text()) if (STATE / 'pr_view_calls').exists() else 0\n"
        "    (STATE / 'pr_view_calls').write_text(str(calls + 1))\n"
        "    fp = STATE / 'pr_view_fail'\n"
        "    if fp.exists():\n"
        "        n = int(fp.read_text())\n"
        "        if n != 0:\n"
        "            if n > 0:\n"
        "                fp.write_text(str(n - 1))\n"
        "            sys.exit(1)\n"
        # headRefOid lookup: serve pr_head if a test pinned one, else echo the last
        # polled sha (so the head 'follows' the sha and the recheck matches by default).
        "    head = (STATE / 'pr_head').read_text() if (STATE / 'pr_head').exists() else (\n"
        "        (STATE / 'last_sha').read_text() if (STATE / 'last_sha').exists() else '')\n"
        "    sys.stdout.write(head)\n"
        "    sys.exit(0)\n"
        "if a and a[0] == 'api':\n"
        "    ep = next((x for x in a if '/commits/' in x), '')\n"
        "    slurp = '--slurp' in a\n"
        "    sha = ep.split('/commits/')[1].split('/')[0]\n"
        "    (STATE / 'last_sha').write_text(sha)\n"
        "    kind = 'check-runs' if 'check-runs' in ep else 'status'\n"
        "    flip = int((STATE / 'flip_after').read_text())\n"
        "    def other(p):\n"
        "        return 'pending' if p == 'terminal' else 'terminal'\n"
        "    if kind == 'check-runs':\n"
        "        n = int((STATE / 'count').read_text()) + 1\n"
        "        (STATE / 'count').write_text(str(n))\n"
        "        phase = 'terminal' if n > flip else 'pending'\n"
        "        if not (STATE / f'{sha}.{kind}.{phase}.json').exists():\n"
        "            phase = other(phase)\n"
        "        (STATE / 'phase').write_text(phase)\n"
        "    else:\n"
        "        phase = (STATE / 'phase').read_text() if (STATE / 'phase').exists() else 'terminal'\n"
        "        if not (STATE / f'{sha}.{kind}.{phase}.json').exists():\n"
        "            phase = other(phase)\n"
        "    payload = (STATE / f'{sha}.{kind}.{phase}.json').read_text()\n"
        "    if slurp and not payload.lstrip().startswith('['):\n"
        "        payload = '[' + payload + ']'\n"
        "    sys.stdout.write(payload)\n"
        "    sys.exit(0)\n"
        "sys.exit(0)\n"
    )
    gh.chmod(0o755)

    class Ctl:
        dir = state

        def env(self):
            return {"PATH": f"{tmp_path}:/usr/bin:/bin", "WAIT_INTERVAL": "0", "WAIT_TIMEOUT": "0"}

        def write(self, sha, kind, phase, payload):
            (state / f"{sha}.{kind}.{phase}.json").write_text(payload)

        def set_flip_after(self, n):
            (state / "flip_after").write_text(str(n))

        def set_pr_head(self, sha):
            """Pin what `gh pr view --json headRefOid` returns (simulates the branch
            head moving to a new commit while the helper polls)."""
            (state / "pr_head").write_text(sha)

        def set_pr_view_fail(self, n):
            """Make the fake `gh pr view` exit non-zero for the next n calls (n < 0
            = every call), simulating a transient GitHub API outage during the head
            recheck."""
            (state / "pr_view_fail").write_text(str(n))

    return Ctl()


# --- fixture builders -------------------------------------------------------


def check_runs(*runs, total_count=None):
    """Build a /check-runs response body. Each run is (name, status, conclusion).

    total_count defaults to the number of runs (a complete page); pass a larger
    value to simulate a truncated page.
    """
    import json

    items = [{"name": n, "status": s, "conclusion": c} for (n, s, c) in runs]
    tc = total_count if total_count is not None else len(items)
    return json.dumps({"check_runs": items, "total_count": tc})


def commit_status(state, *statuses):
    """Build a /status response body. Each status is (context, state)."""
    import json

    return json.dumps({"state": state, "statuses": [{"context": ctx, "state": st} for (ctx, st) in statuses]})
