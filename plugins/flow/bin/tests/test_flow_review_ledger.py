"""Tests for the persistent per-PR review ledger (_ledger core + flow-review-ledger CLI)."""

# ruff: noqa: INP001  # bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BIN = Path(__file__).parent.parent
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import _ledger  # noqa: E402  # sys.path is prepared above


class TestCacheBase:
    def test_posix_honours_xdg_cache_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_ledger.os, "name", "posix")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        assert _ledger.cache_base() == tmp_path / "xdg"

    def test_posix_falls_back_to_dot_cache(self, monkeypatch):
        monkeypatch.setattr(_ledger.os, "name", "posix")
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        assert _ledger.cache_base() == Path("~/.cache").expanduser()

    def test_windows_uses_localappdata(self, monkeypatch):
        monkeypatch.setattr(_ledger.os, "name", "nt")
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
        assert _ledger.cache_base() == _ledger.Path(r"C:\Users\me\AppData\Local")


class TestSplitProject:
    def test_github_pull_url(self):
        assert _ledger.split_project("https://github.com/NoNameItem/claude-tools/pull/96") == (
            "github.com",
            ["NoNameItem", "claude-tools"],
        )

    def test_gitlab_nested_groups(self):
        assert _ledger.split_project("https://gitlab.com/group/sub/proj/-/merge_requests/7") == (
            "gitlab.com",
            ["group", "sub", "proj"],
        )

    def test_enterprise_host_is_lowercased_and_kept(self):
        host, segments = _ledger.split_project("https://GHE.Example.COM/Team/Repo/pull/1")
        assert host == "ghe.example.com"
        assert segments == ["Team", "Repo"]  # path segments keep their API-canonical case

    def test_empty_or_unparseable_url_raises(self):
        for url in ("", "not-a-url", "https://github.com/pull/1"):
            with pytest.raises(_ledger.LedgerPathError):
                _ledger.split_project(url)

    def test_traversal_segment_rejected(self):
        with pytest.raises(_ledger.LedgerPathError):
            _ledger.split_project("https://github.com/../evil/pull/1")


class TestLedgerPath:
    def test_nested_under_cache_base(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_ledger.os, "name", "posix")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        assert _ledger.ledger_path("https://github.com/o/r/pull/42", 42) == (
            tmp_path / "flow" / "review-ledger" / "github.com" / "o" / "r" / "pr-42.json"
        )

    def test_same_iid_in_two_gitlab_projects_does_not_collide(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_ledger.os, "name", "posix")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        first = _ledger.ledger_path("https://gitlab.com/g/a/-/merge_requests/7", 7)
        second = _ledger.ledger_path("https://gitlab.com/g/b/-/merge_requests/7", 7)
        assert first != second

    def test_non_numeric_number_raises(self):
        with pytest.raises(_ledger.LedgerPathError):
            _ledger.ledger_path("https://github.com/o/r/pull/x", "../../etc/passwd")


class TestDocumentIO:
    def test_save_then_load_roundtrip(self, tmp_path):
        path = tmp_path / "deep" / "pr-1.json"
        doc = _ledger.empty_ledger({"platform": "github", "number": 1, "url": "u"})
        doc["rows"]["77"] = {"ref": "C1", "thread_id": "77"}
        _ledger.save_ledger(path, doc)
        assert _ledger.load_ledger(path) == doc

    def test_save_leaves_no_temp_file_behind(self, tmp_path):
        path = tmp_path / "pr-1.json"
        _ledger.save_ledger(path, _ledger.empty_ledger())
        assert [p.name for p in tmp_path.iterdir()] == ["pr-1.json"]

    def test_missing_file_loads_as_empty_ledger(self, tmp_path):
        doc = _ledger.load_ledger(tmp_path / "nope.json")
        assert doc["rows"] == {}
        assert doc["round"] == 0
        assert doc["next_ref"] == {"U": 1, "C": 1}

    def test_corrupt_file_loads_as_empty_ledger(self, tmp_path):
        path = tmp_path / "pr-1.json"
        path.write_text("{ half written", encoding="utf-8")
        assert _ledger.load_ledger(path)["rows"] == {}

    def test_json_that_is_not_a_ledger_loads_as_empty(self, tmp_path):
        path = tmp_path / "pr-1.json"
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        assert _ledger.load_ledger(path)["rows"] == {}


class TestRowPrimitives:
    def test_find_row_by_ref(self):
        doc = {"rows": {"1": {"ref": "U1"}, "2": {"ref": "C3"}}}
        assert _ledger.find_row_by_ref(doc, "C3") == {"ref": "C3"}
        assert _ledger.find_row_by_ref(doc, "C9") is None

    def test_thread_id_prefers_comment_then_discussion_then_summary(self):
        assert _ledger.thread_id_of({"comment_id": 5, "discussion_id": None, "summary_id": None}) == "5"
        assert _ledger.thread_id_of({"comment_id": None, "discussion_id": "abc", "summary_id": None}) == "abc"
        assert _ledger.thread_id_of({"comment_id": None, "discussion_id": None, "summary_id": 9}) == "9"
        assert _ledger.thread_id_of({"comment_id": None, "discussion_id": None, "summary_id": None}) is None

    def test_last_reply_id(self):
        assert _ledger.last_reply_id({"thread": [{"id": 1}, {"id": 4}]}) == 4
        assert _ledger.last_reply_id({"thread": []}) is None
        assert _ledger.last_reply_id({}) is None

    def test_id_advanced(self):
        assert _ledger.id_advanced("10", "9") is True
        assert _ledger.id_advanced("9", "9") is False
        assert _ledger.id_advanced(None, "9") is False
        assert _ledger.id_advanced("9", None) is True
        assert _ledger.id_advanced("abc", "def") is True  # non-numeric ids: any change counts


from conftest import run_helper  # noqa: E402  # after the sys.path bootstrap above


def meta_doc(comments, number=96, url="https://github.com/o/r/pull/96", platform="github"):
    return {
        "platform": platform,
        "unit": {"number": number, "branch": "b", "url": url},
        "me": "me",
        "counts": {"total": len(comments), "already_replied": 0, "actionable": len(comments)},
        "comments": comments,
    }


def inline_comment(comment_id, *, is_bot=False, body="finding", thread=None, **overrides):
    item = {
        "user": "coderabbitai" if is_bot else "alice",
        "is_bot": is_bot,
        "kind": "inline",
        "path": "a.py",
        "start_line": None,
        "line": 42,
        "outdated": False,
        "already_replied": False,
        "comment_id": comment_id,
        "discussion_id": None,
        "summary_id": None,
        "body": body,
        "thread": thread or [],
        "diff_hunk": "@@ -40,3 +40,3 @@\n x",
        "side": "RIGHT",
        "position": None,
        "snippet": None,
        "ref": "IGNORED",  # the collector's per-round ref — reconcile allocates its own
    }
    item.update(overrides)
    return item


class LedgerHarness:
    """Runs flow-review-ledger with the cache base pointed at a tmp dir."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.env = {"XDG_CACHE_HOME": str(tmp_path / "cache"), "PATH": "/usr/bin:/bin"}

    def write_meta(self, meta, name="metadata.json"):
        path = self.tmp_path / name
        path.write_text(json.dumps(meta), encoding="utf-8")
        return str(path)

    def run(self, *args):
        return run_helper("flow-review-ledger", *args, env=self.env)

    def reconcile(self, meta, name="metadata.json"):
        result = self.run("reconcile", "--meta", self.write_meta(meta, name))
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def ledger(self, meta):
        path = _ledger.ledger_path(meta["unit"]["url"], meta["unit"]["number"])
        return _ledger.load_ledger(path)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return LedgerHarness(tmp_path)


class TestReconcileInsert:
    def test_first_round_inserts_every_comment_as_open(self, harness):
        meta = meta_doc([inline_comment(1), inline_comment(2, is_bot=True)])
        out = harness.reconcile(meta)
        assert out["round"] == 1
        assert out["counts"]["total"] == 2
        assert {e["ref"] for e in out["working_set"]} == {"U1", "C1"}
        assert all(e["status"] == "open" for e in out["working_set"])

    def test_stdout_carries_the_resolved_ledger_path(self, harness):
        meta = meta_doc([inline_comment(1)])
        out = harness.reconcile(meta)
        assert out["ledger"] == str(_ledger.ledger_path(meta["unit"]["url"], 96))
        assert Path(out["ledger"]).is_file()

    def test_ref_prefix_follows_is_bot(self, harness):
        meta = meta_doc([inline_comment(1), inline_comment(2, is_bot=True), inline_comment(3, is_bot=True)])
        harness.reconcile(meta)
        rows = harness.ledger(meta)["rows"]
        assert rows["1"]["ref"] == "U1"
        assert rows["2"]["ref"] == "C1"
        assert rows["3"]["ref"] == "C2"

    def test_collector_ref_is_ignored(self, harness):
        meta = meta_doc([inline_comment(1, ref="C7")])
        harness.reconcile(meta)
        assert harness.ledger(meta)["rows"]["1"]["ref"] == "U1"

    def test_kind_and_identity_are_stamped_on_insert(self, harness):
        meta = meta_doc([inline_comment(None, kind="summary", summary_id=900)])
        harness.reconcile(meta)
        row = harness.ledger(meta)["rows"]["900"]
        assert row["kind"] == "summary"
        assert row["thread_mark"] is None  # a summary has no thread → nothing to mark
        assert row["thread_id"] == "900"
        assert row["platform"] == "github"
        assert row["first_seen_round"] == 1

    def test_existing_row_keeps_its_ref_and_counter_does_not_move(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1), inline_comment(2)]))
        rows = harness.ledger(meta)["rows"]
        assert rows["1"]["ref"] == "U1"
        assert rows["2"]["ref"] == "U2"

    def test_round_counter_increments_per_run(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        assert harness.reconcile(meta)["round"] == 2
        assert harness.ledger(meta)["round"] == 2

    def test_snapshot_fields_are_refreshed_every_round(self, harness):
        harness.reconcile(meta_doc([inline_comment(1, body="old", line=42)]))
        harness.reconcile(meta_doc([inline_comment(1, body="new", line=61, outdated=True)]))
        row = harness.ledger(meta_doc([]))["rows"]["1"]
        assert row["body"] == "new"
        assert row["line"] == 61
        assert row["outdated"] is True

    def test_identity_fields_survive_a_conflicting_snapshot(self, harness):
        harness.reconcile(meta_doc([inline_comment(1, is_bot=True)]))
        harness.reconcile(meta_doc([inline_comment(1, is_bot=True, kind="summary")]))
        assert harness.ledger(meta_doc([]))["rows"]["1"]["kind"] == "inline"  # kind is set-on-insert

    def test_working_entry_carries_the_cap_table_columns(self, harness):
        out = harness.reconcile(meta_doc([inline_comment(1, body="x" * 400, is_bot=True)]))
        entry = out["working_set"][0]
        assert entry["is_bot"] is True
        assert entry["path"] == "a.py"
        assert entry["line"] == 42
        assert entry["outdated"] is False
        assert len(entry["brief"]) == _ledger.BRIEF_CHARS

    def test_comment_without_any_platform_id_is_skipped(self, harness):
        meta = meta_doc([inline_comment(None, summary_id=None)])
        out = harness.reconcile(meta)
        assert out["working_set"] == []
        assert out["counts"]["total"] == 0

    def test_corrupt_ledger_is_rebuilt_not_fatal(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        path = _ledger.ledger_path(meta["unit"]["url"], 96)
        path.write_text("{ corrupt", encoding="utf-8")
        out = harness.reconcile(meta)
        assert out["round"] == 1  # degraded to an empty ledger, then re-inserted
        assert out["working_set"][0]["ref"] == "U1"

    def test_missing_unit_url_exits_with_a_message_not_a_traceback(self, harness):
        result = harness.run("reconcile", "--meta", harness.write_meta(meta_doc([inline_comment(1)], url="")))
        assert result.returncode == 2
        assert "flow-review-ledger:" in result.stderr
        assert "Traceback" not in result.stderr

    def test_non_list_comments_exits_with_a_message_not_a_traceback(self, harness):
        meta = meta_doc([inline_comment(1)])
        meta["comments"] = "not-a-list"  # elf.52(a): malformed --meta must not traceback
        result = harness.run("reconcile", "--meta", harness.write_meta(meta))
        assert result.returncode == 2
        assert "flow-review-ledger:" in result.stderr
        assert "Traceback" not in result.stderr


def reply(reply_id, *, user="coderabbitai", body="ack", is_bot=True):
    return {"user": user, "body": body, "id": reply_id, "created_at": "2026-07-20T10:00:00Z", "is_bot": is_bot}


def settle(harness, meta, ref, *, thread_mark, status="done", decision="fix"):
    """Mark a row done directly in the ledger (Task 6's `record` does this in production)."""
    path = _ledger.ledger_path(meta["unit"]["url"], meta["unit"]["number"])
    doc = _ledger.load_ledger(path)
    row = _ledger.find_row_by_ref(doc, ref)
    row["status"] = status
    row["decision"] = decision
    row["thread_mark"] = thread_mark
    _ledger.save_ledger(path, doc)


class TestReconcileLifecycle:
    def test_already_replied_seeds_the_row_as_done(self, harness):
        meta = meta_doc([inline_comment(1, already_replied=True, thread=[reply(50)])])
        out = harness.reconcile(meta)
        row = harness.ledger(meta)["rows"]["1"]
        assert row["status"] == "done"
        assert row["thread_mark"] == 50
        assert out["working_set"] == []

    def test_done_row_is_excluded_from_the_next_round(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        settle(harness, meta, "U1", thread_mark=None)
        assert harness.reconcile(meta)["working_set"] == []

    def test_pending_and_skipped_rows_stay_in_the_working_set(self, harness):
        meta = meta_doc([inline_comment(1), inline_comment(2)])
        harness.reconcile(meta)
        settle(harness, meta, "U1", thread_mark=None, status="pending")
        settle(harness, meta, "U2", thread_mark=None, status="skipped", decision="skip")
        statuses = {e["ref"]: e["status"] for e in harness.reconcile(meta)["working_set"]}
        assert statuses == {"U1": "pending", "U2": "skipped"}

    def test_done_row_reopens_when_a_new_reply_appears(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        settle(harness, meta, "U1", thread_mark=50)
        out = harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51, body="objection")])]))
        assert [e["ref"] for e in out["working_set"]] == ["U1"]
        row = harness.ledger(meta)["rows"]["1"]
        assert row["status"] == "open"
        assert row["decision"] == "fix"  # the prior verdict is kept as history for the analyst

    def test_reopened_row_returns_with_its_original_ref(self, harness):
        meta = meta_doc([inline_comment(1, is_bot=True, thread=[reply(50)]), inline_comment(2, is_bot=True)])
        harness.reconcile(meta)
        settle(harness, meta, "C1", thread_mark=50)
        out = harness.reconcile(
            meta_doc([inline_comment(1, is_bot=True, thread=[reply(50), reply(51)]), inline_comment(2, is_bot=True)])
        )
        assert {e["ref"] for e in out["working_set"]} == {"C1", "C2"}

    def test_no_reopen_loop_when_the_thread_mark_is_current(self, harness):
        """The bot ack case: the bot stays the latest replier forever, but the mark is current."""
        meta = meta_doc([inline_comment(1, thread=[reply(50), reply(51)])])
        harness.reconcile(meta)
        settle(harness, meta, "U1", thread_mark=51)
        assert harness.reconcile(meta)["working_set"] == []
        assert harness.reconcile(meta)["working_set"] == []

    def test_done_summary_never_reopens(self, harness):
        summary = inline_comment(None, kind="summary", summary_id=900, path="(summary)", line=None)
        meta = meta_doc([summary])
        harness.reconcile(meta)
        settle(harness, meta, "U1", thread_mark=None, decision="follow_up")
        # a rerun re-imports the SAME review id → the row is still done → no duplicate follow-up
        assert harness.reconcile(meta)["working_set"] == []

    def test_new_summary_review_gets_a_new_row(self, harness):
        first = inline_comment(None, kind="summary", summary_id=900, path="(summary)", line=None)
        meta = meta_doc([first])
        harness.reconcile(meta)
        settle(harness, meta, "U1", thread_mark=None, decision="follow_up")
        second = inline_comment(None, kind="summary", summary_id=901, path="(summary)", line=None)
        out = harness.reconcile(meta_doc([first, second]))
        assert [e["ref"] for e in out["working_set"]] == ["U2"]

    def test_open_row_is_not_touched_by_the_reopen_rule(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        out = harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51)])]))
        assert [e["status"] for e in out["working_set"]] == ["open"]


class TestGet:
    def test_prints_exactly_the_matching_row(self, harness):
        meta = meta_doc([inline_comment(1, body="the finding", thread=[reply(50)])])
        harness.reconcile(meta)
        result = harness.run("get", "--ref", "U1", "--meta", harness.write_meta(meta))
        assert result.returncode == 0, result.stderr
        row = json.loads(result.stdout)
        assert row["ref"] == "U1"
        assert row["thread_id"] == "1"
        assert row["body"] == "the finding"
        assert row["diff_hunk"].startswith("@@")
        assert row["thread"][0]["id"] == 50

    def test_carries_the_durable_history_of_a_reopened_row(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        settle(harness, meta, "U1", thread_mark=50, decision="wont_fix")
        harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51, body="objection")])]))
        row = json.loads(harness.run("get", "--ref", "U1", "--meta", harness.write_meta(meta)).stdout)
        assert row["status"] == "open"
        assert row["decision"] == "wont_fix"  # prior verdict visible to the analyst
        assert row["thread"][-1]["body"] == "objection"

    def test_resolves_the_path_from_explicit_url_and_number(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = harness.run("get", "--ref", "U1", "--url", meta["unit"]["url"], "--number", "96")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["ref"] == "U1"

    def test_unknown_ref_exits_nonzero_with_a_message(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = harness.run("get", "--ref", "C9", "--meta", harness.write_meta(meta))
        assert result.returncode == 1
        assert "C9" in result.stderr
        assert result.stdout.strip() == ""

    def test_shares_the_lookup_with_find_row_by_ref(self, harness):
        meta = meta_doc([inline_comment(1), inline_comment(2, is_bot=True)])
        harness.reconcile(meta)
        emitted = json.loads(harness.run("get", "--ref", "C1", "--meta", harness.write_meta(meta)).stdout)
        assert emitted == _ledger.find_row_by_ref(harness.ledger(meta), "C1")


class TestRecord:
    def _record(self, harness, meta, decisions, head="abc1234"):
        path = harness.tmp_path / "decisions.json"
        path.write_text(json.dumps(decisions), encoding="utf-8")
        return harness.run("record", "--meta", harness.write_meta(meta), "--decisions", str(path), "--head", head)

    def test_applies_a_decision_by_ref(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = self._record(
            harness,
            meta,
            {"U1": {"status": "done", "decision": "fix", "reason": "guard added", "thread_mark": 77}},
        )
        assert result.returncode == 0, result.stderr
        row = harness.ledger(meta)["rows"]["1"]
        assert row["status"] == "done"
        assert row["decision"] == "fix"
        assert row["reason"] == "guard added"
        assert row["thread_mark"] == 77
        assert row["head"] == "abc1234"
        assert row["last_round"] == 1

    def test_records_a_followup_task_id(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        self._record(harness, meta, {"U1": {"status": "done", "decision": "follow_up", "followup_task_id": "ct-42"}})
        assert harness.ledger(meta)["rows"]["1"]["followup_task_id"] == "ct-42"

    def test_pending_and_skipped_are_written_verbatim(self, harness):
        meta = meta_doc([inline_comment(1), inline_comment(2)])
        harness.reconcile(meta)
        self._record(
            harness,
            meta,
            {"U1": {"status": "pending", "decision": "fix"}, "U2": {"status": "skipped", "decision": "skip"}},
        )
        rows = harness.ledger(meta)["rows"]
        assert rows["1"]["status"] == "pending"
        assert rows["2"]["status"] == "skipped"

    def test_reason_with_shell_metacharacters_survives_verbatim(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        hostile = "won't fix: `$(id)` and a FLOW_RC_EOF line\nsecond line"
        self._record(harness, meta, {"U1": {"status": "done", "decision": "wont_fix", "reason": hostile}})
        assert harness.ledger(meta)["rows"]["1"]["reason"] == hostile

    def test_unknown_ref_warns_but_still_records_the_rest(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = self._record(harness, meta, {"U1": {"status": "done"}, "C9": {"status": "done"}})
        assert result.returncode == 0
        assert "C9" in result.stderr
        assert json.loads(result.stdout) == {"recorded": 1, "unknown": ["C9"]}

    def test_invalid_status_writes_nothing(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = self._record(harness, meta, {"U1": {"status": "finished"}})
        assert result.returncode == 2
        assert harness.ledger(meta)["rows"]["1"]["status"] == "open"

    def test_invalid_decision_writes_nothing(self, harness):
        """elf.53(a): mirrors test_invalid_status_writes_nothing for the `decision` field."""
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = self._record(harness, meta, {"U1": {"decision": "maybe"}})
        assert result.returncode == 2
        assert harness.ledger(meta)["rows"]["1"]["decision"] is None

    def test_re_recording_the_same_decision_is_a_no_op(self, harness):
        """elf.53(b): recording an identical decision twice must not change the row further."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        decision = {"U1": {"status": "done", "decision": "fix", "reason": "guard added", "thread_mark": 50}}
        self._record(harness, meta, decision)
        first = dict(harness.ledger(meta)["rows"]["1"])
        self._record(harness, meta, decision)
        second = harness.ledger(meta)["rows"]["1"]
        assert first == second

    def test_explicit_null_is_a_no_op_for_every_field(self, harness):
        """elf.53(c): the ledger's convention — an explicit JSON null never clears a durable
        field, it means "no new information supplied" (already true for `thread_mark`,
        pinned by test_done_without_thread_mark_reopens_on_our_own_reply). Applied uniformly
        to `status`/`decision`/`reason`/`followup_task_id`/`thread_mark`."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        self._record(
            harness,
            meta,
            {
                "U1": {
                    "status": "done",
                    "decision": "fix",
                    "reason": "guard added",
                    "followup_task_id": "ct-1",
                    "thread_mark": 50,
                }
            },
        )
        before = dict(harness.ledger(meta)["rows"]["1"])
        result = self._record(
            harness,
            meta,
            {
                "U1": {
                    "status": None,
                    "decision": None,
                    "reason": None,
                    "followup_task_id": None,
                    "thread_mark": None,
                }
            },
        )
        assert result.returncode == 0, result.stderr
        after = harness.ledger(meta)["rows"]["1"]
        for field in ("status", "decision", "reason", "followup_task_id", "thread_mark"):
            assert after[field] == before[field], field

    def test_record_against_a_missing_ledger_reports_instead_of_creating_one(self, harness):
        """elf.52(c): Phase 5.7a always runs `record` right after `reconcile` in the same run,
        so a missing ledger at `record` time means something upstream went wrong — silently
        materialising an empty round-0 document would hide that. `record` must fail loudly and
        must not create the ledger file."""
        meta = meta_doc([inline_comment(1)])
        path = _ledger.ledger_path(meta["unit"]["url"], meta["unit"]["number"])
        assert not path.exists()
        result = self._record(harness, meta, {"U1": {"status": "done"}})
        assert result.returncode != 0
        assert "flow-review-ledger:" in result.stderr
        assert "Traceback" not in result.stderr
        assert not path.exists()

    def test_recorded_row_is_excluded_on_the_next_reconcile(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        self._record(harness, meta, {"U1": {"status": "done", "decision": "fix", "thread_mark": 50}})
        assert harness.reconcile(meta)["working_set"] == []

    def test_done_without_thread_mark_reopens_on_our_own_reply(self, harness):
        """The negative twin: `record` keeps the pre-reply mark when the entry omits `thread_mark`.

        `record` cannot know the id of a reply it did not post, so this is deliberate — the
        SETTLING side (review-comments 5.7a) must always supply the id of the reply it just sent.
        Pinned so the trap stays visible: omit it and the settled finding re-opens forever.
        """
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        self._record(harness, meta, {"U1": {"status": "done", "decision": "wont_fix"}})
        assert harness.ledger(meta)["rows"]["1"]["thread_mark"] == 50  # unchanged, pre-reply

        # an explicit null is the same no-op, which is why 5.7a may write `"thread_mark": null`
        # for a `kind == "summary"` row (whose mark is None on insert anyway)
        self._record(harness, meta, {"U1": {"status": "done", "thread_mark": None}})
        assert harness.ledger(meta)["rows"]["1"]["thread_mark"] == 50

        posted = [reply(50), reply(5001, user="me", is_bot=False, body="Won't fix: …")]
        out = harness.reconcile(meta_doc([inline_comment(1, thread=posted)]))
        assert [e["ref"] for e in out["working_set"]] == ["U1"]
        row = harness.ledger(meta)["rows"]["1"]
        assert row["status"] == "open"
        assert row["decision"] == "wont_fix"  # the settled verdict is kept, but it re-triages


class TestStats:
    def _decide(self, harness, meta, decisions, head="h"):
        path = harness.tmp_path / "d.json"
        path.write_text(json.dumps(decisions), encoding="utf-8")
        assert (
            harness.run(
                "record", "--meta", harness.write_meta(meta), "--decisions", str(path), "--head", head
            ).returncode
            == 0
        )

    def test_cumulative_block(self, harness):
        comments = [inline_comment(i) for i in range(1, 5)]
        meta = meta_doc(comments)
        harness.reconcile(meta)
        self._decide(
            harness,
            meta,
            {
                "U1": {"status": "done", "decision": "fix"},
                "U2": {"status": "done", "decision": "wont_fix"},
                "U3": {"status": "done", "decision": "follow_up", "followup_task_id": "ct-42"},
                "U4": {"status": "pending", "decision": "fix"},
            },
        )
        out = harness.run("stats", "--meta", harness.write_meta(meta)).stdout
        assert "Ledger PR #96 (github.com/o/r) — round 1" in out
        assert "Tracked: 4 findings" in out
        assert "Done: 3" in out
        assert "fix 1" in out
        assert "won't-fix 1" in out
        assert "follow-up 1" in out
        assert "Pending: 1" in out
        assert "Follow-ups filed: 1 (ct-42)" in out

    def test_last_round_filters_to_the_current_pass(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        self._decide(harness, meta, {"U1": {"status": "done", "decision": "fix"}})
        harness.reconcile(meta_doc([inline_comment(1), inline_comment(2)]))  # round 2 inserts U2
        out = harness.run("stats", "--meta", harness.write_meta(meta), "--last-round").stdout
        assert "Tracked: 1 findings" in out
        assert "Open: 1" in out

    def test_gitlab_unit_is_labelled_mr(self, harness):
        meta = meta_doc(
            [inline_comment(1)], number=7, url="https://gitlab.com/g/p/-/merge_requests/7", platform="gitlab"
        )
        harness.reconcile(meta)
        out = harness.run("stats", "--url", meta["unit"]["url"], "--number", "7").stdout
        assert "Ledger MR !7 (gitlab.com/g/p)" in out

    def test_missing_ledger_reports_and_exits_zero(self, harness):
        result = harness.run("stats", "--url", "https://github.com/o/r/pull/99", "--number", "99")
        assert result.returncode == 0
        assert "No ledger" in result.stdout

    def test_reversed_decision_no_longer_counts_as_a_followup(self, harness):
        """elf.54: a `follow_up` decision reversed to `fix` must drop out of the "Follow-ups
        filed" count even though the stale `followup_task_id` is still sitting on the row."""
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        self._decide(harness, meta, {"U1": {"status": "done", "decision": "follow_up", "followup_task_id": "ct-1"}})
        out = harness.run("stats", "--meta", harness.write_meta(meta)).stdout
        assert "Follow-ups filed: 1 (ct-1)" in out

        # re-opened and re-decided as `fix` in a later round; followup_task_id is not cleared
        self._decide(harness, meta, {"U1": {"status": "done", "decision": "fix"}})
        assert harness.ledger(meta)["rows"]["1"]["followup_task_id"] == "ct-1"  # stale id lingers
        out = harness.run("stats", "--meta", harness.write_meta(meta)).stdout
        assert "Follow-ups filed" not in out


class TestPurge:
    def test_unlinks_the_ledger(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        path = _ledger.ledger_path(meta["unit"]["url"], 96)
        assert path.is_file()
        result = harness.run("purge", "--url", meta["unit"]["url"], "--number", "96")
        assert result.returncode == 0, result.stderr
        assert not path.exists()

    def test_missing_ledger_is_a_no_op(self, harness):
        result = harness.run("purge", "--url", "https://github.com/o/r/pull/99", "--number", "99")
        assert result.returncode == 0
        assert "No ledger" in result.stdout

    def test_purging_one_pr_leaves_another_alone(self, harness):
        first = meta_doc([inline_comment(1)], number=96, url="https://github.com/o/r/pull/96")
        second = meta_doc([inline_comment(2)], number=97, url="https://github.com/o/r/pull/97")
        harness.reconcile(first, name="m1.json")
        harness.reconcile(second, name="m2.json")
        harness.run("purge", "--url", first["unit"]["url"], "--number", "96")
        assert _ledger.ledger_path(second["unit"]["url"], 97).is_file()

    def test_derives_number_from_github_url_when_number_omitted(self, harness):
        """elf.52(b): `--url` alone carries the number in `.../pull/<n>`."""
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        path = _ledger.ledger_path(meta["unit"]["url"], 96)
        assert path.is_file()
        result = harness.run("purge", "--url", meta["unit"]["url"])
        assert result.returncode == 0, result.stderr
        assert not path.exists()

    def test_derives_number_from_gitlab_url_when_number_omitted(self, harness):
        """elf.52(b): GitLab's `.../-/merge_requests/<n>` route."""
        meta = meta_doc(
            [inline_comment(1)], number=7, url="https://gitlab.com/g/p/-/merge_requests/7", platform="gitlab"
        )
        harness.reconcile(meta)
        path = _ledger.ledger_path(meta["unit"]["url"], 7)
        assert path.is_file()
        result = harness.run("purge", "--url", meta["unit"]["url"])
        assert result.returncode == 0, result.stderr
        assert not path.exists()

    def test_url_without_a_number_keeps_the_clear_error(self, harness):
        """elf.52(b): when the URL carries no number, the original clear error is unchanged."""
        result = harness.run("purge", "--url", "https://github.com/o/r")
        assert result.returncode == 2
        assert "flow-review-ledger:" in result.stderr
        assert "Traceback" not in result.stderr

    def test_explicit_number_still_wins_and_behaviour_is_unchanged(self, harness):
        """elf.52(b): both skill call sites pass --number too — that path must stay byte-identical."""
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        path = _ledger.ledger_path(meta["unit"]["url"], 96)
        result = harness.run("purge", "--url", meta["unit"]["url"], "--number", "96")
        assert result.returncode == 0, result.stderr
        assert not path.exists()
