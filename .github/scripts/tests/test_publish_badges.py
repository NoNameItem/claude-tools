"""Tests for publish_badges.py script."""

from __future__ import annotations

import pytest

from ..publish_badges import extract_project_name


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
