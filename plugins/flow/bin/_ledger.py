"""Shared core of the persistent per-PR review ledger.

Path resolution, atomic document I/O and row lookup, imported by BOTH
`flow-review-ledger` (every subcommand) and `flow-comment-card --ledger`, so the row a
subagent analyses and the row a card renders can never diverge.

The ledger lives under the OS cache base — never in the working tree — so no git operation
from the repo can stage it (committing it would advance the head SHA and break
`flow:review-loop`, whose convergence is decided purely by head advancement).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = 1
BRIEF_CHARS = 120  # chars of `body` kept for the Phase-2 cap table

STATUSES = ("open", "skipped", "pending", "done")
DECISIONS = ("fix", "wont_fix", "follow_up", "outdated", "skip")
KINDS = ("inline", "file", "summary")

# Current-snapshot fields: refreshed from the collector every round. Durable fields
# (status/decision/reason/followup_task_id/thread_mark/first_seen_round/last_round/head) and the
# set-on-insert identity fields (ref/kind/thread_id) are NEVER in this list.
SNAPSHOT_FIELDS = (
    "user",
    "is_bot",
    "path",
    "start_line",
    "line",
    "outdated",
    "already_replied",
    "diff_hunk",
    "snippet",
    "side",
    "position",
    "body",
    "thread",
)

# Segments that delimit the project path in a PR/MR URL: GitHub `/pull/<n>`,
# GitLab `/-/merge_requests/<iid>` (and the legacy form without the `-`).
_ROUTE_MARKERS = frozenset({"pull", "pulls", "merge_requests", "-"})
_UNSAFE_SEGMENTS = frozenset({".", ".."})


class LedgerPathError(ValueError):
    """The PR/MR URL or number cannot be turned into a ledger path."""


def cache_base() -> Path:
    """The OS cache root. Windows: %LOCALAPPDATA%; POSIX (incl. WSL): $XDG_CACHE_HOME."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or "~/AppData/Local"
    else:
        base = os.environ.get("XDG_CACHE_HOME") or "~/.cache"
    return Path(base).expanduser()


def split_project(url: str) -> tuple[str, list[str]]:
    """('github.com', ['owner', 'repo']) — host + project path segments of a PR/MR URL.

    Nested directories mirror the repo path, so collisions are impossible by construction
    (no flattening, no hash): `github.com/foo/bar` and a GHE `foo/bar` never share a file.
    """
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    segments: list[str] = []
    for segment in parts.path.split("/"):
        if not segment:
            continue
        if segment in _ROUTE_MARKERS:
            break
        if segment in _UNSAFE_SEGMENTS:
            msg = f"unsafe path segment {segment!r} in URL {url!r}"
            raise LedgerPathError(msg)
        segments.append(segment)
    if not host or not segments:
        msg = f"cannot derive a project path from URL {url!r}"
        raise LedgerPathError(msg)
    return host, segments


def derive_number(url: str) -> str | None:
    """The PR/MR number embedded in a URL's route segment, or None if the URL carries none.

    Recognises GitHub `.../pull/<n>` (and `/pulls/<n>`) and GitLab `.../-/merge_requests/<n>`
    (with or without the leading `-`, since the segment split just looks for `merge_requests`
    directly followed by a digit). Lets `--url` alone stand in for `--number` on the CLI.

    Scanned RIGHT-TO-LEFT: the route lives at the END of the URL, while an earlier `pull` /
    `merge_requests` segment can only be part of the project path (a GitLab subgroup or repo
    may legitimately be named `pull`). Taking the leftmost match would resolve
    `gitlab.com/group/pull/12/-/merge_requests/7` to 12 — a different, real PR's ledger.
    """
    segments = [segment for segment in urlsplit(url or "").path.split("/") if segment]
    for index in range(len(segments) - 2, -1, -1):
        if segments[index] in ("pull", "pulls", "merge_requests") and segments[index + 1].isdigit():
            return segments[index + 1]
    return None


def ledger_path(url: str, number: object) -> Path:
    """<cache-base>/flow/review-ledger/<host>/<project…>/pr-<n>.json

    The number is normalised to its canonical decimal form, so a zero-padded link
    (`/pull/0012`) and `--number 12` resolve to ONE ledger instead of two.
    """
    host, segments = split_project(url)
    text = str(number if number is not None else "").strip().lstrip("!#")
    if not (text.isascii() and text.isdigit()):
        msg = f"PR/MR number must be numeric, got {number!r}"
        raise LedgerPathError(msg)
    return cache_base().joinpath("flow", "review-ledger", host, *segments, f"pr-{int(text)}.json")


def empty_ledger(unit: dict | None = None) -> dict:
    return {"schema": SCHEMA, "unit": dict(unit or {}), "round": 0, "next_ref": {"U": 1, "C": 1}, "rows": {}}


def load_ledger(path: Path) -> dict:
    """Read the document. A missing, corrupt, or non-ledger file degrades to an empty ledger.

    Graceful degradation is the design's contract: current working data is rebuilt from the
    platform every round, so only durable memory is lost — never a crash.
    """
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_ledger()
    if not isinstance(doc, dict) or not isinstance(doc.get("rows"), dict):
        return empty_ledger()
    doc.setdefault("schema", SCHEMA)
    doc.setdefault("unit", {})
    doc.setdefault("round", 0)
    doc.setdefault("next_ref", {"U": 1, "C": 1})
    return doc


def save_ledger(path: Path, doc: dict) -> None:
    """Write atomically: temp file in the target directory, then replace (mirrors statuskit)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False, indent=2)
        temp_path = Path(handle.name)
    try:
        temp_path.replace(path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise


def find_row_by_ref(doc: dict, ref: str) -> dict | None:
    """The row whose stable ref matches, or None. Shared by `get` and `flow-comment-card`."""
    for row in doc.get("rows", {}).values():
        if row.get("ref") == ref:
            return row
    return None


def thread_id_of(item: dict) -> str | None:
    """The platform thread id: GitHub inline comment, GitLab discussion, or GitHub review body."""
    for key in ("comment_id", "discussion_id", "summary_id"):
        value = item.get(key)
        if value is not None:
            return str(value)
    return None


def last_reply_id(item: dict) -> object:
    thread = item.get("thread") or []
    return thread[-1].get("id") if thread else None


def id_advanced(current: object, mark: object) -> bool:
    """True when `current` is a thread reply we have not accounted for yet.

    Ids are monotonic, so a numeric `>` is exact; a deleted reply can at worst MISS a
    re-surface, never lose data. Non-numeric ids fall back to inequality.
    """
    if current is None:
        return False
    if mark is None:
        return True
    try:
        return int(current) > int(mark)
    except (TypeError, ValueError):
        return str(current) != str(mark)
