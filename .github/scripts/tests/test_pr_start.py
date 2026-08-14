"""Tests for pr_start.py — anchor semantics and the start-message spec."""

from __future__ import annotations

from ..pr_start import Marker, build_spec, parse_marker, plan

HEAD = "0123456789abcdef"


def _commits(count: int) -> list[dict]:
    return [{"sha": f"{i:040d}", "subject": f"feat: change number {i}"} for i in range(count)]


class TestParseMarker:
    def test_plain_marker(self):
        assert parse_marker("msg:4711") == Marker(message_id=4711, replied=False)

    def test_replied_marker(self):
        assert parse_marker("msg:4711 replied") == Marker(message_id=4711, replied=True)

    def test_empty(self):
        assert parse_marker("") == Marker(message_id=None, replied=False)

    def test_none(self):
        assert parse_marker(None) == Marker(message_id=None, replied=False)

    def test_corrupt_marker_degrades(self):
        # A corrupt marker must read as "no marker", never raise: the alternative is a lost
        # notification on a bookkeeping typo.
        assert parse_marker("msg:not-a-number") == Marker(message_id=None, replied=False)


class TestPlan:
    def test_first_push_announces(self):
        result = plan("opened", "", "")
        assert result.send_start is True
        assert result.supersede_message_id is None
        assert result.reason == "announce"

    def test_head_already_announced_is_silent(self):
        # A re-run of an already-announced head: the marker is the memory that suppresses it.
        result = plan("synchronize", "msg:10", "")
        assert result.send_start is False
        assert result.reason == "already-announced"

    def test_head_announced_and_answered_is_still_silent(self):
        assert plan("reopened", "msg:10 replied", "").send_start is False

    def test_unanswered_previous_push_is_superseded(self):
        result = plan("synchronize", "", "msg:99")
        assert result.supersede_message_id == 99
        assert result.send_start is True

    def test_answered_previous_push_is_left_alone(self):
        assert plan("synchronize", "", "msg:99 replied").supersede_message_id is None

    def test_supersede_only_on_synchronize(self):
        # `reopened`/`edited` carry no `before`, and an old marker must not be answered twice.
        assert plan("reopened", "", "msg:99").supersede_message_id is None


class TestBuildSpec:
    def test_verdict_names_the_head(self):
        spec = build_spec(HEAD, _commits(1), False, "A PR", "https://pr", "repo · PR 1")
        assert spec["verdict"][0]["text"] == "New commit "
        assert spec["verdict"][1] == {"text": HEAD[:7], "code": True}
        assert spec["status"] == "started"
        assert spec["silent"] is True
        assert spec["reply_to"] is None
        assert spec["buttons"] == [{"text": "Pull request", "url": "https://pr"}]

    def test_five_commits_are_expanded(self):
        spec = build_spec(HEAD, _commits(5), False, "t", "u", "f")
        block = spec["blocks"][0]
        assert block["title"] == "Commits: 5"
        assert block["open"] is True
        assert len(block["items"]) == 5

    def test_six_commits_collapse(self):
        block = build_spec(HEAD, _commits(6), False, "t", "u", "f")["blocks"][0]
        assert block["title"] == "Commits: 6"
        assert block["open"] is False

    def test_commit_item_shape(self):
        item = build_spec(HEAD, [{"sha": "abc1234def", "subject": "fix: thing"}], False, "t", "u", "f")["blocks"][0][
            "items"
        ][0]
        assert item == [{"text": "abc1234", "code": True}, {"text": " fix: thing"}]

    def test_no_commits_means_no_block(self):
        assert build_spec(HEAD, [], False, "t", "u", "f")["blocks"] == []

    def test_rewritten_history_is_stated(self):
        spec = build_spec(HEAD, _commits(2), True, "t", "u", "f")
        assert "history rewritten" in "".join(segment["text"] for segment in spec["verdict"])

    def test_budget_stops_on_an_element_boundary(self):
        # 600 commits blow the 400-element budget; the block must end with a "more" item rather
        # than with a half-written one, and never exceed the budget.
        block = build_spec(HEAD, _commits(600), False, "t", "u", "f")["blocks"][0]
        assert len(block["items"]) < 600
        assert "more commits" in block["items"][-1][0]["text"]

    def test_text_budget_stops_the_list(self):
        long_subject = "x" * 4000
        commits = [{"sha": f"{i:040d}", "subject": long_subject} for i in range(20)]
        block = build_spec(HEAD, commits, False, "t", "u", "f")["blocks"][0]
        assert len(block["items"]) < 20
        assert "more commits" in block["items"][-1][0]["text"]
