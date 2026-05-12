"""Tests for publish_badges.py script."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..publish_badges import extract_project_name

if TYPE_CHECKING:
    from pathlib import Path


class TestExtractProjectName:
    """Tests for extract_project_name function."""

    @pytest.mark.parametrize(
        ("job_name", "expected"),
        [
            ("Lint (statuskit)", "statuskit"),
            ("Test (statuskit, py3.10)", "statuskit"),
            ("Test (statuskit, py3.11)", "statuskit"),
            ("Test (statuskit, py3.12)", "statuskit"),
            ("SonarCloud (statuskit)", "statuskit"),
            ("Validate (flow)", "flow"),
            ("Lint (flow)", "flow"),
            ("Bar (baz_qux-123)", "baz_qux-123"),
        ],
    )
    def test_matches(self, job_name: str, expected: str) -> None:
        """Should extract project name from job name with trailing parens."""
        assert extract_project_name(job_name) == expected

    @pytest.mark.parametrize(
        "job_name",
        [
            "Detect changes",
            "Validate commits",
            "Notify Start",
            "Notify Finish",
            "Publish badges",
            "Foo ()",
            "",
        ],
    )
    def test_no_match(self, job_name: str) -> None:
        """Should return None when no recognizable project name in parens."""
        assert extract_project_name(job_name) is None


class TestAggregateStatus:
    """Tests for aggregate_status function."""

    def test_all_success(self) -> None:
        from ..publish_badges import aggregate_status

        assert aggregate_status(["success", "success"]) == ("passing", "brightgreen")

    def test_success_and_skipped(self) -> None:
        from ..publish_badges import aggregate_status

        assert aggregate_status(["success", "skipped"]) == ("passing", "brightgreen")

    def test_success_and_failure(self) -> None:
        from ..publish_badges import aggregate_status

        assert aggregate_status(["success", "failure"]) == ("failing", "red")

    @pytest.mark.parametrize(
        "conclusion",
        ["failure", "cancelled", "timed_out", "neutral", "action_required", "stale"],
    )
    def test_single_failing_class(self, conclusion: str) -> None:
        from ..publish_badges import aggregate_status

        assert aggregate_status([conclusion]) == ("failing", "red")

    def test_unknown_conclusion_is_failing(self) -> None:
        from ..publish_badges import aggregate_status

        assert aggregate_status(["surprise"]) == ("failing", "red")

    def test_all_skipped(self) -> None:
        from ..publish_badges import aggregate_status

        assert aggregate_status(["skipped", "skipped"]) is None

    def test_empty(self) -> None:
        from ..publish_badges import aggregate_status

        assert aggregate_status([]) is None


class TestBuildBadgeJson:
    """Tests for build_badge_json function."""

    def test_passing(self) -> None:
        from ..publish_badges import build_badge_json

        assert build_badge_json("passing", "brightgreen") == {
            "schemaVersion": 1,
            "label": "CI",
            "message": "passing",
            "color": "brightgreen",
        }

    def test_failing(self) -> None:
        from ..publish_badges import build_badge_json

        assert build_badge_json("failing", "red") == {
            "schemaVersion": 1,
            "label": "CI",
            "message": "failing",
            "color": "red",
        }


class TestWriteBadgeFile:
    """Tests for write_badge_file function."""

    def test_writes_indented_json_with_trailing_newline(self, tmp_path: Path) -> None:
        from ..publish_badges import write_badge_file

        badge = {
            "schemaVersion": 1,
            "label": "CI",
            "message": "passing",
            "color": "brightgreen",
        }
        write_badge_file(tmp_path, "statuskit", badge)

        path = tmp_path / "statuskit.json"
        content = path.read_text()
        assert content.endswith("\n")
        # Round-trip equals the input.
        import json as _json

        assert _json.loads(content) == badge
        # Indented (multi-line) output, not a single compact line.
        assert "\n" in content.rstrip("\n")

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        from ..publish_badges import write_badge_file

        target = tmp_path / "flow.json"
        target.write_text('{"old": "value"}\n')

        write_badge_file(
            tmp_path,
            "flow",
            {"schemaVersion": 1, "label": "CI", "message": "failing", "color": "red"},
        )

        import json as _json

        assert _json.loads(target.read_text())["message"] == "failing"

    def test_missing_dir_raises(self, tmp_path: Path) -> None:
        from ..publish_badges import write_badge_file

        missing = tmp_path / "does-not-exist"
        with pytest.raises(FileNotFoundError):
            write_badge_file(
                missing,
                "statuskit",
                {"schemaVersion": 1, "label": "CI", "message": "passing", "color": "brightgreen"},
            )


class _FakeResponse:
    """Context-manager-compatible stand-in for an HTTP response."""

    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        # urllib's Response exposes headers via ``.headers`` (Message-like)
        # AND ``.getheader(name)``. We replicate both.
        self.headers = headers or {}

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body

    def getheader(self, name: str, default: str | None = None) -> str | None:
        # Match urllib's case-insensitive header lookup.
        for k, v in self.headers.items():
            if k.lower() == name.lower():
                return v
        return default


def _make_jobs_page(jobs: list[dict]) -> bytes:
    import json as _json

    return _json.dumps({"total_count": len(jobs), "jobs": jobs}).encode()


class TestFetchJobs:
    """Tests for fetch_jobs function."""

    def test_single_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import publish_badges as mod

        page = _make_jobs_page([{"name": "Lint (statuskit)", "status": "completed", "conclusion": "success"}] * 5)
        calls: list[str] = []

        def fake_urlopen(request, timeout: float = 30.0):
            calls.append(request.full_url)
            return _FakeResponse(page)

        monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
        result = mod.fetch_jobs("octo/widget", "999", "TKN")

        assert len(result) == 5
        assert len(calls) == 1
        assert "/repos/octo/widget/actions/runs/999/jobs" in calls[0]
        assert "per_page=100" in calls[0]

    def test_two_pages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import publish_badges as mod

        page1 = _make_jobs_page([{"name": "Lint (statuskit)", "status": "completed", "conclusion": "success"}])
        page2 = _make_jobs_page([{"name": "Lint (flow)", "status": "completed", "conclusion": "success"}])

        responses = [
            _FakeResponse(
                page1,
                headers={"Link": '<https://api.github.com/next?page=2>; rel="next"'},
            ),
            _FakeResponse(page2),
        ]
        calls: list[str] = []

        def fake_urlopen(request, timeout: float = 30.0):
            calls.append(request.full_url)
            return responses.pop(0)

        monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
        result = mod.fetch_jobs("octo/widget", "999", "TKN")

        assert [j["name"] for j in result] == ["Lint (statuskit)", "Lint (flow)"]
        assert len(calls) == 2
        assert calls[1] == "https://api.github.com/next?page=2"

    def test_pagination_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import publish_badges as mod

        page = _make_jobs_page([{"name": "Lint (x)", "status": "completed", "conclusion": "success"}])

        def fake_urlopen(request, timeout: float = 30.0):
            return _FakeResponse(
                page,
                headers={"Link": '<https://api.github.com/next?page=N>; rel="next"'},
            )

        monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError, match="pagination"):
            mod.fetch_jobs("octo/widget", "999", "TKN")

    def test_http_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import urllib.error

        from .. import publish_badges as mod

        def fake_urlopen(request, timeout: float = 30.0):
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", hdrs=None, fp=None)

        monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(urllib.error.HTTPError):
            mod.fetch_jobs("octo/widget", "999", "TKN")

    def test_sends_auth_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import publish_badges as mod

        captured: dict[str, str] = {}

        def fake_urlopen(request, timeout: float = 30.0):
            # urllib's Request stores headers title-cased.
            captured["auth"] = request.get_header("Authorization")
            captured["accept"] = request.get_header("Accept")
            return _FakeResponse(_make_jobs_page([]))

        monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
        mod.fetch_jobs("octo/widget", "999", "TKN")

        assert captured["auth"] == "token TKN"
        assert captured["accept"] == "application/vnd.github+json"
