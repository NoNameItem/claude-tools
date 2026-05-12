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
