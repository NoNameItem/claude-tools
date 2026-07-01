"""Tests for review_gate.py decision logic."""

from __future__ import annotations

from ..review_gate import CODEX_BOT, decide

HEAD = "head1234"
CUTOFF = "2026-07-01T10:00:00Z"  # the event's updated_at
BEFORE = "2026-07-01T09:00:00Z"  # earlier than the cutoff
AFTER = "2026-07-01T11:00:00Z"  # later than the cutoff


def _review(commit_id, submitted_at, login=CODEX_BOT):
    return {"user": {"login": login}, "commit_id": commit_id, "submitted_at": submitted_at}


def _thumb(created_at, content="+1", login=CODEX_BOT):
    return {"user": {"login": login}, "content": content, "created_at": created_at}


class TestContentChange:
    """opened / synchronize / base-change: evidence must be newer than the cutoff."""

    def test_fresh_thumb_passes(self):
        assert decide("synchronize", False, CUTOFF, HEAD, [], [_thumb(AFTER)]) == "pass"

    def test_fresh_review_at_head_passes(self):
        assert decide("synchronize", False, CUTOFF, HEAD, [_review(HEAD, AFTER)], []) == "pass"

    def test_stale_thumb_waits(self):
        # Lingering 👍 from before the push must be rejected.
        assert decide("synchronize", False, CUTOFF, HEAD, [], [_thumb(BEFORE)]) == "wait"

    def test_no_evidence_waits(self):
        assert decide("opened", False, CUTOFF, HEAD, [], []) == "wait"

    def test_review_wrong_sha_waits(self):
        assert decide("synchronize", False, CUTOFF, HEAD, [_review("other", AFTER)], []) == "wait"

    def test_non_codex_thumb_ignored(self):
        assert decide("synchronize", False, CUTOFF, HEAD, [], [_thumb(AFTER, login="nope")]) == "wait"


class TestBaseChange:
    """edited + base change: an old review pinned to head is stale and must not pass."""

    def test_stale_review_at_head_waits(self):
        assert decide("edited", True, CUTOFF, HEAD, [_review(HEAD, BEFORE)], [_thumb(BEFORE)]) == "wait"

    def test_fresh_review_after_base_change_passes(self):
        assert decide("edited", True, CUTOFF, HEAD, [_review(HEAD, AFTER)], []) == "pass"

    def test_edited_without_base_change_treated_as_non_content(self):
        # is_base_change=False -> non-content-change; existing evidence passes.
        # (The workflow `if:` filters this event out, but decide() stays total.)
        assert decide("edited", False, CUTOFF, HEAD, [], [_thumb(BEFORE)]) == "pass"


class TestNonContentChange:
    """reopened / ready_for_review: no new content, so existing evidence stays valid (fix #1)."""

    def test_reopened_with_stale_but_valid_thumb_passes(self):
        # The #1 regression: updated_at is inflated, but the 👍 is still valid.
        assert decide("reopened", False, CUTOFF, HEAD, [], [_thumb(BEFORE)]) == "pass"

    def test_ready_for_review_with_review_at_head_passes(self):
        assert decide("ready_for_review", False, CUTOFF, HEAD, [_review(HEAD, BEFORE)], []) == "pass"

    def test_reopened_no_evidence_waits(self):
        assert decide("reopened", False, CUTOFF, HEAD, [], []) == "wait"
