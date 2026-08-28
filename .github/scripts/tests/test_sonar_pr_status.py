"""Tests for sonar_pr_status.py formatting and API handling."""

from __future__ import annotations

import json
import urllib.error
from typing import Any, ClassVar

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
            # Sub-precision move: 93.44 and 93.43 both render "93.4%" — no visible change, no marker.
            ("coverage", "93.44", "93.43", ""),
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


class TestDeltaMarkerAgreesWithDeltaCell:
    """`delta_marker` and `delta_cell` must never disagree about whether a metric moved.

    Before the fix, `delta_marker` compared raw `float(before)` vs `float(after)` while
    `delta_cell` compared `format_measure()`-rendered text — so a sub-precision move (e.g.
    coverage 93.44 -> 93.43) fed a red/green marker into `trend_segment`'s title and the block's
    `open` flag even though the rendered table showed no change at all on that row.
    """

    def test_sub_precision_percent_change_yields_no_marker_and_a_plain_cell(self) -> None:
        assert delta_marker("coverage", "93.44", "93.43") == ""
        assert delta_cell("coverage", "93.44", "93.43") == "93.4%"

    def test_real_percent_change_still_produces_a_marker(self) -> None:
        assert delta_marker("coverage", "93.4", "94.1") == "🟢"
        assert delta_cell("coverage", "93.4", "94.1") == "🟢 93.4% → 94.1%"


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
        """The delta block must show the same rows as the branch block, or the two drift apart."""
        branch_labels = [row[0] for row in build_branch_block("statuskit", self.BASELINE, {}, self.OVERVIEW)["rows"]]
        delta_labels = [row[0] for row in self._block()["rows"]]
        assert delta_labels == branch_labels

    def test_hotspot_row_present_when_non_zero(self) -> None:
        head = {**self.HEAD, "security_hotspots": "2"}
        assert any(row[0] == "Hotspots" for row in self._block(head=head)["rows"])

    def test_metric_missing_at_head_renders_em_dash_not_a_stale_value(self) -> None:
        # `history_pair` never falls back to an older point for the head end (see TestHistoryPair),
        # so a metric absent from `head` must come through as the same "—" every other unavailable
        # head value gets — never the baseline figure re-shown as if it were current.
        head = dict(self.HEAD)
        del head["ncloc"]
        rows = {row[0]: row[1] for row in self._block(head=head)["rows"]}
        assert rows["Lines of code"] == "—"

    def test_hotspot_row_present_when_missing_at_head_but_present_at_baseline(self) -> None:
        # Regression guard for the bug this suite exists to catch: the hotspots row used to be
        # included only when `head` carried a non-zero count, so a metric merely unresolved at
        # head_date read the same as a confirmed zero and the row vanished instead of showing
        # "value → —". It must survive here on baseline data alone.
        baseline = {**self.BASELINE, "security_hotspots": "3"}
        head = dict(self.HEAD)
        del head["security_hotspots"]
        rows = {row[0]: row[1] for row in self._block(baseline=baseline, head=head)["rows"]}
        assert rows["Hotspots"] == "—"

    @pytest.mark.parametrize(
        ("baseline_hotspots", "head_hotspots", "expected_present"),
        [
            # Pinned as the whole nine-cell table (A = absent, Z = confirmed zero, N = a real
            # value) rather than one-off cases: this row's inclusion rule has already been wrong
            # twice — first dropping a real baseline paired with an unresolved head, then dropping
            # a real baseline that improved to a confirmed zero at head — so a single regression
            # test only proves the last mistake stays fixed, not the next one.
            (None, None, False),  # A -> A
            (None, "0", False),  # A -> Z
            (None, "5", True),  # A -> N
            ("0", None, False),  # Z -> A
            ("0", "0", False),  # Z -> Z
            ("0", "5", True),  # Z -> N
            ("3", None, True),  # N -> A
            ("3", "0", True),  # N -> Z (the regression this round fixes)
            ("3", "5", True),  # N -> N
            # `""` is a second spelling of "A": `split_history` only filters out `None` values, so
            # an empty string is a reachable endpoint value too (Sonar can return one), and it must
            # collapse to the same "absent" state as a missing key rather than being read as real.
            ("", "0", False),  # A(empty) -> Z
            ("", "5", True),  # A(empty) -> N
            ("3", "", True),  # N -> A(empty)
        ],
    )
    def test_hotspot_row_inclusion_table(
        self, baseline_hotspots: str | None, head_hotspots: str | None, expected_present: bool
    ) -> None:
        baseline = dict(self.BASELINE)
        head = dict(self.HEAD)
        if baseline_hotspots is None:
            baseline.pop("security_hotspots", None)
        else:
            baseline["security_hotspots"] = baseline_hotspots
        if head_hotspots is None:
            head.pop("security_hotspots", None)
        else:
            head["security_hotspots"] = head_hotspots
        rows = {row[0]: row[1] for row in self._block(baseline=baseline, head=head)["rows"]}
        assert ("Hotspots" in rows) is expected_present

    def test_hotspot_row_renders_the_nonzero_to_zero_improvement(self) -> None:
        # N -> Z is the case this round fixes: it must not just show the row, it must show the
        # green "3 -> 0" it exists to report — the best news this row can ever carry.
        baseline = {**self.BASELINE, "security_hotspots": "3"}
        head = {**self.HEAD, "security_hotspots": "0"}
        rows = {row[0]: row[1] for row in self._block(baseline=baseline, head=head)["rows"]}
        assert rows["Hotspots"] == "🟢 3 → 0"

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


def _analyses_page(count: int, offset: int) -> list[dict]:
    """A page of distinct, order-trackable analysis stubs (content is irrelevant to pagination)."""
    return [{"key": f"a{i}", "revision": f"rev{i}"} for i in range(offset, offset + count)]


class TestFetchAnalysesPagination:
    def test_pages_through_and_concatenates_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # More than one page's worth of analyses accumulated since the previous release: a
        # single ps=100 call would leave `pick_baseline` unable to see the older pages at all.
        from .. import sonar_pr_status as mod

        pages = [
            _analyses_page(mod._ANALYSES_PAGE_SIZE, 0),
            _analyses_page(mod._ANALYSES_PAGE_SIZE, 100),
            _analyses_page(30, 200),  # short page: the normal end-of-data signal
        ]
        responses = iter(pages)
        seen: list[str] = []

        def fake_fetch(url: str, token: str | None) -> dict:
            seen.append(url)
            return {"analyses": next(responses)}

        monkeypatch.setattr(mod, "fetch_json", fake_fetch)
        result = mod.fetch_analyses("NoNameItem_statuskit", "master", None)
        assert result == pages[0] + pages[1] + pages[2]
        assert len(seen) == 3
        assert "p=1" in seen[0]
        assert "p=2" in seen[1]
        assert "p=3" in seen[2]

    def test_stops_at_the_cap_without_raising(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A misbehaving API that never returns a short page must not spin forever, and must not
        # raise either — every Sonar failure in this file degrades (see module docstring).
        from .. import sonar_pr_status as mod

        def fake_fetch(url: str, token: str | None) -> dict:
            return {"analyses": _analyses_page(mod._ANALYSES_PAGE_SIZE, 0)}

        monkeypatch.setattr(mod, "fetch_json", fake_fetch)
        result = mod.fetch_analyses("NoNameItem_statuskit", "master", None)
        assert len(result) == mod._ANALYSES_PAGE_SIZE * mod._MAX_ANALYSIS_PAGES
        assert "cap" in capsys.readouterr().err


class TestHistoryPair:
    POINTS: ClassVar[list[dict]] = [
        {"date": "2026-07-31T12:06:46+0000", "value": "93.4"},
        {"date": "2026-07-31T12:53:12+0000", "value": "94.1"},
    ]

    def test_both_ends(self) -> None:
        pair = history_pair(self.POINTS, "2026-07-31T12:06:46+0000", "2026-07-31T12:53:12+0000")
        assert pair == ("93.4", "94.1")

    def test_head_date_absent_yields_no_head_value(self) -> None:
        # head_date is always the head analysis's own date (see build_release_blocks), so a miss
        # means Sonar has no value for this metric at that analysis. Reporting an older point as
        # current would be worse than an absent end: the row must render without an arrow.
        pair = history_pair(self.POINTS, "2026-07-31T12:06:46+0000", "2026-08-01T10:00:00+0000")
        assert pair == ("93.4", None)

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

    def test_metric_present_only_at_baseline(self) -> None:
        # Mirror of `ncloc` above but for the opposite end: a metric with a point dated at the
        # baseline and none at head_date (Sonar didn't recompute it for the head analysis). It must
        # land in `baseline` only — `split_history` must not fabricate a head value by reusing the
        # baseline one, or a caller like the release delta block's hotspots row would render a
        # stale figure as current instead of the "unavailable" it actually is.
        history = {
            "security_hotspots": [{"date": "2026-07-31T12:06:46+0000", "value": "3"}],
        }
        baseline, head = split_history(history, "2026-07-31T12:06:46+0000", "2026-07-31T12:53:12+0000")
        assert baseline == {"security_hotspots": "3"}
        assert "security_hotspots" not in head


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


class TestWaitForAnalysis:
    def _responses(self, monkeypatch: pytest.MonkeyPatch, pages: list[list[dict]]) -> list[float]:
        """Stub `fetch_analyses` with one response per call; return the list sleeps are recorded in.

        One response is consumed per call regardless of `max_pages` — each poll tick makes one
        call (bounded to page 1) and, once the loop resolves, exactly one further call rebuilds the
        full list, so callers must supply one extra page beyond what the old single-fetch-per-tick
        contract needed.
        """
        from .. import sonar_pr_status as mod

        remaining = list(pages)
        monkeypatch.setattr(
            mod,
            "fetch_analyses",
            lambda project, branch, token, max_pages=mod._MAX_ANALYSIS_PAGES: remaining.pop(0),
        )
        return []

    def test_found_on_the_first_poll(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_pr_status as mod

        # One response for the poll tick that finds the head, one for the post-loop full re-fetch.
        slept = self._responses(monkeypatch, [ANALYSES, ANALYSES])
        analyses, head = mod.wait_for_analysis("NoNameItem_statuskit", "master", HEAD_SHA, None, sleep=slept.append)
        assert head["revision"] == HEAD_SHA
        assert analyses == ANALYSES
        assert slept == []

    def test_appears_on_the_third_poll(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_pr_status as mod

        without_head = ANALYSES[1:]
        slept = self._responses(monkeypatch, [without_head, without_head, ANALYSES, ANALYSES])
        _, head = mod.wait_for_analysis("NoNameItem_statuskit", "master", HEAD_SHA, None, sleep=slept.append)
        assert head["revision"] == HEAD_SHA
        assert slept == [15.0, 15.0]

    def test_ceiling_is_ten_minutes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_pr_status as mod

        without_head = ANALYSES[1:]
        # 41 poll ticks (none find the head) plus the one full re-fetch after the ceiling is hit.
        slept = self._responses(monkeypatch, [without_head] * 42)
        analyses, head = mod.wait_for_analysis("NoNameItem_statuskit", "master", HEAD_SHA, None, sleep=slept.append)
        assert head is None
        assert analyses == without_head  # the caller degrades to the latest analysis
        assert sum(slept) == 600.0

    def test_timeout_reports_the_degradation(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from .. import sonar_pr_status as mod

        slept = self._responses(monkeypatch, [ANALYSES[1:]] * 42)
        mod.wait_for_analysis("NoNameItem_statuskit", "master", HEAD_SHA, None, sleep=slept.append)
        assert HEAD_SHA in capsys.readouterr().err

    def test_ceiling_reached_but_head_surfaces_in_the_full_history(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from .. import sonar_pr_status as mod

        # Every poll tick only ever sees page 1, so a revision that never surfaces there over all
        # 41 ticks is not necessarily missing — it can still be sitting deeper in the FULL
        # paginated history the post-loop re-fetch builds. That re-fetch must win over conceding:
        # otherwise `build_release_blocks` would fall back to `analyses[0]`, the latest analysis,
        # and report the wrong revision's metrics even though the real one was one call away.
        without_head = ANALYSES[1:]
        slept = self._responses(monkeypatch, [without_head] * 41 + [ANALYSES])
        analyses, head = mod.wait_for_analysis("NoNameItem_statuskit", "master", HEAD_SHA, None, sleep=slept.append)
        assert head is not None
        assert head["revision"] == HEAD_SHA
        assert head in analyses  # `build_release_blocks`'s `analyses.index(head)` must not raise
        assert analyses == ANALYSES
        assert capsys.readouterr().err == ""  # no "falling back to the latest analysis" note

    def test_no_analyses_returns_immediately(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # No project in Sonar (a `flow` release) or the API is down — waiting changes neither. An
        # empty page 1 triggers exactly one full probe first; when that probe is empty too, the
        # wait ends immediately with no polling and no post-loop re-fetch.
        from .. import sonar_pr_status as mod

        slept = self._responses(monkeypatch, [[], []])
        assert mod.wait_for_analysis("NoNameItem_statuskit", "master", HEAD_SHA, None, sleep=slept.append) == ([], None)
        assert slept == []

    def test_empty_page_one_but_probe_finds_the_revision(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Page 1 blipped empty on the very first tick, but the one-shot full probe it triggers
        # finds the revision straight away: the wait must resolve on the spot, with the probe's own
        # full history returned as `analyses` and no "falling back" degradation note (nothing was
        # degraded — the revision was found).
        from .. import sonar_pr_status as mod

        slept = self._responses(monkeypatch, [[], ANALYSES])
        analyses, head = mod.wait_for_analysis("NoNameItem_statuskit", "master", HEAD_SHA, None, sleep=slept.append)
        assert head["revision"] == HEAD_SHA
        assert head in analyses
        assert analyses == ANALYSES
        assert slept == []
        assert capsys.readouterr().err == ""

    def test_empty_page_one_probe_without_revision_keeps_polling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The probe is non-empty (the project exists, the API is alive) but does not yet contain
        # the wanted revision: that must NOT be treated as a concession. Several later ticks come
        # back with an empty page 1 too — the probe must not run again for any of them (it is up to
        # `_MAX_ANALYSIS_PAGES` requests, unaffordable every tick) — until a later tick's page 1
        # finally carries the revision and the wait resolves normally.
        from .. import sonar_pr_status as mod

        without_head = ANALYSES[1:]
        # tick0: empty page 1 -> one-shot probe (non-empty, no revision yet).
        # tick1, tick2: empty page 1 again -> no re-probe, just another transient miss.
        # tick3: page 1 carries the revision -> resolves; then the post-loop full re-fetch.
        slept = self._responses(monkeypatch, [[], without_head, [], [], ANALYSES, ANALYSES])
        analyses, head = mod.wait_for_analysis("NoNameItem_statuskit", "master", HEAD_SHA, None, sleep=slept.append)
        assert head["revision"] == HEAD_SHA
        assert head in analyses
        assert analyses == ANALYSES
        assert slept == [15.0, 15.0, 15.0]


class TestWaitForAnalysisPagination:
    """`fetch_analyses` calls inside `wait_for_analysis` at the `fetch_json` level.

    These exercise the split directly against request URLs, rather than through the
    `fetch_analyses`-stubbing helper above, so the assertions can see the actual `p=` values sent.
    """

    def test_polls_only_page_one_then_fetches_the_full_history_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_pr_status as mod

        # A project whose master history spans three pages: `pick_baseline` needs all of it, but
        # the poll loop must never ask for anything past page 1 — that is where Sonar puts the
        # release commit's analysis the moment it exists.
        page1_without_head = _analyses_page(mod._ANALYSES_PAGE_SIZE, 0)
        head_analysis = _analysis("2026-08-01T00:00:00+0000", HEAD_SHA)
        page1_with_head = [head_analysis, *page1_without_head[:-1]]
        page2 = _analyses_page(mod._ANALYSES_PAGE_SIZE, 100)
        page3 = _analyses_page(30, 200)

        # Poll ticks 1-2 miss, tick 3 finds it (all page 1); then the full re-fetch walks p=1,2,3.
        responses = iter([page1_without_head, page1_without_head, page1_with_head, page1_with_head, page2, page3])
        seen: list[str] = []

        def fake_fetch(url: str, token: str | None) -> dict:
            seen.append(url)
            return {"analyses": next(responses)}

        monkeypatch.setattr(mod, "fetch_json", fake_fetch)
        analyses, head = mod.wait_for_analysis("NoNameItem_statuskit", "master", HEAD_SHA, None, sleep=lambda s: None)

        poll_urls, refetch_urls = seen[:3], seen[3:]
        assert all("p=1" in url for url in poll_urls)
        assert all("p=2" not in url and "p=3" not in url for url in poll_urls)

        assert "p=1" in refetch_urls[0]
        assert "p=2" in refetch_urls[1]
        assert "p=3" in refetch_urls[2]

        assert analyses == page1_with_head + page2 + page3
        assert head == head_analysis
        assert head in analyses  # `build_release_blocks`'s `analyses.index(head)` must not raise

    def test_head_found_while_polling_is_looked_up_fresh_in_the_final_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from .. import sonar_pr_status as mod

        # The page-1 response seen on the poll tick and the page-1 response seen during the
        # post-loop full re-fetch are for the same revision but are NOT the same object, and not
        # even `==` (Sonar can easily add fields, e.g. an `events` entry, between two calls). If
        # `wait_for_analysis` returned the object it saw while polling instead of re-locating it in
        # the final list, `analyses.index(head)` would raise `ValueError` once that exact object is
        # no longer present in the returned list.
        rest = _analyses_page(mod._ANALYSES_PAGE_SIZE - 2, 0)
        stale_head = {"key": "a", "revision": HEAD_SHA, "date": "2026-08-01T00:00:00+0000"}
        fresh_head = {"key": "a", "revision": HEAD_SHA, "date": "2026-08-01T00:00:00+0000", "events": []}
        responses = iter([[stale_head, *rest], [fresh_head, *rest]])

        def fake_fetch(url: str, token: str | None) -> dict:
            return {"analyses": next(responses)}

        monkeypatch.setattr(mod, "fetch_json", fake_fetch)
        analyses, head = mod.wait_for_analysis("NoNameItem_statuskit", "master", HEAD_SHA, None, sleep=lambda s: None)

        assert head is fresh_head
        assert head in analyses
        assert analyses.index(head) == 0  # would raise ValueError if `head` were still `stale_head`


class TestFetchAnalysesMaxPages:
    def test_bounded_call_stops_at_one_page_without_a_cap_warning(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # `wait_for_analysis`'s poll loop deliberately asks for one page only; a short-of-the-full-
        # history stop is then normal, not the runaway-history condition the stderr note is for.
        from .. import sonar_pr_status as mod

        def fake_fetch(url: str, token: str | None) -> dict:
            return {"analyses": _analyses_page(mod._ANALYSES_PAGE_SIZE, 0)}

        monkeypatch.setattr(mod, "fetch_json", fake_fetch)
        result = mod.fetch_analyses("NoNameItem_statuskit", "master", None, max_pages=1)
        assert len(result) == mod._ANALYSES_PAGE_SIZE
        assert capsys.readouterr().err == ""


# Distinguishes "the test didn't pass `head`" from an explicit `head=None` — plain `None`
# can't do that job since `None` is also the real "no head found" value under test.
_UNSET: Any = object()


class TestBuildReleaseBlocks:
    HISTORY: ClassVar[dict] = {
        "coverage": [
            {"date": "2026-07-31T12:06:46+0000", "value": "93.4"},
            {"date": "2026-07-31T12:53:12+0000", "value": "94.1"},
        ],
        "violations": [
            {"date": "2026-07-31T12:06:46+0000", "value": "13"},
            {"date": "2026-07-31T12:53:12+0000", "value": "15"},
        ],
    }

    GATE: ClassVar[dict] = {
        "projectStatus": {
            "status": "OK",
            "conditions": [
                {
                    "metricKey": "new_coverage",
                    "comparator": "LT",
                    "errorThreshold": "80",
                    "actualValue": "96.83",
                    "status": "OK",
                }
            ],
        }
    }

    def _wire(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        analyses: list[dict] | None = None,
        head: dict | None = _UNSET,
        history: dict | None = None,
        branch_blocks: list[dict] | None = None,
    ) -> None:
        from .. import sonar_pr_status as mod

        monkeypatch.setattr(
            mod,
            "wait_for_analysis",
            lambda project, branch, revision, token, sleep=None: (
                ANALYSES if analyses is None else analyses,
                ANALYSES[0] if head is _UNSET else head,
            ),
        )
        monkeypatch.setattr(mod, "fetch_history", lambda *args, **kwargs: self.HISTORY if history is None else history)
        monkeypatch.setattr(mod, "_fetch_severities", lambda *args, **kwargs: {"CRITICAL": 7, "MINOR": 4})
        # The only `fetch_json` call left in this path is the quality gate.
        monkeypatch.setattr(mod, "fetch_json", lambda url, token: self.GATE)
        monkeypatch.setattr(
            mod,
            "build_branch_blocks",
            lambda project, branch, token: [] if branch_blocks is None else branch_blocks,
        )

    def _build(self) -> list[dict]:
        from .. import sonar_pr_status as mod

        return mod.build_release_blocks("NoNameItem_statuskit", "master", "0.5.1", HEAD_SHA, None)

    def test_gate_block_first_then_delta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._wire(monkeypatch)
        titles = [block["title"] for block in self._build()]
        assert titles == [
            "Sonar · statuskit — Quality Gate passed",
            "Sonar · statuskit — since 0.5.0 · 🔴 1 worse, 🟢 1 better",
        ]

    def test_gate_unavailable_keeps_the_delta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_pr_status as mod

        self._wire(monkeypatch)
        monkeypatch.setattr(mod, "fetch_json", lambda url, token: None)  # gate call fails
        blocks = self._build()
        assert len(blocks) == 1
        assert blocks[0]["title"].startswith("Sonar · statuskit — since 0.5.0")

    def test_no_baseline_degrades_to_the_project_state_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = {"type": "table", "title": "Sonar · statuskit — project state", "open": False, "rows": []}
        self._wire(monkeypatch, analyses=ANALYSES[:1], head=ANALYSES[0], branch_blocks=[state])
        assert [block["title"] for block in self._build()] == [
            "Sonar · statuskit — Quality Gate passed",
            "Sonar · statuskit — project state",
        ]

    def test_history_unavailable_degrades_the_same_way(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = {"type": "table", "title": "Sonar · statuskit — project state", "open": False, "rows": []}
        self._wire(monkeypatch, history={}, branch_blocks=[state])
        assert self._build()[-1]["title"] == "Sonar · statuskit — project state"

    def test_project_absent_from_sonar_yields_no_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._wire(monkeypatch, analyses=[], head=None, branch_blocks=[])
        assert self._build() == []

    def test_timed_out_wait_with_no_newer_analysis_degrades_to_project_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Timeout: `head` falls back to `analyses[0]`, whose VERSION event is the previous
        release (0.5.1) because no push landed between it and this release commit. If the version
        being released (0.5.2) is newer still, `pick_baseline` returns that very same analysis —
        the window collapses to a single point. That must degrade to the project-state block, not
        render "since 0.5.1" with every row reported unchanged."""
        from .. import sonar_pr_status as mod

        state = {"type": "table", "title": "Sonar · statuskit — project state", "open": False, "rows": []}
        self._wire(monkeypatch, analyses=ANALYSES, head=None, branch_blocks=[state])
        blocks = mod.build_release_blocks("NoNameItem_statuskit", "master", "0.5.2", HEAD_SHA, None)
        assert [block["title"] for block in blocks] == [
            "Sonar · statuskit — Quality Gate passed",
            "Sonar · statuskit — project state",
        ]


class TestReleaseCli:
    def test_release_mode_passes_version_and_revision(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from .. import sonar_pr_status as mod

        seen: list[tuple] = []

        def fake_build(project, branch, version, revision, token, sleep=None):
            seen.append((project, branch, version, revision))
            return [{"type": "table", "title": "Sonar · statuskit — since 0.5.0", "open": False, "rows": []}]

        monkeypatch.setattr(mod, "build_release_blocks", fake_build)
        monkeypatch.setattr(
            mod.sys,
            "argv",
            [
                "sonar_pr_status.py",
                "--mode",
                "release",
                "--branch",
                "master",
                "--version",
                "0.5.1",
                "--revision",
                HEAD_SHA,
                "--project-keys",
                '["NoNameItem_statuskit"]',
            ],
        )
        assert mod.main() == 0
        assert seen == [("NoNameItem_statuskit", "master", "0.5.1", HEAD_SHA)]
        assert json.loads(capsys.readouterr().out)[0]["title"] == "Sonar · statuskit — since 0.5.0"

    def test_failure_inside_the_loop_still_prints_json(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from .. import sonar_pr_status as mod

        def boom(*args, **kwargs):
            message = "Sonar exploded"
            raise RuntimeError(message)

        monkeypatch.setattr(mod, "build_release_blocks", boom)
        monkeypatch.setattr(
            mod.sys,
            "argv",
            [
                "sonar_pr_status.py",
                "--mode",
                "release",
                "--version",
                "0.5.1",
                "--revision",
                HEAD_SHA,
                "--project-keys",
                '["NoNameItem_statuskit"]',
            ],
        )
        assert mod.main() == 0
        assert json.loads(capsys.readouterr().out) == []

    def test_release_mode_requires_version(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from .. import sonar_pr_status as mod

        monkeypatch.setattr(
            mod.sys,
            "argv",
            [
                "sonar_pr_status.py",
                "--mode",
                "release",
                "--revision",
                HEAD_SHA,
                "--project-keys",
                '["NoNameItem_statuskit"]',
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            mod.main()
        assert exc_info.value.code == 2
        assert "--version is required when --mode release" in capsys.readouterr().err

    def test_release_mode_requires_revision(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from .. import sonar_pr_status as mod

        monkeypatch.setattr(
            mod.sys,
            "argv",
            [
                "sonar_pr_status.py",
                "--mode",
                "release",
                "--version",
                "0.5.1",
                "--project-keys",
                '["NoNameItem_statuskit"]',
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            mod.main()
        assert exc_info.value.code == 2
        assert "--revision is required when --mode release" in capsys.readouterr().err


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
