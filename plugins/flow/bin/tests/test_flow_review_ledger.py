"""Tests for the persistent per-PR review ledger (_ledger core + flow-review-ledger CLI)."""

# bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

from __future__ import annotations

import json
import re
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
            pytest.param({"schema": _ledger.SCHEMA, "rows": {}, "next_ref": None}, id="next_ref-null"),
            pytest.param(
                {"schema": _ledger.SCHEMA, "rows": {}, "next_ref": {"U": [1], "C": 1}}, id="next_ref-value-not-a-number"
            ),
            pytest.param({"schema": _ledger.SCHEMA, "rows": {}, "round": [1]}, id="round-not-a-number"),
            pytest.param({"schema": _ledger.SCHEMA, "rows": {}, "unit": "github"}, id="unit-not-a-mapping"),
            pytest.param({"schema": _ledger.SCHEMA, "rows": {"comment:1": "not a row"}}, id="row-not-a-mapping"),
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
        doc["rows"]["comment:1"] = {"ref": "C1", "thread_id": "1", "seen": False, "thread": []}
        path.write_text(json.dumps(doc), encoding="utf-8")
        assert _ledger.load_ledger(path) == doc

    def test_a_document_without_a_schema_key_counts_as_current(self, tmp_path):
        path = tmp_path / "pr-1.json"
        path.write_text(json.dumps({"round": 3, "rows": {"comment:1": {"ref": "C1"}}}), encoding="utf-8")
        loaded = _ledger.load_ledger(path)
        assert loaded["schema"] == _ledger.SCHEMA
        assert loaded["rows"] == {"comment:1": {"ref": "C1"}}

    def test_a_document_stamped_with_another_schema_loads_as_empty(self, tmp_path):
        """Well-formed but meaning something else: a schema-1 row has no comment-level `seen`,
        so read as-is only its replies' bits would count, and every open thread with no unseen
        reply would be hidden."""
        path = tmp_path / "pr-1.json"
        doc = {"schema": 1, "round": 3, "rows": {"comment:1": {"ref": "C1", "status": "open"}}}
        path.write_text(json.dumps(doc), encoding="utf-8")
        assert _ledger.load_ledger(path) == _ledger.empty_ledger()


# The places an unseen message can sit in a row — the comment itself or a reply — or none.
_UNSEEN_PLACES = {
    "the-comment": {"seen": False, "thread": [{"id": 1, "seen": True}]},
    "a-reply": {"seen": True, "thread": [{"id": 1, "seen": True}, {"id": 2, "seen": False}]},
    "nothing": {"seen": True, "thread": [{"id": 1, "seen": True}]},
    "nothing-threadless": {"seen": True, "thread": []},
}


class TestIsWorking:
    """One predicate answers "is there still work on this row" — `reconcile`, `counts_of` and
    `fold_stats` all go through it, which is how a row could otherwise be absent from the
    working set and still be reported as `Open: 1`."""

    @pytest.mark.parametrize("platform_state", _ledger.PLATFORM_STATES)
    @pytest.mark.parametrize("unseen", list(_UNSEEN_PLACES))
    def test_only_a_live_thread_with_something_unseen_is_work(self, platform_state, unseen):
        """Selection reads `platform_state` and the `seen` bits, and nothing else."""
        row = {"platform_state": platform_state, **_UNSEEN_PLACES[unseen]}
        expected = platform_state == "live" and not unseen.startswith("nothing")
        assert _ledger.has_unseen(row) is not unseen.startswith("nothing")
        assert _ledger.is_working(row) is expected

    def test_a_row_without_any_seen_bit_is_not_work(self):
        """Every ledger writer stamps the bit, so a row without one did not come from a ledger;
        treating it as new would make raw collector output look like a working set."""
        assert _ledger.is_working({"platform_state": "live", "thread": [{"id": 1}]}) is False


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


class TestReplyPrimitives:
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
        "counts": {"total": len(comments)},
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
    def test_first_round_inserts_every_comment_unseen(self, harness):
        meta = meta_doc([inline_comment(1), inline_comment(2, is_bot=True)])
        out = harness.reconcile(meta)
        assert out["round"] == 1
        assert out["counts"]["total"] == 2
        assert {e["ref"] for e in out["working_set"]} == {"U1", "C1"}
        assert all("status" not in e for e in out["working_set"])
        assert [row["seen"] for row in harness.ledger(meta)["rows"].values()] == [False, False]

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
        # seed as seen — see the GitLab general-discussion case below, which DOES have a thread.
        assert row["thread"] == []
        assert row["thread_id"] == "900"
        assert row["platform"] == "github"
        assert row["first_seen_round"] == 1

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
        harness.reconcile(meta_doc([inline_comment(1, line=42)]))
        harness.reconcile(meta_doc([inline_comment(1, line=61, outdated=True)]))
        row = harness.ledger(meta_doc([]))["rows"]["comment:1"]
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

    def test_a_gitlab_general_discussion_summary_seeds_its_thread_unseen(self, harness):
        general = gitlab_discussion("d1", kind="summary", thread=[reply(50)])
        meta = meta_doc([general], platform="gitlab", url="https://gitlab.com/g/p/-/merge_requests/7", number=7)
        harness.reconcile(meta)
        row = harness.ledger(meta)["rows"]["discussion:d1"]
        assert [x["seen"] for x in row["thread"]] == [False]
        assert "thread_mark" not in row

    def test_the_seeded_thread_is_sorted_by_created_at(self, harness):
        meta = meta_doc(
            [
                inline_comment(
                    1,
                    thread=[
                        reply(51, created_at="2026-07-20T12:00:00Z"),
                        reply(50, created_at="2026-07-20T10:00:00Z"),
                    ],
                )
            ]
        )
        harness.reconcile(meta)
        assert [x["id"] for x in harness.ledger(meta)["rows"]["comment:1"]["thread"]] == [50, 51]


def reply(reply_id, *, user="coderabbitai", body="ack", is_bot=True, created_at="2026-07-20T10:00:00Z"):
    return {"user": user, "body": body, "id": reply_id, "created_at": created_at, "is_bot": is_bot}


MARK = _ledger.AGENT_MARKER


def ours(reply_id, body="Fixed: guard added", created_at="2026-07-20T11:00:00Z"):
    return reply(reply_id, user="me", is_bot=False, body=f"{body}\n\n{MARK}", created_at=created_at)


def owner(reply_id, body="maybe this check is not needed", created_at="2026-07-20T12:00:00Z"):
    return reply(reply_id, user="me", is_bot=False, body=body, created_at=created_at)


def settle(harness, meta, ref, *, decision="fix"):
    """Settle a row directly in the ledger: the comment and every stored reply painted seen.

    This is what `record` does in production for an entry marked `"settled": true` — the round
    delivered the thread's outcome — so a settled row holds nothing unseen.
    """
    path = _ledger.ledger_path(meta["unit"]["url"], meta["unit"]["number"])
    doc = _ledger.load_ledger(path)
    row = _ledger.find_row_by_ref(doc, ref)
    row["seen"] = True
    row["decision"] = decision
    for stored in row.get("thread") or []:
        stored["seen"] = True
    _ledger.save_ledger(path, doc)


def force_row(harness, meta, ref, **fields):
    """Force a row's stored fields directly to an exact combination, bypassing every writer.

    A generalisation of `settle`: any field can be forced (`seen`, `platform_state`, `thread`,
    ...), for tests whose point is what a stored combination does next, not how the row got
    there.
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


class TestUnseenSelection:
    def test_pr151_new_bot_thread_with_an_unmarked_owner_reply_is_working(self, harness):
        meta = meta_doc([inline_comment(1, is_bot=True, thread=[owner(50)])])
        out = harness.reconcile(meta)
        assert [e["ref"] for e in out["working_set"]] == ["C1"]
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["seen"] is False
        assert (row["thread"][0]["seen"], row["thread"][0]["author_role"]) == (False, "owner")
        assert "status" not in row

    def test_pr151_card_renders_the_reconciled_row_with_markers_and_the_owner_label(self, harness):
        """End to end on one ledger: `reconcile` writes the row, `flow-comment-card --ledger`
        reads it. Each half has its own test on its own input, so a key that one side writes and
        the other reads under another name (`seen`, `author_role`) would pass both."""
        meta = meta_doc([inline_comment(1, is_bot=True, thread=[owner(50)])])
        out = harness.reconcile(meta)
        verdict = harness.tmp_path / "verdict.json"
        verdict.write_text("{}", encoding="utf-8")
        card = run_helper(
            "flow-comment-card", "--ledger", out["ledger"], "--ref", "C1", "--verdict", str(verdict), env=harness.env
        )
        assert card.returncode == 0, card.stderr
        assert "> [new] **@coderabbitai:** finding" in card.stdout
        assert "> ↳ [new] **@me (you):** maybe this check is not needed" in card.stdout

    def test_an_owner_reply_after_our_answer_brings_the_thread_back(self, harness):
        meta = meta_doc([inline_comment(1, is_bot=True)])
        harness.reconcile(meta)
        settle(harness, meta, "C1")
        meta["comments"][0]["thread"] = [ours(60), owner(70)]
        assert [e["ref"] for e in harness.reconcile(meta)["working_set"]] == ["C1"]

    def test_our_marked_reply_with_an_unrecorded_id_arrives_seen(self, harness):
        meta = meta_doc([inline_comment(1, is_bot=True)])
        harness.reconcile(meta)
        settle(harness, meta, "C1")
        meta["comments"][0]["thread"] = [ours(60)]
        assert harness.reconcile(meta)["working_set"] == []
        stored = harness.ledger(meta)["rows"]["comment:1"]["thread"][0]
        assert (stored["seen"], stored["author_role"]) == (True, "agent")

    def test_a_bot_reply_quoting_the_marker_arrives_unseen(self, harness):
        meta = meta_doc([inline_comment(1, is_bot=True)])
        harness.reconcile(meta)
        settle(harness, meta, "C1")
        meta["comments"][0]["thread"] = [reply(61, body=f"> {MARK}\nThanks")]
        assert [e["ref"] for e in harness.reconcile(meta)["working_set"]] == ["C1"]

    def test_a_lost_ledger_seeds_everything_up_to_our_last_marked_reply(self, harness):
        meta = meta_doc([inline_comment(1, is_bot=True, thread=[reply(50), ours(60)])])
        assert harness.reconcile(meta)["working_set"] == []
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["seen"] is True
        assert [r["seen"] for r in row["thread"]] == [True, True]

    def test_a_lost_ledger_keeps_a_reply_after_ours_unseen(self, harness):
        thread = [ours(60), reply(70, created_at="2026-07-20T13:00:00Z")]
        meta = meta_doc([inline_comment(1, is_bot=True, thread=thread)])
        assert [e["ref"] for e in harness.reconcile(meta)["working_set"]] == ["C1"]
        assert [r["seen"] for r in harness.ledger(meta)["rows"]["comment:1"]["thread"]] == [True, False]

    @pytest.mark.parametrize(
        "collector_order",
        [
            pytest.param([60, 70, 80, 90], id="chronological"),
            pytest.param([80, 90, 60, 70], id="later-exchange-first"),
            pytest.param([90, 80, 70, 60], id="newest-first"),
        ],
    )
    def test_a_lost_ledger_seeds_by_the_last_marked_reply_in_time_order(self, harness, collector_order):
        """Ours, a reviewer, ours, a reviewer: everything up to our SECOND reply is seen, the
        reviewer after it is not. `seed_thread` sorts before it looks for our last reply, so the
        collector's order changes nothing; picking by position would paint the last reviewer
        reply seen and hide the thread, or leave one of ours unseen."""
        by_id = {
            60: ours(60, created_at="2026-07-20T10:00:00Z"),
            70: reply(70, created_at="2026-07-20T11:00:00Z"),
            80: ours(80, created_at="2026-07-20T12:00:00Z"),
            90: reply(90, created_at="2026-07-20T13:00:00Z"),
        }
        meta = meta_doc([inline_comment(1, is_bot=True, thread=[by_id[i] for i in collector_order])])
        assert [e["ref"] for e in harness.reconcile(meta)["working_set"]] == ["C1"]
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["seen"] is True
        assert [r["id"] for r in row["thread"]] == [60, 70, 80, 90]
        assert {r["id"]: r["seen"] for r in row["thread"]} == {60: True, 70: True, 80: True, 90: False}

    def test_seeding_never_paints_a_row_the_ledger_already_holds(self, harness):
        """C2: a reviewer reply that raced our answer stays unseen on an existing row."""
        meta = meta_doc([inline_comment(1, is_bot=True)])
        harness.reconcile(meta)
        meta["comments"][0]["thread"] = [reply(50, created_at="2026-07-20T10:30:00Z"), ours(60)]
        harness.reconcile(meta)
        assert [r["seen"] for r in harness.ledger(meta)["rows"]["comment:1"]["thread"]] == [False, True]

    def test_a_resolved_thread_with_unseen_messages_is_not_working(self, harness):
        meta = meta_doc([inline_comment(1, is_bot=True, resolved=True, thread=[owner(50)])])
        assert harness.reconcile(meta)["working_set"] == []

    def test_unresolving_returns_only_a_thread_with_something_unseen(self, harness):
        meta = meta_doc([inline_comment(1, is_bot=True, resolved=True), inline_comment(2, is_bot=True, resolved=True)])
        harness.reconcile(meta)
        settle(harness, meta, "C2")
        for item in meta["comments"]:
            item["resolved"] = False
        assert [e["ref"] for e in harness.reconcile(meta)["working_set"]] == ["C1"]

    def test_a_schema_1_ledger_degrades_to_empty(self, harness):
        meta = meta_doc([inline_comment(1)])
        path = _ledger.ledger_path(meta["unit"]["url"], meta["unit"]["number"])
        path.parent.mkdir(parents=True, exist_ok=True)
        old = {
            "schema": 1,
            "round": 4,
            "next_ref": {"U": 9, "C": 1},
            "rows": {"comment:1": {"ref": "U8", "status": "open", "thread": [], "platform_state": "live"}},
        }
        path.write_text(json.dumps(old), encoding="utf-8")
        out = harness.reconcile(meta)
        assert out["round"] == 1
        assert [e["ref"] for e in out["working_set"]] == ["U1"]

    @pytest.mark.parametrize(
        ("user", "me", "role"),
        [
            pytest.param("me", "me", "owner", id="posted-from-the-run-account"),
            pytest.param("alice", "me", "reviewer", id="another-account"),
            pytest.param("me", None, "reviewer", id="run-account-unknown"),
        ],
    )
    def test_the_comment_itself_carries_its_author_role(self, harness, user, me, role):
        """The comment's role is the owner's or a reviewer's, never the agent's: the agent only
        ever answers a thread. With no known run account nothing is ours, as for a reply."""
        meta = meta_doc([inline_comment(1, user=user)])
        meta["me"] = me
        harness.reconcile(meta)
        assert harness.ledger(meta)["rows"]["comment:1"]["author_role"] == role


class TestRecordSettled:
    def _one(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        return meta

    def test_a_settled_entry_paints_the_comment_and_every_reply(self, harness):
        meta = self._one(harness)
        posted = {"id": 60, "user": "me", "body": f"Fixed\n\n{MARK}", "created_at": "2026-07-20T11:00:00Z"}
        assert (
            record_decisions(harness, meta, {"U1": {"settled": True, "decision": "fix", "reply": posted}}).returncode
            == 0
        )
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["seen"] is True
        assert all(r["seen"] for r in row["thread"])
        assert harness.reconcile(meta)["working_set"] == []

    def test_an_unsettled_entry_keeps_the_decision_and_paints_nothing(self, harness):
        meta = self._one(harness)
        entry = {"decision": "fix", "reason": "apply failed: patch did not match"}
        assert record_decisions(harness, meta, {"U1": entry}).returncode == 0
        out = harness.reconcile(meta)
        assert [(e["ref"], e["decision"]) for e in out["working_set"]] == [("U1", "fix")]

    def test_a_reply_without_settled_rejects_the_batch(self, harness):
        meta = self._one(harness)
        r = record_decisions(harness, meta, {"U1": {"decision": "fix", "reply": {"id": 60}}})
        assert r.returncode == 2
        assert harness.ledger(meta)["rows"]["comment:1"]["decision"] is None

    def test_the_removed_status_key_is_rejected_with_a_pointer_to_settled(self, harness):
        meta = self._one(harness)
        r = record_decisions(harness, meta, {"U1": {"status": "done"}})
        assert r.returncode == 2
        assert '"settled": true' in r.stderr

    def test_a_github_summary_settles_without_a_reply(self, harness):
        meta = meta_doc([summary_comment(9)])
        harness.reconcile(meta)
        # summary_comment's author is not a bot account → a U ref
        assert record_decisions(harness, meta, {"U1": {"settled": True, "decision": "wont_fix"}}).returncode == 0
        assert harness.reconcile(meta)["working_set"] == []

    @pytest.mark.parametrize("settled", ["yes", 1, None])
    def test_a_settled_that_is_not_a_bool_rejects_the_batch(self, harness, settled):
        """`1` and `"yes"` look truthy and `null` looks like "clear it"; none of them says
        unambiguously whether the outcome was delivered, so none is guessed at."""
        meta = self._one(harness)
        r = record_decisions(harness, meta, {"U1": {"settled": settled, "decision": "fix"}})
        assert r.returncode == 2
        assert "Traceback" not in r.stderr
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert (row["decision"], row["seen"]) == (None, False)


class TestReconcileLifecycle:
    def test_done_row_is_excluded_from_the_next_round(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        settle(harness, meta, "U1")
        assert harness.reconcile(meta)["working_set"] == []

    def test_done_row_reopens_when_a_new_reply_appears(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        settle(harness, meta, "U1")
        out = harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51, body="objection")])]))
        assert [e["ref"] for e in out["working_set"]] == ["U1"]
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert (row["seen"], [x["seen"] for x in row["thread"]]) == (True, [True, False])  # only the new one
        assert row["decision"] == "fix"  # the prior verdict is kept as history for the analyst

    def test_reopened_row_returns_with_its_original_ref(self, harness):
        meta = meta_doc([inline_comment(1, is_bot=True, thread=[reply(50)]), inline_comment(2, is_bot=True)])
        harness.reconcile(meta)
        settle(harness, meta, "C1")
        out = harness.reconcile(
            meta_doc([inline_comment(1, is_bot=True, thread=[reply(50), reply(51)]), inline_comment(2, is_bot=True)])
        )
        assert {e["ref"] for e in out["working_set"]} == {"C1", "C2"}

    def test_done_github_summary_never_reopens(self, harness):
        """The GitHub companion case: a review-body summary is threadless, so its stored thread
        is empty. Once its comment is painted, nothing in it can be unseen again. That is the
        deterministic elf.31 guarantee: a re-imported review carries the same, immutable summary
        id."""
        summary = inline_comment(None, kind="summary", summary_id=900, path="(summary)", line=None)
        meta = meta_doc([summary])
        harness.reconcile(meta)
        settle(harness, meta, "U1", decision="follow_up")
        # a rerun re-imports the SAME review id → the row is still settled → no duplicate follow-up
        assert harness.reconcile(meta)["working_set"] == []

    def test_done_gitlab_general_discussion_reopens_on_a_new_note(self, harness):
        """The regression this class guards against: `gl_collect` emits a GitLab general
        (no-position) discussion with `kind == "summary"` too, but it carries a real
        `discussion_id` and an appendable thread — unlike a GitHub review-body summary, it is
        NOT threadless. A settled row for it must come back when the discussion gains a new
        note, or that feedback silently disappears from `flow:review-loop`."""
        general = inline_comment(
            None, kind="summary", discussion_id="d1", path="(summary)", line=None, thread=[reply(50)]
        )
        meta = meta_doc([general])
        harness.reconcile(meta)
        settle(harness, meta, "U1")
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
        assert [x["seen"] for x in row["thread"]] == [True, False]

    def test_new_summary_review_gets_a_new_row(self, harness):
        first = inline_comment(None, kind="summary", summary_id=900, path="(summary)", line=None)
        meta = meta_doc([first])
        harness.reconcile(meta)
        settle(harness, meta, "U1", decision="follow_up")
        second = inline_comment(None, kind="summary", summary_id=901, path="(summary)", line=None)
        out = harness.reconcile(meta_doc([first, second]))
        assert [e["ref"] for e in out["working_set"]] == ["U2"]

    def test_an_untriaged_row_stays_work_as_its_thread_grows(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        out = harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51)])]))
        assert [e["ref"] for e in out["working_set"]] == ["U1"]
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert (row["seen"], [x["seen"] for x in row["thread"]]) == (False, [False, False])


class TestReconcileResolution:
    """`platform_state` is a snapshot field recomputed every round independently of a new reply,
    and it never writes a `seen` bit: a resolve/unresolve changes where the platform stands, not
    what the workflow has acted on (see `platform_state_of`)."""

    def test_a_new_resolved_row_is_stored_unseen_and_out_of_the_working_set(self, harness):
        meta = meta_doc([inline_comment(1, resolved=True)])
        out = harness.reconcile(meta)
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["seen"] is False
        assert row["platform_state"] == "resolved"
        assert _ledger.is_working(row) is False
        assert out["working_set"] == []

    def test_a_previously_resolved_row_returns_when_the_new_snapshot_says_unresolved(self, harness):
        """Someone hit "Unresolve" on a thread nobody had triaged: its comment was stored unseen
        while it sat resolved, so the platform-axis recomputation alone brings it back — and it
        does so without painting or clearing any bit."""
        meta = meta_doc([inline_comment(1, resolved=True)])
        harness.reconcile(meta)
        out = harness.reconcile(meta_doc([inline_comment(1, resolved=False)]))
        assert [e["ref"] for e in out["working_set"]] == ["U1"]
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["platform_state"] == "live"
        assert _ledger.is_working(row) is True
        assert row["seen"] is False  # no bit was written by the platform axis

    def test_a_row_absent_from_the_next_rounds_snapshot_is_marked_absent(self, harness):
        """The thread no longer exists on the platform -> `platform_state: absent`, excluded from
        the working set, and `counts["working"]` (which reconcile derives from the emitted
        `working_set`, not a row tally) reflects the shrunk set. The `seen` bits are untouched —
        absence is the platform's verdict, not ours."""
        meta = meta_doc([inline_comment(1), inline_comment(2)])
        harness.reconcile(meta)
        out = harness.reconcile(meta_doc([inline_comment(2)]))  # comment 1 vanished
        assert [e["ref"] for e in out["working_set"]] == ["U2"]
        assert out["counts"]["working"] == len(out["working_set"]) == 1
        rows = harness.ledger(meta)["rows"]
        assert rows["comment:1"]["platform_state"] == "absent"
        assert rows["comment:1"]["seen"] is False
        assert rows["comment:2"]["seen"] is False

    def test_a_deleted_row_returns_to_work_when_the_thread_reappears(self, harness):
        """`absent` is a verdict about the CURRENT snapshot, not a tombstone: the very next round
        that sees the thread again recomputes `platform_state` back to `live`, no special-casing
        needed. The row's decision survives the round-trip intact — the old `deleted` status
        routed revival through a status write that lost exactly this history."""
        meta = meta_doc([inline_comment(1, thread=[reply(10)])])
        harness.reconcile(meta)
        # Unsettled: the follow-up was filed, its reply never posted, so nothing is painted.
        result = record_decisions(
            harness,
            meta,
            {"U1": {"decision": "follow_up", "reason": "later", "followup_task_id": "ct-1"}},
        )
        assert result.returncode == 0, result.stderr
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

    def test_a_settled_row_absent_next_round_stays_settled(self, harness):
        """The `seen` bits are ours, `absent` is the platform's — the two never clobber each
        other."""
        meta = meta_doc([inline_comment(1, resolved=True, thread=[reply(50)])])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"settled": True, "decision": "wont_fix"}})
        assert result.returncode == 0, result.stderr
        harness.reconcile(meta_doc([]))  # the row vanishes from the snapshot entirely
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert _ledger.has_unseen(row) is False
        assert row["platform_state"] == "absent"

    def test_an_unresolved_thread_returns_to_work_when_it_was_never_triaged(self, harness):
        """The escape hatch that makes the exclusion above safe: a thread that sat resolved
        before anyone looked at it keeps its messages unseen, so un-resolving brings it back even
        when no new reply arrived. (Un-resolving a fully seen thread does not — there is nothing
        new in it; see `TestUnseenSelection`.)"""
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

        The new replies are still stored, unseen, so an un-resolve later brings the thread back
        with them.
        """
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51)], resolved=True)]))
        out = harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51), reply(52)], resolved=True)]))
        assert out["working_set"] == []
        assert out["counts"]["working"] == 0
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["platform_state"] == "resolved"
        assert [x["seen"] for x in row["thread"]] == [False, False, False]

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


def test_a_fully_seen_row_returns_when_its_thread_gains_an_unseen_reply(harness):
    """Only the new reply arrives unseen: the comment keeps its painted bit, and the reply alone
    is what puts the row back in the working set."""
    meta = meta_doc([inline_comment(1, thread=[reply(10)])])
    harness.reconcile(meta)
    force_row(harness, meta, "U1", seen=True, platform_state="live", thread=[{**reply(10), "seen": True}])

    harness.reconcile(meta_doc([inline_comment(1, resolved=False, thread=[reply(10), reply(11)])]))
    row = harness.ledger(meta)["rows"]["comment:1"]
    assert row["seen"] is True
    assert [x["seen"] for x in row["thread"]] == [True, False]
    assert _ledger.is_working(row) is True


def test_record_never_writes_platform_state(harness):
    meta = meta_doc([inline_comment(1, resolved=True, thread=[reply(10)])])
    harness.reconcile(meta)
    assert harness.ledger(meta)["rows"]["comment:1"]["platform_state"] == "resolved"
    result = record_decisions(harness, meta, {"U1": {"settled": True, "decision": "wont_fix", "reason": "why"}})
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
    # platform_state x where the unseen message sits: the comment, a reply, or nowhere. Both
    # unseen variants are in the table because `has_unseen` reads two different bits.
    table = [
        (platform_state, comment_seen, reply_seen)
        for platform_state in _ledger.PLATFORM_STATES
        for comment_seen, reply_seen in ((False, True), (True, False), (True, True))
    ]
    meta = meta_doc([inline_comment(n, thread=[reply(10)]) for n in range(1, len(table) + 1)])
    harness.reconcile(meta)
    for n, (platform_state, comment_seen, reply_seen) in enumerate(table, start=1):
        thread = [{**reply(10), "author_role": "reviewer", "seen": reply_seen}]
        force_row(harness, meta, f"U{n}", platform_state=platform_state, seen=comment_seen, thread=thread)

    out = harness.run("stats", "--meta", harness.write_meta(meta)).stdout
    assert "Tracked: 9 findings" in out
    assert "Done: 3" in out  # nothing unseen, on every platform_state
    assert "Open: 2" in out  # live with something unseen — exactly `is_working`
    assert "Resolved upstream: 2" in out
    assert "Deleted upstream: 2" in out


def test_stats_open_line_equals_the_working_set(harness):
    """review-loop parses `Open: N` as the size of what is left to do. It must be the number
    `reconcile` reports for the same ledger, or the loop's convergence report contradicts the
    working set the round actually ran on."""
    comments = [inline_comment(n, thread=[reply(10)]) for n in range(1, 6)]
    meta = meta_doc(comments)
    harness.reconcile(meta)
    decisions = {
        "U2": {"settled": True, "decision": "fix"},  # live, fully seen
        "U4": {"decision": "fix", "reason": "apply failed"},  # live, decided, nothing delivered
    }
    assert record_decisions(harness, meta, decisions).returncode == 0
    comments[2]["resolved"] = True  # U3: resolved with its messages unseen
    final = meta_doc(comments[:4])  # U5: gone from the platform, unseen
    out = harness.reconcile(final)

    stats = harness.run("stats", "--meta", harness.write_meta(final)).stdout
    match = re.search(r"^\s*Open: (\d+)", stats, re.MULTILINE)
    assert match is not None, stats
    assert int(match.group(1)) == out["counts"]["working"] == len(out["working_set"]) == 2


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

    def test_carries_the_durable_history_of_a_returning_row(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        settle(harness, meta, "U1", decision="wont_fix")
        harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51, body="objection")])]))
        row = json.loads(harness.run("get", "--ref", "U1", "--meta", harness.write_meta(meta)).stdout)
        assert row["decision"] == "wont_fix"  # prior verdict visible to the analyst
        assert (row["thread"][-1]["body"], row["thread"][-1]["seen"]) == ("objection", False)  # what changed

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
        assert emitted == row  # as stored: no computed fields, every message carries its own bit


class TestRecord:
    def test_applies_a_decision_by_ref(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"settled": True, "decision": "fix", "reason": "guard added"}})
        assert result.returncode == 0, result.stderr
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["seen"] is True
        assert row["decision"] == "fix"
        assert row["reason"] == "guard added"
        assert row["head"] == "abc1234"
        assert row["last_round"] == 1

    def test_records_a_followup_task_id(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        record_decisions(
            harness,
            meta,
            {"U1": {"settled": True, "decision": "follow_up", "followup_task_id": "ct-42"}},
        )
        assert harness.ledger(meta)["rows"]["comment:1"]["followup_task_id"] == "ct-42"

    def test_reason_with_shell_metacharacters_survives_verbatim(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        hostile = "won't fix: `$(id)` and a FLOW_RC_EOF line\nsecond line"
        record_decisions(harness, meta, {"U1": {"settled": True, "decision": "wont_fix", "reason": hostile}})
        assert harness.ledger(meta)["rows"]["comment:1"]["reason"] == hostile

    def test_unknown_ref_warns_but_still_records_the_rest(self, harness):
        """Rows that DID match are still saved and the payload is unchanged, but the exit code
        is non-zero (the plugin's "no silent failures" convention) so a caller that does not
        inspect the JSON still learns the batch was not fully recorded."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"settled": True}, "C9": {"settled": True}})
        assert result.returncode == 1
        assert "C9" in result.stderr
        assert json.loads(result.stdout) == {"recorded": 1, "unknown": ["C9"]}
        assert harness.ledger(meta)["rows"]["comment:1"]["seen"] is True

    def test_invalid_decision_writes_nothing(self, harness):
        """elf.53(a): an unknown `decision` rejects the batch before anything is written."""
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"decision": "maybe"}})
        assert result.returncode == 2
        assert harness.ledger(meta)["rows"]["comment:1"]["decision"] is None

    def test_re_recording_the_same_decision_is_a_no_op(self, harness):
        """elf.53(b): recording an identical decision twice must not change the row further."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        decision = {"U1": {"settled": True, "decision": "fix", "reason": "guard added"}}
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
                    "settled": True,
                    "decision": "follow_up",
                    "reason": "deferred",
                    "followup_task_id": "ct-1",
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
        for field in ("seen", "decision", "reason", "followup_task_id"):
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
        assert row["seen"] is True  # untouched: an entry without `settled` never unpaints

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
            {"U1": {"settled": True, "decision": "follow_up", "followup_task_id": "ct-1"}},
        )
        assert result.returncode == 0, result.stderr
        result = record_decisions(
            harness,
            meta,
            {
                "U1": {
                    "settled": True,
                    "decision": "fix",
                    "reason": "guard added",
                    "followup_task_id": None,
                }
            },
        )
        assert result.returncode == 0, result.stderr
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert row["followup_task_id"] is None
        assert row["decision"] == "fix"
        # and it stays cleared through a later `follow_up` that files no task
        result = record_decisions(harness, meta, {"U1": {"settled": True, "decision": "follow_up"}})
        assert result.returncode == 0, result.stderr
        assert harness.ledger(meta)["rows"]["comment:1"]["followup_task_id"] is None

    def test_record_against_a_missing_ledger_reports_instead_of_creating_one(self, harness):
        """elf.52(c): Phase 5.7a always runs `record` right after `reconcile` in the same run,
        so a missing ledger at `record` time means something upstream went wrong — silently
        materialising an empty round-0 document would hide that. `record` must fail loudly and
        must not create the ledger file."""
        meta = meta_doc([inline_comment(1)])
        path = _ledger.ledger_path(meta["unit"]["url"], meta["unit"]["number"])
        assert not path.exists()
        result = record_decisions(harness, meta, {"U1": {"settled": True}})
        assert result.returncode != 0
        assert "flow-review-ledger:" in result.stderr
        assert "Traceback" not in result.stderr
        assert not path.exists()

    def test_recorded_row_is_excluded_on_the_next_reconcile(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"settled": True, "decision": "fix"}})
        assert result.returncode == 0, result.stderr
        assert harness.reconcile(meta)["working_set"] == []


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
                    "U1": {"settled": True, "decision": "fix"},
                    "U2": {"settled": True, "decision": "wont_fix"},
                    "U3": {"settled": True, "decision": "follow_up", "followup_task_id": "ct-42"},
                    "U4": {"decision": "fix"},  # decided, the action did not land
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
        assert "(decided, action did not land: 1)" in out
        assert "Follow-ups filed: 1 (ct-42)" in out

    def test_a_resolved_row_is_reported_as_resolved_upstream_not_as_open(self, harness):
        """`stats` is what review-loop prints in its convergence report, so it must answer "is
        there work left" the same way `reconcile` does. Counting a resolved row under `Open` would
        make that report contradict itself: nothing in the working set, yet `Open: 1`."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1, thread=[reply(50), reply(51)], resolved=True)]))
        # A reply lands on the thread while the platform still reports it resolved: it is stored
        # unseen, but a resolved thread is not work, whatever its bits say.
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
        assert record_decisions(harness, meta, {"U1": {"settled": True, "decision": "fix"}}).returncode == 0
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
                {"U1": {"settled": True, "decision": "follow_up", "followup_task_id": "ct-1"}},
            ).returncode
            == 0
        )
        out = harness.run("stats", "--meta", harness.write_meta(meta)).stdout
        assert "Follow-ups filed: 1 (ct-1)" in out

        # re-opened and re-decided as `fix` in a later round; followup_task_id is not cleared
        assert record_decisions(harness, meta, {"U1": {"settled": True, "decision": "fix"}}).returncode == 0
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


class TestRecordReply:
    """`record`'s new one-round instruction: the reply this round posted."""

    @staticmethod
    def _thread(harness, meta):
        return harness.ledger(meta)["rows"]["comment:1"]["thread"]

    def test_record_paints_every_stored_reply_seen(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50), reply(51)])])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"settled": True, "decision": "fix"}})
        assert result.returncode == 0, result.stderr
        assert [x.get("seen") for x in self._thread(harness, meta)] == [True, True]

    def test_an_unsettled_entry_leaves_every_bit_unseen(self, harness):
        """An outcome that did not land (here: the apply failed) is not what `seen` asserts, so
        nothing is painted and the thread is triaged again next round with its decision."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"decision": "fix", "reason": "apply failed"}})
        assert result.returncode == 0, result.stderr
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert (row["seen"], [x.get("seen") for x in row["thread"]]) == (False, [False])

    def test_record_appends_the_posted_reply_marked_seen(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        posted = {"id": 60, "user": "me", "body": "Fixed: guard added", "created_at": "2026-07-20T11:00:00Z"}
        result = record_decisions(harness, meta, {"U1": {"settled": True, "decision": "fix", "reply": posted}})
        assert result.returncode == 0, result.stderr
        thread = self._thread(harness, meta)
        assert [x["id"] for x in thread] == [50, 60]
        assert (thread[-1]["seen"], thread[-1]["author_role"]) == (True, "agent")
        assert thread[-1]["body"] == "Fixed: guard added"

    def test_the_appended_reply_sorts_by_created_at_not_arrival(self, harness):
        """Arrival order is wrong in C2's own scenario: a reviewer's reply merged after ours
        can predate it, and a thread where our answer precedes the objection it answers reads
        backwards."""
        meta = meta_doc([inline_comment(1, thread=[reply(50, created_at="2026-07-20T10:00:00Z")])])
        harness.reconcile(meta)
        posted = {"id": 60, "user": "me", "body": "Fixed", "created_at": "2026-07-20T09:00:00Z"}
        record_decisions(harness, meta, {"U1": {"settled": True, "decision": "fix", "reply": posted}})
        assert [x["id"] for x in self._thread(harness, meta)] == [60, 50]

    def test_appending_the_same_reply_twice_stores_it_once(self, harness):
        """5.7 checkpoints a ref the moment its reply is accepted, then 5.7a closes the round.
        Storing it twice would show our answer twice on every later card."""
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        posted = {"id": 60, "user": "me", "body": "Fixed", "created_at": "2026-07-20T11:00:00Z"}
        entry = {"U1": {"settled": True, "decision": "fix", "reply": posted}}
        record_decisions(harness, meta, entry)
        record_decisions(harness, meta, entry)
        assert [x["id"] for x in self._thread(harness, meta)] == [50, 60]

    def test_a_stored_numeric_id_matches_a_string_id_handed_back(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(50)])])
        harness.reconcile(meta)
        base = {"user": "me", "body": "Fixed", "created_at": "2026-07-20T11:00:00Z"}
        record_decisions(harness, meta, {"U1": {"settled": True, "decision": "fix", "reply": {**base, "id": 60}}})
        record_decisions(harness, meta, {"U1": {"settled": True, "decision": "fix", "reply": {**base, "id": "60"}}})
        assert [str(x["id"]) for x in self._thread(harness, meta)] == ["50", "60"]

    def test_reply_is_not_stored_as_a_row_field(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        posted = {"id": 60, "user": "me", "body": "Fixed", "created_at": "2026-07-20T11:00:00Z"}
        record_decisions(harness, meta, {"U1": {"settled": True, "decision": "fix", "reply": posted}})
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert "reply" not in row
        assert "settled" not in row  # an instruction to `record`, never stored

    def test_a_reply_without_an_id_rejects_the_whole_batch(self, harness):
        """The id is the sole basis of matching: a reply stored without one is appended again
        by the next reconcile as if new, and the thread holds our answer twice."""
        meta = meta_doc([inline_comment(1), inline_comment(2)])
        harness.reconcile(meta)
        result = record_decisions(
            harness,
            meta,
            {
                "U1": {"settled": True, "decision": "fix"},
                "U2": {"settled": True, "decision": "wont_fix", "reply": {"user": "me", "body": "x"}},
            },
        )
        assert result.returncode == 2
        assert "`id`" in result.stderr  # rejected for the missing id, not for a missing `settled`
        rows = harness.ledger(meta)["rows"]
        assert (rows["comment:1"]["decision"], rows["comment:1"]["seen"]) == (None, False)
        assert (rows["comment:2"]["decision"], rows["comment:2"]["seen"]) == (None, False)

    def test_a_reply_that_is_not_an_object_rejects_the_batch(self, harness):
        meta = meta_doc([inline_comment(1)])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"settled": True, "decision": "fix", "reply": "3518155060"}})
        assert result.returncode == 2
        assert "`id`" in result.stderr
        row = harness.ledger(meta)["rows"]["comment:1"]
        assert (row["decision"], row["seen"]) == (None, False)


class TestSeenSetLifecycle:
    """The behaviours the seen-set model exists to deliver."""

    @staticmethod
    def _row(harness, meta):
        return harness.ledger(meta)["rows"]["comment:1"]

    @staticmethod
    def _posted(reply_id, created_at="2026-07-20T12:00:00Z"):
        return {"id": reply_id, "user": "me", "body": f"Fixed: guard added\n\n{MARK}", "created_at": created_at}

    def test_a_reply_racing_the_round_resurfaces_next_round(self, harness):
        """C2, the originating defect. 105 lands while the human triages — after Phase 2
        collected the thread and before Phase 5 posts 110. Our own reply must not stand in for
        it, and the stored thread must read in the order the argument happened."""
        meta = meta_doc([inline_comment(1, thread=[reply(100, created_at="2026-07-20T10:00:00Z")])])
        harness.reconcile(meta)
        result = record_decisions(
            harness, meta, {"U1": {"settled": True, "decision": "fix", "reply": self._posted(110)}}
        )
        assert result.returncode == 0, result.stderr
        assert _ledger.has_unseen(self._row(harness, meta)) is False

        racing = meta_doc(
            [
                inline_comment(
                    1,
                    thread=[
                        reply(100, created_at="2026-07-20T10:00:00Z"),
                        reply(105, body="objection", created_at="2026-07-20T11:00:00Z"),
                        ours(110, created_at="2026-07-20T12:00:00Z"),
                    ],
                )
            ]
        )
        out = harness.reconcile(racing)
        assert [e["ref"] for e in out["working_set"]] == ["U1"]
        row = self._row(harness, meta)
        assert row["decision"] == "fix"  # the prior verdict survives as history
        assert [(x["id"], x["seen"]) for x in row["thread"]] == [(100, True), (105, False), (110, True)]

    def test_our_own_reply_does_not_resurface_even_when_record_never_saw_it(self, harness):
        """The POST succeeded and the `--jq` extraction did not, so `record` got no `reply`.
        The forge hands our reply back next round; arriving already seen — by its marker, not
        by the login — is what stops a second public reply into the same thread."""
        meta = meta_doc([inline_comment(1, thread=[reply(100)])])
        harness.reconcile(meta)
        assert record_decisions(harness, meta, {"U1": {"settled": True, "decision": "fix"}}).returncode == 0
        later = meta_doc([inline_comment(1, thread=[reply(100), ours(110, created_at="2026-07-20T12:00:00Z")])])
        assert harness.reconcile(later)["working_set"] == []
        assert _ledger.has_unseen(self._row(harness, meta)) is False

    def test_a_deleted_reply_resurfaces_once_and_is_then_painted(self, harness):
        """Append-only: `record` paints everything WE store, not everything the forge returns,
        so a reply deleted before we ever read it surfaces exactly once and stays quotable."""
        meta = meta_doc([inline_comment(1, thread=[reply(100)])])
        harness.reconcile(meta)
        settle(harness, meta, "U1")
        grew = meta_doc([inline_comment(1, thread=[reply(100), reply(105, body="objection")])])
        assert [e["ref"] for e in harness.reconcile(grew)["working_set"]] == ["U1"]
        assert record_decisions(harness, meta, {"U1": {"settled": True, "decision": "wont_fix"}}).returncode == 0
        shrunk = meta_doc([inline_comment(1, thread=[reply(100)])])
        assert harness.reconcile(shrunk)["working_set"] == []
        assert [x["id"] for x in self._row(harness, meta)["thread"]] == [100, 105]

    @pytest.mark.parametrize("decision", ["fix", "wont_fix", "follow_up", "outdated"])
    def test_a_github_summary_settles_with_no_reply_under_every_decision(self, harness, decision):
        """C3: the old table gave a recording rule for `follow_up` only, so an agent that
        decided `wont_fix` on a review-body summary found no matching row and left it
        unsettled — re-triaged every round."""
        meta = meta_doc([summary_comment(900)])
        harness.reconcile(meta)
        result = record_decisions(harness, meta, {"U1": {"settled": True, "decision": decision}})
        assert result.returncode == 0, result.stderr
        assert harness.reconcile(meta)["working_set"] == []

    def test_an_edited_reply_body_does_not_overwrite_the_stored_one(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(100, body="original")])])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1, thread=[reply(100, body="edited in place")])]))
        assert self._row(harness, meta)["thread"][0]["body"] == "original"

    def test_an_edited_comment_body_does_not_overwrite_the_stored_one(self, harness):
        """`body` left SNAPSHOT_FIELDS: the text the agent triaged is the text we keep."""
        meta = meta_doc([inline_comment(1, body="original")])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1, body="edited in place")]))
        assert self._row(harness, meta)["body"] == "original"

    def test_the_code_fields_are_still_refreshed_every_round(self, harness):
        """Freezing these would strand a finding at a line the diff has since moved."""
        meta = meta_doc([inline_comment(1, line=42, outdated=False)])
        harness.reconcile(meta)
        harness.reconcile(meta_doc([inline_comment(1, line=57, outdated=True)]))
        row = self._row(harness, meta)
        assert row["line"] == 57
        assert row["outdated"] is True

    def test_no_row_carries_a_thread_mark(self, harness):
        meta = meta_doc([inline_comment(1, thread=[reply(100)])])
        harness.reconcile(meta)
        assert "thread_mark" not in self._row(harness, meta)

    def test_a_reply_recorded_with_a_string_id_is_not_appended_again_as_an_int(self, harness):
        """`merge_thread` normalises both sides through `str()`. Task 2's companion test covers
        `paint_seen`'s side; this one covers the merge, where a mismatch would store our own
        reply a second time. The copy handed back here carries no marker on purpose: a broken
        match would then also bring the thread back as an unseen owner reply."""
        meta = meta_doc([inline_comment(1, thread=[reply(100)])])
        harness.reconcile(meta)
        posted = {"id": "110", "user": "me", "body": "Fixed", "created_at": "2026-07-20T12:00:00Z"}
        result = record_decisions(harness, meta, {"U1": {"settled": True, "decision": "fix", "reply": posted}})
        assert result.returncode == 0, result.stderr
        later = meta_doc(
            [
                inline_comment(
                    1,
                    thread=[reply(100), reply(110, user="me", is_bot=False, created_at="2026-07-20T12:00:00Z")],
                )
            ]
        )
        assert harness.reconcile(later)["working_set"] == []
        thread = self._row(harness, meta)["thread"]
        assert [str(x["id"]) for x in thread] == ["100", "110"]


def test_the_high_water_mark_machinery_is_gone():
    """Deleted with the model, not merely unused: a surviving `id_advanced` invites a second
    answer to 'did this thread advance?', which is the drift the seen set exists to end."""
    for name in ("id_advanced", "last_reply_id", "threadless"):
        assert not hasattr(_ledger, name), f"_ledger.{name} should have been deleted"


def test_the_status_model_is_gone():
    """Deleted with the model, not merely unused: selection reads `platform_state` and the
    `seen` bits only, and a surviving status enum or login check invites a second answer to
    'does this thread need a look?' — the anti-goal of the unseen-signal design."""
    for name in ("STATUSES", "is_ours", "resurfaced"):
        assert not hasattr(_ledger, name), f"_ledger.{name} should have been deleted"


class TestResolveTarget:
    """`resolve_id` is current-snapshot data, not durable memory: the platform owns it, so the
    row takes whatever this round observed."""

    def test_reconcile_stores_the_resolve_target(self, harness):
        meta = meta_doc([inline_comment(1, resolve_id="PRRT_kwABC")])
        harness.reconcile(meta)
        assert harness.ledger(meta)["rows"]["comment:1"]["resolve_id"] == "PRRT_kwABC"

    def test_a_later_round_refreshes_it(self, harness):
        meta = meta_doc([inline_comment(1, resolve_id="PRRT_new")])
        harness.reconcile(meta_doc([inline_comment(1, resolve_id="PRRT_old")]))
        harness.reconcile(meta)
        assert harness.ledger(meta)["rows"]["comment:1"]["resolve_id"] == "PRRT_new"

    def test_get_hands_the_resolve_target_to_the_reply_step(self, harness):
        """Phase 5.7 reads one row via `get`; if the field did not survive that projection the
        skill would have to re-read the collector document it deliberately does not keep."""
        meta = meta_doc([inline_comment(1, is_bot=True, resolve_id="PRRT_kwABC")])
        harness.reconcile(meta)
        result = harness.run("get", "--ref", "C1", "--meta", harness.write_meta(meta))
        assert result.returncode == 0, result.stderr
        row = json.loads(result.stdout)
        assert row["resolve_id"] == "PRRT_kwABC"
        assert row["is_bot"] is True


class TestMessageModel:
    def test_marked_reply_from_the_run_account_is_the_agents(self):
        msg = {"user": "me", "body": f"Fixed: guard added\n\n{_ledger.AGENT_MARKER}"}
        assert _ledger.author_role(msg, "me") == "agent"

    def test_unmarked_reply_from_the_run_account_is_the_owners(self):
        assert _ledger.author_role({"user": "me", "body": "maybe this check is not needed"}, "me") == "owner"

    def test_a_bot_quoting_the_marker_stays_a_reviewer(self):
        msg = {"user": "coderabbitai", "body": f"> Fixed\n> {_ledger.AGENT_MARKER}\nThanks!"}
        assert _ledger.author_role(msg, "me") == "reviewer"

    def test_marker_after_crlf_and_trailing_whitespace_still_counts(self):
        msg = {"user": "me", "body": f"Fixed\r\n\r\n{_ledger.AGENT_MARKER}\r\n  "}
        assert _ledger.author_role(msg, "me") == "agent"

    @pytest.mark.parametrize("me", [None, ""])
    def test_an_unknown_run_account_makes_everyone_a_reviewer(self, me):
        assert _ledger.author_role({"user": "me", "body": _ledger.AGENT_MARKER}, me) == "reviewer"
        assert _ledger.author_role({"user": "", "body": "x"}, me) == "reviewer"

    def test_strip_marker_removes_it_and_the_whitespace_before_it(self):
        assert _ledger.strip_marker(f"Fixed: x\n\n{_ledger.AGENT_MARKER}\n") == "Fixed: x"
        assert _ledger.strip_marker("plain text") == "plain text"

    def test_has_unseen_counts_the_comment_itself(self):
        assert _ledger.has_unseen({"seen": False, "thread": []}) is True
        assert _ledger.has_unseen({"seen": True, "thread": [{"seen": False}]}) is True
        assert _ledger.has_unseen({"seen": True, "thread": [{"seen": True}]}) is False
        assert _ledger.has_unseen({"thread": []}) is False  # no bit at all → not a ledger row
