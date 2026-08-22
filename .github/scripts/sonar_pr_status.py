#!/usr/bin/env python3
"""Build render-ready Sonar blocks for a Telegram CI notification.

Two shapes, both emitted as `table` blocks in the notify-spec contract:

* ``--mode pr``     — per project: the quality gate (from ``conditions``, so a gate that gains
  a condition shows up with no code change) plus a new-code summary with a severity breakdown
  Sonar's own comment does not provide.
* ``--mode branch`` — per project: the overall state of the branch. A push message answers "did
  my commit break anything", and accumulated problems (e.g. a BLOCKER vulnerability) are only
  visible in the overall state. The delta since the previous release belongs to ``release``.
* ``--mode release`` — per project: the quality gate on ``master`` plus a version-to-version
  delta of the whole project since the previous release. Waits for the analysis of the tag's
  commit, because ``publish.yml`` and the analysis are independent workflow runs.

Data comes from the SonarCloud Web API, never from the check run's markdown ``output.summary``:
the API is a documented contract and carries the gate thresholds and per-condition status that
the markdown only implies through image filenames.

The script never raises out of ``main``: on any API failure it degrades to the check run's
``output.title`` alone, and on total failure prints ``[]``. A Sonar outage must cost detail,
not the notification.

Usage:
    python3 sonar_pr_status.py --mode pr --pr 118 --check-runs-file runs.json
    python3 sonar_pr_status.py --mode branch --branch master --project-keys '["NoNameItem_statuskit"]'
    python3 sonar_pr_status.py --mode release --branch master --version 0.5.1 --revision dab4b1f \
        --project-keys '["NoNameItem_statuskit"]'

Environment variables:
    SONAR_TOKEN  Optional. Public projects answer anonymously; passed anyway so private ones work.

Output (stdout):
    A JSON array of notify-spec `table` blocks (possibly empty).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_API_BASE = "https://sonarcloud.io"
_REQUEST_TIMEOUT = 30.0
_SONAR_APP_SLUG = "sonarqubecloud"

# publish.yml and the Sonar analysis of the same commit are two independent workflow runs, and
# neither waits for the other: on statuskit 0.5.1 the analysis landed 10 s after publish finished.
_POLL_INTERVAL_SECONDS = 15.0
_POLL_CEILING_SECONDS = 600.0

_RATINGS = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}

# The version name Sonar writes when an analysis carries no `sonar.projectVersion`. It is a value,
# not an absence — a baseline picker that only checks for a missing field would accept it.
_NO_VERSION = "not provided"

# Minimum length of a git short SHA for matching (7 characters, git default).
_MIN_SHORT_SHA_LEN = 7

# Metrics rendered as a percentage with one decimal.
_PERCENT_METRICS = frozenset(
    {
        "coverage",
        "new_coverage",
        "duplicated_lines_density",
        "new_duplicated_lines_density",
        "new_security_hotspots_reviewed",
        "security_hotspots_reviewed",
    }
)

# Human labels for the gate's condition metrics. Unknown keys fall back to a humanised key,
# so a gate revision needs no code change here either.
_CONDITION_LABELS = {
    "new_reliability_rating": "Reliability",
    "new_security_rating": "Security",
    "new_maintainability_rating": "Maintainability",
    "new_coverage": "Coverage",
    "new_duplicated_lines_density": "Duplication",
    "new_security_hotspots_reviewed": "Hotspots reviewed",
    "new_violations": "New issues",
    "new_accepted_issues": "Accepted issues",
}

# Severity order for a breakdown. Covers both the classic severities and the software-quality
# ones returned inline by `security_issues`.
_SEVERITY_ORDER = ("BLOCKER", "CRITICAL", "HIGH", "MAJOR", "MEDIUM", "MINOR", "LOW", "INFO")

_PR_METRICS = [
    "new_violations",
    "new_accepted_issues",
    "new_vulnerabilities",
    "new_security_issues",
    "new_security_hotspots",
    "new_coverage",
    "new_duplicated_lines_density",
    "new_lines",
]

_BRANCH_METRICS = [
    "coverage",
    "violations",
    "vulnerabilities",
    "security_issues",
    "security_hotspots",
    "reliability_rating",
    "security_rating",
    "sqale_rating",
    "duplicated_lines_density",
    "ncloc",
]

# Which way is good. `+1`: a rise is an improvement; `-1`: a rise is a regression. A metric absent
# from this map is neutral (`ncloc`) — it renders a plain arrow and never moves the trend counter.
# Ratings are Sonar's `1..5` with `1` = A, so a numeric rise is a downgrade.
_METRIC_POLARITY = {
    "coverage": 1,
    "violations": -1,
    "vulnerabilities": -1,
    "security_hotspots": -1,
    "duplicated_lines_density": -1,
    "reliability_rating": -1,
    "security_rating": -1,
    "sqale_rating": -1,
}


def extract_projects(check_runs: list[dict]) -> list[tuple[str, str]]:
    """Discover analysed Sonar projects from the head SHA's check runs.

    The project key is read from the SonarCloud check run's ``details_url``
    (``…/dashboard?id=NoNameItem_statuskit&pullRequest=112``), so monorepo projects each get
    their own block with no configuration.

    Returns:
        ``(project_key, dashboard_url)`` pairs, in first-seen order, deduplicated.
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for run in check_runs:
        if run.get("app_slug") != _SONAR_APP_SLUG:
            continue
        details_url = run.get("details_url") or ""
        query = urllib.parse.parse_qs(urllib.parse.urlparse(details_url).query)
        keys = query.get("id") or []
        if not keys or keys[0] in seen:
            continue
        seen.add(keys[0])
        found.append((keys[0], details_url))
    return found


def rating_letter(value: str | None) -> str:
    """Map Sonar's numeric rating (``"1".."5"``, sometimes ``"1.0"``) to ``A``..``E``."""
    if value is None:
        return "—"
    key = value.split(".")[0]
    return _RATINGS.get(key, value)


def format_measure(metric: str, value: str | None) -> str:
    """Format a raw measure value for display.

    Sonar omits metrics it did not evaluate (``new_coverage`` on a PR with nothing to measure —
    verified on #114); those render as ``—`` rather than a fake ``0.0%``.
    """
    if value is None or value == "":
        return "—"
    if metric.endswith("_rating"):
        return rating_letter(value)
    if metric in _PERCENT_METRICS:
        # A malformed value here must degrade this one row, not the whole notification: `main`
        # wraps the entire per-project loop in one `except Exception`, so an unguarded ValueError
        # would discard every other project's already-built blocks along with this one.
        try:
            return f"{float(value):.1f}%"
        except ValueError:
            return value
    # Counts come back as "1357" but sometimes "1357.0" — normalise to a plain integer.
    try:
        return str(int(float(value)))
    except ValueError:
        return value


def format_threshold(metric: str, comparator: str, threshold: str | None) -> str:
    """Render a gate condition's threshold the way a human reads it.

    ``LT`` means "error when actual is lower", so it displays as ``need ≥ X``; ``GT`` as
    ``need ≤ X``. Ratings are the special case: the numeric threshold becomes a letter.
    """
    if threshold is None:
        return ""
    if metric.endswith("_rating"):
        return f"need {rating_letter(threshold)}"
    suffix = "%" if metric in _PERCENT_METRICS else ""
    if comparator == "LT":
        return f"need ≥ {threshold}{suffix}"
    if comparator == "GT":
        return f"need ≤ {threshold}{suffix}"
    return f"need {threshold}{suffix}"


def format_breakdown(counts: dict) -> str:
    """Render a severity breakdown like ``"blocker 1, critical 7, minor 4"``.

    Accepts both the facet shape (classic severities) and the inline ``security_issues``
    payload (which also carries a ``total`` key). Zero counts are skipped, so the string is
    empty when there is nothing to break down.
    """
    parts = []
    for severity in _SEVERITY_ORDER:
        count = counts.get(severity)
        if isinstance(count, int) and count > 0:
            parts.append(f"{severity.lower()} {count}")
    return ", ".join(parts)


def delta_marker(metric: str, before: str | None, after: str | None) -> str:
    """``🟢`` / ``🔴`` for a metric whose direction means something, ``""`` otherwise.

    Telegram renders no colour except emoji — ``<span style="color:…">`` and friends are accepted
    by the Bot API and silently dropped — so the marker is the only way a row can be red or green,
    and ``<b>`` stays reserved for "this is a problem".
    """
    polarity = _METRIC_POLARITY.get(metric, 0)
    if not polarity or before is None or after is None:
        return ""
    # Must agree with `delta_cell`'s "no visible change" check, or the two can disagree: a percent
    # metric moving 93.44 -> 93.43 renders as the same "93.4%" in the table (`delta_cell` compares
    # the rendered text and short-circuits), but a raw `float(after) - float(before)` here is still
    # nonzero — so a row with no visible change fed a false regression into `trend_segment`'s title
    # and the block's `open` flag. Comparing the same rendered/rounded values `delta_cell` uses
    # makes that impossible.
    if format_measure(metric, before) == format_measure(metric, after):
        return ""
    try:
        change = float(after) - float(before)
    except ValueError:
        return ""
    if change == 0:
        return ""
    return "🟢" if change * polarity > 0 else "🔴"


def delta_cell(metric: str, before: str | None, after: str | None, after_text: str | None = None) -> str:
    """Render one delta row's right-hand cell.

    Four cases, in the order they are checked: one end of the window missing (current value, no
    arrow), unchanged (the value alone), changed with a polarity (``🟢 93.4% → 94.1%``), changed
    without one (``2121 → 2280``).

    ``after_text`` overrides the head's rendering so ``Issues`` can carry today's severity
    breakdown — Sonar exposes no history for facets, so a row reads "was 13, is 15, and here is
    what today's 15 consists of".
    """
    head_text = format_measure(metric, after)
    text = head_text if after_text is None else after_text
    if before in (None, "") or after in (None, ""):
        return text
    base_text = format_measure(metric, before)
    if base_text == head_text:
        return text
    marker = delta_marker(metric, before, after)
    return f"{marker} {base_text} → {text}" if marker else f"{base_text} → {text}"


def _count_with_breakdown(total: str | None, counts: dict) -> str:
    """``"13 (blocker 1, critical 7)"`` — or just the total when there is no breakdown."""
    if total is None or total == "":
        return "—"
    breakdown = format_breakdown(counts)
    return f"{total} ({breakdown})" if breakdown else total


def _parse_inline_counts(value: str | None) -> dict:
    """Parse the JSON payload Sonar returns inline for ``security_issues``-style metrics."""
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _link(text: str, url: str) -> dict:
    """The block's optional `link`, rendered as `<p><a>` after the table."""
    return {"text": text, "url": url}


def _overview_url(project: str, branch: str) -> str:
    """The project dashboard URL for a given branch, shared by the branch and release paths."""
    return f"{_API_BASE}/project/overview?id={urllib.parse.quote(project)}&branch={urllib.parse.quote(branch)}"


def build_gate_block(project: str, project_status: dict, dashboard_url: str) -> dict:
    """Build the quality-gate block from the API's ``conditions`` array.

    Collapsed when the gate passed, open when it failed; breached rows are bold. The row set is
    whatever the API returned for this PR — four conditions on a release PR is correct output,
    not missing data.
    """
    status = project_status.get("projectStatus", {})
    passed = status.get("status") == "OK"
    rows: list = []
    for condition in status.get("conditions", []):
        metric = condition.get("metricKey", "")
        failed = condition.get("status") == "ERROR"
        label = _CONDITION_LABELS.get(metric, metric.removeprefix("new_").replace("_", " ").capitalize())
        actual = format_measure(metric, condition.get("actualValue"))
        threshold = format_threshold(metric, condition.get("comparator", ""), condition.get("errorThreshold"))
        value = f"{actual} ({threshold})" if threshold else actual
        icon = "❌" if failed else "✅"
        rows.append([{"text": f"{icon} {label}", "bold": failed}, {"text": value, "bold": failed}])
    return {
        "type": "table",
        "title": f"Sonar · {project} — Quality Gate {'passed' if passed else 'failed'}",
        "open": not passed,
        "rows": rows,
        "link": _link("Dashboard", dashboard_url),
    }


def build_new_code_block(
    project: str,
    measures: dict,
    severities: dict,
    _dashboard_url: str,
    issues_url: str,
) -> dict:
    """Build the always-collapsed new-code block.

    Carries the figures Sonar puts in its PR comment plus the severity breakdown it does not
    provide — the part that makes a green gate honest. Never bold: this block reports, the gate
    block judges.

    ``_dashboard_url`` is accepted but unused: this block links to the filtered new-code issue
    list (``issues_url``), not the dashboard. Kept in the signature for positional symmetry with
    ``build_gate_block`` at the ``build_pr_blocks`` call site.
    """
    rows: list = [
        ["New issues", _count_with_breakdown(measures.get("new_violations"), severities)],
        ["Accepted issues", format_measure("new_accepted_issues", measures.get("new_accepted_issues"))],
        [
            "Vulnerabilities",
            _count_with_breakdown(
                measures.get("new_vulnerabilities"), _parse_inline_counts(measures.get("new_security_issues"))
            ),
        ],
        ["Coverage on new code", format_measure("new_coverage", measures.get("new_coverage"))],
        [
            "Duplication on new code",
            format_measure("new_duplicated_lines_density", measures.get("new_duplicated_lines_density")),
        ],
        ["New lines", format_measure("new_lines", measures.get("new_lines"))],
    ]
    # Hotspots are being folded into vulnerabilities upstream; show the row only while a
    # non-zero count still exists, so it disappears on its own as the migration completes.
    hotspots = measures.get("new_security_hotspots")
    if hotspots not in (None, "", "0"):
        rows.append(["Hotspots", format_measure("new_security_hotspots", hotspots)])
    return {
        "type": "table",
        "title": f"Sonar · {project} — new code",
        "open": False,
        "rows": rows,
        "link": _link("Issues on new code", issues_url),
    }


def build_branch_block(project: str, measures: dict, severities: dict, overview_url: str) -> dict:
    """Build the overall project-state block used by push and release notifications."""
    rows: list = [
        ["Coverage", format_measure("coverage", measures.get("coverage"))],
        ["Issues", _count_with_breakdown(measures.get("violations"), severities)],
        [
            "Vulnerabilities",
            _count_with_breakdown(
                measures.get("vulnerabilities"), _parse_inline_counts(measures.get("security_issues"))
            ),
        ],
        ["Reliability", format_measure("reliability_rating", measures.get("reliability_rating"))],
        ["Security", format_measure("security_rating", measures.get("security_rating"))],
        ["Maintainability", format_measure("sqale_rating", measures.get("sqale_rating"))],
        ["Duplication", format_measure("duplicated_lines_density", measures.get("duplicated_lines_density"))],
        ["Lines of code", format_measure("ncloc", measures.get("ncloc"))],
    ]
    hotspots = measures.get("security_hotspots")
    if hotspots not in (None, "", "0"):
        rows.append(["Hotspots", format_measure("security_hotspots", hotspots)])
    return {
        "type": "table",
        "title": f"Sonar · {project} — project state",
        "open": False,
        "rows": rows,
        "link": _link("Dashboard", overview_url),
    }


def trend_segment(markers: list[str]) -> str:
    """``"🔴 2 worse, 🟢 2 better"`` — the title's verdict, visible while the block is collapsed.

    Counts only markers, so neutral metrics (``ncloc``) never move it. Red leads because that is
    the part worth acting on; green is omitted at zero, and an unmoved release gets no segment.
    """
    worse = markers.count("🔴")
    better = markers.count("🟢")
    if worse:
        return f"🔴 {worse} worse, 🟢 {better} better" if better else f"🔴 {worse} worse"
    return f"🟢 {better} better" if better else ""


def build_release_delta_block(
    project: str,
    baseline_version: str,
    baseline: dict,
    head: dict,
    severities: dict,
    overview_url: str,
) -> dict:
    """Build the version-to-version delta block for a release notification.

    Same rows as ``build_branch_block`` — the reader of a release message and the reader of a push
    message care about the same metrics — but each value carries where it came from. Open when
    something regressed, so a red release cannot hide inside a collapsed block.

    Severity breakdowns are current-state only: Sonar has no history for facets.
    """
    cells: list[tuple[str, str, str | None]] = [
        ("Coverage", "coverage", None),
        ("Issues", "violations", _count_with_breakdown(head.get("violations"), severities)),
        (
            "Vulnerabilities",
            "vulnerabilities",
            _count_with_breakdown(head.get("vulnerabilities"), _parse_inline_counts(head.get("security_issues"))),
        ),
        ("Reliability", "reliability_rating", None),
        ("Security", "security_rating", None),
        ("Maintainability", "sqale_rating", None),
        ("Duplication", "duplicated_lines_density", None),
        ("Lines of code", "ncloc", None),
    ]
    # Unlike the other blocks, this one reads two ends of a history window rather than one live
    # snapshot, so "the row exists only while a non-zero count does" is ambiguous here: a missing
    # head point (`history_pair` never falls back to an older one — see its docstring) looks
    # identical to a confirmed zero if only `head` is consulted, and the row would vanish outright
    # instead of rendering "—" like every other metric does when its head end is unavailable. So
    # decide from both ends: keep the row whenever baseline data exists to show, even with the
    # head unresolved, and only fold it away when head reports a genuine zero with nothing at
    # baseline to fall back on either. (`build_branch_block`'s otherwise-identical check above has
    # no baseline to pair with — it is a single snapshot, not a window — so it is left alone.)
    baseline_hotspots, head_hotspots = baseline.get("security_hotspots"), head.get("security_hotspots")
    head_unavailable = head_hotspots in (None, "")
    if (not head_unavailable and head_hotspots != "0") or (head_unavailable and baseline_hotspots not in (None, "")):
        cells.append(("Hotspots", "security_hotspots", None))

    rows: list = []
    markers: list[str] = []
    for label, metric, after_text in cells:
        before, after = baseline.get(metric), head.get(metric)
        rows.append([label, delta_cell(metric, before, after, after_text)])
        markers.append(delta_marker(metric, before, after))

    trend = trend_segment(markers)
    title = f"Sonar · {project} — since {baseline_version}"
    return {
        "type": "table",
        "title": f"{title} · {trend}" if trend else title,
        "open": "🔴" in markers,
        "rows": rows,
        "link": _link("Dashboard", overview_url),
    }


def degraded_block(project: str, title: str, dashboard_url: str) -> dict:
    """Fallback block when the API is unreachable: the check run's title and a link, nothing else.

    There is deliberately no second parser — one path for the numbers, and a notification that
    never fails because of Sonar.
    """
    return {
        "type": "table",
        "title": f"Sonar · {project} — {title}",
        "open": False,
        "rows": [],
        "link": _link("Dashboard", dashboard_url),
    }


def fetch_json(url: str, token: str | None) -> dict | None:
    """GET a SonarCloud API URL. Returns the parsed body, or ``None`` on any failure."""
    headers = {"Accept": "application/json", "User-Agent": "sonar-pr-status"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 - SonarCloud API URL, not user input
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT) as response:  # noqa: S310 - same URL as above
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        print(f"Sonar API call failed ({url}): {exc}", file=sys.stderr)
        return None


def _api_url(path: str, params: dict[str, str]) -> str:
    return f"{_API_BASE}/api/{path}?{urllib.parse.urlencode(params)}"


def _scope_params(pull_request: str | None, branch: str | None) -> dict[str, str]:
    """Sonar addresses a PR analysis with ``pullRequest`` and a branch one with ``branch``."""
    if pull_request:
        return {"pullRequest": pull_request}
    return {"branch": branch} if branch else {}


def _fetch_measures(project: str, metrics: list[str], scope: dict[str, str], token: str | None) -> dict:
    """Fetch measures, reading the new-code value from `periods` when `value` is absent.

    New-code metrics are sometimes returned only inside `periods` — falling back keeps
    `Coverage on new code` from rendering as `—` when Sonar did measure it.
    """
    params = {"component": project, "metricKeys": ",".join(metrics), **scope}
    payload = fetch_json(_api_url("measures/component", params), token)
    if not payload:
        return {}
    measures = {}
    for measure in payload.get("component", {}).get("measures", []):
        metric = measure.get("metric")
        if not metric:
            continue
        value = measure.get("value")
        if value is None and measure.get("periods"):
            value = measure["periods"][0].get("value")
        if value is not None:
            measures[metric] = value
    return measures


def _fetch_severities(project: str, scope: dict[str, str], token: str | None, new_code: bool) -> dict:
    params = {"componentKeys": project, "ps": "1", "facets": "severities", "resolved": "false", **scope}
    if new_code:
        params["inNewCodePeriod"] = "true"
    payload = fetch_json(_api_url("issues/search", params), token)
    if not payload:
        return {}
    for facet in payload.get("facets", []):
        if facet.get("property") == "severities":
            return {entry["val"]: entry["count"] for entry in facet.get("values", [])}
    return {}


# Analyses accumulate on `master` between releases; `pick_baseline` scans the full list for the
# previous release's VERSION event, so a single page is not enough once more than one page's worth
# of analyses has landed since then — the event falls outside the window and the delta block
# silently degrades to the absolute one (see module docstring). Page size matches Sonar's own cap.
_ANALYSES_PAGE_SIZE = 100

# Hard cap on pagination, mirroring `publish_badges.fetch_jobs`: bounds a misbehaving API or an
# ever-growing history instead of looping forever. 20 pages * 100 analyses = 2000, comfortably
# above anything a real release window holds.
_MAX_ANALYSIS_PAGES = 20


def fetch_analyses(
    project: str,
    branch: str,
    token: str | None,
    max_pages: int = _MAX_ANALYSIS_PAGES,
) -> list[dict]:
    """Fetch up to `max_pages` pages of the branch's analysis history, newest first.

    `max_pages` exists for `wait_for_analysis`'s poll loop: Sonar returns analyses newest-first, so
    the release commit's analysis is on page 1 the instant it exists, and that loop can tick up to
    41 times over the ten-minute ceiling. Walking the full (potentially `_MAX_ANALYSIS_PAGES` x
    `_ANALYSES_PAGE_SIZE`-deep) history on every tick would multiply request volume for no benefit
    and risk SonarCloud rate-limiting, so the loop passes `max_pages=1` and the default here stays
    the full cap for every other caller (including `wait_for_analysis`'s own post-loop re-fetch).

    Unlike `publish_badges.fetch_jobs`, hitting the cap must never raise: every Sonar failure in
    this file degrades instead of propagating past `main`'s per-project `except Exception` (see
    module docstring). The stderr note about a truncated walk only fires when `max_pages` is the
    full default — an intentional partial fetch (`max_pages=1`) truncating is normal, not a
    degradation worth reporting.

    ``[]`` when Sonar has no such project.
    """
    analyses: list[dict] = []
    page = 1
    while page <= max_pages:
        params = {"project": project, "branch": branch, "ps": str(_ANALYSES_PAGE_SIZE), "p": str(page)}
        payload = fetch_json(_api_url("project_analyses/search", params), token)
        if not payload:
            break
        batch = payload.get("analyses", [])
        analyses.extend(batch)
        # Sonar's `paging.total` is the authoritative stop signal when present, but a short page
        # (or an empty one) ends the walk just as well and works even if `paging` is absent.
        total = (payload.get("paging") or {}).get("total")
        if total is not None and len(analyses) >= total:
            break
        if len(batch) < _ANALYSES_PAGE_SIZE:
            break
        page += 1
    else:
        if max_pages >= _MAX_ANALYSIS_PAGES:
            print(
                f"Sonar analysis pagination for {project} hit the {max_pages}-page cap; "
                f"returning the {len(analyses)} analyses collected so far.",
                file=sys.stderr,
            )
    return analyses


def fetch_history(
    project: str, branch: str, metrics: list[str], from_date: str, token: str | None
) -> dict[str, list[dict]]:
    """Fetch each metric's dated points from the baseline date onwards.

    One call covers both ends of the window. ``ps=1000`` because the window holds one point per
    analysis on ``master``, and a release cycle can easily hold a hundred.
    """
    params = {
        "component": project,
        "branch": branch,
        "metrics": ",".join(metrics),
        "from": from_date,
        "ps": "1000",
    }
    payload = fetch_json(_api_url("measures/search_history", params), token)
    if not payload:
        return {}
    return {
        measure["metric"]: measure.get("history", [])
        for measure in payload.get("measures", [])
        if measure.get("metric")
    }


def history_pair(points: list[dict], baseline_date: str, head_date: str) -> tuple[str | None, str | None]:
    """``(baseline value, head value)`` for one metric's points.

    Only the point dated exactly ``head_date`` counts as the head value. ``head_date`` is always
    the head analysis's own date (``build_release_blocks`` sets it from the matched revision, or
    from ``analyses[0]`` on a timed-out wait), so a miss here means Sonar has no value for this
    metric at that analysis, not that we asked for the wrong date. Falling back to an older point
    would present a stale value as current, so a metric with no point at either end returns
    ``None`` there and the row renders without an arrow.
    """
    by_date = {point.get("date"): point.get("value") for point in points}
    return by_date.get(baseline_date), by_date.get(head_date)


def split_history(history: dict[str, list[dict]], baseline_date: str, head_date: str) -> tuple[dict, dict]:
    """Turn the per-metric point lists into the two ``{metric: value}`` maps the block renders."""
    baseline: dict = {}
    head: dict = {}
    for metric, points in history.items():
        before, after = history_pair(points, baseline_date, head_date)
        if before is not None:
            baseline[metric] = before
        if after is not None:
            head[metric] = after
    return baseline, head


def revision_matches(stored: str | None, wanted: str | None) -> bool:
    """Compare a commit stored by Sonar with the one we are looking for.

    Sonar stores the full 40-character SHA and ``GITHUB_SHA`` is full too, but a hand-run
    ``--revision dab4b1f`` must match as well — so a prefix of at least 7 characters counts.
    """
    if not stored or not wanted:
        return False
    shorter, longer = sorted((stored, wanted), key=len)
    return len(shorter) >= _MIN_SHORT_SHA_LEN and longer.startswith(shorter)


def version_event(analysis: dict) -> str | None:
    """The name of the analysis's ``VERSION`` event, if it carries one."""
    for event in analysis.get("events", []):
        if event.get("category") == "VERSION":
            return event.get("name")
    return None


def find_analysis(analyses: list[dict], revision: str) -> dict | None:
    """The analysis produced from ``revision`` — the release commit, on a release run."""
    for analysis in analyses:
        if revision_matches(analysis.get("revision"), revision):
            return analysis
    return None


def wait_for_analysis(
    project: str,
    branch: str,
    revision: str,
    token: str | None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[dict], dict | None]:
    """Poll until the release commit's analysis appears in Sonar.

    Returns ``(analyses, head)``. ``analyses`` is always the FULL paginated history — that is what
    `pick_baseline` scans for the previous release's `VERSION` event, so it must include pages
    beyond wherever `head` happened to be found. Reaching the ceiling no longer guarantees
    ``head`` is ``None``: the poll loop only ever inspects page 1, so a revision that never
    surfaced there can still be sitting deeper in the full paginated history fetched once the loop
    gives up, and that deeper history is checked before conceding. ``head`` is ``None`` only when
    the revision is absent from that full history too — the caller then falls back to the latest
    analysis, which is a smaller lie than no notification.

    Each poll tick fetches only page 1 (`fetch_analyses(..., max_pages=1)`): Sonar returns analyses
    newest-first, so the release commit's analysis appears on page 1 the instant it exists, and
    this loop can tick up to 41 times over the ten-minute ceiling. Paginating the whole history on
    every tick would multiply request volume for no benefit and risk SonarCloud rate-limiting. The
    full, unbounded pagination happens after the loop resolves either way — found or timed out —
    solely to build the list `pick_baseline` needs, plus at most one earlier probe (below) when a
    tick's page 1 comes back empty.

    An empty page-1 response no longer ends the wait immediately by itself: `fetch_json` returns
    ``[]`` both when the project genuinely has no analyses in Sonar (a ``flow`` release, an outage)
    and when that single request merely blipped (a transient 5xx or timeout), and page 1 alone
    cannot tell the two apart. The first time any tick's page 1 comes back empty, one full
    paginated fetch (`fetch_analyses` with the default, unbounded `max_pages`) probes deeper before
    conceding. Only when that probe is *also* empty do we give up on the spot — the project is
    demonstrably absent from Sonar or the API is down, and neither is fixed by waiting ten minutes.
    A non-empty probe proves the API is alive, so the wait keeps polling instead of bailing out,
    even if the probe itself does not contain the wanted revision yet (see below).

    ``sleep`` is injected so tests do not actually wait.
    """
    attempts = int(_POLL_CEILING_SECONDS // _POLL_INTERVAL_SECONDS)
    found = False
    # Set once the deep probe below has proven the project exists in Sonar. Kept across ticks so a
    # later empty page 1 is treated as just another transient miss instead of re-running the probe
    # (up to `_MAX_ANALYSIS_PAGES` requests) on every one of the up to 41 ticks in the ceiling.
    project_seen = False
    for attempt in range(attempts + 1):
        page_one = fetch_analyses(project, branch, token, max_pages=1)
        if not page_one:
            if not project_seen:
                # A one-shot deep probe: page 1 alone cannot distinguish "no analyses exist" from
                # "this one request blipped", so fall back to the full paginated history before
                # conceding. One-shot because the probe is up to `_MAX_ANALYSIS_PAGES` requests —
                # affordable once, but repeating it on every empty-page-1 tick would multiply
                # request volume for no benefit and risk SonarCloud rate-limiting.
                analyses = fetch_analyses(project, branch, token)
                if not analyses:
                    return [], None
                project_seen = True
                deep_match = find_analysis(analyses, revision)
                if deep_match is not None:
                    return analyses, deep_match
                # The probe proved the project exists (non-empty) but the revision is not in it
                # yet: the empty page 1 was a transient blip, not evidence the analysis is missing.
                # Conceding here would hand `build_release_blocks` the latest analysis — another
                # revision's metrics — just because one request blipped, so keep polling instead.
            if attempt < attempts:
                sleep(_POLL_INTERVAL_SECONDS)
            continue
        if find_analysis(page_one, revision) is not None:
            found = True
            break
        if attempt < attempts:
            sleep(_POLL_INTERVAL_SECONDS)

    # The full re-fetch happens after polling ends, so a `head` found on page 1 earlier can be a
    # stale object — new analyses may have landed on `master` between that tick and this call. Look
    # it up fresh in the final list rather than reusing it: `build_release_blocks`'s
    # `analyses.index(head)` requires `head` to be an element of `analyses`, and re-finding it here
    # is what guarantees that (instead of raising `ValueError` on an object no longer present).
    analyses = fetch_analyses(project, branch, token)
    if not found:
        # The poll loop only ever inspected page 1 (`max_pages=1` above), so the revision may
        # simply have been sitting beyond the newest 100 records the whole time. This full,
        # unbounded list is strictly more evidence than any single poll tick had — checking it
        # before giving up is required, or we would discard a real match and report another
        # revision's metrics (`build_release_blocks` falls back to `analyses[0]`, the latest
        # analysis, whenever `head` is ``None``).
        deep_match = find_analysis(analyses, revision)
        if deep_match is not None:
            return analyses, deep_match
        print(
            f"No Sonar analysis for revision {revision} after {_POLL_CEILING_SECONDS:.0f}s; "
            f"falling back to the latest analysis.",
            file=sys.stderr,
        )
        return analyses, None
    return analyses, find_analysis(analyses, revision)


def pick_baseline(analyses: list[dict], released_version: str) -> dict | None:
    """The previous release's analysis — the left edge of the delta window.

    ``analyses`` must start at the head analysis (newest first), so a baseline is never picked
    from an analysis newer than the release. The newest ``VERSION`` event wins, except:

    * the released version itself — that is the head, not a baseline;
    * ``"not provided"`` — a real event name written by analyses from before
      ``sonar.projectVersion`` was seeded (2026-07-31), not an absent field.

    ``None`` means the project has no comparable earlier release; the caller degrades to absolute
    values.
    """
    for analysis in analyses:
        name = version_event(analysis)
        if name and name not in (released_version, _NO_VERSION):
            return analysis
    return None


def build_pr_blocks(
    project: str, dashboard_url: str, pull_request: str, token: str | None, fallback: str
) -> list[dict]:
    """Gate block + new-code block for one project, degrading to the check-run title."""
    scope = _scope_params(pull_request, None)
    status = fetch_json(_api_url("qualitygates/project_status", {"projectKey": project, **scope}), token)
    if not status:
        return [degraded_block(_short_name(project), fallback, dashboard_url)]
    short = _short_name(project)
    measures = _fetch_measures(project, _PR_METRICS, scope, token)
    severities = _fetch_severities(project, scope, token, new_code=True)
    issues_url = (
        _API_BASE
        + "/project/issues?"
        + urllib.parse.urlencode(
            {"id": project, "pullRequest": pull_request, "issueStatuses": "OPEN,CONFIRMED", "sinceLeakPeriod": "true"}
        )
    )
    return [
        build_gate_block(short, status, dashboard_url),
        build_new_code_block(short, measures, severities, dashboard_url, issues_url),
    ]


def build_branch_blocks(project: str, branch: str, token: str | None) -> list[dict]:
    """Project-state block for one project. Returns ``[]`` when the project is not in Sonar."""
    scope = _scope_params(None, branch)
    measures = _fetch_measures(project, _BRANCH_METRICS, scope, token)
    if not measures:
        return []
    severities = _fetch_severities(project, scope, token, new_code=False)
    overview_url = _overview_url(project, branch)
    return [build_branch_block(_short_name(project), measures, severities, overview_url)]


def build_release_blocks(
    project: str,
    branch: str,
    version: str,
    revision: str,
    token: str | None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict]:
    """Gate block + version-to-version delta block for one released project.

    The gate is the same one the PR path shows: the new-code period on ``master`` is
    ``previous_version``, so it judges precisely the code this release adds. The delta is about
    the whole project — two coordinate systems, two blocks.

    Every failure narrows the output instead of raising: see the design's degradation table.
    """
    scope = _scope_params(None, branch)
    short = _short_name(project)
    overview_url = _overview_url(project, branch)

    analyses, head = wait_for_analysis(project, branch, revision, token, sleep)
    if head is None and analyses:
        head = analyses[0]

    body: list[dict] = []
    if head is not None and analyses:
        head_date = head.get("date")
        baseline = pick_baseline(analyses[analyses.index(head) :], version)
        baseline_date = baseline.get("date") if baseline is not None else None
        # A baseline whose date equals the head's is no baseline at all. On the timed-out wait
        # path `head` falls back to `analyses[0]`, and `pick_baseline` is handed a slice that
        # starts at that same head — so it can return the head's own analysis (e.g. no push
        # landed between the previous release and this one). Without this guard the window
        # collapses to a single point and the block renders "since <version>" with every row
        # reported unchanged, passing off the previous release's numbers as this one's. `.get`
        # also means a malformed analysis record (missing "date") degrades the same way instead
        # of raising past the per-project loop in `main`.
        if baseline is not None and baseline_date is not None and head_date is not None and baseline_date != head_date:
            history = fetch_history(project, branch, _BRANCH_METRICS, baseline_date, token)
            if history:
                baseline_measures, head_measures = split_history(history, baseline_date, head_date)
                severities = _fetch_severities(project, scope, token, new_code=False)
                body = [
                    build_release_delta_block(
                        short,
                        version_event(baseline) or "",
                        baseline_measures,
                        head_measures,
                        severities,
                        overview_url,
                    )
                ]
    if not body:
        # No baseline, no history, or no analyses at all — today's absolute block is the same
        # rendering a project's first release gets, so it needs no "unavailable" presentation.
        body = build_branch_blocks(project, branch, token)
    if not body:
        return []

    status = fetch_json(_api_url("qualitygates/project_status", {"projectKey": project, **scope}), token)
    gate = [build_gate_block(short, status, overview_url)] if status else []
    return gate + body


def _short_name(project_key: str) -> str:
    """``NoNameItem_statuskit`` -> ``statuskit`` (the name a human recognises)."""
    return project_key.split("_", 1)[-1]


def main() -> int:
    """CLI entrypoint. Always returns 0 — no Sonar data is a valid outcome."""
    parser = argparse.ArgumentParser(description="Build Sonar blocks for a Telegram notification.")
    parser.add_argument("--mode", choices=["pr", "branch", "release"], required=True)
    parser.add_argument("--pr", default=None, help="PR number (mode=pr).")
    parser.add_argument("--branch", default="master", help="Branch name (mode=branch|release).")
    parser.add_argument("--check-runs-file", default=None, help="JSON file with the head SHA's check runs (mode=pr).")
    parser.add_argument("--project-keys", default=None, help="JSON array, e.g. '[\"NoNameItem_statuskit\"]'.")
    parser.add_argument("--version", default="", help="Released version (mode=release).")
    parser.add_argument("--revision", default="", help="Commit SHA the release tag points at (mode=release).")
    args = parser.parse_args()
    if args.mode == "release":
        if not args.version:
            parser.error("--version is required when --mode release")
        if not args.revision:
            parser.error("--revision is required when --mode release")

    token = os.environ.get("SONAR_TOKEN") or None
    blocks: list[dict] = []

    try:
        if args.mode == "pr":
            check_runs = []
            if args.check_runs_file:
                with open(args.check_runs_file) as handle:  # noqa: PTH123 - one-off read, no Path object needed
                    check_runs = json.load(handle)
            titles = {
                key: run.get("output_title") or "Quality Gate"
                for run in check_runs
                if run.get("app_slug") == _SONAR_APP_SLUG
                for key, _ in extract_projects([run])
            }
            for project, dashboard_url in extract_projects(check_runs):
                blocks.extend(
                    build_pr_blocks(project, dashboard_url, args.pr, token, titles.get(project, "Quality Gate"))
                )
        elif args.mode == "release":
            keys = json.loads(args.project_keys) if args.project_keys else []
            for project in keys:
                blocks.extend(build_release_blocks(project, args.branch, args.version, args.revision, token))
        else:
            keys = json.loads(args.project_keys) if args.project_keys else []
            for project in keys:
                blocks.extend(build_branch_blocks(project, args.branch, token))
    except Exception as exc:
        print(f"Sonar block assembly failed: {exc}", file=sys.stderr)
        blocks = []

    print(json.dumps(blocks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
