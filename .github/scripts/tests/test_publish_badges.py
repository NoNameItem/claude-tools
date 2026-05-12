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
