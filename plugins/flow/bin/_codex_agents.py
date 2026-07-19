"""Classification and safe-write logic for optional, project-scoped Flow Codex agent profiles.

Security-sensitive by design: this module only ever reads `.codex/agents/*.toml` inside the
given project root, never `.codex/config.toml` (which can hold machine-local credentials) and
never anything under a user's home directory. It never overwrites or renames an existing file
and never follows a symlink out of the project root. A profile it writes is never a security
boundary — the fixed `ALLOWED_KEYS` set below has no sandbox/approval/MCP/credential/file-access
key, so any file that adds one fails the compatibility check and is reported as a conflict
instead of being silently accepted.

Requires Python 3.11+ for `tomllib`. This is the one Flow bin/ helper (with its thin CLI
`flow-codex-agent-setup`) documented as exempt from "every Flow helper runs on Python 3.9" --
see `plugins/flow/bin/tests/test_py39_compat.py`. The version check below runs before the
`tomllib` import so a pre-3.11 interpreter gets a concise diagnostic instead of a raw
ModuleNotFoundError traceback.
"""

from __future__ import annotations

import sys

# UP036 (outdated-version-block) is a false positive here: ruff's `target-version = "py311"`
# describes the syntax this repo's source assumes, but this is a *runtime* guard against an
# interpreter older than that -- e.g. this script invoked directly with `/usr/bin/python3`
# (3.9) or another pre-3.11 `python3` found on PATH. Suppressed and flagged per repo policy
# (CLAUDE.md "Linter Warnings": fix, don't suppress, unless explicitly justified).
if sys.version_info < (3, 11):  # noqa: UP036
    sys.stderr.write(
        "flow-codex-agent-setup requires Python 3.11+ (it uses tomllib to parse Codex agent "
        "profiles); this optional helper is unavailable on this interpreter. Every other Flow "
        "helper is unaffected.\n"
    )
    sys.exit(1)

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

# Internal working shapes are genuinely dynamic (JSON-in, JSON-out), so they're typed `Any`
# rather than `object` -- `object` would force an explicit `isinstance` narrowing at every
# access, which buys nothing here since the shape is enforced by construction (this module
# is the only writer of these dicts) and by the test suite (real filesystem behavior, not
# mocks). The three public seams named in the design (`inspect_project`, `render_profile`,
# `create_profiles`) keep the exact `dict[str, object]` signature specified for them; a
# `dict[str, Any]` return value is assignable there without a cast.
ScanResult = dict[str, Any]
Profiles = dict[str, dict[str, Any]]
Plan = dict[str, Any]

# --- stable contract (verbatim per design) -------------------------------------------------

PROFILE_NAMES = {
    "fast": "flow-fast",
    "balanced": "flow-balanced",
    "strongest": "flow-strongest",
}
REASONING_EFFORTS = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
}
DEVELOPER_INSTRUCTIONS = (
    "Follow the role, task, access boundary, execution mode, and output contract "
    "supplied by the parent Flow workflow. Do not broaden the task or perform "
    "unrelated work. Return only the requested result."
)
DESCRIPTIONS = {
    "fast": "Flow fast capability profile for bounded and mechanical work.",
    "balanced": "Flow balanced capability profile for code-grounded analysis.",
    "strongest": "Flow strongest capability profile for difficult architecture and security reasoning.",
}
ALLOWED_KEYS = {
    "name",
    "description",
    "model",
    "model_reasoning_effort",
    "developer_instructions",
}

_REQUIRED_NAME_TO_TIER = {name: tier for tier, name in PROFILE_NAMES.items()}

NAME_ASSIGNMENT = re.compile(
    r'^name\s*=\s*"(flow-(?:fast|balanced|strongest))"\s*$',
    re.MULTILINE,
)


def compatible_profile(data: dict[str, object], tier: str) -> bool:
    """True iff `data` (a parsed agent TOML) is Flow-compatible for `tier`.

    Only `model` and `model_reasoning_effort` may vary from user edits; every other key and
    value must match exactly. The closed `ALLOWED_KEYS` set has no sandbox/approval/MCP/
    credential/file-access key, so any extra key (an attempt to broaden the profile into a
    security boundary) fails this check and is reported as a conflict, not accepted.
    """
    return (
        set(data) == ALLOWED_KEYS
        and data.get("name") == PROFILE_NAMES[tier]
        and data.get("description") == DESCRIPTIONS[tier]
        and data.get("developer_instructions") == DEVELOPER_INSTRUCTIONS
        and isinstance(data.get("model"), str)
        and bool(str(data["model"]).strip())
        and data.get("model_reasoning_effort") in REASONING_EFFORTS
    )


def malformed_identity(text: str) -> str | None:
    """Recover a required profile's identity from unparseable TOML text.

    Only a single, unambiguous top-level `name = "flow-..."` assignment counts; zero or
    multiple matches return None, which the caller must treat as a GLOBAL ambiguity (it cannot
    prove the file doesn't secretly claim one of the three required names).
    """
    names = set(NAME_ASSIGNMENT.findall(text))
    return names.pop() if len(names) == 1 else None


def reject_symlink_components(project_root: Path, target: Path) -> None:
    """Raise ValueError if `target` escapes `project_root` or any path component is a symlink.

    Must be called before reading OR writing any candidate path. Checked component-by-component
    (not via `resolve()`, which would silently follow the very symlinks this is meant to catch).
    """
    root = project_root.resolve(strict=True)
    candidate = target.absolute()
    if root != candidate and root not in candidate.parents:
        msg = f"target escapes project root: {candidate}"
        raise ValueError(msg)
    current = root
    for part in candidate.relative_to(root).parts:
        current = current / part
        if current.exists() and current.is_symlink():
            msg = f"symlink target component is not allowed: {current}"
            raise ValueError(msg)


def render_profile(tier: str, model: str, reasoning: str) -> str:
    """Render `tier`'s agent profile as TOML text (JSON string quoting, also valid TOML)."""
    values = {
        "name": PROFILE_NAMES[tier],
        "description": DESCRIPTIONS[tier],
        "model": model.strip(),
        "model_reasoning_effort": reasoning,
        "developer_instructions": DEVELOPER_INSTRUCTIONS,
    }
    return "".join(f"{key} = {json.dumps(value)}\n" for key, value in values.items())


# --- scanning: read-only, never touches `.codex/config.toml` or anything outside agents/ ---


def _parse_agent_file(path: Path) -> tuple[str | None, dict[str, object] | None, str | None]:
    """Return (required_name_or_None, parsed_data_or_None, global_ambiguity_reason_or_None).

    `required_name` is set only when the file's internal `name` is one of the three required
    profile names (filename is never consulted). On malformed TOML with a recoverable, unique
    required name, `data` is None (contract details are unknown) but `required_name` is still
    set, so the caller can still scope the conflict to just that tier. On malformed TOML with
    no unique recoverable identity, a reason is returned instead -- that's a GLOBAL block.
    """
    try:
        text = path.read_text()
    except OSError as exc:
        # An unreadable candidate (e.g. made unreadable after the symlink check) means we
        # cannot prove the three required names are absent/unique, so block globally rather
        # than let the OSError escape as a traceback out of the no-try/except `inspect` path.
        return None, None, f"cannot read agent file {path.name}: {exc}"
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        name = malformed_identity(text)
        if name is None:
            return None, None, f"cannot determine a unique identity for malformed TOML: {path.name}"
        return name, None, None
    name = data.get("name")
    if isinstance(name, str) and name in _REQUIRED_NAME_TO_TIER:
        return name, data, None
    return None, data, None


def _scan(project_root: Path) -> ScanResult:
    """Pure, read-only scan of `.codex/agents/*.toml`. Never writes; never reads config.toml.

    Rejects any symlink path component before reading directory contents or file bodies. Any
    symlink anywhere in `.codex`/`.codex/agents`/a candidate file is treated as a reason to
    block the ENTIRE operation (not just the affected tier) -- a conservative "stop everything"
    stance, matching the ambiguous-identity handling below.
    """
    agents_dir = project_root / ".codex" / "agents"
    scan: ScanResult = {
        "agents_dir": agents_dir,
        "symlink_conflicts": [],
        "identity": {name: [] for name in PROFILE_NAMES.values()},
        "global_conflicts": [],
        "canonical_occupied": {},
    }
    try:
        reject_symlink_components(project_root, agents_dir)
    except ValueError as exc:
        scan["symlink_conflicts"].append(str(exc))
        return scan
    if not agents_dir.is_dir():
        return scan
    for path in sorted(agents_dir.glob("*.toml")):
        try:
            reject_symlink_components(project_root, path)
        except ValueError as exc:
            scan["symlink_conflicts"].append(str(exc))
            continue
        name, data, ambiguous = _parse_agent_file(path)
        if ambiguous is not None:
            scan["global_conflicts"].append(ambiguous)
            continue
        if name is not None:
            scan["identity"][name].append((path, data))
    for tier, name in PROFILE_NAMES.items():
        canonical = agents_dir / f"{name}.toml"
        matched_paths = {p for p, _ in scan["identity"][name]}
        if canonical.is_file() and canonical not in matched_paths:
            scan["canonical_occupied"][tier] = canonical
    return scan


def _classify(scan: ScanResult) -> Profiles:
    """Per-tier status (compatible/conflict/missing) from a `_scan()` result."""
    profiles: Profiles = {}
    for tier, name in PROFILE_NAMES.items():
        matches = scan["identity"][name]
        reason: str | None
        if len(matches) > 1:
            status, reason = "conflict", f"duplicate identity {name!r} claimed by {len(matches)} files"
        elif len(matches) == 1:
            path, data = matches[0]
            if data is not None and compatible_profile(data, tier):
                status, reason = "compatible", None
            else:
                status, reason = "conflict", f"{path.name} claims {name!r} but does not match the required contract"
        elif tier in scan["canonical_occupied"]:
            occupant = scan["canonical_occupied"][tier]
            status, reason = "conflict", f"{occupant.name} already exists with a different identity"
        else:
            status, reason = "missing", None
        profiles[name] = {"tier": tier, "status": status, "reason": reason}
    return profiles


def _linked_worktree(project_root: Path) -> bool:
    """True iff `project_root` is a linked worktree (git-dir differs from git-common-dir).

    Never raises; a non-git directory or any git failure is treated as "not a linked worktree".
    """
    try:
        common = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        git_dir = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return False
    if not common or not git_dir:
        return False

    def _abs(raw: str) -> Path:
        p = Path(raw)
        return (p if p.is_absolute() else project_root / p).resolve()

    return _abs(common) != _abs(git_dir)


def _conflicts_list(scan: ScanResult, profiles: Profiles) -> list[dict[str, Any]]:
    items = [
        {"name": name, "reason": info["reason"]} for name, info in profiles.items() if info["status"] == "conflict"
    ]
    items += [{"reason": msg} for msg in scan["symlink_conflicts"]]
    return items


def inspect_project(project_root: Path) -> dict[str, object]:
    """Scan-only classification of the three required profiles; never writes."""
    project_root = Path(project_root)
    scan = _scan(project_root)
    profiles = _classify(scan)
    return {
        "project_root": str(project_root),
        "agents_dir": str(scan["agents_dir"]),
        "linked_worktree": _linked_worktree(project_root),
        "profiles": profiles,
        "conflicts": _conflicts_list(scan, profiles),
        "global_conflicts": list(scan["global_conflicts"]),
        "missing": [],
        "compatible": [name for name, info in profiles.items() if info["status"] == "compatible"],
    }


# --- request validation + planning (shared by preview and create) --------------------------


def _validate_request_shape(request: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """tier -> (raw model, raw reasoning). Raises ValueError on a structurally bad request."""
    profiles = request.get("profiles") if isinstance(request, dict) else None
    if not isinstance(profiles, list):
        msg = "request JSON must have a 'profiles' list"
        raise ValueError(msg)
    requested: dict[str, tuple[Any, Any]] = {}
    for item in profiles:
        if not isinstance(item, dict) or "tier" not in item:
            msg = "each entry in 'profiles' must be an object with a 'tier'"
            raise ValueError(msg)
        tier = item["tier"]
        if not isinstance(tier, str) or tier not in PROFILE_NAMES:
            msg = f"unknown tier: {tier!r}"
            raise ValueError(msg)
        requested[tier] = (item.get("model"), item.get("reasoning"))
    return requested


def _is_valid_value(model: object, reasoning: object) -> bool:
    return (
        isinstance(model, str) and bool(model.strip()) and isinstance(reasoning, str) and reasoning in REASONING_EFFORTS
    )


def _plan(project_root: Path, request: dict[str, Any]) -> Plan:
    """Scan + classify + overlay the request. Never writes; the shared preview/create core."""
    project_root = Path(project_root)
    scan = _scan(project_root)
    profiles = _classify(scan)
    requested = _validate_request_shape(request)

    missing: list[dict[str, Any]] = []
    for tier, (model, reasoning) in requested.items():
        name = PROFILE_NAMES[tier]
        info = profiles[name]
        if info["status"] != "missing":
            continue
        if not _is_valid_value(model, reasoning):
            info["status"] = "invalid"
            info["reason"] = "requested model/reasoning failed validation"
            continue
        content = render_profile(tier, model, reasoning)
        tomllib.loads(content)  # round-trip the generated TOML before ever proposing it
        missing.append(
            {
                "tier": tier,
                "name": name,
                "path": str(scan["agents_dir"] / f"{name}.toml"),
                "content": content,
            }
        )

    symlink_blocked = bool(scan["symlink_conflicts"])
    global_conflicts = list(scan["global_conflicts"])
    return {
        "project_root": str(project_root),
        "agents_dir": str(scan["agents_dir"]),
        "linked_worktree": _linked_worktree(project_root),
        "profiles": profiles,
        "conflicts": _conflicts_list(scan, profiles),
        "global_conflicts": global_conflicts,
        "missing": missing,
        "blocked": symlink_blocked or bool(global_conflicts),
    }


def preview_profiles(project_root: Path, request: dict[str, object]) -> dict[str, object]:
    """Preview what `create_profiles` would do. Never writes."""
    plan: Plan = _plan(project_root, request)
    plan.pop("blocked", None)
    plan["compatible"] = [name for name, info in plan["profiles"].items() if info["status"] == "compatible"]
    return plan


def create_profiles(project_root: Path, request: dict[str, object]) -> dict[str, object]:
    """Rescan, then create only still-missing, independently safe profiles with `O_EXCL`.

    Never overwrites or renames an existing file. A global block (any symlink anywhere in
    `.codex`/`.codex/agents`, or any malformed file whose identity can't be proven unique)
    creates nothing at all, because uniqueness of the three required names cannot be proven.
    A per-tier race (another writer creates the target between rescan and write) reclassifies
    only that tier as a conflict and preserves the concurrent writer's bytes untouched.
    """
    plan: Plan = _plan(project_root, request)
    blocked = plan.pop("blocked")
    project_root = Path(plan["project_root"])
    agents_dir = Path(plan["agents_dir"])
    created: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    if not blocked and plan["missing"]:
        try:
            reject_symlink_components(project_root, agents_dir)
        except ValueError as exc:
            plan["conflicts"].append({"reason": str(exc)})
            blocked = True
        else:
            agents_dir.mkdir(parents=True, exist_ok=True)

    if not blocked:
        for item in plan["missing"]:
            target = agents_dir / f"{item['name']}.toml"
            try:
                reject_symlink_components(project_root, target)
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                fd = os.open(target, flags, 0o600)
                with os.fdopen(fd, "w") as stream:
                    stream.write(item["content"])
            except FileExistsError:
                plan["profiles"][item["name"]]["status"] = "conflict"
                plan["profiles"][item["name"]]["reason"] = f"{target.name} was created concurrently"
                plan["conflicts"].append({"name": item["name"], "reason": "created concurrently"})
            except ValueError as exc:  # symlink containment, re-checked right before the write
                plan["profiles"][item["name"]]["status"] = "conflict"
                plan["profiles"][item["name"]]["reason"] = str(exc)
                plan["conflicts"].append({"name": item["name"], "reason": str(exc)})
            except OSError as exc:
                failed.append({"name": item["name"], "reason": str(exc)})
            else:
                plan["profiles"][item["name"]]["status"] = "created"
                created.append({"name": item["name"], "path": str(target)})

    created_names = {c["name"] for c in created}
    plan["missing"] = [item for item in plan["missing"] if item["name"] not in created_names]
    plan["created"] = created
    plan["failed"] = failed
    plan["compatible"] = [name for name, info in plan["profiles"].items() if info["status"] == "compatible"]
    return plan
