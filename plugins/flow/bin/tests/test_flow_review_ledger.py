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
    """One predicate answers "is there still work on this row" — `reconcile`, `counts_of` and
    `fold_stats` all go through it, which is how a row could otherwise be absent from the
    working set and still be reported as `Open: 1`."""

    @pytest.mark.parametrize(
        ("status", "platform_state", "expected"),
        [
            ("open", "live", True),
            ("open", "resolved", False),
            ("open", "absent", False),
            ("done", "live", False),
            ("done", "resolved", False),
            ("done", "absent", False),
        ],
    )
    def test_only_open_status_and_live_platform_state_together_are_still_work(self, status, platform_state, expected):
        """Two independent axes, one condition each: `status` is ours, `platform_state` is the
        platform's, and BOTH must say "still live" for the row to count as outstanding work."""
        assert _ledger.is_working({"status": status, "platform_state": platform_state}) is expected


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


class TestReplyPrimitives:
    def test_is_ours_matches_the_run_account(self):
        assert _ledger.is_ours({"user": "me"}, "me")
        assert not _ledger.is_ours({"user": "coderabbitai"}, "me")

    def test_is_ours_is_false_when_the_account_is_unknown(self):
        """A meta document without `me` must not make every reply ours."""
        assert not _ledger.is_ours({"user": "me"}, None)
        assert not _ledger.is_ours({"user": "me"}, "")

    def test_reply_order_sorts_chronologically(self):
        replies = [
            {"id": 2, "created_at": "2026-07-20T12:00:00Z"},
            {"id": 1, "created_at": "2026-07-20T10:00:00Z"},
        ]
        assert [r["id"] for r in sorted(replies, key=_ledger.reply_order)] == [1, 2]

    def test_reply_order_parses_a_trailing_z(self):
        """`fromisoformat` learned the bare `Z` only in 3.11; these helpers run on a 3.9 floor,
        so the suffix is rewritten before parsing. Without it the sort degrades to a no-op on
        exactly the interpreters CI never exercises."""
        assert _ledger.reply_order({"created_at": "2026-07-20T10:00:00Z"})[0] == 0

    def test_reply_order_parses_an_explicit_offset_with_fractional_seconds(self):
        assert _ledger.reply_order({"created_at": "2026-07-20T10:00:00.000+02:00"})[0] == 0

    def test_reply_order_sinks_an_unusable_timestamp_to_the_tail(self):
        replies = [
            {"id": 1, "created_at": None},
            {"id": 2, "created_at": "2026-07-20T10:00:00Z"},
            {"id": 3, "created_at": "not a date"},
        ]
        assert [r["id"] for r in sorted(replies, key=_ledger.reply_order)] == [2, 1, 3]

    def test_reply_order_keeps_insertion_order_for_equal_timestamps(self):
        stamp = "2026-07-20T10:00:00Z"
        replies = [{"id": 1, "created_at": stamp}, {"id": 2, "created_at": stamp}]
        assert [r["id"] for r in sorted(replies, key=_ledger.reply_order)] == [1, 2]

    def test_unseen_lists_only_replies_carrying_a_false_bit(self):
        row = {
            "thread": [
                {"id": 1, "seen": True},
                {"id": 2, "seen": False},
                {"id": 3},  # no bit at all -> not from a ledger row, so not "new to us"
            ]
        }
        assert [r["id"] for r in _ledger.unseen(row)] == [2]

    def test_unseen_tolerates_a_thread_that_is_not_a_list(self):
        """`flow-comment-card` renders untyped input through this helper; a string thread must
        not reach `.get` and die as a bare traceback."""
        assert _ledger.unseen({"thread": "nonsense"}) == []
        assert _ledger.unseen({"thread": ["not a dict"]}) == []
        assert _ledger.unseen({}) == []


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


def summary_comment(summary_id, *, body="### Codex Review", **overrides):
    """A GitHub review-body summary: no reply target, no resolvable thread."""
    item = {
        "user": "chatgpt-codex-connector",
        "is_bot": False,
        "kind": "summary",
        "path": "(summary)",
        "start_line": None,
        "line": None,
        "outdated": False,
        "already_replied": False,
        "comment_id": None,
        "discussion_id": None,
        "summary_id": summary_id,
        "body": body,
        "thread": [],
        "diff_hunk": None,
        "side": None,
        "position": None,
        "snippet": None,
        "ref": "IGNORED",
    }
    item.update(overrides)
    return item


def gitlab_discussion(discussion_id, *, kind="inline", thread=None, resolved=False, **overrides):
    """A GitLab discussion — general ones are `kind == "summary"` yet fully repliable."""
    item = {
        "user": "alice",
        "is_bot": False,
        "kind": kind,
        "path": "(summary)" if kind == "summary" else "a.py",
        "start_line": None,
        "line": None if kind == "summary" else 42,
        "outdated": False,
        "already_replied": False,
        "comment_id": None,
        "discussion_id": discussion_id,
        "summary_id": None,
        "body": "finding",
        "thread": thread or [],
        "diff_hunk": None,
        "side": None,
        "position": None,
        "snippet": None,
        "resolved": resolved,
        "ref": "IGNORED",
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


def reply(reply_id, *, user="coderabbitai", body="ack", is_bot=True, created_at="2026-07-20T10:00:00Z"):
    return {"user": user, "body": body, "id": reply_id, "created_at": created_at, "is_bot": is_bot}


def settle(harness, meta, ref, *, thread_mark, status="done", decision="fix"):
    """Mark a row done directly in the ledger (Task 6's `record` does this in production)."""
    path = _ledger.ledger_path(meta["unit"]["url"], meta["unit"]["number"])
    doc = _ledger.load_ledger(path)
    row = _ledger.find_row_by_ref(doc, ref)
    row["status"] = status
    row["decision"] = decision
    row["thread_mark"] = thread_mark
    _ledger.save_ledger(path, doc)


def force_row(harness, meta, ref, **fields):
    """Force a row's stored fields directly to an exact combination, bypassing every writer.

    A generalisation of `settle` for the transition table below: any field can be forced
    (`status`, `platform_state`, `thread_mark`, ...), because the point of that table is the
    transition OUT of a stored combination, not how the row got there.
    """
    path = _ledger.ledger_path(meta["unit"]["url"], meta["unit"]["number"])
    doc = _ledger.load_ledger(path)
    row = _ledger.find_row_by_ref(doc, ref)
    row.update(fields)
    _ledger.save_ledger(path, doc)


def record_decisions(harness, meta, decisions, head="abc1234"):
    """Run `record` with a decisions file; returns the CompletedProcess.

    The one way this file drives `record` — promoted from the old `TestRecord._record`, and
    also used by `TestStats` call sites that used to keep their own private `_decide` copy.
    """
    path = harness.tmp_path / "decisions.json"
    path.write_text(json.dumps(decisions), encoding="utf-8")
    return harness.run("record", "--meta", harness.write_meta(meta), "--decisions", str(path), "--head", head)


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
    """`platform_state` is a snapshot field recomputed every round independently of a new reply:
    a platform-side resolve/unresolve is not something `reopen_if_advanced`'s reply-id check can
    ever see (see `platform_state_of`)."""

    def test_resolved_true_seeds_a_new_row_as_open_off_the_platform_axis(self, harness):
        meta = meta_doc([inline_comment(1, resolved=True)])
        out = harness.reconcile(meta)
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["status"] == "open"
        assert row["platform_state"] == "resolved"
        assert _ledger.is_working(row) is False
        assert out["working_set"] == []

    def test_a_previously_resolved_row_reopens_when_the_new_snapshot_says_unresolved(self, harness):
        """Someone hit "Unresolve" — an explicit request to look again that no reply id
        advanced, so `reopen_if_advanced` would never catch it; only the platform-axis
        recomputation does, and it does so without touching `status` at all."""
        meta = meta_doc([inline_comment(1, resolved=True)])
        harness.reconcile(meta)
        before = harness.ledger(meta)["rows"]["comment:1"]["status"]
        out = harness.reconcile(meta_doc([inline_comment(1, resolved=False)]))
        assert [e["ref"] for e in out["working_set"]] == ["U1"]
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["platform_state"] == "live"
        assert _ledger.is_working(row) is True
        assert row["status"] == before  # no status write happened

    def test_a_row_absent_from_the_next_rounds_snapshot_is_marked_absent(self, harness):
        """The thread no longer exists on the platform -> `platform_state: absent`, excluded from
        the working set, and `counts["working"]` (which reconcile derives from the emitted
        `working_set`, not a row tally) reflects the shrunk set. `status` is untouched — absence
        is the platform's verdict, not ours."""
        meta = meta_doc([inline_comment(1), inline_comment(2)])
        harness.reconcile(meta)
        out = harness.reconcile(meta_doc([inline_comment(2)]))  # comment 1 vanished
        assert [e["ref"] for e in out["working_set"]] == ["U2"]
        assert out["counts"]["working"] == len(out["working_set"]) == 1
        rows = harness.ledger(meta)["rows"]
        assert rows["comment:1"]["platform_state"] == "absent"
        assert rows["comment:1"]["status"] == "open"
        assert rows["comment:2"]["status"] == "open"

    def test_a_deleted_row_returns_to_work_when_the_thread_reappears(self, harness):
        """`absent` is a verdict about the CURRENT snapshot, not a tombstone: the very next round
        that sees the thread again recomputes `platform_state` back to `live`, no special-casing
        needed. The row's decision survives the round-trip intact — the old `deleted` status
        routed revival through a status write that lost exactly this history."""
        meta = meta_doc([inline_comment(1, thread=[reply(10)])])
        harness.reconcile(meta)
        record_decisions(
            harness,
            meta,
            {
                "U1": {
                    "status": "open",
                    "decision": "follow_up",
                    "reason": "later",
                    "followup_task_id": "ct-1",
                    "thread_mark": 10,
                }
            },
        )
        harness.reconcile(meta_doc([]))
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["platform_state"] == "absent"
        out = harness.reconcile(meta)
        assert [e["ref"] for e in out["working_set"]] == ["U1"]
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["platform_state"] == "live"
        assert row["decision"] == "follow_up"
        assert row["reason"] == "later"
        assert row["followup_task_id"] == "ct-1"

    def test_an_already_done_row_absent_next_round_stays_done(self, harness):
        """`done` is ours, `absent` is the platform's — the two axes never clobber each other."""
        meta = meta_doc([inline_comment(1, resolved=True, thread=[reply(50)])])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"status": "done", "decision": "wont_fix", "thread_mark": 50}})
        assert result.returncode == 0, result.stderr
        harness.reconcile(meta_doc([]))  # the row vanishes from the snapshot entirely
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["status"] == "done"
        assert row["platform_state"] == "absent"

    def test_an_unresolved_thread_returns_to_work_even_though_its_status_was_never_open(self, harness):
        """The escape hatch that makes the exclusion above safe: un-resolving is what a reviewer
        does to ask for another look, and it must work even when no reply id advanced and no
        status write ever happened."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)], resolved=True)])
        harness.reconcile(meta)
        assert harness.reconcile(meta)["working_set"] == []
        out = harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50)], resolved=False)]))
        assert [e["ref"] for e in out["working_set"]] == ["U1"]

    def test_a_reply_arriving_while_still_resolved_does_not_return_a_resolved_thread_to_work(self, harness):
        """A DELIBERATE choice: a thread the platform still reports as resolved stays out of the
        working set no matter how many replies land in it. A reviewer who wants another look
        un-resolves the thread or opens a new one — both of which do bring it back (see the
        un-resolve test above). The alternative, re-opening on any reply, means every "thanks,
        looks good" re-triages a settled finding.

        `reopen_if_advanced` never fires here because it only touches a `done` row, and nothing
        in this redesign sets `status` from a resolve — the row was never `done` to begin with.
        """
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51)], resolved=True)]))
        out = harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51), reply(52)], resolved=True)]))
        assert out["working_set"] == []
        assert out["counts"]["working"] == 0
        assert harness.ledger(meta)["rows"]["comment:1"]["platform_state"] == "resolved"

    def test_reconciles_own_counts_do_not_report_a_resolved_row_as_open(self, harness):
        """`counts` and `working_set` travel in ONE payload, so they must not contradict each
        other: a resolved row is out of the working set AND out of `open`, landing instead in
        `resolved_upstream`."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51)], resolved=True)]))
        out = harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51), reply(52)], resolved=True)]))
        assert out["counts"]["working"] == 0
        assert out["counts"]["open"] == 0
        assert out["counts"]["resolved_upstream"] == 1
        assert out["counts"]["total"] == 1


# Observation → the collector's item this round, or None for "not in the snapshot at all".
_OBSERVATIONS = {
    "present_live": {"resolved": False},
    "present_resolved": {"resolved": True},
    "absent": None,
}

# (stored status, stored platform_state, observation) -> (status, platform_state, is_working)
_TRANSITIONS = {
    ("open", "live", "present_live"): ("open", "live", True),
    ("open", "live", "present_resolved"): ("open", "resolved", False),
    ("open", "live", "absent"): ("open", "absent", False),
    ("open", "resolved", "present_live"): ("open", "live", True),
    ("open", "resolved", "present_resolved"): ("open", "resolved", False),
    ("open", "resolved", "absent"): ("open", "absent", False),
    ("open", "absent", "present_live"): ("open", "live", True),
    ("open", "absent", "present_resolved"): ("open", "resolved", False),
    ("open", "absent", "absent"): ("open", "absent", False),
    ("done", "live", "present_live"): ("done", "live", False),
    ("done", "live", "present_resolved"): ("done", "resolved", False),
    ("done", "live", "absent"): ("done", "absent", False),
    ("done", "resolved", "present_live"): ("done", "live", False),
    ("done", "resolved", "present_resolved"): ("done", "resolved", False),
    ("done", "resolved", "absent"): ("done", "absent", False),
    ("done", "absent", "present_live"): ("done", "live", False),
    ("done", "absent", "present_resolved"): ("done", "resolved", False),
    ("done", "absent", "absent"): ("done", "absent", False),
}


def test_transitions_table_is_exhaustive_by_construction():
    """The docstring below claims "exhaustive by construction: 2 statuses x 3 platform states x
    3 observations" — but `_TRANSITIONS` is 18 hand-written keys with nothing tying them to
    `_ledger.STATUSES` / `_ledger.PLATFORM_STATES` / `_OBSERVATIONS`. A new platform state (or a
    typo dropping one of the 18 rows) would silently go uncovered while the claim stayed
    unchallenged. This pins the table to the actual enums so the claim is enforced, not just
    asserted in prose."""
    assert set(_TRANSITIONS) == {
        (status, platform_state, observation)
        for status in _ledger.STATUSES
        for platform_state in _ledger.PLATFORM_STATES
        for observation in _OBSERVATIONS
    }


@pytest.mark.parametrize(
    ("status", "platform_state", "observation", "expected"),
    [(status, state, obs, expected) for (status, state, obs), expected in _TRANSITIONS.items()],
)
def test_the_whole_transition_table(harness, status, platform_state, observation, expected):
    """Exhaustive by construction: 2 statuses x 3 platform states x 3 observations.

    The audit that motivated this redesign found six uncovered transitions precisely because
    tests were written one per noticed case. Adding a value to either axis must stop this table
    from covering everything unless it is extended deliberately.

    The thread never grows between the two rounds, so `reopen_if_advanced` cannot fire and this
    table isolates the platform axis. Re-opening has its own test below.
    """
    meta = meta_doc([inline_comment(1, thread=[reply(10)])])
    harness.reconcile(meta)
    # Round 1 seeds the row; it is then forced into the stored combination directly, because the
    # point is the transition OUT of every state, not how each state was reached.
    force_row(harness, meta, "U1", status=status, platform_state=platform_state, thread_mark=10)

    item = _OBSERVATIONS[observation]
    comments = [] if item is None else [inline_comment(1, thread=[reply(10)], **item)]
    payload = harness.reconcile(meta_doc(comments))

    row = harness.ledger(meta)["rows"]["comment:1"]
    assert (row["status"], row["platform_state"]) == expected[:2]
    assert _ledger.is_working(row) is expected[2]
    assert (len(payload["working_set"]) == 1) is expected[2]


def test_a_done_row_still_reopens_when_its_thread_advances(harness):
    """The one status write reconcile still performs, isolated from the platform axis."""
    meta = meta_doc([inline_comment(1, thread=[reply(10)])])
    harness.reconcile(meta)
    force_row(harness, meta, "U1", status="done", platform_state="live", thread_mark=10)

    harness.reconcile(meta_doc([inline_comment(1, resolved=False, thread=[reply(10), reply(11)])]))
    row = harness.ledger(meta)["rows"]["comment:1"]
    assert row["status"] == "open"
    assert _ledger.is_working(row) is True


def test_reconcile_never_writes_status_from_platform_state(harness):
    """The disease this redesign cures: the platform used to overwrite OUR field.

    A decided-but-undelivered row walks the whole platform axis — resolved, un-resolved, gone,
    back — and every durable field we own must come out byte-identical.
    """
    meta = meta_doc([inline_comment(1, thread=[reply(10)])])
    harness.reconcile(meta)
    result = record_decisions(
        harness, meta, {"U1": {"status": "open", "decision": "fix", "reason": "push deferred", "thread_mark": 10}}
    )
    assert result.returncode == 0, result.stderr
    ours = ("status", "decision", "reason", "followup_task_id")

    def mine():
        return {k: harness.ledger(meta)["rows"]["comment:1"][k] for k in ours}

    before = mine()

    for resolved in (True, False, True):
        harness.reconcile(meta_doc([inline_comment(1, resolved=resolved, thread=[reply(10)])]))
        assert mine() == before
    harness.reconcile(meta_doc([]))  # the thread vanishes
    assert mine() == before
    harness.reconcile(meta_doc([inline_comment(1, thread=[reply(10)])]))  # and comes back
    assert mine() == before


def test_a_decided_but_undelivered_row_is_not_settled_by_a_platform_resolve(harness):
    """The concrete bug: `record` wrote "decided, reply withheld", a human clicked Resolve, and
    the row was silently marked done — the promised reply never posted and never re-surfaced."""
    meta = meta_doc([inline_comment(1, thread=[reply(10)])])
    harness.reconcile(meta)
    record_decisions(
        harness, meta, {"U1": {"status": "open", "decision": "fix", "reason": "push deferred", "thread_mark": 10}}
    )

    harness.reconcile(meta_doc([inline_comment(1, resolved=True, thread=[reply(10)])]))
    row = harness.ledger(meta)["rows"]["comment:1"]
    assert row["status"] == "open", "the platform must not settle a decision we never delivered"
    assert row["decision"] == "fix"
    assert row["platform_state"] == "resolved"
    assert _ledger.is_working(row) is False, "excluded on the platform axis only"

    harness.reconcile(meta_doc([inline_comment(1, resolved=False, thread=[reply(10)])]))
    row = harness.ledger(meta)["rows"]["comment:1"]
    assert _ledger.is_working(row) is True, "un-resolving returns it with its decision intact"
    assert row["decision"] == "fix"


def test_record_never_writes_platform_state(harness):
    meta = meta_doc([inline_comment(1, resolved=True, thread=[reply(10)])])
    harness.reconcile(meta)
    assert harness.ledger(meta)["rows"]["comment:1"]["platform_state"] == "resolved"
    result = record_decisions(
        harness, meta, {"U1": {"status": "done", "decision": "wont_fix", "reason": "why", "thread_mark": 10}}
    )
    assert result.returncode == 0, result.stderr
    assert harness.ledger(meta)["rows"]["comment:1"]["platform_state"] == "resolved"


def test_the_stats_buckets_partition_every_row(harness):
    """`done` + `Open` + `Resolved upstream` + `Deleted upstream` must account for every tracked
    row, or `stats` — what review-loop prints in its convergence report — contradicts
    `reconcile`: nothing in the working set, yet `Open: 1`.

    Asserted through the rendered `stats` output because `flow-review-ledger` is a script without
    a `.py` extension: this test file drives it as a SUBPROCESS and imports only `_ledger`. Do not
    add an importlib shim to reach `fold_stats` directly.
    """
    meta = meta_doc([inline_comment(n, thread=[reply(10)]) for n in range(1, 7)])
    harness.reconcile(meta)
    combinations = [
        ("open", "live"),
        ("open", "resolved"),
        ("open", "absent"),
        ("done", "live"),
        ("done", "resolved"),
        ("done", "absent"),
    ]
    for n, (status, platform_state) in enumerate(combinations, start=1):
        force_row(harness, meta, f"U{n}", status=status, platform_state=platform_state, thread_mark=10)

    out = harness.run("stats", "--meta", harness.write_meta(meta)).stdout
    assert "Tracked: 6 findings" in out
    assert "Done: 3" in out  # done x (live, resolved, absent)
    assert "Open: 1" in out  # only (open, live) is work
    assert "Resolved upstream: 1" in out
    assert "Deleted upstream: 1" in out


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
        row = _ledger.find_row_by_ref(harness.ledger(meta), "C1")
        assert emitted == {**row, "resurfaced": _ledger.resurfaced(row)}

    def test_get_reports_whether_the_row_resurfaced(self, harness):
        """The Phase-3 subagent must not compute this itself: a prose rule and a code rule for
        the same question drift, which is the class of bug this whole change is cleaning up."""
        meta = meta_doc([inline_comment(1, thread=[reply(10)])])
        harness.reconcile(meta)
        force_row(harness, meta, "U1", thread_mark=10, thread=[reply(10), reply(11)])
        result = harness.run("get", "--meta", harness.write_meta(meta), "--ref", "U1")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["resurfaced"] is True

    def test_get_reports_not_resurfaced_for_an_undelivered_decision(self, harness):
        """`open` + a decision + an unadvanced thread means "decided, never delivered" — the
        round's job is to deliver it, not to re-litigate it."""
        meta = meta_doc([inline_comment(1, thread=[reply(10), reply(11)])])
        harness.reconcile(meta)
        force_row(harness, meta, "U1", thread_mark=11, decision="fix", reason="push deferred")
        result = harness.run("get", "--meta", harness.write_meta(meta), "--ref", "U1")
        assert json.loads(result.stdout)["resurfaced"] is False

    def test_the_computed_field_is_not_persisted(self, harness):
        """Derived per read; a stored copy would be a second source of truth to keep in sync."""
        meta = meta_doc([inline_comment(1, thread=[reply(10)])])
        harness.reconcile(meta)
        force_row(harness, meta, "U1", thread_mark=10, thread=[reply(10), reply(11)])
        harness.run("get", "--meta", harness.write_meta(meta), "--ref", "U1")
        assert "resurfaced" not in harness.ledger(meta)["rows"]["comment:1"]


class TestRecord:
    def test_applies_a_decision_by_ref(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = record_decisions(
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
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        record_decisions(
            harness,
            meta,
            {"U1": {"status": "done", "decision": "follow_up", "followup_task_id": "ct-42", "thread_mark": 50}},
        )
        assert harness.ledger(meta)["rows"]["comment:1"]["followup_task_id"] == "ct-42"

    def test_reason_with_shell_metacharacters_survives_verbatim(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        hostile = "won't fix: `$(id)` and a FLOW_RC_EOF line\nsecond line"
        record_decisions(
            harness, meta, {"U1": {"status": "done", "decision": "wont_fix", "reason": hostile, "thread_mark": 50}}
        )
        assert harness.ledger(meta)["rows"]["comment:1"]["reason"] == hostile

    def test_unknown_ref_warns_but_still_records_the_rest(self, harness):
        """Rows that DID match are still saved and the payload is unchanged, but the exit code
        is non-zero (the plugin's "no silent failures" convention) so a caller that does not
        inspect the JSON still learns the batch was not fully recorded."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        result = record_decisions(
            harness, meta, {"U1": {"status": "done", "thread_mark": 50}, "C9": {"status": "done"}}
        )
        assert result.returncode == 1
        assert "C9" in result.stderr
        assert json.loads(result.stdout) == {"recorded": 1, "unknown": ["C9"]}
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "done"

    def test_invalid_status_writes_nothing(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"status": "finished"}})
        assert result.returncode == 2
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "open"

    def test_invalid_decision_writes_nothing(self, harness):
        """elf.53(a): mirrors test_invalid_status_writes_nothing for the `decision` field."""
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"decision": "maybe"}})
        assert result.returncode == 2
        assert harness.ledger(meta)["rows"]["comment:1"]["decision"] is None

    def test_re_recording_the_same_decision_is_a_no_op(self, harness):
        """elf.53(b): recording an identical decision twice must not change the row further."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        decision = {"U1": {"status": "done", "decision": "fix", "reason": "guard added", "thread_mark": 50}}
        result = record_decisions(harness, meta, decision)
        assert result.returncode == 0, result.stderr
        first = dict(harness.ledger(meta)["rows"]["comment:1"])
        result = record_decisions(harness, meta, decision)
        assert result.returncode == 0, result.stderr
        second = harness.ledger(meta)["rows"]["comment:1"]
        assert first == second

    def _settle_all_fields(self, harness, meta):
        record_decisions(
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
        result = record_decisions(harness, meta, {"U1": {}})
        assert result.returncode == 0, result.stderr
        after = harness.ledger(meta)["rows"]["comment:1"]
        for field in ("status", "decision", "reason", "followup_task_id", "thread_mark"):
            assert after[field] == before[field], field

    def test_explicit_null_clears_decision_reason_and_followup_task_id(self, harness):
        """The other half: ordinary JSON-merge semantics — an explicit null CLEARS the field."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        self._settle_all_fields(harness, meta)
        result = record_decisions(harness, meta, {"U1": {"decision": None, "reason": None, "followup_task_id": None}})
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
        result = record_decisions(
            harness,
            meta,
            {"U1": {"status": "done", "decision": "follow_up", "followup_task_id": "ct-1", "thread_mark": 50}},
        )
        assert result.returncode == 0, result.stderr
        result = record_decisions(
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
        assert result.returncode == 0, result.stderr
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["followup_task_id"] is None
        assert row["decision"] == "fix"
        # and it stays cleared through a later `follow_up` that files no task
        result = record_decisions(harness, meta, {"U1": {"status": "done", "decision": "follow_up", "thread_mark": 50}})
        assert result.returncode == 0, result.stderr
        assert harness.ledger(meta)["rows"]["comment:1"]["followup_task_id"] is None

    def test_explicit_null_status_is_rejected_and_writes_nothing(self, harness):
        """`status` is the one NON-nullable field: the row has no "no status" state, so a null
        there is malformed input, rejected like an unknown status — all-or-nothing."""
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"status": None, "decision": "fix"}})
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
        result = record_decisions(
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
        result = record_decisions(harness, meta, {"U1": {"status": "done"}})
        assert result.returncode != 0
        assert "flow-review-ledger:" in result.stderr
        assert "Traceback" not in result.stderr
        assert not path.exists()

    def test_recorded_row_is_excluded_on_the_next_reconcile(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"status": "done", "decision": "fix", "thread_mark": 50}})
        assert result.returncode == 0, result.stderr
        assert harness.reconcile(meta)["working_set"] == []


class TestRecordThreadMarkInvariant:
    def _ledger_bytes(self, meta):
        return _ledger.ledger_path(meta["unit"]["url"], meta["unit"]["number"]).read_text(encoding="utf-8")

    def test_explicit_null_thread_mark_is_rejected_on_threaded_row(self, harness):
        """An explicit null on a threaded row clears the mark to "nothing accounted for", which
        causes the next reconcile to re-open on our reply."""
        meta = meta_doc([inline_comment(1, thread=[reply(10)])])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"status": "done", "thread_mark": None}})
        assert result.returncode == 2
        assert "thread_mark" in result.stderr

    def test_done_without_thread_mark_is_allowed_for_a_github_summary(self, harness):
        """The one row shape with no reply target and no platform resolution: our `done` is its
        only exit, and it has no thread to mark."""
        meta = meta_doc([summary_comment(900)])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"status": "done", "decision": "wont_fix"}})
        assert result.returncode == 0, result.stderr
        assert harness.ledger(meta)["rows"]["summary:900"]["status"] == "done"

    def test_a_gitlab_summary_is_not_exempt(self, harness):
        """It is `kind == "summary"` too, but carries a real discussion id, so it is threaded —
        only a GitHub review body is exempt."""
        meta = meta_doc(
            [gitlab_discussion("d1", kind="summary")],
            url="https://gitlab.com/g/r/-/merge_requests/96",
            platform="gitlab",
        )
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"status": "done", "decision": "fix"}})
        assert result.returncode == 2
        assert "thread_mark" in result.stderr

    def test_done_without_thread_mark_is_rejected_on_inline_comment_with_empty_thread(self, harness):
        """An inline comment with no replies yet has thread_mark=None. If it will receive a
        reply (the one we are about to post), we must account for it. Omitting thread_mark
        lets the row stay at None, so the next reply reads as an advance and reopens forever."""
        meta = meta_doc([inline_comment(1)])  # no thread= kwarg → thread=[]
        harness.reconcile(meta)
        before = self._ledger_bytes(meta)

        result = record_decisions(harness, meta, {"U1": {"status": "done", "decision": "fix"}})
        assert result.returncode == 2
        assert "thread_mark" in result.stderr
        assert self._ledger_bytes(meta) == before, "the whole batch is rejected, nothing written"

    def test_a_rejected_batch_writes_none_of_its_other_refs(self, harness):
        """When one entry has thread_mark=None and is threaded, the whole batch is rejected."""
        meta = meta_doc([inline_comment(1), inline_comment(2)])  # Both have empty threads
        harness.reconcile(meta)
        before = self._ledger_bytes(meta)

        result = record_decisions(
            harness,
            meta,
            {
                "U1": {"status": "done", "decision": "fix", "thread_mark": 77},
                "U2": {"status": "done", "decision": "fix"},  # No thread_mark, thread_mark=None → rejected
            },
        )
        assert result.returncode == 2
        assert self._ledger_bytes(meta) == before, "U1 must not land just because it was first"


class TestStats:
    def test_cumulative_block(self, harness):
        comments = [inline_comment(i, thread=[reply(50)]) for i in range(1, 5)]
        meta = meta_doc(comments)
        harness.reconcile(meta)
        assert (
            record_decisions(
                harness,
                meta,
                {
                    "U1": {"status": "done", "decision": "fix", "thread_mark": 50},
                    "U2": {"status": "done", "decision": "wont_fix", "thread_mark": 50},
                    "U3": {"status": "done", "decision": "follow_up", "followup_task_id": "ct-42", "thread_mark": 50},
                    "U4": {"status": "open", "decision": "fix"},
                },
            ).returncode
            == 0
        )
        out = harness.run("stats", "--meta", harness.write_meta(meta)).stdout
        assert "Ledger PR #96 (github.com/o/r) — round 1" in out
        assert "Tracked: 4 findings" in out
        assert "Done: 3" in out
        assert "fix 1" in out
        assert "won't-fix 1" in out
        assert "follow-up 1" in out
        assert "Open: 1" in out
        assert "(decided but not delivered: 1)" in out
        assert "Follow-ups filed: 1 (ct-42)" in out

    def test_a_resolved_row_is_reported_as_resolved_upstream_not_as_open(self, harness):
        """`stats` is what review-loop prints in its convergence report, so it must answer "is
        there work left" the same way `reconcile` does. Counting a resolved row under `Open` would
        make that report contradict itself: nothing in the working set, yet `Open: 1`."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51)], resolved=True)]))
        # A reply lands on the thread while the platform still reports it resolved: `status` was
        # never touched by the resolve to begin with, so there is nothing for the reply to re-open.
        harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51), reply(52)], resolved=True)]))
        out = harness.run("stats", "--meta", harness.write_meta(meta)).stdout
        assert "Open: 0" in out
        assert "Resolved upstream: 1" in out

    def test_resolved_upstream_is_omitted_when_there_is_none(self, harness):
        """Same rule as `Deleted upstream`: a permanent zero would be noise on every clean run."""
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        out = harness.run("stats", "--meta", harness.write_meta(meta)).stdout
        assert "Resolved upstream" not in out
        assert "Deleted upstream" not in out

    def test_last_round_filters_to_the_current_pass(self, harness):
        """`last_round` is written only by `new_row` (on insert) and `cmd_record` (on a
        decision) — `cmd_reconcile` must NOT bump it just because a row is present in a round's
        snapshot, or `--last-round` (and the "last pass" block `flow:review-loop` prints at
        convergence) would balloon to the whole ledger the moment every row simply survives into
        the next round."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        assert (
            record_decisions(harness, meta, {"U1": {"status": "done", "decision": "fix", "thread_mark": 50}}).returncode
            == 0
        )
        harness.reconcile(
            meta_doc([inline_comment(1, thread=[reply(50)]), inline_comment(2)])
        )  # round 2: U1 merely re-seen, U2 created
        out = harness.run("stats", "--meta", harness.write_meta(meta), "--last-round").stdout
        assert "Tracked: 1 findings" in out
        assert "Open: 1" in out
        # The regression this guards against: U1 was decided in round 1 and only RE-SEEN (not
        # re-decided) in round 2, so it must not sneak into round 2's "last pass" view.
        assert "Done: 0" in out

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
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        assert (
            record_decisions(
                harness,
                meta,
                {"U1": {"status": "done", "decision": "follow_up", "followup_task_id": "ct-1", "thread_mark": 50}},
            ).returncode
            == 0
        )
        out = harness.run("stats", "--meta", harness.write_meta(meta)).stdout
        assert "Follow-ups filed: 1 (ct-1)" in out

        # re-opened and re-decided as `fix` in a later round; followup_task_id is not cleared
        assert (
            record_decisions(harness, meta, {"U1": {"status": "done", "decision": "fix", "thread_mark": 50}}).returncode
            == 0
        )
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


class TestPlatformStateOf:
    def test_a_resolved_item_maps_to_resolved(self) -> None:
        assert _ledger.platform_state_of({"resolved": True}) == "resolved"

    def test_an_unresolved_item_maps_to_live(self) -> None:
        assert _ledger.platform_state_of({"resolved": False}) == "live"

    def test_a_missing_resolved_key_maps_to_live(self) -> None:
        # `None` is legal for exactly one input — a GitHub review-body summary, which has no
        # thread and never consults the resolution side-query. "Not applicable" for such a row
        # means "live until we settle it". It no longer means "could not determine": the
        # collector aborts instead (see the collector task), so that second meaning is gone.
        assert _ledger.platform_state_of({}) == "live"
        assert _ledger.platform_state_of({"resolved": None}) == "live"


class TestThreadless:
    def test_a_github_summary_is_threadless(self) -> None:
        assert _ledger.threadless({"platform": "github", "kind": "summary"}) is True

    def test_a_github_inline_row_is_not(self) -> None:
        assert _ledger.threadless({"platform": "github", "kind": "inline"}) is False

    def test_a_gitlab_summary_is_not_threadless(self) -> None:
        # A GitLab general discussion is `kind == "summary"` too, but it carries a real
        # discussion id and can be replied to, so it is a normal threaded row. Conflating the
        # two would let a `done` row skip its thread mark and re-open on our own reply forever.
        assert _ledger.threadless({"platform": "gitlab", "kind": "summary"}) is False


class TestResurfaced:
    def test_a_row_whose_thread_grew_past_its_mark_is_resurfaced(self) -> None:
        row = {"thread": [{"id": 10}, {"id": 20}], "thread_mark": 10}
        assert _ledger.resurfaced(row) is True

    def test_a_row_whose_mark_is_current_is_not(self) -> None:
        row = {"thread": [{"id": 10}, {"id": 20}], "thread_mark": 20}
        assert _ledger.resurfaced(row) is False

    def test_a_threadless_row_is_never_resurfaced(self) -> None:
        assert _ledger.resurfaced({"thread": [], "thread_mark": None}) is False

    def test_it_reuses_id_advanced(self) -> None:
        # One rule for "did the thread advance?", not two: the flag and `reopen_if_advanced`
        # must never disagree about the same row.
        row = {"thread": [{"id": 7}], "thread_mark": None}
        assert _ledger.resurfaced(row) is _ledger.id_advanced(7, None)


class TestRecordReply:
    """`record`'s new one-round instruction: the reply this round posted."""

    @staticmethod
    def _thread(harness, meta):
        return harness.ledger(meta)["rows"]["comment:1"]["thread"]

    def test_record_paints_every_stored_reply_seen(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50), reply(51)])])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"status": "done", "decision": "fix", "thread_mark": 51}})
        assert result.returncode == 0, result.stderr
        assert [x.get("seen") for x in self._thread(harness, meta)] == [True, True]

    def test_record_paints_on_an_open_row_too(self, harness):
        """The re-litigation fix depends on it: a decided-but-undelivered row went through
        Phase 4 with the whole thread in front of the agent, which is what `seen` asserts."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        result = record_decisions(
            harness, meta, {"U1": {"status": "open", "decision": "fix", "reason": "push skipped"}}
        )
        assert result.returncode == 0, result.stderr
        assert [x.get("seen") for x in self._thread(harness, meta)] == [True]

    def test_record_appends_the_posted_reply_marked_seen(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        posted = {"id": 60, "user": "me", "body": "Fixed: guard added", "created_at": "2026-07-20T11:00:00Z"}
        result = record_decisions(
            harness, meta, {"U1": {"status": "done", "decision": "fix", "thread_mark": 60, "reply": posted}}
        )
        assert result.returncode == 0, result.stderr
        thread = self._thread(harness, meta)
        assert [x["id"] for x in thread] == [50, 60]
        assert thread[-1]["seen"] is True
        assert thread[-1]["body"] == "Fixed: guard added"

    def test_the_appended_reply_sorts_by_created_at_not_arrival(self, harness):
        """Arrival order is wrong in C2's own scenario: a reviewer's reply merged after ours
        can predate it, and a thread where our answer precedes the objection it answers reads
        backwards."""
        meta = meta_doc([inline_comment(1, thread=[reply(50, created_at="2026-07-20T10:00:00Z")])])
        harness.reconcile(meta)
        posted = {"id": 60, "user": "me", "body": "Fixed", "created_at": "2026-07-20T09:00:00Z"}
        record_decisions(
            harness, meta, {"U1": {"status": "done", "decision": "fix", "thread_mark": 60, "reply": posted}}
        )
        assert [x["id"] for x in self._thread(harness, meta)] == [60, 50]

    def test_appending_the_same_reply_twice_stores_it_once(self, harness):
        """5.7 checkpoints a ref the moment its reply is accepted, then 5.7a closes the round.
        Storing it twice would render it twice and re-surface the finding forever."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        posted = {"id": 60, "user": "me", "body": "Fixed", "created_at": "2026-07-20T11:00:00Z"}
        entry = {"U1": {"status": "done", "decision": "fix", "thread_mark": 60, "reply": posted}}
        record_decisions(harness, meta, entry)
        record_decisions(harness, meta, entry)
        assert [x["id"] for x in self._thread(harness, meta)] == [50, 60]

    def test_a_stored_numeric_id_matches_a_string_id_handed_back(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        base = {"user": "me", "body": "Fixed", "created_at": "2026-07-20T11:00:00Z"}
        record_decisions(
            harness, meta, {"U1": {"status": "done", "decision": "fix", "thread_mark": 60, "reply": {**base, "id": 60}}}
        )
        record_decisions(
            harness,
            meta,
            {"U1": {"status": "done", "decision": "fix", "thread_mark": 60, "reply": {**base, "id": "60"}}},
        )
        assert [str(x["id"]) for x in self._thread(harness, meta)] == ["50", "60"]

    def test_reply_is_not_stored_as_a_row_field(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        posted = {"id": 60, "user": "me", "body": "Fixed", "created_at": "2026-07-20T11:00:00Z"}
        record_decisions(
            harness, meta, {"U1": {"status": "done", "decision": "fix", "thread_mark": 60, "reply": posted}}
        )
        assert "reply" not in harness.ledger(meta)["rows"]["comment:1"]

    def test_a_reply_without_an_id_rejects_the_whole_batch(self, harness):
        """The id is the sole basis of matching: a reply stored without one is appended again
        by the next reconcile as if new, and the row re-surfaces forever."""
        meta = meta_doc([inline_comment(1), inline_comment(2)])
        harness.reconcile(meta)
        result = record_decisions(
            harness,
            meta,
            {
                "U1": {"status": "done", "decision": "fix", "thread_mark": 60},
                "U2": {
                    "status": "done",
                    "decision": "wont_fix",
                    "thread_mark": 61,
                    "reply": {"user": "me", "body": "x"},
                },
            },
        )
        assert result.returncode == 2
        assert "reply" in result.stderr
        rows = harness.ledger(meta)["rows"]
        assert rows["comment:1"]["status"] == "open"
        assert rows["comment:2"]["status"] == "open"

    def test_a_reply_that_is_not_an_object_rejects_the_batch(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = record_decisions(
            harness, meta, {"U1": {"status": "done", "decision": "fix", "thread_mark": 60, "reply": "3518155060"}}
        )
        assert result.returncode == 2
        assert harness.ledger(meta)["rows"]["comment:1"]["status"] == "open"
