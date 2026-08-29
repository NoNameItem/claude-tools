#!/usr/bin/env python3
"""Judge a release-please PR by the Sonar state of the component it releases.

The merge gate looks at new code only, deliberately (see the quality-gate design, D3), and
`python-ci` — with it the scanner — is skipped for `release-please--*` branches, so nothing else in
a release run looks at accumulated debt. This script is that check.

It never reads "the branch's current status": a scan of the push this release was cut from may
still be running, and the branch would answer with the previous commit's verdict. It resolves an
analysis that judges exactly the released code and reads THAT analysis's verdict instead.

Unlike `sonar_pr_status.py`, which must never fail a job, this script is a gate: no data means
exit 1.

Usage:
    python3 sonar_release_gate.py \
        --head-ref release-please--branches--master--components--statuskit \
        --base-sha 0123456789abcdef0123456789abcdef01234567

Environment variables:
    SONAR_TOKEN           Optional. Public projects answer anonymously.
    GITHUB_STEP_SUMMARY   Optional. The report is appended when present.

Exit codes:
    0  the gate passed, or the component is not analysed by SonarCloud
    1  the gate failed, Sonar did not answer, or no analysis covers the released code
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

try:  # The scripts run both as files (`python3 .github/scripts/…`) and as a package under pytest.
    from .projects import discover_projects
except ImportError:
    from projects import discover_projects  # type: ignore[unresolved-import] - runtime sys.path in script mode

try:
    # `_api_url` is imported rather than re-derived so both scripts keep one API base URL.
    from .sonar_pr_status import _api_url, fetch_analyses, fetch_json, format_measure, format_threshold
except ImportError:
    from sonar_pr_status import (  # type: ignore[unresolved-import] - runtime sys.path in script mode
        _api_url,
        fetch_analyses,
        fetch_json,
        format_measure,
        format_threshold,
    )

if TYPE_CHECKING:
    from collections.abc import Callable

# Sonar being unreachable is not a statement about code quality, so the gate retries before it
# refuses (design D5).
_API_ATTEMPTS = 3
_API_BACKOFF_SECONDS = 5.0

_STATUS_ICON = {"OK": "✅", "ERROR": "❌"}

# release-please's branch naming, fixed by `separate-pull-requests: true` in release-please-config.json.
_RELEASE_REF_PREFIX = "release-please--"
_RELEASE_REF_MARKER = "--components--"

# The project-type name `projects.py` reports for a Python package; only those are analysed by Sonar.
_SONAR_PROJECT_KIND = "python"

# SonarCloud project keys in this organisation.
_PROJECT_KEY_PREFIX = "NoNameItem_"

# The poll that closes the race between a master scan and this job (design D3). Same cadence and
# ceiling as `sonar_pr_status.wait_for_analysis`, for the same reason: a scan takes tens of seconds
# once the push's tests finish, and ten minutes is generous enough that reaching it means the push
# CI is broken rather than slow.
_POLL_INTERVAL_SECONDS = 15.0
_POLL_CEILING_SECONDS = 600.0


@dataclass(frozen=True)
class ReleaseTarget:
    """What a release PR releases, in the terms this check needs."""

    component: str
    project_key: str
    path: str


@dataclass(frozen=True)
class GateError:
    """A reason `main` must fail closed (D5), distinct from a legitimate skip."""

    message: str


def component_from_ref(head_ref: str) -> str | None:
    """``release-please--branches--master--components--statuskit`` -> ``statuskit``.

    The head ref answers "what is being released"; `detect` answers "what changed". They coincide
    on a release PR only because release-please happens to touch just that component's files.
    """
    if not head_ref.startswith(_RELEASE_REF_PREFIX):
        return None
    _, _, component = head_ref.partition(_RELEASE_REF_MARKER)
    return component or None


def resolve_target(component: str, repo_root: Path) -> ReleaseTarget | None:
    """The Sonar project for a released component, or ``None`` when it has none.

    ``None`` covers two different situations that `main` must not treat alike: a component that
    exists but is not a Python package (e.g. `flow` — a legitimate skip), and a component this repo
    does not know at all (a renamed package, a stale `release-please-config.json`, a broken
    checkout — fail-closed material under D5). Telling them apart means asking `discover_projects`
    directly rather than through this function; see `main`.
    """
    project = discover_projects(repo_root).get(component)
    if project is None or project.kind != _SONAR_PROJECT_KIND:
        return None
    return ReleaseTarget(
        component=component,
        project_key=f"{_PROJECT_KEY_PREFIX}{component}",
        path=project.path,
    )


def resolve_component(head_ref: str, repo_root: Path) -> str | GateError:
    """The released component named by ``head_ref``, or why it cannot be resolved.

    Both failure cases fail closed (D5): a ref with no component marker at all, and a component
    this repo does not recognise (a renamed package, a stale `release-please-config.json`, a
    broken checkout). The second is kept distinct from `resolve_target`'s "no Sonar project"
    `None`, which the caller must treat as a legitimate skip for a known non-Python component
    (`flow`), not as missing data.
    """
    component = component_from_ref(head_ref)
    if component is None:
        return GateError(f"Cannot tell what is being released from head ref '{head_ref}'.")
    if component not in discover_projects(repo_root):
        return GateError(f"Component `{component}` is not a known package or plugin in this repository.")
    return component


def is_ancestor(revision: str, base_sha: str, repo_root: Path) -> bool:
    """Is ``revision`` reachable from the release base?

    An analysis of a commit that landed AFTER the base judges code this release does not contain.
    A revision the clone does not know (git exits 128) is not usable either, and lands here as
    ``False``.
    """
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", revision, base_sha],  # noqa: S607 - git from PATH, as elsewhere here
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def package_changed_between(revision: str, base_sha: str, path: str, repo_root: Path) -> bool:
    """Did anything Sonar analyses change between the analysed commit and the released one?

    ``path`` is the package directory, which is exactly what makes `push.yml` run the scanner for
    this project — tooling-only changes route to the info-only call, which skips Sonar, so they
    correctly do not count as staleness (design D4).

    A tree comparison (``git diff``), not a history walk (``git log``): the question is "do the two
    trees differ under ``path``", and a commit-plus-revert pair or merge-commit history
    simplification can make `git log` answer "changed" for a tree that did not (harmless here —
    it is the conservative direction — but needless and more expensive than asking directly).
    """
    result = subprocess.run(
        ["git", "diff", "--quiet", revision, base_sha, "--", path],  # noqa: S607 - git from PATH, as elsewhere here
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    return result.returncode != 0


def pick_analysis(
    analyses: list[dict],
    base_sha: str,
    path: str,
    repo_root: Path,
    rejected: set[str] | None = None,
) -> dict | None:
    """The newest analysis that judges the released state of ``path``, or ``None``.

    Both conditions are required: the analysed revision is an ancestor of the release base, and
    nothing under ``path`` changed between it and that base. The second is what makes a still
    running scan visible as "not usable yet" and, at the same time, keeps an older analysis valid
    when master merely moved ahead on docs or plugins.

    ``rejected``, when given, is a set of revisions already known to fail either check. The pair
    ``(revision, base_sha)`` is fixed for the lifetime of one poll, so a revision rejected once can
    never become usable — only a new analysis at the top of the list can change the answer. The
    caller carries this set across poll ticks so `is_ancestor`/`package_changed_between` are not
    re-run for revisions already ruled out.
    """
    for analysis in analyses:
        revision = analysis.get("revision")
        if not revision or revision in (rejected if rejected is not None else ()):
            continue
        if not is_ancestor(revision, base_sha, repo_root):
            if rejected is not None:
                rejected.add(revision)
            continue
        if package_changed_between(revision, base_sha, path, repo_root):
            if rejected is not None:
                rejected.add(revision)
            continue
        return analysis
    return None


def wait_for_release_analysis(
    target: ReleaseTarget,
    branch: str,
    token: str | None,
    base_sha: str,
    repo_root: Path,
    sleep: Callable[[float], None] = time.sleep,
) -> dict | None:
    """Poll page 1 of the branch's analyses until one of them judges the released code.

    Page 1 is enough: Sonar returns analyses newest-first, so a scan that finishes mid-wait appears
    there the instant it exists. ``sleep`` is injected so tests do not actually wait.
    """
    attempts = int(_POLL_CEILING_SECONDS // _POLL_INTERVAL_SECONDS)
    rejected: set[str] = set()
    first_tick = True
    for attempt in range(attempts + 1):
        analyses = fetch_analyses(target.project_key, branch, token, max_pages=1)
        if first_tick and not analyses:
            print(
                f"{target.project_key} has no analyses on {branch} — the project may not exist in SonarCloud yet.",
                file=sys.stderr,
            )
        first_tick = False
        found = pick_analysis(analyses, base_sha, target.path, repo_root, rejected)
        if found is not None:
            return found
        if attempt < attempts:
            print(
                f"No analysis of {branch} covers {base_sha[:7]} yet; retrying in {_POLL_INTERVAL_SECONDS:.0f}s.",
                file=sys.stderr,
            )
            sleep(_POLL_INTERVAL_SECONDS)
    return None


def fetch_status(analysis_id: str, token: str | None, sleep: Callable[[float], None] = time.sleep) -> dict | None:
    """The stored quality-gate verdict of one analysis, or ``None`` when Sonar never answered.

    Addressing the analysis by id is what makes the answer immune to a scan finishing mid-run: a
    branch-scoped query would silently switch to the newer analysis (design D3).
    """
    url = _api_url("qualitygates/project_status", {"analysisId": analysis_id})
    for attempt in range(_API_ATTEMPTS):
        payload = fetch_json(url, token)
        if payload:
            return payload.get("projectStatus")
        if attempt < _API_ATTEMPTS - 1:
            sleep(_API_BACKOFF_SECONDS * (attempt + 1))
    return None


def render_report(status: dict, analysis: dict, project_key: str) -> str:
    """The Markdown report for the step summary — one row per gate condition.

    Release PRs are silent in Telegram by design, so this table is the only place a human reads
    the verdict without opening SonarCloud.
    """
    revision = (analysis.get("revision") or "")[:7]
    conditions = status.get("conditions", [])
    date = analysis.get("date") or "unknown date"
    gate_status = status.get("status", "UNKNOWN")
    lines = [
        f"### Sonar release gate — {project_key}",
        "",
        f"Analysis `{revision}` · {date} · gate **{gate_status}** · {len(conditions)} conditions",
        "",
        "| Condition | Threshold | Actual | |",
        "| --- | --- | --- | --- |",
    ]
    for condition in conditions:
        metric = condition.get("metricKey", "")
        threshold = format_threshold(metric, condition.get("comparator", ""), condition.get("errorThreshold"))
        actual = format_measure(metric, condition.get("actualValue"))
        icon = _STATUS_ICON.get(condition.get("status", ""), "•")
        lines.append(f"| `{metric}` | {threshold} | {actual} | {icon} |")
    return "\n".join(lines)


def emit(text: str) -> None:
    """Print to the log and, when running in Actions, append to the step summary."""
    print(text)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(f"{text}\n")


def main() -> int:
    """CLI entrypoint. Returns 0 only when the gate passed or the component is not in Sonar."""
    parser = argparse.ArgumentParser(description="Fail a release PR when master's Sonar state is not releasable.")
    parser.add_argument("--head-ref", required=True, help="The release PR's head ref.")
    parser.add_argument("--base-sha", required=True, help="The PR's base commit on the release branch.")
    parser.add_argument("--branch", default="master", help="Branch analysed in Sonar.")
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root)
    component = resolve_component(args.head_ref, repo_root)
    if isinstance(component, GateError):
        print(f"::error::{component.message}")
        return 1

    target = resolve_target(component, repo_root)
    if target is None:
        emit(f"Component `{component}` is not analysed by SonarCloud — nothing to check.")
        return 0

    token = os.environ.get("SONAR_TOKEN") or None
    analysis = wait_for_release_analysis(target, args.branch, token, args.base_sha, repo_root)
    if analysis is None:
        print(
            f"::error::No SonarCloud analysis of {args.branch} covers the release base "
            f"{args.base_sha[:7]} after {_POLL_CEILING_SECONDS:.0f}s — master's analysis is missing or stale."
        )
        return 1

    analysis_key = analysis.get("key", "")
    if not analysis_key:
        print(f"::error::The resolved analysis of {args.branch} carries no key; cannot ask SonarCloud for its verdict.")
        return 1

    status = fetch_status(analysis_key, token)
    if status is None:
        print("::error::SonarCloud did not answer; the release gate does not pass on missing data.")
        return 1

    emit(render_report(status, analysis, target.project_key))
    for condition in status.get("conditions", []):
        if condition.get("status") != "ERROR":
            continue
        metric = condition.get("metricKey", "")
        actual = format_measure(metric, condition.get("actualValue"))
        threshold = format_threshold(metric, condition.get("comparator", ""), condition.get("errorThreshold"))
        print(f"::error::{metric}: {actual} ({threshold})")

    return 0 if status.get("status") == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
