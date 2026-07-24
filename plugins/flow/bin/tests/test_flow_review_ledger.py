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
