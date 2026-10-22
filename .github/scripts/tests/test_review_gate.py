"""Tests for review_gate.py decision logic."""

from __future__ import annotations

import pytest

from ..review_gate import CODEX_BOT, decide, format_nudge_marker, parse_nudge_marker, receipt_sha

HEAD = "head1234"
CUTOFF = "2026-07-01T10:00:00Z"  # push / base-change time, or head committer date
BEFORE = "2026-07-01T09:00:00Z"  # earlier than the cutoff
AFTER = "2026-07-01T11:00:00Z"  # later than the cutoff

# PR #151 as it stood when its gate timed out (claude-tools-5vg.31): the nudge cutoff from the
# codex-nudge marker, the head, and Codex's two comments — the receipt of the clean round and the
# summary comment it edits in place.
HEAD151 = "a84dae4d57dea301ea163a58897ed55335a5221d"
CUTOFF151 = "2026-10-21T22:29:55Z"
RECEIPT_AT = "2026-10-21T22:32:32Z"
RECEIPT_BODY = (
    "<!-- codex-review-receipt:v1 -->\n\nCodex Review: Didn't find any major issues. :rocket:\n\n"
    "**Reviewed commit:** `a84dae4d57`\n"
)
SUMMARY_BODY = (
    "<!-- codex-pull-request-review-summary -->\n"
    '<!-- codex-review-state:v1 {"code_review":{"commit_sha":"a84dae4d57dea301ea163a58897ed55335a5221d",'
    '"has_any_findings":true,"has_unresolved_findings":true,"status":"completed"},'
    '"security_review":{"commit_sha":null,"has_any_findings":null,"has_unresolved_findings":null,"status":null}} -->\n'
    "\n## Codex Review Summary\n"
)


def _review(commit_id, submitted_at, login=CODEX_BOT):
    return {"user": {"login": login}, "commit_id": commit_id, "submitted_at": submitted_at}


def _thumb(created_at, content="+1", login=CODEX_BOT):
    return {"user": {"login": login}, "content": content, "created_at": created_at}


def _comment(body, created_at, updated_at=None, login=CODEX_BOT, comment_id=6328012482):
    return {
        "id": comment_id,
        "user": {"login": login},
        "created_at": created_at,
        "updated_at": updated_at or created_at,
        "body": body,
    }


def _receipt(sha, created_at=RECEIPT_AT, marker="codex-review-receipt:v1"):
    return _comment(f"<!-- {marker} -->\n\n**Reviewed commit:** `{sha}`\n", created_at)


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


class TestReceipt:
    """Third evidence: Codex's `codex-review-receipt:v1` comment naming the head commit.

    Codex's 👍 now waits for the whole PR to be finding-free (claude-tools-5vg.31), so a clean
    round on a PR Codex still considers dirty leaves only this receipt.
    """

    def _decide(self, comments):
        return decide(CUTOFF151, HEAD151, [], [], comments)

    def test_151_receipt_only_passes(self):
        assert self._decide([_comment(RECEIPT_BODY, RECEIPT_AT)]) == "pass"

    def test_seven_char_prefix_passes(self):
        assert self._decide([_receipt("a84dae4")]) == "pass"

    def test_receipt_for_other_sha_waits(self):
        assert self._decide([_receipt("3975fc8c78")]) == "wait"

    def test_receipt_before_cutoff_waits(self):
        assert self._decide([_receipt("a84dae4d57", "2026-10-21T22:00:00Z")]) == "wait"

    def test_receipt_at_cutoff_waits(self):
        # Strictly newer, like the other two paths.
        assert self._decide([_receipt("a84dae4d57", CUTOFF151)]) == "wait"

    def test_receipt_by_non_bot_waits(self):
        assert self._decide([_comment(RECEIPT_BODY, RECEIPT_AT, login="NoNameItem")]) == "wait"

    def test_six_char_prefix_waits(self):
        assert self._decide([_receipt("a84dae")]) == "wait"

    def test_receipt_without_reviewed_commit_waits(self):
        body = "<!-- codex-review-receipt:v1 -->\n\nCodex Review: ok\n"
        assert self._decide([_comment(body, RECEIPT_AT)]) == "wait"

    @pytest.mark.parametrize("version", ["v2", "v10"])
    def test_other_receipt_version_waits(self, version):
        # Deliberate: a new receipt version is a format change to look at, not to trust blindly.
        assert self._decide([_receipt("a84dae4d57", marker=f"codex-review-receipt:{version}")]) == "wait"

    @pytest.mark.parametrize("created_at", ["2026-10-20T14:07:41Z", RECEIPT_AT])
    def test_summary_comment_never_passes(self, created_at):
        # It carries the full head SHA and `completed`, but it is edited in place: it does not say
        # which round it describes.
        summary = _comment(SUMMARY_BODY, created_at, "2026-10-21T22:32:35Z", comment_id=6292793328)
        assert self._decide([summary]) == "wait"

    def test_receipt_null_created_at_waits(self):
        assert self._decide([_receipt("a84dae4d57", None)]) == "wait"

    def test_receipt_null_body_waits(self):
        assert self._decide([_comment(None, RECEIPT_AT)]) == "wait"

    def test_null_user_is_ignored(self):
        # A deleted ("ghost") account comes back as `user: null` — never Codex, never a crash.
        reviews = [{"user": None, "commit_id": HEAD151, "submitted_at": RECEIPT_AT}]
        reactions = [{"user": None, "content": "+1", "created_at": RECEIPT_AT}]
        comments = [{**_receipt("a84dae4d57"), "user": None}]
        assert decide(CUTOFF151, HEAD151, reviews, reactions, comments) == "wait"

    def test_mixed_receipts_one_fresh_head_passes(self):
        comments = [
            _receipt("a84dae4d57", "2026-10-21T01:00:00Z"),
            _receipt("3975fc8c78"),
            _receipt("a84dae4d57"),
        ]
        assert self._decide(comments) == "pass"
        assert self._decide(comments[::-1]) == "pass"


class TestReceiptSha:
    def test_reads_the_reviewed_commit(self):
        assert receipt_sha(RECEIPT_BODY) == "a84dae4d57"

    def test_summary_is_not_a_receipt(self):
        assert receipt_sha(SUMMARY_BODY) is None

    def test_none_body(self):
        assert receipt_sha(None) is None

    def test_other_version_is_not_a_receipt(self):
        assert receipt_sha(_receipt("a84dae4d57", marker="codex-review-receipt:v2")["body"]) is None


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
        out = self._run(payload, "decide", "--cutoff", CUTOFF, "--head-sha", HEAD)
        assert out == "pass"

    def test_cli_wait(self):
        payload = {"reviews": [], "reactions": [_thumb(BEFORE)]}
        out = self._run(payload, "decide", "--cutoff", CUTOFF, "--head-sha", HEAD)
        assert out == "wait"

    def test_cli_receipt_pass(self):
        payload = {"reviews": [], "reactions": [], "comments": [_comment(RECEIPT_BODY, RECEIPT_AT)]}
        out = self._run(payload, "decide", "--cutoff", CUTOFF151, "--head-sha", HEAD151)
        assert out == "pass"


class TestNudgeMarker:
    def test_round_trip(self):
        description = format_nudge_marker(4242, "2026-08-01T10:00:00Z")
        assert description == "comment:4242@2026-08-01T10:00:00Z"
        assert parse_nudge_marker(description) == (4242, "2026-08-01T10:00:00Z")

    def test_marker_fits_a_commit_status_description(self):
        # GitHub truncates a status description at 140 characters; a truncated marker would
        # silently lose the cutoff and re-ask Codex on every re-run.
        assert len(format_nudge_marker(10**12, "2026-08-01T10:00:00Z")) < 140

    @pytest.mark.parametrize(
        "description",
        ["", None, "comment:@2026-08-01T10:00:00Z", "comment:12", "msg:12", "comment:abc@2026-08-01T10:00:00Z"],
    )
    def test_malformed_marker_reads_as_absent(self, description):
        # "Absent" means "ask Codex again" — never a crash, and never a poll against a cutoff we
        # made up.
        assert parse_nudge_marker(description) is None

    def test_surrounding_whitespace_is_tolerated(self):
        assert parse_nudge_marker("  comment:7@2026-08-01T10:00:00Z  ") == (7, "2026-08-01T10:00:00Z")
