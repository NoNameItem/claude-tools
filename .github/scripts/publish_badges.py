#!/usr/bin/env python3
"""Publish per-project CI badges to the badges-data branch.

Reads the current GitHub Actions workflow run's job list, aggregates
conclusions per project (extracted from job names by trailing-parens
convention), and writes shields.io endpoint JSON files to ``--output-dir``.

Usage:
    publish_badges.py --output-dir <path> [--repo <owner/repo>] [--run-id <id>]

Environment variables:
    GITHUB_TOKEN       Required. PAT or workflow token with actions:read.
    GITHUB_REPOSITORY  Default for --repo when not provided.
    GITHUB_RUN_ID      Default for --run-id when not provided.

Exit codes:
    0  success (zero files written is still success)
    1  API error, parse error, missing required env, or pagination cap hit
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Anchored at end. Group 1 is the project; an optional ", suffix" (e.g.
# python version in the test matrix) is allowed but discarded.
_PROJECT_PATTERN = re.compile(r"\((?P<project>[\w][\w-]*)(?:, [^)]+)?\)$")


def extract_project_name(job_name: str) -> str | None:
    """Extract project name from a job name.

    Matches names of the form ``"<prefix> (<project>)"`` or
    ``"<prefix> (<project>, <suffix>)"``. Project must start with a
    word character and may contain word chars and hyphens.

    Args:
        job_name: The GitHub Actions job ``name`` field.

    Returns:
        The project slug, or ``None`` if the name has no recognizable
        trailing project group.
    """
    match = _PROJECT_PATTERN.search(job_name)
    return match.group("project") if match else None


# Conclusions that count as a real positive signal.
_SUCCESS_CONCLUSIONS = frozenset({"success"})

# Conclusions that contribute no signal (don't downgrade, don't upgrade).
_NEUTRAL_CONCLUSIONS = frozenset({"skipped"})


def aggregate_status(conclusions: list[str | None]) -> tuple[str, str] | None:
    """Aggregate per-job conclusions into a single (message, color) tuple.

    Rules:
        * All success (optionally mixed with skipped) -> ("passing", "brightgreen")
        * Any non-success / non-skipped conclusion       -> ("failing", "red")
        * All skipped, or empty input                    -> None (caller skips write)

    Args:
        conclusions: A list of GitHub ``conclusion`` strings for one project.
            ``None`` and unknown values are treated conservatively as failing.

    Returns:
        ``(message, color)`` for shields.io, or ``None`` if there is no
        signal (caller MUST NOT touch the badge file in that case).
    """
    saw_signal = False
    for c in conclusions:
        if c in _NEUTRAL_CONCLUSIONS:
            continue
        if c in _SUCCESS_CONCLUSIONS:
            saw_signal = True
            continue
        # Anything else (failure, cancelled, timed_out, neutral, action_required,
        # stale, unexpected strings, or None) is conservatively a failure.
        return ("failing", "red")

    if not saw_signal:
        return None
    return ("passing", "brightgreen")


def build_badge_json(message: str, color: str) -> dict:
    """Build the shields.io endpoint dict for a project's CI status.

    Args:
        message: The badge value (e.g. ``"passing"`` or ``"failing"``).
        color: A shields.io color name (e.g. ``"brightgreen"``, ``"red"``).

    Returns:
        A dict matching the shields.io endpoint schema v1.
    """
    return {
        "schemaVersion": 1,
        "label": "CI",
        "message": message,
        "color": color,
    }


def write_badge_file(output_dir: Path, project: str, badge: dict) -> None:
    """Write ``{output_dir}/{project}.json`` with indent=2 and trailing newline.

    The output directory must already exist. The caller (the workflow)
    supplies a checkout of the ``badges-data`` branch.

    Args:
        output_dir: Existing directory (the ``badges-data`` checkout).
        project: Project slug; becomes the basename of the file.
        badge: A dict in shields.io endpoint shape.

    Raises:
        FileNotFoundError: If ``output_dir`` does not exist.
    """
    if not output_dir.is_dir():
        msg = f"Output directory does not exist: {output_dir}"
        raise FileNotFoundError(msg)
    path = output_dir / f"{project}.json"
    path.write_text(json.dumps(badge, indent=2) + "\n")


# Hard cap on pagination: 10 pages * 100 jobs = 1000 jobs/run.
# Real runs are well under 100 jobs total; the cap exists only to bound a
# misbehaving API or pagination loop.
_MAX_PAGES = 10

# Single-request timeout (seconds). Keeps a hung TLS handshake from stalling
# the workflow indefinitely.
_REQUEST_TIMEOUT = 30.0

_LINK_NEXT_PATTERN = re.compile(r'<([^>]+)>;\s*rel="next"')


def _get_next_url(response: object) -> str | None:
    """Parse the next-page URL from a Link header, or return None."""
    header = response.getheader("Link") if hasattr(response, "getheader") else None
    if not header:
        return None
    match = _LINK_NEXT_PATTERN.search(header)
    return match.group(1) if match else None


def fetch_jobs(repo: str, run_id: str, token: str) -> list[dict]:
    """Fetch every job for a workflow run, following pagination.

    Args:
        repo: ``"owner/name"`` from ``$GITHUB_REPOSITORY``.
        run_id: Workflow run ID (``$GITHUB_RUN_ID``).
        token: GitHub token with ``actions:read`` permission.

    Returns:
        List of job dicts as returned by the GitHub REST API.

    Raises:
        RuntimeError: If the response advertises more than ``_MAX_PAGES`` pages.
        urllib.error.HTTPError: Propagated unchanged on non-2xx responses.
    """
    base = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs"
    query = urllib.parse.urlencode({"per_page": 100})
    url: str | None = f"{base}?{query}"
    jobs: list[dict] = []
    pages = 0

    while url is not None:
        pages += 1
        if pages > _MAX_PAGES:
            msg = f"pagination cap exceeded ({_MAX_PAGES} pages)"
            raise RuntimeError(msg)
        request = urllib.request.Request(  # noqa: S310
            url,
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "publish-badges",
            },
        )
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT) as response:  # noqa: S310
            payload = json.loads(response.read())
            jobs.extend(payload.get("jobs", []))
            url = _get_next_url(response)

    return jobs


def publish_badges(
    repo: str,
    run_id: str,
    token: str,
    output_dir: Path,
) -> dict[str, str]:
    """Fetch jobs, aggregate per project, write badge files.

    Args:
        repo: ``"owner/name"`` from ``$GITHUB_REPOSITORY``.
        run_id: Workflow run ID (``$GITHUB_RUN_ID``).
        token: GitHub token with ``actions:read``.
        output_dir: Existing checkout of the ``badges-data`` branch.

    Returns:
        Map of project slug to a human label: ``"passing"``, ``"failing"``,
        or ``"skipped (no write)"``. Projects whose names never appeared in
        a job (or whose only jobs were in-flight) are absent from the map.
    """
    jobs = fetch_jobs(repo, run_id, token)

    # Group conclusions by project, filtered to completed jobs only.
    grouped: dict[str, list[str | None]] = {}
    for job in jobs:
        if job.get("status") != "completed":
            continue
        project = extract_project_name(job.get("name", ""))
        if project is None:
            continue
        grouped.setdefault(project, []).append(job.get("conclusion"))

    summary: dict[str, str] = {}
    for project, conclusions in grouped.items():
        aggregate = aggregate_status(conclusions)
        if aggregate is None:
            summary[project] = "skipped (no write)"
            continue
        message, color = aggregate
        write_badge_file(output_dir, project, build_badge_json(message, color))
        summary[project] = message

    return summary


def _print_summary(summary: dict[str, str]) -> None:
    """Print a fixed-width table for the workflow log."""
    project_w = max([len("Project"), *[len(p) for p in summary]])
    status_w = max([len("Status"), *[len(s) for s in summary.values()]])
    header = f"{'Project':<{project_w}}  {'Status':<{status_w}}  Color"
    separator = "-" * len(header)
    print(header)
    print(separator)
    for project, status in sorted(summary.items()):
        color = {
            "passing": "brightgreen",
            "failing": "red",
            "skipped (no write)": "-",
        }.get(status, "-")
        print(f"{project:<{project_w}}  {status:<{status_w}}  {color}")


def main() -> int:
    """CLI entrypoint. Returns 0 on success, 1 on failure."""
    parser = argparse.ArgumentParser(description="Publish per-project CI badges to the badges-data branch.")
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Path to a checkout of the badges-data branch.",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="owner/name (default: $GITHUB_REPOSITORY).",
    )
    parser.add_argument(
        "--run-id",
        default=os.environ.get("GITHUB_RUN_ID"),
        help="Workflow run ID (default: $GITHUB_RUN_ID).",
    )
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN env var is required", file=sys.stderr)
        return 1
    if not args.repo:
        print("Error: --repo or $GITHUB_REPOSITORY is required", file=sys.stderr)
        return 1
    if not args.run_id:
        print("Error: --run-id or $GITHUB_RUN_ID is required", file=sys.stderr)
        return 1

    try:
        summary = publish_badges(args.repo, args.run_id, token, args.output_dir)
    except Exception as exc:
        # Script-level catch-all: translate any Python exception into
        # exit 1 with a one-line stderr message for the workflow log.
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
