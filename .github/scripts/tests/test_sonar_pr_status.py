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
    build_release_delta_block,
    delta_cell,
    delta_marker,
    extract_projects,
    find_analysis,
    format_breakdown,
    format_measure,
    format_threshold,
    history_pair,
    pick_baseline,
    rating_letter,
    revision_matches,
    split_history,
    trend_segment,
    version_event,
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


class TestTrendSegment:
    def test_regressions_lead_and_improvements_follow(self) -> None:
        assert trend_segment(["🔴", "🔴", "🟢", "🟢", ""]) == "🔴 2 worse, 🟢 2 better"

    def test_green_omitted_when_zero(self) -> None:
        assert trend_segment(["🔴", "", ""]) == "🔴 1 worse"

    def test_improvements_only(self) -> None:
        assert trend_segment(["🟢", "🟢", "🟢"]) == "🟢 3 better"

    def test_nothing_changed_is_empty(self) -> None:
        assert trend_segment(["", "", ""]) == ""


class TestBuildReleaseDeltaBlock:
    OVERVIEW = "https://sonarcloud.io/project/overview?id=NoNameItem_statuskit&branch=master"

    BASELINE: ClassVar[dict] = {
        "coverage": "93.4",
        "violations": "13",
        "vulnerabilities": "1",
        "reliability_rating": "1.0",
        "security_rating": "5.0",
        "sqale_rating": "1.0",
        "duplicated_lines_density": "0.0",
        "ncloc": "2121",
        "security_hotspots": "0",
    }

    HEAD: ClassVar[dict] = {
        **BASELINE,
        "coverage": "94.1",
        "violations": "15",
        "ncloc": "2280",
        "security_issues": '{"total":1,"HIGH":0,"MEDIUM":0,"LOW":0,"INFO":0,"BLOCKER":1}',
    }

    def _block(self, head: dict | None = None, baseline: dict | None = None) -> dict:
        return build_release_delta_block(
            "statuskit",
            "0.5.0",
            self.BASELINE if baseline is None else baseline,
            self.HEAD if head is None else head,
            {"CRITICAL": 7, "MINOR": 4},
            self.OVERVIEW,
        )

    def test_title_carries_baseline_and_trend(self) -> None:
        assert self._block()["title"] == "Sonar · statuskit — since 0.5.0 · 🔴 1 worse, 🟢 1 better"

    def test_title_drops_the_trend_when_nothing_moved(self) -> None:
        block = self._block(head=dict(self.BASELINE))
        assert block["title"] == "Sonar · statuskit — since 0.5.0"

    def test_open_when_a_metric_regressed(self) -> None:
        assert self._block()["open"] is True

    def test_collapsed_when_only_improvements(self) -> None:
        head = {**self.BASELINE, "coverage": "94.1"}
        assert self._block(head=head)["open"] is False

    def test_rows(self) -> None:
        rows = {row[0]: row[1] for row in self._block()["rows"]}
        assert rows["Coverage"] == "🟢 93.4% → 94.1%"
        assert rows["Issues"] == "🔴 13 → 15 (critical 7, minor 4)"
        assert rows["Vulnerabilities"] == "1 (blocker 1)"
        assert rows["Security"] == "E"
        assert rows["Lines of code"] == "2121 → 2280"

    def test_row_labels_match_the_branch_block(self) -> None:
        labels = [row[0] for row in self._block()["rows"]]
        assert labels == [
            "Coverage",
            "Issues",
            "Vulnerabilities",
            "Reliability",
            "Security",
            "Maintainability",
            "Duplication",
            "Lines of code",
        ]

    def test_hotspot_row_present_when_non_zero(self) -> None:
        head = {**self.HEAD, "security_hotspots": "2"}
        assert any(row[0] == "Hotspots" for row in self._block(head=head)["rows"])

    def test_no_bold_anywhere(self) -> None:
        assert '"bold": true' not in json.dumps(self._block())

    def test_links_to_the_overview(self) -> None:
        assert self._block()["link"] == {"text": "Dashboard", "url": self.OVERVIEW}


def _analysis(date: str, revision: str, version: str | None = None) -> dict:
    events = [{"category": "VERSION", "name": version}] if version else []
    return {"key": date, "date": date, "events": events, "revision": revision}


HEAD_SHA = "dab4b1f00b091b8c2bd1f7fa402500a42e77d059"
PREV_SHA = "53704e5abd6ce69689bc4c1ce99460c29e16dfdd"
OLD_SHA = "b761151bc3e962b0ad5d96588a418988be50046e"

ANALYSES = [
    _analysis("2026-07-31T12:53:12+0000", HEAD_SHA, "0.5.1"),
    _analysis("2026-07-31T12:06:46+0000", PREV_SHA, "0.5.0"),
    _analysis("2026-07-21T14:58:36+0000", OLD_SHA, "not provided"),
]


class TestRevisionMatches:
    def test_full_sha(self) -> None:
        assert revision_matches(HEAD_SHA, HEAD_SHA) is True

    def test_short_sha_from_a_manual_run(self) -> None:
        assert revision_matches(HEAD_SHA, "dab4b1f") is True

    def test_different_commit(self) -> None:
        assert revision_matches(HEAD_SHA, PREV_SHA) is False

    def test_too_short_to_be_a_sha(self) -> None:
        assert revision_matches(HEAD_SHA, "dab") is False

    def test_missing_values(self) -> None:
        assert revision_matches(None, HEAD_SHA) is False
        assert revision_matches(HEAD_SHA, None) is False


class TestVersionEvent:
    def test_reads_the_version_event(self) -> None:
        assert version_event(ANALYSES[0]) == "0.5.1"

    def test_ignores_other_categories(self) -> None:
        analysis = {"events": [{"category": "QUALITY_PROFILE", "name": "Changes in 'Sonar way' (py)"}]}
        assert version_event(analysis) is None

    def test_no_events(self) -> None:
        assert version_event({}) is None


class TestFindAnalysis:
    def test_finds_the_release_commit(self) -> None:
        assert find_analysis(ANALYSES, HEAD_SHA)["date"] == "2026-07-31T12:53:12+0000"

    def test_absent_revision(self) -> None:
        assert find_analysis(ANALYSES, "0" * 40) is None


class TestPickBaseline:
    def test_head_already_carries_the_released_version(self) -> None:
        # The release analysis landed: the baseline is the second-newest VERSION event.
        assert pick_baseline(ANALYSES, "0.5.1")["date"] == "2026-07-31T12:06:46+0000"

    def test_head_does_not_carry_it_yet(self) -> None:
        # Timed out and fell back to a later plain analysis: the newest VERSION event is the baseline.
        analyses = [_analysis("2026-08-01T09:00:00+0000", "f" * 40), *ANALYSES]
        assert pick_baseline(analyses, "0.6.0")["date"] == "2026-07-31T12:53:12+0000"

    def test_rejects_not_provided(self) -> None:
        # Only the poisoned pre-seeding event is left — that is no baseline at all.
        assert pick_baseline(ANALYSES[2:], "0.5.1") is None

    def test_no_previous_release(self) -> None:
        assert pick_baseline(ANALYSES[:1], "0.5.1") is None


class TestFetchAnalyses:
    def test_returns_the_analyses_array(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_pr_status as mod

        seen: list[str] = []

        def fake_fetch(url: str, token: str | None) -> dict:
            seen.append(url)
            return {"analyses": ANALYSES}

        monkeypatch.setattr(mod, "fetch_json", fake_fetch)
        assert mod.fetch_analyses("NoNameItem_statuskit", "master", None) == ANALYSES
        assert "project_analyses/search" in seen[0]
        assert "branch=master" in seen[0]

    def test_api_failure_is_an_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_pr_status as mod

        monkeypatch.setattr(mod, "fetch_json", lambda url, token: None)
        assert mod.fetch_analyses("NoNameItem_statuskit", "master", None) == []


class TestHistoryPair:
    POINTS: ClassVar[list[dict]] = [
        {"date": "2026-07-31T12:06:46+0000", "value": "93.4"},
        {"date": "2026-07-31T12:53:12+0000", "value": "94.1"},
    ]

    def test_both_ends(self) -> None:
        pair = history_pair(self.POINTS, "2026-07-31T12:06:46+0000", "2026-07-31T12:53:12+0000")
        assert pair == ("93.4", "94.1")

    def test_head_date_absent_falls_back_to_the_last_point(self) -> None:
        pair = history_pair(self.POINTS, "2026-07-31T12:06:46+0000", "2026-08-01T10:00:00+0000")
        assert pair == ("93.4", "94.1")

    def test_metric_missing_at_the_baseline(self) -> None:
        # A metric that did not exist when the previous release was cut: no arrow, current value only.
        pair = history_pair(self.POINTS[1:], "2026-07-31T12:06:46+0000", "2026-07-31T12:53:12+0000")
        assert pair == (None, "94.1")

    def test_no_points_at_all(self) -> None:
        assert history_pair([], "2026-07-31T12:06:46+0000", "2026-07-31T12:53:12+0000") == (None, None)


class TestSplitHistory:
    def test_splits_every_metric(self) -> None:
        history = {
            "coverage": [
                {"date": "2026-07-31T12:06:46+0000", "value": "93.4"},
                {"date": "2026-07-31T12:53:12+0000", "value": "94.1"},
            ],
            "ncloc": [{"date": "2026-07-31T12:53:12+0000", "value": "2280"}],
        }
        baseline, head = split_history(history, "2026-07-31T12:06:46+0000", "2026-07-31T12:53:12+0000")
        assert baseline == {"coverage": "93.4"}
        assert head == {"coverage": "94.1", "ncloc": "2280"}


class TestFetchHistory:
    def test_parses_measures_into_point_lists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_pr_status as mod

        seen: list[str] = []

        def fake_fetch(url: str, token: str | None) -> dict:
            seen.append(url)
            return {
                "measures": [
                    {"metric": "coverage", "history": [{"date": "2026-07-31T12:06:46+0000", "value": "93.4"}]},
                ]
            }

        monkeypatch.setattr(mod, "fetch_json", fake_fetch)
        history = mod.fetch_history("NoNameItem_statuskit", "master", ["coverage"], "2026-07-31T12:06:46+0000", None)
        assert history == {"coverage": [{"date": "2026-07-31T12:06:46+0000", "value": "93.4"}]}
        assert "measures/search_history" in seen[0]
        assert "from=2026-07-31T12%3A06%3A46%2B0000" in seen[0]

    def test_api_failure_is_an_empty_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_pr_status as mod

        monkeypatch.setattr(mod, "fetch_json", lambda url, token: None)
        assert mod.fetch_history("NoNameItem_statuskit", "master", ["coverage"], "2026-07-31", None) == {}


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
