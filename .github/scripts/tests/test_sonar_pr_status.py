"""Tests for sonar_pr_status.py formatting and API handling."""

from __future__ import annotations

import json
import urllib.error
from typing import ClassVar

import pytest

from ..sonar_pr_status import (
    build_branch_block,
    build_gate_block,
    build_new_code_block,
    delta_cell,
    delta_marker,
    extract_projects,
    format_breakdown,
    format_measure,
    format_threshold,
    rating_letter,
)

DASHBOARD = "https://sonarcloud.io/dashboard?id=NoNameItem_statuskit&pullRequest=112"


def _sonar_run(details_url: str = DASHBOARD, slug: str = "sonarqubecloud", title: str = "Quality Gate passed") -> dict:
    return {"name": "SonarCloud Code Analysis", "app_slug": slug, "details_url": details_url, "output_title": title}


class TestExtractProjects:
    def test_extracts_key_and_url(self) -> None:
        assert extract_projects([_sonar_run()]) == [("NoNameItem_statuskit", DASHBOARD)]

    def test_ignores_other_apps(self) -> None:
        assert extract_projects([_sonar_run(slug="github-actions")]) == []

    def test_ignores_url_without_id(self) -> None:
        assert extract_projects([_sonar_run(details_url="https://sonarcloud.io/dashboard")]) == []

    def test_deduplicates(self) -> None:
        assert len(extract_projects([_sonar_run(), _sonar_run()])) == 1

    def test_two_projects(self) -> None:
        other = "https://sonarcloud.io/dashboard?id=NoNameItem_read-comics&pullRequest=1"
        keys = [key for key, _ in extract_projects([_sonar_run(), _sonar_run(details_url=other)])]
        assert keys == ["NoNameItem_statuskit", "NoNameItem_read-comics"]


class TestRatingLetter:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("1", "A"), ("1.0", "A"), ("2.0", "B"), ("3.0", "C"), ("4.0", "D"), ("5.0", "E")],
    )
    def test_maps(self, value: str, expected: str) -> None:
        assert rating_letter(value) == expected

    def test_unknown_passes_through(self) -> None:
        assert rating_letter("9") == "9"


class TestFormatMeasure:
    @pytest.mark.parametrize(
        ("metric", "value", "expected"),
        [
            ("new_coverage", "96.83", "96.8%"),
            ("new_duplicated_lines_density", "0.0", "0.0%"),
            ("new_reliability_rating", "1.0", "A"),
            ("security_rating", "5.0", "E"),
            ("new_lines", "1357", "1357"),
            ("ncloc", "2121", "2121"),
            ("new_coverage", None, "—"),
            ("new_duplicated_lines_density", None, "—"),
        ],
    )
    def test_formats(self, metric: str, value: str | None, expected: str) -> None:
        assert format_measure(metric, value) == expected

    def test_malformed_percent_value_degrades_instead_of_raising(self) -> None:
        """A percent metric guards `float(value)` the same way the count branch already does:
        one malformed value from the API must degrade this row, not blow up `main`'s per-project
        loop and discard every other project's already-built blocks (see module docstring).
        """
        assert format_measure("new_coverage", "not-a-number") == "not-a-number"


class TestFormatThreshold:
    @pytest.mark.parametrize(
        ("metric", "comparator", "threshold", "expected"),
        [
            ("new_coverage", "LT", "80", "need ≥ 80%"),
            ("new_duplicated_lines_density", "GT", "3", "need ≤ 3%"),
            ("new_reliability_rating", "GT", "1", "need A"),
            ("new_security_hotspots_reviewed", "LT", "100", "need ≥ 100%"),
        ],
    )
    def test_formats(self, metric: str, comparator: str, threshold: str, expected: str) -> None:
        assert format_threshold(metric, comparator, threshold) == expected


class TestFormatBreakdown:
    def test_orders_and_skips_zeros(self) -> None:
        assert (
            format_breakdown({"MINOR": 4, "BLOCKER": 1, "CRITICAL": 7, "INFO": 0}) == "blocker 1, critical 7, minor 4"
        )

    def test_software_quality_severities(self) -> None:
        assert format_breakdown({"total": 1, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0, "BLOCKER": 1}) == "blocker 1"

    def test_all_zero(self) -> None:
        assert format_breakdown({"BLOCKER": 0}) == ""


class TestDeltaMarker:
    @pytest.mark.parametrize(
        ("metric", "before", "after", "expected"),
        [
            ("coverage", "93.4", "94.1", "🟢"),
            ("coverage", "94.1", "93.4", "🔴"),
            ("violations", "13", "15", "🔴"),
            ("violations", "15", "13", "🟢"),
            ("vulnerabilities", "0", "1", "🔴"),
            ("duplicated_lines_density", "0.0", "1.5", "🔴"),
            ("security_hotspots", "2", "0", "🟢"),
            # Sonar encodes ratings 1..5 with 1 = A, so a numeric rise is a downgrade.
            ("reliability_rating", "1.0", "2.0", "🔴"),
            ("security_rating", "5.0", "1.0", "🟢"),
            ("sqale_rating", "1.0", "1.0", ""),
            # Neutral metric: no marker, and so no trend counter either.
            ("ncloc", "2121", "2280", ""),
            ("coverage", None, "93.4", ""),
            ("coverage", "93.4", None, ""),
            ("coverage", "93.4", "not-a-number", ""),
        ],
    )
    def test_marker(self, metric: str, before: str | None, after: str | None, expected: str) -> None:
        assert delta_marker(metric, before, after) == expected


class TestDeltaCell:
    def test_changed_with_polarity(self) -> None:
        assert delta_cell("coverage", "93.4", "94.1") == "🟢 93.4% → 94.1%"

    def test_changed_without_polarity(self) -> None:
        assert delta_cell("ncloc", "2121", "2280") == "2121 → 2280"

    def test_unchanged_renders_the_value_alone(self) -> None:
        assert delta_cell("coverage", "93.4", "93.4") == "93.4%"

    def test_one_end_missing_renders_the_current_value(self) -> None:
        assert delta_cell("coverage", None, "93.4") == "93.4%"
        assert delta_cell("coverage", "93.4", None) == "—"

    def test_ratings_render_as_letters(self) -> None:
        assert delta_cell("security_rating", "1.0", "5.0") == "🔴 A → E"

    def test_breakdown_rides_on_the_head_value(self) -> None:
        cell = delta_cell("violations", "13", "15", after_text="15 (critical 7, minor 4)")
        assert cell == "🔴 13 → 15 (critical 7, minor 4)"

    def test_unchanged_keeps_the_breakdown(self) -> None:
        assert delta_cell("violations", "13", "13", after_text="13 (critical 7)") == "13 (critical 7)"

    def test_display_equal_values_count_as_unchanged(self) -> None:
        # 93.40 and 93.44 both render as 93.4% — an arrow between two identical strings is noise.
        assert delta_cell("coverage", "93.40", "93.44") == "93.4%"


class TestBuildGateBlock:
    def _status(self, status: str = "OK", conditions: list[dict] | None = None) -> dict:
        return {
            "projectStatus": {
                "status": status,
                "conditions": conditions
                if conditions is not None
                else [
                    {
                        "metricKey": "new_reliability_rating",
                        "comparator": "GT",
                        "errorThreshold": "1",
                        "actualValue": "1.0",
                        "status": "OK",
                    },
                    {
                        "metricKey": "new_coverage",
                        "comparator": "LT",
                        "errorThreshold": "80",
                        "actualValue": "96.83",
                        "status": "OK",
                    },
                ],
            }
        }

    def test_passed_block_is_collapsed_and_unbolded(self) -> None:
        block = build_gate_block("statuskit", self._status(), DASHBOARD)
        assert block["title"] == "Sonar · statuskit — Quality Gate passed"
        assert block["open"] is False
        assert block["rows"][0] == [{"text": "✅ Reliability", "bold": False}, {"text": "A (need A)", "bold": False}]
        assert block["rows"][1][1]["text"] == "96.8% (need ≥ 80%)"

    def test_failed_condition_is_open_and_bold(self) -> None:
        conditions = [
            {
                "metricKey": "new_coverage",
                "comparator": "LT",
                "errorThreshold": "80",
                "actualValue": "42.0",
                "status": "ERROR",
            },
        ]
        block = build_gate_block("statuskit", self._status("ERROR", conditions), DASHBOARD)
        assert block["title"] == "Sonar · statuskit — Quality Gate failed"
        assert block["open"] is True
        assert block["rows"][0] == [{"text": "❌ Coverage", "bold": True}, {"text": "42.0% (need ≥ 80%)", "bold": True}]

    def test_row_set_follows_the_api(self) -> None:
        # A release-please PR returns only four conditions — that is correct output, not missing data.
        conditions = [
            {
                "metricKey": f"new_{name}_rating",
                "comparator": "GT",
                "errorThreshold": "1",
                "actualValue": "1.0",
                "status": "OK",
            }
            for name in ("reliability", "security", "maintainability")
        ]
        block = build_gate_block("statuskit", self._status("OK", conditions), DASHBOARD)
        assert len(block["rows"]) == 3

    def test_dashboard_link_is_a_block_field(self) -> None:
        # The validated layout renders it as <p><a> after the table, not as a table row.
        block = build_gate_block("statuskit", self._status(), DASHBOARD)
        assert block["link"] == {"text": "Dashboard", "url": DASHBOARD}
        assert all(len(row) == 2 for row in block["rows"])


class TestBuildNewCodeBlock:
    MEASURES: ClassVar[dict] = {
        "new_violations": "6",
        "new_accepted_issues": "0",
        "new_vulnerabilities": "0",
        "new_coverage": "96.83",
        "new_duplicated_lines_density": "0.0",
        "new_lines": "1357",
    }

    def test_rows(self) -> None:
        block = build_new_code_block(
            "statuskit", self.MEASURES, {"CRITICAL": 5, "MINOR": 1}, DASHBOARD, "https://issues"
        )
        assert block["title"] == "Sonar · statuskit — new code"
        assert block["open"] is False
        labels = [row[0] for row in block["rows"] if isinstance(row[0], str)]
        assert labels[:6] == [
            "New issues",
            "Accepted issues",
            "Vulnerabilities",
            "Coverage on new code",
            "Duplication on new code",
            "New lines",
        ]
        assert block["rows"][0][1] == "6 (critical 5, minor 1)"

    def test_absent_metric_renders_em_dash(self) -> None:
        measures = dict(self.MEASURES)
        del measures["new_coverage"]
        block = build_new_code_block("statuskit", measures, {}, DASHBOARD, "https://issues")
        assert block["rows"][3][1] == "—"

    def test_hotspot_row_omitted_at_zero(self) -> None:
        block = build_new_code_block("statuskit", self.MEASURES, {}, DASHBOARD, "https://issues")
        assert all("Hotspots" not in str(row[0]) for row in block["rows"])

    def test_hotspot_row_present_when_non_zero(self) -> None:
        measures = {**self.MEASURES, "new_security_hotspots": "2"}
        block = build_new_code_block("statuskit", measures, {}, DASHBOARD, "https://issues")
        assert any("Hotspots" in str(row[0]) for row in block["rows"])

    def test_green_block_has_no_bold(self) -> None:
        block = build_new_code_block("statuskit", self.MEASURES, {}, DASHBOARD, "https://issues")
        flat = json.dumps(block)
        assert '"bold": true' not in flat


class TestBuildBranchBlock:
    MEASURES: ClassVar[dict] = {
        "coverage": "93.4",
        "violations": "13",
        "vulnerabilities": "1",
        "security_issues": '{"total":1,"HIGH":0,"MEDIUM":0,"LOW":0,"INFO":0,"BLOCKER":1}',
        "reliability_rating": "1.0",
        "security_rating": "5.0",
        "sqale_rating": "1.0",
        "duplicated_lines_density": "0.0",
        "ncloc": "2121",
    }

    def test_rows(self) -> None:
        block = build_branch_block(
            "statuskit",
            self.MEASURES,
            {"BLOCKER": 1, "CRITICAL": 7, "MAJOR": 1, "MINOR": 4},
            "https://sonarcloud.io/project/overview?id=NoNameItem_statuskit",
        )
        assert block["title"] == "Sonar · statuskit — project state"
        rows = {row[0]: row[1] for row in block["rows"] if isinstance(row[0], str)}
        assert rows["Coverage"] == "93.4%"
        assert rows["Issues"] == "13 (blocker 1, critical 7, major 1, minor 4)"
        assert rows["Vulnerabilities"] == "1 (blocker 1)"
        assert rows["Security"] == "E"
        assert rows["Lines of code"] == "2121"


class TestFetchAndDegrade:
    def test_degraded_block_uses_check_run_title(self) -> None:
        from ..sonar_pr_status import degraded_block

        block = degraded_block("statuskit", "Quality Gate failed", DASHBOARD)
        assert block["title"] == "Sonar · statuskit — Quality Gate failed"
        assert block["rows"] == []
        assert block["link"] == {"text": "Dashboard", "url": DASHBOARD}

    def test_http_error_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_pr_status as mod

        def fake_urlopen(request, timeout: float = 30.0):
            raise urllib.error.HTTPError(request.full_url, 500, "Boom", hdrs=None, fp=None)

        monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
        assert mod.fetch_json("https://sonarcloud.io/api/measures/component", None) is None

    def test_timeout_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_pr_status as mod

        def fake_urlopen(request, timeout: float = 30.0):
            raise TimeoutError

        monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
        assert mod.fetch_json("https://sonarcloud.io/api/measures/component", None) is None
