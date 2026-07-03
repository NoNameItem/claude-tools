"""Tests for review_gate.py decision logic."""

from __future__ import annotations

from ..review_gate import CODEX_BOT, decide

HEAD = "head1234"
CUTOFF = "2026-07-01T10:00:00Z"  # push / base-change time, or head committer date
BEFORE = "2026-07-01T09:00:00Z"  # earlier than the cutoff
AFTER = "2026-07-01T11:00:00Z"  # later than the cutoff


def _review(commit_id, submitted_at, login=CODEX_BOT):
    return {"user": {"login": login}, "commit_id": commit_id, "submitted_at": submitted_at}


def _thumb(created_at, content="+1", login=CODEX_BOT):
    return {"user": {"login": login}, "content": content, "created_at": created_at}


class TestDecide:
    """Unified freshness check: evidence (review@head or 👍) must be newer than the cutoff."""

    def test_fresh_thumb_passes(self):
        assert decide(CUTOFF, HEAD, [], [_thumb(AFTER)]) == "pass"

    def test_fresh_review_at_head_passes(self):
        assert decide(CUTOFF, HEAD, [_review(HEAD, AFTER)], []) == "pass"

    def test_stale_thumb_waits(self):
        # A 👍 older than the cutoff (lingering after a push, or from an earlier head on
        # ready_for_review) must be rejected — closes Codex #96 C3/C4.
        assert decide(CUTOFF, HEAD, [], [_thumb(BEFORE)]) == "wait"

    def test_stale_review_at_head_waits(self):
        # A review pinned to head but submitted before the cutoff (e.g. before a base change)
        # is stale — closes Codex #96 C1.
        assert decide(CUTOFF, HEAD, [_review(HEAD, BEFORE)], []) == "wait"

    def test_no_evidence_waits(self):
        assert decide(CUTOFF, HEAD, [], []) == "wait"

    def test_review_wrong_sha_waits(self):
        assert decide(CUTOFF, HEAD, [_review("other", AFTER)], []) == "wait"

    def test_non_codex_thumb_ignored(self):
        assert decide(CUTOFF, HEAD, [], [_thumb(AFTER, login="nope")]) == "wait"

    def test_non_codex_review_ignored(self):
        assert decide(CUTOFF, HEAD, [_review(HEAD, AFTER, login="nope")], []) == "wait"

    def test_pending_review_none_submitted_at_waits(self):
        # A pending Codex review has submitted_at: null — must be "wait", not a TypeError.
        assert decide(CUTOFF, HEAD, [_review(HEAD, None)], []) == "wait"

    def test_thumb_none_created_at_waits(self):
        assert decide(CUTOFF, HEAD, [], [_thumb(None)]) == "wait"

    def test_fresh_review_and_stale_thumb_passes(self):
        # The fresh SHA-pinned review carries it even if a stale 👍 is present.
        assert decide(CUTOFF, HEAD, [_review(HEAD, AFTER)], [_thumb(BEFORE)]) == "pass"


class TestCli:
    """main(): reads reviews/reactions JSON on stdin, prints pass/wait."""

    def _run(self, payload, *args):
        import json
        import subprocess
        import sys
        from pathlib import Path

        script = Path(__file__).resolve().parent.parent / "review_gate.py"
        return subprocess.run(
            [sys.executable, str(script), *args],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def test_cli_pass(self):
        payload = {"reviews": [], "reactions": [_thumb(AFTER)]}
        out = self._run(payload, "--cutoff", CUTOFF, "--head-sha", HEAD)
        assert out == "pass"

    def test_cli_wait(self):
        payload = {"reviews": [], "reactions": [_thumb(BEFORE)]}
        out = self._run(payload, "--cutoff", CUTOFF, "--head-sha", HEAD)
        assert out == "wait"
