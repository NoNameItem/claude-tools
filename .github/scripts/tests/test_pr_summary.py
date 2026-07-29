"""Tests for pr_summary.py verdict logic."""

from __future__ import annotations

import itertools

import pytest

from ..pr_summary import CheckState, build_spec, collect_states, decide, parse_marker

HEAD = "abc123"

REQUIRED = ["Validate PR", "Python CI Gate", "Claude Code Plugin CI Gate", "review-gate"]

# Auto-assigned when a test doesn't care about `id` explicitly: monotonically increasing across
# calls, so entries listed earlier in a test get a lower id than entries listed later — matching
# how real check-run ids increase over time and letting existing tests (written before `id` was
# part of `_latest`'s tie-break) keep expressing "which run is newest" via call order.
_run_id_counter = itertools.count(1)


def _run(
    name: str,
    conclusion: str | None,
    status: str = "completed",
    started_at: str = "2026-07-27T10:00:00Z",
    run_id: int | None = None,
) -> dict:
    return {
        "id": run_id if run_id is not None else next(_run_id_counter),
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "started_at": started_at,
        "html_url": f"https://github.com/o/r/runs/{name}",
    }


def _payload(**overrides) -> dict:
    payload = {
        "head_sha": HEAD,
        "current_head_sha": HEAD,
        "is_fork": False,
        "required_contexts": REQUIRED,
        "statuses": [{"context": "review-gate", "state": "success", "target_url": "https://x"}],
        "check_runs": [
            _run("Validate PR", "success"),
            _run("Python CI Gate", "success"),
            _run("Claude Code Plugin CI Gate", "success"),
        ],
        "unresolved_threads": 0,
        "anchor_description": "msg:4711",
        "verdict_description": "",
    }
    payload.update(overrides)
    return payload


class TestParseMarker:
    @pytest.mark.parametrize(
        ("description", "expected"),
        [
            ("msg:4711", (4711, None)),
            ("msg:4711 v:ready", (4711, "ready")),
            # The verdict marker written while no anchor existed: `v:` with no `msg:` at all.
            ("v:ready", (None, "ready")),
            ("", (None, None)),
            ("garbage", (None, None)),
            ("msg:notanint v:ready", (None, "ready")),
        ],
    )
    def test_parse(self, description: str, expected: tuple) -> None:
        assert parse_marker(description) == expected


class TestCollectStates:
    def test_status_and_check_run_both_resolve(self) -> None:
        states = collect_states(
            ["review-gate", "Python CI Gate"],
            [{"context": "review-gate", "state": "failure", "target_url": "https://s"}],
            [_run("Python CI Gate", "success")],
        )
        assert states == [
            CheckState("review-gate", "failure", "https://s"),
            CheckState("Python CI Gate", "success", "https://github.com/o/r/runs/Python CI Gate"),
        ]

    def test_missing_context(self) -> None:
        states = collect_states(["Nope"], [], [])
        assert states[0].state == "missing"

    def test_non_terminal_check_run_is_pending(self) -> None:
        states = collect_states(["Python CI Gate"], [], [_run("Python CI Gate", None, status="in_progress")])
        assert states[0].state == "pending"

    def test_latest_run_wins(self) -> None:
        states = collect_states(
            ["Python CI Gate"],
            [],
            [
                _run("Python CI Gate", "failure", started_at="2026-07-27T09:00:00Z"),
                _run("Python CI Gate", "success", started_at="2026-07-27T11:00:00Z"),
            ],
        )
        assert states[0].state == "success"

    def test_queued_entry_with_no_started_at_beats_older_completed_entry(self) -> None:
        # A queued re-run attempt has no `started_at` at all. Ranking by `started_at` alone (the
        # old implementation) sorts the missing value as "", which loses to any real timestamp —
        # so the stale completed attempt would win instead of the in-flight one. This only matters
        # if the caller ever passes `filter=all` (today's `filter=latest` default never surfaces
        # both), but `_latest` must still be correct over that input shape.
        queued = {
            "id": 999,
            "name": "Python CI Gate",
            "status": "queued",
            "conclusion": None,
            "started_at": None,
            "html_url": "https://github.com/o/r/runs/Python CI Gate",
        }
        states = collect_states(
            ["Python CI Gate"],
            [],
            [
                _run("Python CI Gate", "success", started_at="2026-07-27T09:00:00Z", run_id=1),
                queued,
            ],
        )
        assert states[0].state == "pending"

    def test_newer_id_wins_among_completed_entries(self) -> None:
        # started_at is deliberately the OPPOSITE of id order here: the old `started_at`-only key
        # would pick the entry with the later timestamp (success), not the entry with the higher
        # id (failure) — proving the tie-break is actually keyed on `id`, not on `started_at`.
        states = collect_states(
            ["Python CI Gate"],
            [],
            [
                _run("Python CI Gate", "success", started_at="2026-07-27T11:00:00Z", run_id=5),
                _run("Python CI Gate", "failure", started_at="2026-07-27T09:00:00Z", run_id=7),
            ],
        )
        assert states[0].state == "failure"

    @pytest.mark.parametrize("conclusion", ["neutral", "skipped"])
    def test_soft_conclusions_pass(self, conclusion: str) -> None:
        states = collect_states(["Python CI Gate"], [], [_run("Python CI Gate", conclusion)])
        assert states[0].state == "success"

    @pytest.mark.parametrize("conclusion", ["failure", "timed_out", "cancelled", "action_required", "stale"])
    def test_hard_conclusions_fail(self, conclusion: str) -> None:
        states = collect_states(["Python CI Gate"], [], [_run("Python CI Gate", conclusion)])
        assert states[0].state == "failure"


class TestDecide:
    def test_ready(self) -> None:
        decision = decide(_payload())
        assert decision.send is True
        assert decision.verdict == "ready"

    def test_comments(self) -> None:
        decision = decide(_payload(unresolved_threads=2))
        assert decision.verdict == "comments"

    def test_failed_lists_failed_contexts(self) -> None:
        decision = decide(_payload(statuses=[{"context": "review-gate", "state": "failure", "target_url": None}]))
        assert decision.verdict == "failed"
        assert decision.failed_contexts == ["review-gate"]

    def test_stale_head_is_silent(self) -> None:
        decision = decide(_payload(current_head_sha="def456"))
        assert decision.send is False
        assert decision.reason == "stale-head"

    def test_empty_current_head_is_not_stale(self) -> None:
        # An API blip must not silence a real notification.
        assert decide(_payload(current_head_sha="")).send is True

    def test_missing_required_context_is_silent(self) -> None:
        decision = decide(_payload(statuses=[]))
        assert decision.send is False
        assert decision.reason == "waiting"

    def test_non_terminal_required_context_is_silent(self) -> None:
        decision = decide(_payload(statuses=[{"context": "review-gate", "state": "pending", "target_url": None}]))
        assert decision.send is False
        assert decision.reason == "waiting"

    def test_fork_drops_review_gate(self) -> None:
        decision = decide(_payload(is_fork=True, statuses=[]))
        assert decision.send is True
        assert decision.verdict == "ready"
        assert all(state.context != "review-gate" for state in decision.states)

    def test_same_verdict_for_the_same_anchor_is_silent(self) -> None:
        decision = decide(_payload(verdict_description="msg:4711 v:ready"))
        assert decision.send is False
        assert decision.reason == "duplicate"

    def test_changed_verdict_re_notifies(self) -> None:
        decision = decide(_payload(verdict_description="msg:4711 v:failed"))
        assert decision.send is True
        assert decision.verdict == "ready"

    def test_same_verdict_for_a_new_anchor_re_notifies(self) -> None:
        # The `edited` / `reopened` case: same head SHA, so the verdict is unchanged, but
        # notify-start sent a fresh "checks running" message and moved the anchor. Dedup keyed on
        # the verdict alone would swallow this and leave that new message hanging forever.
        decision = decide(_payload(anchor_description="msg:4712", verdict_description="msg:4711 v:ready"))
        assert decision.send is True
        assert decision.verdict == "ready"
        assert decision.message_id == 4712

    def test_reply_targets_the_current_anchor_not_the_recorded_one(self) -> None:
        decision = decide(_payload(anchor_description="msg:4712", verdict_description="msg:4711 v:failed"))
        assert decision.message_id == 4712

    def test_without_an_anchor_dedup_falls_back_to_the_verdict_alone(self) -> None:
        # No anchor exists (notify-start had not written one when this call ran), so there is no
        # per-update signal. Re-sending on every call would be worse than staying silent.
        decision = decide(_payload(anchor_description="", verdict_description="msg:4711 v:ready"))
        assert decision.send is False
        assert decision.reason == "duplicate"
        assert decision.message_id is None

    def test_anchor_appearing_after_an_anchorless_verdict_is_not_a_change(self) -> None:
        # The aggregator recorded `v:ready` with no `msg:` because no anchor existed yet. When the
        # real anchor shows up, that must NOT read as an anchor change: the verdict is unchanged,
        # so nothing new is reported. (Before the marker was split, this path recorded the id of
        # the message it had just sent as a surrogate anchor, and this call re-sent a duplicate.)
        decision = decide(_payload(anchor_description="msg:4712", verdict_description="v:ready"))
        assert decision.send is False
        assert decision.reason == "duplicate"

    def test_anchorless_verdict_still_re_notifies_when_the_verdict_changes(self) -> None:
        decision = decide(_payload(anchor_description="msg:4712", verdict_description="v:failed"))
        assert decision.send is True
        assert decision.verdict == "ready"
        assert decision.message_id == 4712

    def test_failed_jobs_include_non_required_runs(self) -> None:
        decision = decide(
            _payload(
                check_runs=[
                    _run("Validate PR", "success"),
                    _run("Python CI Gate", "failure"),
                    _run("Claude Code Plugin CI Gate", "success"),
                    _run("Python CI / SonarCloud (statuskit)", "failure"),
                ]
            )
        )
        assert decision.verdict == "failed"
        assert decision.failed_jobs == ["Python CI / SonarCloud (statuskit)"]

    def test_failed_jobs_ignores_stale_failure_superseded_by_passing_rerun(self) -> None:
        decision = decide(
            _payload(
                check_runs=[
                    _run("Validate PR", "success"),
                    _run("Python CI Gate", "failure"),
                    _run("Claude Code Plugin CI Gate", "success"),
                    _run("Python CI / SonarCloud (statuskit)", "failure", started_at="2026-07-27T09:00:00Z"),
                    _run("Python CI / SonarCloud (statuskit)", "success", started_at="2026-07-27T11:00:00Z"),
                ]
            )
        )
        assert decision.verdict == "failed"
        assert decision.failed_jobs == []

    def test_failed_jobs_reports_job_whose_latest_attempt_failed(self) -> None:
        decision = decide(
            _payload(
                check_runs=[
                    _run("Validate PR", "success"),
                    _run("Python CI Gate", "failure"),
                    _run("Claude Code Plugin CI Gate", "success"),
                    _run("Python CI / SonarCloud (statuskit)", "success", started_at="2026-07-27T09:00:00Z"),
                    _run("Python CI / SonarCloud (statuskit)", "failure", started_at="2026-07-27T11:00:00Z"),
                ]
            )
        )
        assert decision.verdict == "failed"
        assert decision.failed_jobs == ["Python CI / SonarCloud (statuskit)"]

    def test_message_id_from_marker(self) -> None:
        assert decide(_payload()).message_id == 4711


class TestBuildSpec:
    """The validated layout, asserted so a refactor cannot silently redesign the message."""

    def _spec(self, **overrides) -> dict:
        decision = decide(_payload(**overrides))
        return build_spec(decision, "A title", "https://pr", "claude-tools · PR 118", "https://checks")

    def test_ready_verdict_and_collapsed_table(self) -> None:
        spec = self._spec()
        assert spec["verdict"] == [{"text": "Ready to merge"}]
        assert spec["blocks"][0]["title"] == "All checks passed"
        assert spec["blocks"][0].get("open") is not True
        assert spec["buttons"] == [{"text": "Pull request", "url": "https://pr"}]

    def test_row_shape_is_name_then_centred_icon(self) -> None:
        row = self._spec()["blocks"][0]["rows"][0]
        assert row == [{"text": "Validate PR", "bold": False}, {"text": "✅", "align": "center"}]

    def test_comments_verdict_counts_only(self) -> None:
        assert self._spec(unresolved_threads=3)["verdict"] == [{"text": "All checks passed, unresolved comments: 3"}]

    def test_failed_table_is_bare_and_only_the_name_is_bold(self) -> None:
        spec = self._spec(statuses=[{"context": "review-gate", "state": "failure", "target_url": None}])
        checks = spec["blocks"][0]
        assert "title" not in checks  # bare table, not wrapped in <details>
        failed_row = next(row for row in checks["rows"] if row[0]["text"] == "review-gate")
        assert failed_row == [{"text": "review-gate", "bold": True}, {"text": "❌", "align": "center"}]
        assert spec["verdict"] == [{"text": "Checks failed: "}, {"text": "review-gate", "bold": True}]
        assert spec["buttons"][-1] == {"text": "Checks", "url": "https://checks"}

    def test_failed_jobs_block_carries_the_count(self) -> None:
        spec = self._spec(
            check_runs=[
                _run("Validate PR", "success"),
                _run("Python CI Gate", "failure"),
                _run("Claude Code Plugin CI Gate", "success"),
                _run("Python CI / SonarCloud (statuskit)", "failure"),
            ]
        )
        jobs_block = spec["blocks"][1]
        assert jobs_block["title"] == "Failed jobs: 1"
        assert jobs_block["open"] is True
