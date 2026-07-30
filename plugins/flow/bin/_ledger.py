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

STATUSES = ("open", "skipped", "pending", "done", "deleted")
DECISIONS = ("fix", "wont_fix", "follow_up", "outdated", "skip")
KINDS = ("inline", "file", "summary")

# The platform's own verdict on a thread, recomputed from every round's snapshot — never
# remembered as a status. `absent` means the thread is not in the snapshot at all; because the
# collector aborts rather than returning a short page, absence is trustworthy.
PLATFORM_STATES = ("live", "resolved", "absent")

# Statuses that take a row OUT of the working set. `done` is settled by us, `deleted` is
# settled by the platform (the thread no longer exists). Every "is this row still work?"
# test goes through this set — a literal `status != "done"` would silently pull `deleted`
# rows back into the working set the moment a second terminal status existed.
TERMINAL_STATUSES = frozenset({"done", "deleted"})

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
    "resolved",
    "diff_hunk",
    "snippet",
    "side",
    "position",
    "body",
    "thread",
)

# Segments that mark the route in a PR/MR URL: GitHub `/pull/<n>` (and `/pulls/<n>`),
# GitLab `/-/merge_requests/<iid>` (and the legacy form without the `-`).
_ROUTE_MARKERS = ("pull", "pulls", "merge_requests")
_UNSAFE_SEGMENTS = frozenset({".", ".."})

# Ports that carry no information because the scheme already implies them: including them
# would make `https://host/…` and `https://host:443/…` — the same origin — two ledgers.
_DEFAULT_PORTS = {"http": 80, "https": 443}

_NT_CACHE_DEFAULT = "~/AppData/Local"
_POSIX_CACHE_DEFAULT = "~/.cache"


class LedgerPathError(ValueError):
    """The PR/MR URL or number cannot be turned into a ledger path."""


def cache_base_setting() -> str:
    """The raw cache-root setting for this OS, before any Path is built.

    Kept separate from `cache_base` so the platform branch stays assertable on every runner:
    `Path()` under `os.name == "nt"` builds a WindowsPath, which raises NotImplementedError on
    POSIX under Python <= 3.12. A test that simulates Windows by patching `os.name` therefore
    cannot call `cache_base()` on the Linux CI (3.11) at all -- the error escapes from the
    patched global state into pytest's own machinery and aborts the whole session.
    """
    if os.name == "nt":
        return os.environ.get("LOCALAPPDATA") or _NT_CACHE_DEFAULT
    return os.environ.get("XDG_CACHE_HOME") or _POSIX_CACHE_DEFAULT


def cache_base() -> Path:
    """The OS cache root. Windows: %LOCALAPPDATA%; POSIX (incl. WSL): $XDG_CACHE_HOME.

    A RELATIVE setting is ignored in favour of the platform default, per the XDG Base
    Directory spec ("All paths set in these environment variables must be absolute. If an
    implementation encounters a relative path in any of these variables it should consider
    the path invalid and ignore it."). `.expanduser()` alone would not catch this: it
    expands a leading `~` but leaves `.cache` relative, and a relative root resolves against
    the process cwd — which for a helper launched from the repo puts the ledger INSIDE the
    working tree, the one thing this module's docstring guarantees never happens.
    """
    base = Path(cache_base_setting()).expanduser()
    if not base.is_absolute():
        base = Path(_NT_CACHE_DEFAULT if os.name == "nt" else _POSIX_CACHE_DEFAULT).expanduser()
    return base


def _locate_route(segments: list[str]) -> int | None:
    """Index of the rightmost route-marker segment immediately followed by a digit, or None.

    The single place that decides "where does the route start" — `split_project` and
    `derive_number` both call it, so they cannot drift apart on the same URL again.

    Scanned RIGHT-TO-LEFT: the route lives at the END of the URL, while an earlier `pull` /
    `merge_requests` segment can only be part of the project path (a GitLab subgroup or repo
    may legitimately be named `pull`). Requiring the segment right after the marker to be a
    digit is what makes stopping at the first right-to-left match safe: a project segment
    named `pull` is essentially never immediately followed by another segment that is both a
    digit AND the true route number. Taking the leftmost match would resolve
    `gitlab.com/group/pull/12/-/merge_requests/7` to 12 — a different, real PR's ledger.
    """
    for index in range(len(segments) - 2, -1, -1):
        if segments[index] in _ROUTE_MARKERS and segments[index + 1].isdigit():
            return index
    return None


def split_project(url: str) -> tuple[str, list[str]]:
    """('github.com', ['owner', 'repo']) — host + project path segments of a PR/MR URL.

    Nested directories mirror the repo path, so collisions are impossible by construction
    (no flattening, no hash): `github.com/foo/bar` and a GHE `foo/bar` never share a file.
    """
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    # An IPv6 literal keeps its colons here: `urlsplit` strips only the brackets, so
    # `https://[2001:db8::1]/…` arrives as `2001:db8::1`. A colon is illegal in an NTFS path
    # component — the same constraint the port below is written for — so translate them. `-`
    # keeps the address readable and stays distinct from the `_` that introduces the port.
    host = host.replace(":", "-")
    # `.hostname` drops the port, but the port is part of the ORIGIN: two self-hosted forges
    # behind one hostname on different ports own different PRs, and without this they would
    # share (and clobber) one ledger file. Joined with `_`, never `:` — a colon is illegal in
    # an NTFS path component, and this path is built on Windows too.
    port = parts.port
    if port is not None and port != _DEFAULT_PORTS.get((parts.scheme or "").lower()):
        host = f"{host}_{port}"
    raw_segments = [segment for segment in parts.path.split("/") if segment]
    route_index = _locate_route(raw_segments)
    if route_index is not None:
        # The GitLab route is `.../-/merge_requests/<n>`: the `-` right before the marker is
        # the route delimiter, not a project segment, so it must not end up in the project
        # path either. `derive_number` never needs this because `merge_requests` alone is
        # its marker; a `-` NOT immediately followed by `merge_requests`+digit is left alone,
        # so a project legitimately named `-` still survives intact.
        if route_index > 0 and raw_segments[route_index] == "merge_requests" and raw_segments[route_index - 1] == "-":
            route_index -= 1
    project_segments = raw_segments if route_index is None else raw_segments[:route_index]
    segments: list[str] = []
    for segment in project_segments:
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
    """
    segments = [segment for segment in urlsplit(url or "").path.split("/") if segment]
    index = _locate_route(segments)
    return segments[index + 1] if index is not None else None


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


def is_working(row: dict) -> bool:
    """True when the row is still outstanding work — the ONE answer to that question.

    Two independent verdicts retire a row, and both are consulted here because three call sites
    (the `reconcile` loop, `counts_of`'s fallback, `fold_stats`) used to answer this separately
    and could disagree — a row absent from the working set while `stats` still reported it as
    `Open: 1`:

    - our own terminal `status` — `done` settled by us, `deleted` settled by the platform;
    - the platform's `resolved` flag, which is deliberately terminal too. A reviewer who wants
      another look un-resolves the thread or opens a new one; un-resolving brings the row
      straight back (`apply_resolution`). Re-opening on any reply instead would mean every
      "thanks, looks good" re-triages a settled finding.

    `resolved` is THREE-valued, so only an explicit True retires the row. None means "not
    determined this round" — GitHub's resolution side-query degrades instead of aborting the
    whole collection — and reading that as resolved would retire every outstanding finding the
    moment that query hiccupped. Consulting the flag here rather than in the re-open path is
    also what makes the outcome independent of whether the side-query succeeded: the row keeps
    its last KNOWN answer (see `refresh_snapshot`), so a degraded round decides the same way a
    clean one does.
    """
    return row.get("status") not in TERMINAL_STATUSES and row.get("resolved") is not True


def _is_count(value: object) -> bool:
    """A whole, non-negative JSON number. `bool` is an `int` subclass, so exclude it explicitly."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _structure_is_sound(doc: dict) -> bool:
    """Every structural field is either ABSENT — `load_ledger`'s `setdefault` supplies it — or
    already the right type.

    `setdefault` alone cannot enforce this: it fills a MISSING key and walks straight past a
    present-but-wrong-typed one. So `{"rows": {}, "next_ref": null}` loaded "successfully" and
    detonated rounds later inside `alloc_ref`'s `counters.get` as an AttributeError — a type
    `main()` does not catch, so the helper printed a traceback instead of honouring the
    degrade-to-empty contract below. Checking here puts the guard on the one door every
    document enters through, rather than at each of the seven places that consume a field.
    """
    rows = doc.get("rows")
    if not isinstance(rows, dict) or not all(isinstance(row, dict) for row in rows.values()):
        return False
    if "unit" in doc and not isinstance(doc["unit"], dict):
        return False
    if "round" in doc and not _is_count(doc["round"]):
        return False
    if "next_ref" in doc:
        counters = doc["next_ref"]
        if not isinstance(counters, dict) or not all(_is_count(value) for value in counters.values()):
            return False
    return True


def load_ledger(path: Path) -> dict:
    """Read the document. A missing, corrupt, or non-ledger file degrades to an empty ledger.

    Graceful degradation is the design's contract: current working data is rebuilt from the
    platform every round, so only durable memory is lost — never a crash. "Corrupt" covers both
    unparseable bytes and a file that parses but is not shaped like a ledger (see
    `_structure_is_sound`) — the second kind is the dangerous one, because it fails far from
    here, in whichever consumer first trusts the field.
    """
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_ledger()
    if not isinstance(doc, dict) or not _structure_is_sound(doc):
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


# Which id field carries the thread, and the namespace its value belongs to. GitHub numbers
# review bodies and inline comments from SEPARATE sequences, so the same integer can name both
# — the prefix is what keeps them apart as ledger keys.
_THREAD_SOURCES = (("comment_id", "comment"), ("discussion_id", "discussion"), ("summary_id", "summary"))


def thread_id_of(item: dict) -> str | None:
    """The BARE platform thread id: GitHub inline comment, GitLab discussion, or review body.

    Bare on purpose — this value is the row's reply target and goes straight into a platform
    API path (`.../comments/{id}/replies`, `.../discussions/{id}/notes`). Use `row_key_of`
    for the ledger key; a namespaced value reaching the API is a 404 on every reply.
    """
    for key, _prefix in _THREAD_SOURCES:
        value = item.get(key)
        if value is not None:
            return str(value)
    return None


def row_key_of(item: dict) -> str | None:
    """The ledger row key: `<source>:<id>`, or None when the item carries no platform id.

    Namespaced because the key's only job is identity WITHIN the ledger, where ids from
    three independent platform sequences share one dict. Never sent to a platform API.
    """
    for key, prefix in _THREAD_SOURCES:
        value = item.get(key)
        if value is not None:
            return f"{prefix}:{value}"
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


def platform_state_of(item: dict) -> str:
    """The platform axis for an item PRESENT in this round's snapshot.

    Absence is not decided here — `reconcile` sets `absent` in its own pass over the rows the
    snapshot did not contain.

    `resolved` is a bool for everything with a resolvable thread. `None` is legal for exactly
    one input, a GitHub review-body summary, which has no thread and never consults the
    resolution side-query; it maps to `live`, because "not applicable" for such a row means
    "live until we settle it". `None` no longer also means "could not determine" — the
    collector aborts on that instead, which is what allowed this function to be two lines.
    """
    return "resolved" if item.get("resolved") else "live"


def threadless(row: dict) -> bool:
    """True for the ONE row shape with no reply target and no platform resolution.

    A GitHub review body is not a thread: there is no endpoint to reply into and nothing to
    resolve, so our own `done` is its only exit. A GitLab general discussion is also
    `kind == "summary"` but carries a real discussion id, so it is a normal threaded row —
    conflating the two would let a `done` row skip its thread mark and then re-open on our own
    reply, forever.
    """
    return row.get("platform") == "github" and row.get("kind") == "summary"


def resurfaced(row: dict) -> bool:
    """True when the row's thread holds a reply we have not accounted for.

    Deliberately the same `id_advanced` call `reopen_if_advanced` makes: "did the thread
    advance?" gets ONE implementation, or the flag a Phase-3 subagent reads and the re-open the
    reconcile performs will eventually disagree about the same row. It stays true from the
    re-open until `record` writes a fresh mark, because only `record` advances the mark.
    """
    return id_advanced(last_reply_id(row), row.get("thread_mark"))
