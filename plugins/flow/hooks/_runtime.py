"""Pure functions shared by the Flow hook handlers."""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

FLOW_HELPER = re.compile(r"^flow-[a-z0-9][a-z0-9-]*$")


def canonical_prologue(plugin_root: Path) -> str:
    """Return the one shell prologue used to expose Flow helpers."""
    quoted_bin = shlex.quote(str(plugin_root / "bin"))
    return f'export PATH={quoted_bin}:"$PATH"\n'


def literal_helpers(plugin_root: Path) -> frozenset[str]:
    """Return executable, literally named Flow helpers shipped by the plugin."""
    bin_dir = plugin_root / "bin"
    return frozenset(
        path.name
        for path in bin_dir.iterdir()
        if path.is_file() and os.access(path, os.X_OK) and FLOW_HELPER.fullmatch(path.name)
    )


def _mentions_helper(command: str, helpers: frozenset[str]) -> bool:
    return any(re.search(rf"(?<![A-Za-z0-9_-]){re.escape(name)}(?![A-Za-z0-9_-])", command) for name in helpers)


def rewrite_pre_tool_use(payload: dict[str, Any], plugin_root: Path) -> dict[str, Any] | None:
    """Prepend the Flow PATH prologue when a shell command names a shipped helper."""
    if not isinstance(payload, dict):
        message = "PreToolUse input must be an object"
        raise ValueError(message)
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        message = "PreToolUse tool_input must be an object"
        raise ValueError(message)

    keys = [key for key in ("cmd", "command") if key in tool_input]
    if len(keys) != 1 or not isinstance(tool_input[keys[0]], str):
        message = "PreToolUse requires exactly one string command field"
        raise ValueError(message)

    key = keys[0]
    command = tool_input[key]
    prologue = canonical_prologue(plugin_root)
    if command.startswith(prologue) or not _mentions_helper(command, literal_helpers(plugin_root)):
        return None

    updated_input = dict(tool_input)
    updated_input[key] = prologue + command
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": updated_input,
        }
    }


def render_session_context(env: Mapping[str, str]) -> str:
    """Compose the shared contract with exactly one active harness adapter."""
    root_value = env.get("PLUGIN_ROOT") or env.get("CLAUDE_PLUGIN_ROOT")
    if not root_value:
        message = "Flow plugin root is unavailable"
        raise ValueError(message)
    plugin_root = Path(root_value).resolve()
    runtime = plugin_root / "hooks" / "runtime"
    common = (runtime / "common.md").read_text(encoding="utf-8")
    adapter_name = "codex.md" if env.get("PLUGIN_ROOT") else "claude-code.md"
    adapter = (runtime / adapter_name).read_text(encoding="utf-8")
    return (common + "\n\n" + adapter).replace(
        "{{FLOW_PATH_EXPORT}}",
        canonical_prologue(plugin_root).strip(),
    )
