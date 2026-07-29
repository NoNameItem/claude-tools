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

    def test_relative_xdg_cache_home_is_ignored_per_the_xdg_spec(self, monkeypatch):
        """A relative value is invalid per the XDG Base Directory spec — and worse, resolving
        it against the process cwd could put the ledger INSIDE a repo launched from, which is
        exactly what this module's docstring guarantees never happens."""
        monkeypatch.setattr(_ledger.os, "name", "posix")
        monkeypatch.setenv("XDG_CACHE_HOME", ".cache")
        result = _ledger.cache_base()
        assert result == Path("~/.cache").expanduser()
        assert result.is_absolute()

    # The two Windows cases assert the SETTING, never a constructed Path. Calling `cache_base()`
    # with `os.name` patched to "nt" builds a WindowsPath, which raises NotImplementedError on
    # POSIX under Python <= 3.12 -- and because the patch is live global state, the error escapes
    # into pytest's own tmp_path/cache machinery as an INTERNALERROR that aborts the entire
    # session. Locally that stayed invisible (Python 3.14 allows the foreign flavour); CI runs the
    # 3.11 floor, where it does not.
    def test_windows_uses_localappdata(self, monkeypatch):
        monkeypatch.setattr(_ledger.os, "name", "nt")
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
        assert _ledger.cache_base_setting() == r"C:\Users\me\AppData\Local"

    def test_windows_falls_back_to_appdata_local(self, monkeypatch):
        monkeypatch.setattr(_ledger.os, "name", "nt")
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        assert _ledger.cache_base_setting() == "~/AppData/Local"


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

    def test_rightmost_route_marker_wins_over_a_project_segment_named_pull(self):
        """Mirrors TestDeriveNumber's case with the same URL: the GitLab subgroup literally
        named `pull` is part of the project path, not the route."""
        assert _ledger.split_project("https://gitlab.com/group/pull/12/-/merge_requests/7") == (
            "gitlab.com",
            ["group", "pull", "12"],
        )

    def test_github_repo_segment_named_pull_does_not_swallow_the_route(self):
        """Mirrors TestDeriveNumber's case with the same URL: a repo literally named `pull`
        must survive in the project path instead of being truncated at the first `pull`."""
        assert _ledger.split_project("https://github.com/o/pull/pull/7") == (
            "github.com",
            ["o", "pull"],
        )

    def test_non_default_port_is_folded_into_the_host(self):
        """Joined with `_`, never `:` — a colon is illegal in an NTFS path component, and this
        path is built on Windows too."""
        assert _ledger.split_project("https://forge.example:8443/o/r/pull/1") == (
            "forge.example_8443",
            ["o", "r"],
        )

    def test_default_port_for_the_scheme_is_not_included(self):
        """`https://h/…` and `https://h:443/…` are the same origin and must stay ONE ledger —
        an explicit default port must not be folded into the host like a real, informative one
        would be."""
        assert _ledger.split_project("https://h/o/r/pull/1")[0] == "h"
        assert _ledger.split_project("https://h:443/o/r/pull/1")[0] == "h"

    def test_an_ipv6_literal_host_carries_no_colon_into_the_path(self):
        """`urlsplit` strips the brackets but keeps the inner colons, and a colon is illegal in an
        NTFS path component — the same reason the port is folded with `_`. Left alone, the very
        first `mkdir` for a self-hosted forge reached by IPv6 literal would fail on Windows."""
        host, segments = _ledger.split_project("https://[2001:db8::1]/o/r/pull/1")
        assert ":" not in host
        assert host == "2001-db8--1"
        assert segments == ["o", "r"]

    def test_an_ipv6_host_with_a_non_default_port_keeps_both_separators_distinct(self):
        """`-` for the address's own colons, `_` for the port — so the port stays readable as a
        port instead of blurring into the address."""
        assert _ledger.split_project("https://[2001:db8::1]:8443/o/r/pull/1")[0] == "2001-db8--1_8443"


class TestDeriveNumber:
    def test_github_and_gitlab_routes(self):
        assert _ledger.derive_number("https://github.com/o/r/pull/96") == "96"
        assert _ledger.derive_number("https://github.com/o/r/pulls/96") == "96"
        assert _ledger.derive_number("https://gitlab.com/g/p/-/merge_requests/7") == "7"
        assert _ledger.derive_number("https://gitlab.com/g/p/merge_requests/7") == "7"
        assert _ledger.derive_number("https://github.com/o/r") is None
        assert _ledger.derive_number("") is None

    def test_rightmost_route_marker_wins_over_a_project_segment_named_pull(self):
        """A GitLab subgroup literally named `pull` must not shadow the real `merge_requests`
        route: the URL below is project `group/pull/12`, MR `7` — not PR 12."""
        assert _ledger.derive_number("https://gitlab.com/group/pull/12/-/merge_requests/7") == "7"

    def test_github_repo_segment_named_pull_does_not_swallow_the_route(self):
        """`.index()` stops at the FIRST `pull`; with a repo named `pull` that one is followed by
        the route marker, not a digit, so the real number must still be found."""
        assert _ledger.derive_number("https://github.com/o/pull/pull/7") == "7"

    def test_trailing_segments_after_the_number_are_ignored(self):
        assert _ledger.derive_number("https://github.com/o/r/pull/96/files") == "96"


class TestLedgerPath:
    def test_zero_padded_number_resolves_to_the_same_ledger(self, tmp_path, monkeypatch):
        """`/pull/0012` and `--number 12` are the same PR — they must not start two ledgers."""
        monkeypatch.setattr(_ledger.os, "name", "posix")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        url = "https://github.com/o/r/pull/12"
        padded = _ledger.derive_number("https://github.com/o/r/pull/0012")
        assert _ledger.ledger_path(url, padded) == _ledger.ledger_path(url, 12)
        assert _ledger.ledger_path(url, "0012").name == "pr-12.json"

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

    def test_two_ports_on_the_same_host_do_not_collide(self, tmp_path, monkeypatch):
        """Two self-hosted forges behind one hostname on different ports own different PRs —
        without the port in the host component they would share (and clobber) one ledger."""
        monkeypatch.setattr(_ledger.os, "name", "posix")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        first = _ledger.ledger_path("https://forge.example:8443/o/r/pull/1", 1)
        second = _ledger.ledger_path("https://forge.example:9443/o/r/pull/1", 1)
        assert first != second

    def test_non_numeric_number_raises(self):
        with pytest.raises(_ledger.LedgerPathError):
            _ledger.ledger_path("https://github.com/o/r/pull/x", "../../etc/passwd")

    def test_repo_named_pull_and_repo_named_pulls_do_not_collide(self, tmp_path, monkeypatch):
        """A repo literally named `pull` (own PR #7) and a repo literally named `pulls` (own
        PR #7) must resolve to different ledgers instead of both truncating to `acme/pr-7.json`."""
        monkeypatch.setattr(_ledger.os, "name", "posix")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        repo_named_pull = _ledger.ledger_path("https://github.com/acme/pull/pull/7", 7)
        repo_named_pulls = _ledger.ledger_path("https://github.com/acme/pulls/pull/7", 7)
        assert repo_named_pull != repo_named_pulls


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

    @pytest.mark.parametrize(
        "doc",
        [
            pytest.param({"rows": {}, "next_ref": None}, id="next_ref-null"),
            pytest.param({"rows": {}, "next_ref": {"U": [1], "C": 1}}, id="next_ref-value-not-a-number"),
            pytest.param({"rows": {}, "round": [1]}, id="round-not-a-number"),
            pytest.param({"rows": {}, "unit": "github"}, id="unit-not-a-mapping"),
            pytest.param({"rows": {"comment:1": "not a row"}}, id="row-not-a-mapping"),
        ],
    )
    def test_structurally_corrupt_fields_load_as_empty(self, tmp_path, doc):
        """`setdefault` only fills a MISSING key, so a present-but-wrong-typed field survived and
        detonated later — `next_ref: null` reached `alloc_ref`'s `counters.get` as an
        AttributeError, which `main()` (catching only OSError/ValueError) let escape as a raw
        traceback. That contradicts this function's own contract: a file we did not write degrades
        to an empty ledger, never a crash."""
        path = tmp_path / "pr-1.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        loaded = _ledger.load_ledger(path)
        assert loaded == _ledger.empty_ledger()

    def test_a_valid_document_survives_the_structural_check(self, tmp_path):
        """The guard rejects wrong TYPES, not unfamiliar content: a well-formed ledger — including
        one whose round has advanced and whose rows are populated — must load unchanged."""
        path = tmp_path / "pr-1.json"
        doc = _ledger.empty_ledger({"platform": "github", "number": 1, "url": "u"})
        doc["round"] = 4
        doc["next_ref"] = {"U": 3, "C": 7}
        doc["rows"]["comment:1"] = {"ref": "C1", "thread_id": "1", "status": "open"}
        path.write_text(json.dumps(doc), encoding="utf-8")
        assert _ledger.load_ledger(path) == doc


class TestIsWorking:
    """One predicate answers "is there still work on this row" — three call sites used to answer
    it independently (the reconcile loop, `counts_of`'s fallback, and `fold_stats`), which is how a
    row could be absent from the working set and still be reported as `Open: 1`."""

    @pytest.mark.parametrize(
        ("status", "resolved", "expected"),
        [
            ("open", None, True),
            ("open", False, True),
            ("pending", None, True),
            ("skipped", None, True),
            ("done", False, False),
            ("deleted", False, False),
            ("open", True, False),
            ("pending", True, False),
            ("skipped", True, False),
        ],
    )
    def test_terminal_status_or_platform_resolution_takes_a_row_out_of_the_working_set(
        self, status, resolved, expected
    ):
        """`resolved is True` is the platform's own verdict that the thread is settled, and it is
        deliberately terminal: a reviewer who wants another look un-resolves or opens a new thread.
        Only an explicit True counts — None means "not determined this round" and must never be
        read as "resolved", or one failed side-query would retire every open finding."""
        assert _ledger.is_working({"status": status, "resolved": resolved}) is expected


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

    def test_row_key_of_is_namespaced_with_the_same_priority_as_thread_id(self):
        """`row_key_of` picks the same id, in the same comment/discussion/summary priority
        order, as `thread_id_of` — but prefixes it, since the ledger key's only job is
        identity WITHIN the document, where three independent platform sequences share one
        dict."""
        assert _ledger.row_key_of({"comment_id": 5, "discussion_id": None, "summary_id": None}) == "comment:5"
        assert _ledger.row_key_of({"comment_id": None, "discussion_id": "abc", "summary_id": None}) == "discussion:abc"
        assert _ledger.row_key_of({"comment_id": None, "discussion_id": None, "summary_id": 9}) == "summary:9"
        assert _ledger.row_key_of({"comment_id": None, "discussion_id": None, "summary_id": None}) is None

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
        assert rows["comment:1"]["ref"] == "U1"
        assert rows["comment:2"]["ref"] == "C1"
        assert rows["comment:3"]["ref"] == "C2"

    def test_collector_ref_is_ignored(self, harness):
        meta = meta_doc([inline_comment(1, ref="C7")])
        harness.reconcile(meta)
        assert harness.ledger(meta)["rows"]["comment:1"]["ref"] == "U1"

    def test_kind_and_identity_are_stamped_on_insert(self, harness):
        meta = meta_doc([inline_comment(None, kind="summary", summary_id=900)])
        harness.reconcile(meta)
        row = harness.ledger(meta)["rows"]["summary:900"]
        assert row["kind"] == "summary"
        # this fixture's summary carries no thread (the GitHub review-body case) → nothing to
        # mark; `thread_mark` is seeded from the thread, not from `kind` — see the GitLab
        # general-discussion case below, which DOES have a thread and seeds a real mark.
        assert row["thread_mark"] is None
        assert row["thread_id"] == "900"
        assert row["platform"] == "github"
        assert row["first_seen_round"] == 1

    def test_gitlab_general_discussion_summary_seeds_thread_mark_from_its_thread(self, harness):
        """A GitLab general (no-position) discussion is emitted by `gl_collect` with
        `kind == "summary"` too, but — unlike a GitHub review-body summary — it carries a real
        `discussion_id` and an appendable thread (see `gl_collect`). `thread_mark` must seed
        from that thread like any other row, not be forced to null because of `kind`."""
        meta = meta_doc(
            [inline_comment(None, kind="summary", discussion_id="d1", path="(summary)", line=None, thread=[reply(50)])]
        )
        harness.reconcile(meta)
        assert harness.ledger(meta)["rows"]["discussion:d1"]["thread_mark"] == 50

    def test_existing_row_keeps_its_ref_and_counter_does_not_move(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1), inline_comment(2)]))
        rows = harness.ledger(meta)["rows"]
        assert rows["comment:1"]["ref"] == "U1"
        assert rows["comment:2"]["ref"] == "U2"

    def test_round_counter_increments_per_run(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        assert harness.reconcile(meta)["round"] == 2
        assert harness.ledger(meta)["round"] == 2

    def test_snapshot_fields_are_refreshed_every_round(self, harness):
        harness.reconcile(meta_doc([inline_comment(1, body="old", line=42)]))
        harness.reconcile(meta_doc([inline_comment(1, body="new", line=61, outdated=True)]))
        row = harness.ledger(meta_doc([]))["rows"]["comment:1"]
        assert row["body"] == "new"
        assert row["line"] == 61
        assert row["outdated"] is True

    def test_identity_fields_survive_a_conflicting_snapshot(self, harness):
        harness.reconcile(meta_doc([inline_comment(1, is_bot=True)]))
        harness.reconcile(meta_doc([inline_comment(1, is_bot=True, kind="summary")]))
        assert harness.ledger(meta_doc([]))["rows"]["comment:1"]["kind"] == "inline"  # kind is set-on-insert

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

    def test_summary_and_inline_comment_sharing_the_same_numeric_id_get_two_rows(self, harness):
        """C1: GitHub numbers review-body summaries and inline comments from SEPARATE
        sequences, so the same integer can legitimately name both. `row_key_of`'s namespacing
        is what keeps them apart — a bare numeric key would let one clobber the other."""
        summary = inline_comment(None, kind="summary", summary_id=1, path="(summary)", line=None)
        inline = inline_comment(1)
        meta = meta_doc([summary, inline])
        out = harness.reconcile(meta)
        rows = harness.ledger(meta)["rows"]
        assert set(rows) == {"summary:1", "comment:1"}
        refs = {rows["summary:1"]["ref"], rows["comment:1"]["ref"]}
        assert len(refs) == 2  # two distinct, independent refs — neither row clobbered the other
        assert {e["ref"] for e in out["working_set"]} == refs

    def test_thread_id_on_the_row_stays_bare_for_every_source(self, harness):
        """`row["thread_id"]` is the reply target and goes straight into a platform API path —
        unlike the ledger's own (namespaced) key, it must never carry a `row_key_of` prefix, or
        every reply would 404."""
        comment = inline_comment(5)
        discussion = inline_comment(None, kind="summary", discussion_id="d9", path="(summary)", line=None)
        summary = inline_comment(None, kind="summary", summary_id=42, path="(summary)", line=None)
        meta = meta_doc([comment, discussion, summary])
        harness.reconcile(meta)
        rows = harness.ledger(meta)["rows"]
        assert rows["comment:5"]["thread_id"] == "5"
        assert rows["discussion:d9"]["thread_id"] == "d9"
        assert rows["summary:42"]["thread_id"] == "42"


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
        row = harness.ledger(meta)["rows"]["comment:1"]
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
        row = harness.ledger(meta)["rows"]["comment:1"]
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

    def test_done_github_summary_never_reopens(self, harness):
        """The GitHub companion case: a review-body summary is threadless, so it can never carry
        a reply we haven't accounted for — `id_advanced` is False whenever `current` is None,
        independent of `kind`. That is the deterministic elf.31 guarantee: a re-imported review
        carries the same, immutable summary id."""
        summary = inline_comment(None, kind="summary", summary_id=900, path="(summary)", line=None)
        meta = meta_doc([summary])
        harness.reconcile(meta)
        settle(harness, meta, "U1", thread_mark=None, decision="follow_up")
        # a rerun re-imports the SAME review id → the row is still done → no duplicate follow-up
        assert harness.reconcile(meta)["working_set"] == []

    def test_done_gitlab_general_discussion_reopens_on_a_new_note(self, harness):
        """The regression this class guards against: `gl_collect` emits a GitLab general
        (no-position) discussion with `kind == "summary"` too, but it carries a real
        `discussion_id` and an appendable thread — unlike a GitHub review-body summary, it is
        NOT threadless. A `done` row for it must still re-open when the discussion gains a new
        note, or that feedback silently disappears from `flow:review-loop`."""
        general = inline_comment(
            None, kind="summary", discussion_id="d1", path="(summary)", line=None, thread=[reply(50)]
        )
        meta = meta_doc([general])
        harness.reconcile(meta)
        settle(harness, meta, "U1", thread_mark=50)
        out = harness.reconcile(
            meta_doc(
                [
                    inline_comment(
                        None,
                        kind="summary",
                        discussion_id="d1",
                        path="(summary)",
                        line=None,
                        thread=[reply(50), reply(51, body="one more thing")],
                    )
                ]
            )
        )
        assert [e["ref"] for e in out["working_set"]] == ["U1"]
        row = harness.ledger(meta)["rows"]["discussion:d1"]
        assert row["status"] == "open"

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


class TestReconcileResolution:
    """`resolved` is a snapshot field that drives status independently of a new reply: a
    platform-side resolve/unresolve is not something `reopen_if_advanced`'s reply-id check can
    ever see (see `apply_resolution`)."""

    def test_resolved_true_seeds_a_new_row_as_done(self, harness):
        meta = meta_doc([inline_comment(1, resolved=True)])
        out = harness.reconcile(meta)
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["status"] == "done"
        assert out["working_set"] == []

    def test_a_previously_resolved_row_reopens_when_the_new_snapshot_says_unresolved(self, harness):
        """Someone hit "Unresolve" — an explicit request to look again that no reply id
        advanced, so `reopen_if_advanced` would never catch it; only `apply_resolution` does."""
        meta = meta_doc([inline_comment(1, resolved=True)])
        harness.reconcile(meta)
        out = harness.reconcile(meta_doc([inline_comment(1, resolved=False)]))
        assert [e["ref"] for e in out["working_set"]] == ["U1"]
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "open"

    def test_resolved_none_leaves_a_done_rows_status_untouched(self, harness):
        """`resolved is None` means "unknown this round" (e.g. a GitHub side-query hiccup), not
        "not resolved" — treating it as False would mass-reopen every settled thread the moment
        that query failed."""
        meta = meta_doc([inline_comment(1, resolved=True)])
        harness.reconcile(meta)
        out = harness.reconcile(meta_doc([inline_comment(1)]))  # resolved absent -> None
        assert out["working_set"] == []
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "done"

    def test_resolved_none_leaves_an_open_rows_status_untouched(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        out = harness.reconcile(meta_doc([inline_comment(1)]))  # resolved absent -> None
        assert [e["status"] for e in out["working_set"]] == ["open"]
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "open"

    def test_a_row_absent_from_the_next_rounds_snapshot_is_marked_deleted(self, harness):
        """The thread no longer exists on the platform -> `deleted`, excluded from the working
        set, and `counts["working"]` (which reconcile derives from the emitted `working_set`,
        not a row tally) reflects the shrunk set."""
        meta = meta_doc([inline_comment(1), inline_comment(2)])
        harness.reconcile(meta)
        out = harness.reconcile(meta_doc([inline_comment(2)]))  # comment 1 vanished
        assert [e["ref"] for e in out["working_set"]] == ["U2"]
        assert out["counts"]["working"] == len(out["working_set"]) == 1
        rows = harness.ledger(meta)["rows"]
        assert rows["comment:1"]["status"] == "deleted"
        assert rows["comment:2"]["status"] == "open"

    def test_an_unknown_round_does_not_erase_the_remembered_resolution(self, harness):
        """A failed side-query (`resolved: None`) must not cost the row its memory of having been
        resolved: `apply_resolution` compares the next round's value against the stored one, so if
        "unknown" overwrote it, the genuine un-resolve in round 3 would read as "was never
        resolved" and the finding would stay `done` forever -- invisible, with no reply and no
        working-set entry."""
        meta = meta_doc([inline_comment(1, resolved=True)])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1)]))  # side-query failed → resolved is None
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "done"
        out = harness.reconcile(meta_doc([inline_comment(1, resolved=False)]))
        assert [e["ref"] for e in out["working_set"]] == ["U1"]
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "open"

    def test_a_deleted_row_returns_to_work_when_the_thread_reappears(self, harness):
        """`deleted` is a verdict about the CURRENT snapshot, not a tombstone. If the thread is
        back, the verdict was wrong -- keeping it terminal would silently retire a live finding,
        and nothing else can revive it (`reopen_if_advanced` and `apply_resolution` both key on
        `done`)."""
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([]))
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "deleted"
        out = harness.reconcile(meta)
        assert [e["ref"] for e in out["working_set"]] == ["U1"]
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "open"

    def test_an_already_done_row_absent_next_round_stays_done_not_deleted(self, harness):
        """`deleted` is settled by the platform, `done` by us — `mark_absent` must not clobber a
        terminal status that is already ours with a different terminal status."""
        meta = meta_doc([inline_comment(1, resolved=True)])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([]))  # the row vanishes from the snapshot entirely
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "done"

    def test_settling_a_row_by_resolution_accounts_for_the_replies_already_in_the_thread(self, harness):
        """Settling a row leaves NO unaccounted reply behind it. Without that, a resolve that
        arrives together with a new reply settles the status but not `thread_mark`, so the reply
        stays "unseen" forever: on any later round where the side-query degrades to unknown,
        `reopen_if_advanced` fires on the stale mark and `apply_resolution` — a no-op on None —
        cannot undo it. The settled thread silently returns to the working set and gets a second
        reply."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51)], resolved=True)]))
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["status"] == "done"
        assert row["thread_mark"] == 51

        out = harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51)])]))
        assert out["working_set"] == []
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "done"

    def test_a_reply_arriving_after_the_resolve_does_not_return_a_resolved_thread_to_work(self, harness):
        """A DELIBERATE choice, and the inverse of what this test asserted when it was written: a
        thread the platform still reports as resolved stays out of the working set no matter how
        many replies land in it. A reviewer who wants another look un-resolves the thread or opens
        a new one — both of which do bring it back (see the un-resolve test above). The alternative,
        re-opening on any reply, means every "thanks, looks good" re-triages a settled finding.

        The reply-id bookkeeping below is untouched: `reopen_if_advanced` still flips the status to
        `open` here. What changed is that WORKING-SET membership now also consults `resolved`, so
        the row is excluded regardless — which is what makes the behaviour independent of whether
        this round's resolution side-query happened to succeed."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51)], resolved=True)]))
        out = harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51), reply(52)])]))
        assert out["working_set"] == []
        assert out["counts"]["working"] == 0
        assert harness.ledger(meta)["rows"]["comment:1"]["resolved"] is True

    def test_reconciles_own_counts_do_not_report_a_resolved_row_as_open(self, harness):
        """`counts` and `working_set` travel in ONE payload, so they must not contradict each other.
        Migrating only `counts["working"]` moved the disagreement one field over: the same object
        would claim `working: 0` and `open: 1` for the same row, and `stats` — folded correctly —
        would then disagree with `reconcile` about the same ledger."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51)], resolved=True)]))
        out = harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51), reply(52)])]))
        assert out["counts"]["working"] == 0
        assert out["counts"]["open"] == 0
        assert out["counts"]["resolved_upstream"] == 1
        assert out["counts"]["total"] == 1

    def test_an_unresolved_thread_returns_to_work_even_though_its_status_was_never_open(self, harness):
        """The escape hatch that makes the rule above safe: un-resolving is what a reviewer does to
        ask for another look, and it must work even when no reply id advanced."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)], resolved=True)])
        harness.reconcile(meta)
        assert harness.reconcile(meta)["working_set"] == []
        out = harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50)], resolved=False)]))
        assert [e["ref"] for e in out["working_set"]] == ["U1"]


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
        row = harness.ledger(meta)["rows"]["comment:1"]
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
        assert harness.ledger(meta)["rows"]["comment:1"]["followup_task_id"] == "ct-42"

    def test_pending_and_skipped_are_written_verbatim(self, harness):
        meta = meta_doc([inline_comment(1), inline_comment(2)])
        harness.reconcile(meta)
        self._record(
            harness,
            meta,
            {"U1": {"status": "pending", "decision": "fix"}, "U2": {"status": "skipped", "decision": "skip"}},
        )
        rows = harness.ledger(meta)["rows"]
        assert rows["comment:1"]["status"] == "pending"
        assert rows["comment:2"]["status"] == "skipped"

    def test_reason_with_shell_metacharacters_survives_verbatim(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        hostile = "won't fix: `$(id)` and a FLOW_RC_EOF line\nsecond line"
        self._record(harness, meta, {"U1": {"status": "done", "decision": "wont_fix", "reason": hostile}})
        assert harness.ledger(meta)["rows"]["comment:1"]["reason"] == hostile

    def test_unknown_ref_warns_but_still_records_the_rest(self, harness):
        """Rows that DID match are still saved and the payload is unchanged, but the exit code
        is non-zero (the plugin's "no silent failures" convention) so a caller that does not
        inspect the JSON still learns the batch was not fully recorded."""
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = self._record(harness, meta, {"U1": {"status": "done"}, "C9": {"status": "done"}})
        assert result.returncode == 1
        assert "C9" in result.stderr
        assert json.loads(result.stdout) == {"recorded": 1, "unknown": ["C9"]}
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "done"

    def test_invalid_status_writes_nothing(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = self._record(harness, meta, {"U1": {"status": "finished"}})
        assert result.returncode == 2
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "open"

    def test_invalid_decision_writes_nothing(self, harness):
        """elf.53(a): mirrors test_invalid_status_writes_nothing for the `decision` field."""
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = self._record(harness, meta, {"U1": {"decision": "maybe"}})
        assert result.returncode == 2
        assert harness.ledger(meta)["rows"]["comment:1"]["decision"] is None

    def test_re_recording_the_same_decision_is_a_no_op(self, harness):
        """elf.53(b): recording an identical decision twice must not change the row further."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        decision = {"U1": {"status": "done", "decision": "fix", "reason": "guard added", "thread_mark": 50}}
        self._record(harness, meta, decision)
        first = dict(harness.ledger(meta)["rows"]["comment:1"])
        self._record(harness, meta, decision)
        second = harness.ledger(meta)["rows"]["comment:1"]
        assert first == second

    def _settle_all_fields(self, harness, meta):
        self._record(
            harness,
            meta,
            {
                "U1": {
                    "status": "done",
                    "decision": "follow_up",
                    "reason": "deferred",
                    "followup_task_id": "ct-1",
                    "thread_mark": 50,
                }
            },
        )

    def test_omitting_a_key_is_a_no_op_for_every_field(self, harness):
        """Half of the convention: an ABSENT key means "no new information" — the stored value
        survives. (The other half: an explicit null CLEARS, see the tests below.)"""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        self._settle_all_fields(harness, meta)
        before = dict(harness.ledger(meta)["rows"]["comment:1"])
        result = self._record(harness, meta, {"U1": {}})
        assert result.returncode == 0, result.stderr
        after = harness.ledger(meta)["rows"]["comment:1"]
        for field in ("status", "decision", "reason", "followup_task_id", "thread_mark"):
            assert after[field] == before[field], field

    def test_explicit_null_clears_decision_reason_and_followup_task_id(self, harness):
        """The other half: ordinary JSON-merge semantics — an explicit null CLEARS the field."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        self._settle_all_fields(harness, meta)
        result = self._record(harness, meta, {"U1": {"decision": None, "reason": None, "followup_task_id": None}})
        assert result.returncode == 0, result.stderr
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["decision"] is None
        assert row["reason"] is None
        assert row["followup_task_id"] is None
        assert row["status"] == "done"  # untouched: the key was absent

    def test_null_followup_task_id_clears_a_previous_rounds_task(self, harness):
        """review-comments/SKILL.md 5.7a's canonical decisions.json writes
        `"followup_task_id": null` on a `fix` entry for exactly this reason: a ref decided
        `follow_up` in an earlier round and re-decided `fix` now must NOT keep the stale task id
        (it re-surfaces in "Follow-ups filed" the moment a later round decides `follow_up` again
        without supplying a fresh one)."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        self._record(harness, meta, {"U1": {"status": "done", "decision": "follow_up", "followup_task_id": "ct-1"}})
        self._record(
            harness,
            meta,
            {
                "U1": {
                    "status": "done",
                    "decision": "fix",
                    "reason": "guard added",
                    "followup_task_id": None,
                    "thread_mark": 50,
                }
            },
        )
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["followup_task_id"] is None
        assert row["decision"] == "fix"
        # and it stays cleared through a later `follow_up` that files no task
        self._record(harness, meta, {"U1": {"status": "done", "decision": "follow_up", "thread_mark": 50}})
        assert harness.ledger(meta)["rows"]["comment:1"]["followup_task_id"] is None

    def test_explicit_null_status_is_rejected_and_writes_nothing(self, harness):
        """`status` is the one NON-nullable field: the row has no "no status" state, so a null
        there is malformed input, rejected like an unknown status — all-or-nothing."""
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = self._record(harness, meta, {"U1": {"status": None, "decision": "fix"}})
        assert result.returncode == 2
        assert "Traceback" not in result.stderr
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["status"] == "open"
        assert row["decision"] is None  # nothing written at all

    def test_null_thread_mark_on_a_summary_row_is_the_skill_example(self, harness):
        """5.7a's `C5` entry: a GitHub `kind == "summary"` row has no thread, so its mark is
        `null`. Clearing an already-empty mark is inert, and a summary never re-opens."""
        summary = inline_comment(None, kind="summary", summary_id=900, path="(summary)", line=None)
        meta = meta_doc([summary])
        harness.reconcile(meta)
        result = self._record(
            harness,
            meta,
            {"U1": {"status": "done", "decision": "follow_up", "followup_task_id": "ct-9", "thread_mark": None}},
        )
        assert result.returncode == 0, result.stderr
        assert harness.ledger(meta)["rows"]["summary:900"]["thread_mark"] is None
        assert harness.reconcile(meta)["working_set"] == []

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
        assert harness.ledger(meta)["rows"]["comment:1"]["thread_mark"] == 50  # unchanged, pre-reply

        posted = [reply(50), reply(5001, user="me", is_bot=False, body="Won't fix: …")]
        out = harness.reconcile(meta_doc([inline_comment(1, thread=posted)]))
        assert [e["ref"] for e in out["working_set"]] == ["U1"]
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["status"] == "open"
        assert row["decision"] == "wont_fix"  # the settled verdict is kept, but it re-triages

    def test_null_thread_mark_on_a_threaded_row_clears_it_and_re_opens(self, harness):
        """The same trap by the other door: on a row that HAS a thread, an explicit null clears
        the mark, so the next reply reads as an advance (`id_advanced(current, None)` is True) and
        the settled row re-opens. `null` is only for a threadless row (a GitHub review-body
        summary) — NOT for every `kind == "summary"` row, since a GitLab general-discussion
        summary has a thread too; a threaded `done` entry must carry the id of the reply just
        posted."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        self._record(harness, meta, {"U1": {"status": "done", "decision": "fix", "thread_mark": None}})
        assert harness.ledger(meta)["rows"]["comment:1"]["thread_mark"] is None
        out = harness.reconcile(meta)
        assert [e["ref"] for e in out["working_set"]] == ["U1"]
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "open"


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

    def test_a_resolved_row_is_reported_as_resolved_upstream_not_as_open(self, harness):
        """`stats` is what review-loop prints in its convergence report, so it must answer "is
        there work left" the same way `reconcile` does. Counting a resolved row under `Open` would
        make that report contradict itself: nothing in the working set, yet `Open: 1`."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51)], resolved=True)]))
        # A reply lands on the resolved thread while this round's resolution is unknown: the row's
        # status goes back to `open`, but the platform's last known verdict still settles it.
        harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51), reply(52)])]))
        out = harness.run("stats", "--meta", harness.write_meta(meta)).stdout
        assert "Open: 0" in out
        assert "Resolved upstream: 1" in out

    def test_resolved_upstream_is_omitted_when_there_is_none(self, harness):
        """Same rule as `Deleted upstream`: a permanent zero would be noise on every clean run."""
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        assert "Resolved upstream" not in harness.run("stats", "--meta", harness.write_meta(meta)).stdout

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
        assert harness.ledger(meta)["rows"]["comment:1"]["followup_task_id"] == "ct-1"  # stale id lingers
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

    def test_zero_padded_url_purges_the_same_ledger(self, harness):
        """A zero-padded link must hit the ledger `--number 12` created, not a second one."""
        meta = meta_doc([inline_comment(1)], number=12, url="https://github.com/o/r/pull/12")
        harness.reconcile(meta)
        path = _ledger.ledger_path(meta["unit"]["url"], 12)
        assert path.is_file()
        result = harness.run("purge", "--url", "https://github.com/o/r/pull/0012")
        assert result.returncode == 0, result.stderr
        assert not path.exists()

    def test_subgroup_named_pull_purges_the_merge_request_not_the_subgroup(self, harness):
        """The rightmost route marker decides: project `group/pull/12`, MR `7`."""
        url = "https://gitlab.com/group/pull/12/-/merge_requests/7"
        meta = meta_doc([inline_comment(1)], number=7, url=url, platform="gitlab")
        harness.reconcile(meta)
        path = _ledger.ledger_path(url, 7)
        assert path.is_file()
        result = harness.run("purge", "--url", url)
        assert result.returncode == 0, result.stderr
        assert not path.exists()

    def test_explicit_number_still_wins_and_behaviour_is_unchanged(self, harness):
        """elf.52(b): both skill call sites pass --number too — that path must stay byte-identical."""
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        path = _ledger.ledger_path(meta["unit"]["url"], 96)
        result = harness.run("purge", "--url", meta["unit"]["url"], "--number", "96")
        assert result.returncode == 0, result.stderr
        assert not path.exists()
