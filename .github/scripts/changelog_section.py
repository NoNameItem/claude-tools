#!/usr/bin/env python3
"""Read the top version section of a release-please CHANGELOG.

Release-please force-pushes EVERY pending release PR on EVERY merge to master, and on a pure
rebase the only thing that changes inside the CHANGELOG is the date in the section heading. So
the blob SHA is useless as a signal and the *ordered list of entries in the top section* is the
signal — which is what `entries_changed` compares, and what `_reusable-release-pr-summary.yml`
uses to stay silent when somebody else's merge rebased this PR. Release-please's own output is
order-stable, so this is accurate for every automated push; a hand edit that only reorders two
entries, without adding or removing any, reads as a change and produces one extra notification.

Pure text in, data out: no network, no filesystem beyond the CLI's own file reads.

Usage:
    python3 changelog_section.py section < CHANGELOG.md
    python3 changelog_section.py changed --before before.md --after after.md
    python3 changelog_section.py path --config release-please-config.json --branch "$HEAD_REF"

Output (stdout):
    section  {"version": str, "date": str, "entries": [str]}  — or {} when there is no section
    changed  "true" | "false"
    path     "packages/statuskit/CHANGELOG.md" — or nothing when the component is unknown
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# release-please writes `## [0.5.1](https://…compare/a...b) (2026-07-31)`; a plain
# `## 1.2.3 (2026-01-01)` and a bare `## Unreleased` are accepted too, so a hand-edited
# changelog degrades to a parse rather than to None.
_SECTION_HEADING = re.compile(r"^##\s+(?:\[(?P<linked>[^\]]+)\]\([^)]*\)|(?P<bare>\S+))\s*(?:\((?P<date>[^)]*)\))?\s*$")

_BRANCH_PREFIX = "release-please--branches--"
_COMPONENT_MARKER = "--components--"
_DEFAULT_CHANGELOG = "CHANGELOG.md"


@dataclass(frozen=True)
class Section:
    """The newest version block of a CHANGELOG."""

    version: str
    date: str
    entries: list[str]


def parse_top_section(text: str) -> Section | None:
    """Parse the first `## …` block of a CHANGELOG.

    Args:
        text: The whole file.

    Returns:
        The section, with `entries` holding its non-empty body lines (sub-headings included) and
        the heading itself — version and date — kept out of them. ``None`` when the file carries
        no version heading at all, which is a real state for a project that never released.
    """
    lines = text.splitlines()
    match = None
    start = None
    for i, line in enumerate(lines):
        m = _SECTION_HEADING.match(line)
        if m is not None:
            start = i
            match = m
            break
    if match is None:
        return None
    end = next(
        (j for j in range(start + 1, len(lines)) if _SECTION_HEADING.match(lines[j])),
        len(lines),
    )
    # Blank lines are dropped rather than preserved: release-please varies the spacing between
    # the heading and the first sub-heading, and a comparison that trips on whitespace would
    # report a change on every force-push.
    entries = [line.rstrip() for line in lines[start + 1 : end] if line.strip()]
    return Section(
        version=match.group("linked") or match.group("bare") or "",
        date=match.group("date") or "",
        entries=entries,
    )


def entries_changed(before: str | None, after: str | None) -> bool:
    """Whether the top section's entries differ, as an ordered list, between two revisions.

    The date lives in the heading and is therefore never compared — that is the whole point:
    a force-push caused by another component's merge moves only the date. Order is compared too,
    not just membership: release-please's own output is order-stable, so this only bites on a hand
    edit that reorders two entries without adding or removing any — that reads as a change and
    produces one extra notification.

    A missing/unparsable `before` counts as a change (there is something new to announce); a
    missing/unparsable `after` counts as no change (there is nothing to announce).
    """
    new = parse_top_section(after) if after else None
    if new is None:
        return False
    old = parse_top_section(before) if before else None
    if old is None:
        return True
    return old.entries != new.entries


def component_from_branch(head_ref: str) -> str | None:
    """Extract the release-please component from its deterministic branch name.

    `release-please--branches--master--components--statuskit` → `statuskit`.
    """
    if not head_ref.startswith(_BRANCH_PREFIX) or _COMPONENT_MARKER not in head_ref:
        return None
    return head_ref.split(_COMPONENT_MARKER, 1)[1] or None


def changelog_path_for(config: dict, component: str) -> str | None:
    """Locate a component's CHANGELOG through release-please's own config.

    Read from `release-please-config.json` rather than hard-coded, so adding a package does not
    silently break its release notification.
    """
    for directory, package in (config.get("packages") or {}).items():
        if package.get("package-name") == component:
            changelog = package.get("changelog-path") or _DEFAULT_CHANGELOG
            return f"{directory.rstrip('/')}/{changelog}"
    return None


def _read(path: str | None) -> str | None:
    """Read a file, or return None when it is absent — a missing revision is a normal input."""
    if not path:
        return None
    file = Path(path)
    return file.read_text() if file.is_file() else None


def main() -> int:
    """CLI entrypoint. Always returns 0 — every outcome here is a normal one."""
    parser = argparse.ArgumentParser(description="Read a release-please CHANGELOG.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("section", help="Print the top section of the CHANGELOG read from stdin.")

    changed = sub.add_parser("changed", help="Compare the top sections of two revisions.")
    changed.add_argument("--before", default=None)
    changed.add_argument("--after", default=None)

    path = sub.add_parser("path", help="Print a component's CHANGELOG path.")
    path.add_argument("--config", required=True)
    path.add_argument("--branch", required=True)

    args = parser.parse_args()

    if args.command == "section":
        section = parse_top_section(sys.stdin.read())
        print(json.dumps(asdict(section) if section else {}))
        return 0

    if args.command == "changed":
        print("true" if entries_changed(_read(args.before), _read(args.after)) else "false")
        return 0

    component = component_from_branch(args.branch)
    if component:
        config = json.loads(Path(args.config).read_text())
        print(changelog_path_for(config, component) or "", end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
