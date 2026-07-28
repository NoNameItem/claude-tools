#!/usr/bin/env python3
"""Build render-ready Sonar blocks for a Telegram CI notification.

Two shapes, both emitted as `table` blocks in the notify-spec contract:

* ``--mode pr``     — per project: the quality gate (from ``conditions``, so a gate that gains
  a condition shows up with no code change) plus a new-code summary with a severity breakdown
  Sonar's own comment does not provide.
* ``--mode branch`` — per project: the overall state of the branch. New-code metrics on
  ``master`` are meaningless until ``sonar.projectVersion`` has seeded a new-code period, and
  accumulated problems (e.g. a BLOCKER vulnerability) are only visible in the overall state.

Data comes from the SonarCloud Web API, never from the check run's markdown ``output.summary``:
the API is a documented contract and carries the gate thresholds and per-condition status that
the markdown only implies through image filenames.

The script never raises out of ``main``: on any API failure it degrades to the check run's
``output.title`` alone, and on total failure prints ``[]``. A Sonar outage must cost detail,
not the notification.

Usage:
    python3 sonar_pr_status.py --mode pr --pr 118 --check-runs-file runs.json
    python3 sonar_pr_status.py --mode branch --branch master --project-keys '["NoNameItem_statuskit"]'

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
import urllib.error
import urllib.parse
import urllib.request

_API_BASE = "https://sonarcloud.io"
_REQUEST_TIMEOUT = 30.0
_SONAR_APP_SLUG = "sonarqubecloud"

_RATINGS = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}

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
        return f"{float(value):.1f}%"
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
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT) as response:  # noqa: S310
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
    overview_url = f"{_API_BASE}/project/overview?id={urllib.parse.quote(project)}&branch={urllib.parse.quote(branch)}"
    return [build_branch_block(_short_name(project), measures, severities, overview_url)]


def _short_name(project_key: str) -> str:
    """``NoNameItem_statuskit`` -> ``statuskit`` (the name a human recognises)."""
    return project_key.split("_", 1)[-1]


def main() -> int:
    """CLI entrypoint. Always returns 0 — no Sonar data is a valid outcome."""
    parser = argparse.ArgumentParser(description="Build Sonar blocks for a Telegram notification.")
    parser.add_argument("--mode", choices=["pr", "branch"], required=True)
    parser.add_argument("--pr", default=None, help="PR number (mode=pr).")
    parser.add_argument("--branch", default="master", help="Branch name (mode=branch).")
    parser.add_argument("--check-runs-file", default=None, help="JSON file with the head SHA's check runs (mode=pr).")
    parser.add_argument("--project-keys", default=None, help="JSON array, e.g. '[\"NoNameItem_statuskit\"]'.")
    args = parser.parse_args()

    token = os.environ.get("SONAR_TOKEN") or None
    blocks: list[dict] = []

    try:
        if args.mode == "pr":
            check_runs = []
            if args.check_runs_file:
                with open(args.check_runs_file) as handle:  # noqa: PTH123
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
