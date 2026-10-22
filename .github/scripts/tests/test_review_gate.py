"""Tests for review_gate.py decision logic."""

from __future__ import annotations

import pytest

from ..review_gate import (
    CODEX_BOT,
    codex_activity,
    decide,
    format_breakdown,
    format_nudge_marker,
    parse_nudge_marker,
    receipt_sha,
    timeout_report,
)

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


# The summary comment as #151's poll saw it: created long before the nudge, edited right after it.
STALE_SUMMARY = _comment(SUMMARY_BODY, "2026-10-20T14:07:41Z", "2026-10-21T22:32:35Z", comment_id=6292793328)
ACTIVITY_151 = [_comment(RECEIPT_BODY, RECEIPT_AT), STALE_SUMMARY]

# (cutoff, head, reviews, reactions, comments) — the inputs of the TestDecide / TestReceipt cases, so
# the breakdown's "accepted" can be checked against decide() over every one of them.
DECIDE_CASES = [
    (CUTOFF, HEAD, [], [_thumb(AFTER)], []),
    (CUTOFF, HEAD, [_review(HEAD, AFTER)], [], []),
    (CUTOFF, HEAD, [], [_thumb(BEFORE)], []),
    (CUTOFF, HEAD, [_review(HEAD, BEFORE)], [], []),
    (CUTOFF, HEAD, [], [], []),
    (CUTOFF, HEAD, [_review("other", AFTER)], [], []),
    (CUTOFF, HEAD, [], [_thumb(AFTER, login="nope")], []),
    (CUTOFF, HEAD, [_review(HEAD, AFTER, login="nope")], [], []),
    (CUTOFF, HEAD, [_review(HEAD, None)], [], []),
    (CUTOFF, HEAD, [], [_thumb(None)], []),
    (CUTOFF, HEAD, [_review(HEAD, AFTER)], [_thumb(BEFORE)], []),
    (CUTOFF151, HEAD151, [], [], ACTIVITY_151),
    (CUTOFF151, HEAD151, [], [], [_receipt("a84dae4")]),
    (CUTOFF151, HEAD151, [], [], [_receipt("3975fc8c78")]),
    (CUTOFF151, HEAD151, [], [], [_receipt("a84dae4d57", "2026-10-21T22:00:00Z")]),
    (CUTOFF151, HEAD151, [], [], [_receipt("a84dae4d57", CUTOFF151)]),
    (CUTOFF151, HEAD151, [], [], [_comment(RECEIPT_BODY, RECEIPT_AT, login="NoNameItem")]),
    (CUTOFF151, HEAD151, [], [], [_receipt("a84dae")]),
    (CUTOFF151, HEAD151, [], [], [_receipt("a84dae4d57", marker="codex-review-receipt:v2")]),
    (CUTOFF151, HEAD151, [], [], [STALE_SUMMARY]),
    (CUTOFF151, HEAD151, [], [], [_receipt("a84dae4d57", None)]),
    (CUTOFF151, HEAD151, [], [], [_comment(None, RECEIPT_AT)]),
    (CUTOFF151, HEAD151, [], [], [_receipt("3975fc8c78"), _receipt("a84dae4d57")]),
    (CUTOFF151, HEAD151, [], [], [_comment("<!-- codex-review-receipt:v1 -->\n\nCodex Review: ok\n", RECEIPT_AT)]),
    (CUTOFF151, HEAD151, [], [], [_receipt("a84dae4d57", marker="codex-review-receipt:v10")]),
    (CUTOFF151, HEAD151, [], [], [_receipt("a84dae4d57", marker="codex-review-receipt:v1-beta")]),
    (CUTOFF151, HEAD151, [], [], [_receipt("A84DAE4D57")]),
    (CUTOFF151, HEAD151, [], [], [_comment(SUMMARY_BODY, RECEIPT_AT, comment_id=6292793328)]),
    (
        CUTOFF151,
        HEAD151,
        [{"user": None, "commit_id": HEAD151, "submitted_at": RECEIPT_AT}],
        [{"user": None, "content": "+1", "created_at": RECEIPT_AT}],
        [{**_receipt("a84dae4d57"), "user": None}],
    ),
    (
        CUTOFF151,
        HEAD151,
        [],
        [],
        [_receipt("a84dae4d57", "2026-10-21T01:00:00Z"), _receipt("3975fc8c78"), _receipt("a84dae4d57")],
    ),
    (
        CUTOFF151,
        HEAD151,
        [],
        [],
        [_receipt("a84dae4d57"), _receipt("3975fc8c78"), _receipt("a84dae4d57", "2026-10-21T01:00:00Z")],
    ),
]


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


class TestActivity:
    """codex_activity(): what Codex did after the cutoff, and whether each item counts."""

    def _activity(self, reviews=(), reactions=(), comments=()):
        return codex_activity(CUTOFF151, HEAD151, list(reviews), list(reactions), list(comments))

    def test_nothing_after_cutoff_is_empty(self):
        summary = _comment(SUMMARY_BODY, "2026-10-20T14:07:41Z", comment_id=6292793328)
        assert self._activity(reactions=[_thumb("2026-10-21T01:00:00Z")], comments=[summary]) == []

    def test_151_lists_receipt_accepted_and_summary_seen(self):
        receipt, summary = self._activity(comments=ACTIVITY_151)
        assert receipt.channel == summary.channel == "comment"
        assert receipt.accepted is True
        for fragment in ("6328012482", "codex-review-receipt:v1", "a84dae4d57"):
            assert fragment in receipt.detail
        assert summary.accepted is False
        assert summary.at == "2026-10-21T22:32:35Z"
        for fragment in ("6292793328", "codex-review-state:v1", "a84dae4d57", "completed", "edited"):
            assert fragment in summary.detail

    @pytest.mark.parametrize("version", ["v2", "v1-beta", "v1.1"])
    def test_other_receipt_version_named_in_full(self, version):
        # The case the breakdown exists for: a new receipt format must read as "not v1", under its
        # own full name — not truncated to `…:v1`, which would make the gate look broken.
        (item,) = self._activity(comments=[_receipt("a84dae4d57", marker=f"codex-review-receipt:{version}")])
        assert item.accepted is False
        assert f"codex-review-receipt:{version} " in f"{item.detail} "
        assert "not a v1 receipt" in item.detail

    def test_unrecognised_reviewed_commit_shown(self):
        # Spec: lowercase hex only — but the breakdown must say the line is there and unreadable,
        # not that it is missing.
        (item,) = self._activity(comments=[_receipt("A84DAE4D57")])
        assert item.accepted is False
        assert "unrecognised Reviewed commit" in item.detail
        assert "A84DAE4D57" in item.detail

    def test_null_user_items_not_listed(self):
        # A deleted ("ghost") account: never Codex, and never a crash — the CLI runs this before decide().
        assert (
            self._activity(
                reviews=[{"user": None, "commit_id": HEAD151, "submitted_at": RECEIPT_AT}],
                reactions=[{"user": None, "content": "+1", "created_at": RECEIPT_AT}],
                comments=[{**_receipt("a84dae4d57"), "user": None}],
            )
            == []
        )

    @pytest.mark.parametrize(
        "body",
        # The second one mimics the workflow's 2000-char slice cutting the JSON and the `-->`.
        ['<!-- codex-review-state:v1 {"code_review": -->', SUMMARY_BODY[:120]],
    )
    def test_malformed_state_listed_by_markers(self, body):
        (item,) = self._activity(comments=[_comment(body, RECEIPT_AT)])
        assert "codex-review-state:v1" in item.detail

    def test_null_body_comment_listed(self):
        (item,) = self._activity(comments=[_comment(None, RECEIPT_AT)])
        assert item.accepted is False

    def test_review_and_reaction_listed(self):
        review, reaction = self._activity(
            reviews=[_review("3975fc8c78" + "0" * 30, RECEIPT_AT)],
            reactions=[_thumb(RECEIPT_AT, content="eyes")],
        )
        assert (review.channel, review.accepted) == ("review", False)
        assert "3975fc8c78" in review.detail
        assert (reaction.channel, reaction.accepted) == ("reaction", False)
        assert "eyes" in reaction.detail

    def test_non_codex_items_excluded(self):
        assert (
            self._activity(
                reviews=[_review("3975fc8c78" + "0" * 30, RECEIPT_AT, login="NoNameItem")],
                reactions=[_thumb(RECEIPT_AT, content="eyes", login="NoNameItem")],
                comments=[_comment(RECEIPT_BODY, RECEIPT_AT, login="NoNameItem")],
            )
            == []
        )

    @pytest.mark.parametrize("case", DECIDE_CASES)
    def test_activity_agrees_with_decide(self, case):
        # One rule, two readers: the breakdown must never say "accepted" while decide() waits.
        expected = "pass" if any(a.accepted for a in codex_activity(*case)) else "wait"
        assert decide(*case) == expected


class TestBreakdown:
    def test_empty_breakdown(self):
        line = format_breakdown(CUTOFF151, [])
        assert line.startswith(f"Codex since {CUTOFF151}:")
        for channel in ("reviews: none", "reactions: none", "comments: none"):
            assert channel in line

    def test_breakdown_is_one_line_with_ids(self):
        line = format_breakdown(CUTOFF151, codex_activity(CUTOFF151, HEAD151, [], [], ACTIVITY_151))
        assert "\n" not in line
        assert "6328012482" in line
        assert "6292793328" in line
        assert "reviews: none" in line


class TestTimeoutReport:
    def test_silent(self):
        assert timeout_report(CUTOFF151, HEAD151, 25, []) == [
            f"::error::Codex has not reviewed {HEAD151} within 25 min. Re-run this job once Codex finishes"
            " — the codex-nudge marker means it will not be asked twice."
        ]

    def test_active_but_not_accepted(self):
        lines = timeout_report(CUTOFF151, HEAD151, 25, codex_activity(CUTOFF151, HEAD151, [], [], [STALE_SUMMARY]))
        assert lines[0].startswith("Codex was active on this PR after the nudge")
        assert any("6292793328" in line for line in lines)
        assert lines[-1].startswith("::error::")
        assert HEAD151 in lines[-1]
        assert "25 min" in lines[-1]
        assert all("\n" not in line for line in lines)


class TestCli:
    """main(): reads reviews/reactions/comments JSON on stdin, prints pass/wait (breakdown on stderr)."""

    def _run_full(self, payload, *args):
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
        )

    def _run(self, payload, *args):
        return self._run_full(payload, *args).stdout.strip()

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

    def test_cli_breakdown_on_stderr(self):
        # The workflow compares stdout to the exact string "pass" — the breakdown must not leak in.
        payload = {"reviews": [], "reactions": [], "comments": ACTIVITY_151}
        result = self._run_full(payload, "decide", "--cutoff", CUTOFF151, "--head-sha", HEAD151)
        assert result.stdout.strip() == "pass"
        assert "6328012482" in result.stderr

    def test_cli_timeout_report(self):
        payload = {"comments": [STALE_SUMMARY]}
        args = ("timeout-report", "--cutoff", CUTOFF151, "--head-sha", HEAD151, "--minutes", "25")
        out = self._run(payload, *args)
        assert out.splitlines()[-1].startswith("::error::")
        assert "6292793328" in out


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
