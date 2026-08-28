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

import subprocess
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

try:  # The scripts run both as files (`python3 .github/scripts/…`) and as a package under pytest.
    from .projects import discover_projects
except ImportError:
    from projects import discover_projects  # type: ignore[unresolved-import]

try:
    from .sonar_pr_status import fetch_analyses
except ImportError:
    from sonar_pr_status import fetch_analyses  # type: ignore[unresolved-import]

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

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
    """The Sonar project for a released component, or ``None`` when it has none (e.g. `flow`)."""
    project = discover_projects(repo_root).get(component)
    if project is None or project.kind != _SONAR_PROJECT_KIND:
        return None
    return ReleaseTarget(
        component=component,
        project_key=f"{_PROJECT_KEY_PREFIX}{component}",
        path=project.path,
    )


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
    """
    result = subprocess.run(
        ["git", "log", "--oneline", f"{revision}..{base_sha}", "--", path],  # noqa: S607 - git from PATH
        cwd=repo_root,
        capture_output=True,
        check=True,
        text=True,
    )
    return bool(result.stdout.strip())


def pick_analysis(analyses: list[dict], base_sha: str, path: str, repo_root: Path) -> dict | None:
    """The newest analysis that judges the released state of ``path``, or ``None``.

    Both conditions are required: the analysed revision is an ancestor of the release base, and
    nothing under ``path`` changed between it and that base. The second is what makes a still
    running scan visible as "not usable yet" and, at the same time, keeps an older analysis valid
    when master merely moved ahead on docs or plugins.
    """
    for analysis in analyses:
        revision = analysis.get("revision")
        if not revision or not is_ancestor(revision, base_sha, repo_root):
            continue
        if package_changed_between(revision, base_sha, path, repo_root):
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
    for attempt in range(attempts + 1):
        analyses = fetch_analyses(target.project_key, branch, token, max_pages=1)
        found = pick_analysis(analyses, base_sha, target.path, repo_root)
        if found is not None:
            return found
        if attempt < attempts:
            print(
                f"No analysis of {branch} covers {base_sha[:7]} yet; retrying in {_POLL_INTERVAL_SECONDS:.0f}s.",
                file=sys.stderr,
            )
            sleep(_POLL_INTERVAL_SECONDS)
    return None
