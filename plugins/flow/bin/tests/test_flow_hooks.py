"""Tests for Flow's shared hook runtime and Codex helper resolver."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

import pytest

FLOW_ROOT = Path(__file__).parents[2]
HOOKS_ROOT = FLOW_ROOT / "hooks"


def _load_runtime():
    spec = importlib.util.spec_from_file_location("flow_hook_runtime", HOOKS_ROOT / "_runtime.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNTIME = _load_runtime()
canonical_prologue = RUNTIME.canonical_prologue
literal_helpers = RUNTIME.literal_helpers
render_session_context = RUNTIME.render_session_context
rewrite_pre_tool_use = RUNTIME.rewrite_pre_tool_use


def test_rewrite_return_type_is_optional_dict() -> None:
    return_type = get_type_hints(rewrite_pre_tool_use)["return"]
    assert return_type is not Any
    assert get_origin(return_type) is not None

    return_args = get_args(return_type)
    assert type(None) in return_args
    dict_types = [return_arg for return_arg in return_args if return_arg is not type(None)]
    assert len(dict_types) == 1
    assert get_origin(dict_types[0]) is dict
    assert get_args(dict_types[0]) == (str, Any)


@pytest.fixture
def flow_plugin_root() -> Path:
    return FLOW_ROOT


def run_hook(
    name: str,
    payload: object,
    *,
    env: dict[str, str] | None = None,
    raw_stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    hook_env = os.environ.copy()
    hook_env.pop("PLUGIN_ROOT", None)
    hook_env.pop("CLAUDE_PLUGIN_ROOT", None)
    if env:
        hook_env.update(env)
    stdin = raw_stdin if raw_stdin is not None else json.dumps(payload)
    return subprocess.run(
        [str(HOOKS_ROOT / name)],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        env=hook_env,
    )


@pytest.mark.parametrize(
    "command",
    [
        "flow-sync pull",
        "flow-review-collect 12 > metadata.json",
        "bd graph --all --json | flow-task-tree",
        'bd update task --assignee "$(flow-actor)"',
        'flow-link-doc task Git "$(git branch --show-current)"',
    ],
)
def test_rewrite_preserves_original_command_after_one_prologue(
    flow_plugin_root: Path,
    command: str,
) -> None:
    payload = {"tool_name": "Bash", "tool_input": {"cmd": command, "yield_time_ms": 10_000}}
    output = rewrite_pre_tool_use(payload, flow_plugin_root)
    assert output is not None
    updated = output["hookSpecificOutput"]["updatedInput"]
    prologue = canonical_prologue(flow_plugin_root)
    assert updated["cmd"] == prologue + command
    assert updated["yield_time_ms"] == 10_000
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert payload["tool_input"]["cmd"] == command


def test_rewrite_is_idempotent_only_for_the_exact_prefix(flow_plugin_root: Path) -> None:
    prologue = canonical_prologue(flow_plugin_root)
    command = prologue + "flow-sync pull"
    payload = {"tool_name": "Bash", "tool_input": {"cmd": command}}
    assert rewrite_pre_tool_use(payload, flow_plugin_root) is None

    near_prefix = prologue.rstrip("\n") + " \nflow-sync pull"
    output = rewrite_pre_tool_use({"tool_input": {"cmd": near_prefix}}, flow_plugin_root)
    assert output is not None
    assert output["hookSpecificOutput"]["updatedInput"]["cmd"] == prologue + near_prefix


def test_non_flow_command_is_untouched(flow_plugin_root: Path) -> None:
    payload = {"tool_name": "Bash", "tool_input": {"cmd": "git status --short"}}
    assert rewrite_pre_tool_use(payload, flow_plugin_root) is None


def test_every_shipped_helper_triggers(flow_plugin_root: Path) -> None:
    helpers = literal_helpers(flow_plugin_root)
    shipped_helpers = frozenset(
        path.name for path in (flow_plugin_root / "bin").glob("flow-*") if path.is_file() and os.access(path, os.X_OK)
    )
    assert helpers == shipped_helpers
    assert helpers
    for helper in helpers:
        payload = {"tool_name": "Bash", "tool_input": {"cmd": f"{helper} --help"}}
        assert rewrite_pre_tool_use(payload, flow_plugin_root) is not None


@pytest.mark.parametrize("command_key", ["cmd", "command"])
def test_handler_rewrites_both_command_keys(command_key: str) -> None:
    command = "flow-sync pull"
    payload = {
        "tool_name": "Bash",
        "tool_input": {command_key: command, "yield_time_ms": 10_000},
    }
    result = run_hook(
        "codex-pre-tool-use",
        payload,
        env={"PLUGIN_ROOT": str(FLOW_ROOT)},
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    updated = output["hookSpecificOutput"]["updatedInput"]
    assert updated[command_key] == canonical_prologue(FLOW_ROOT) + command
    assert updated["yield_time_ms"] == 10_000


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"tool_input": None},
        {"tool_input": {}},
        {"tool_input": {"cmd": 42}},
        {"tool_input": {"cmd": "flow-sync pull", "command": "flow-sync pull"}},
        [],
    ],
)
def test_malformed_pre_tool_input_fails_open(payload: object) -> None:
    result = run_hook(
        "codex-pre-tool-use",
        payload,
        env={"PLUGIN_ROOT": str(FLOW_ROOT)},
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "Flow helper resolver inactive" in output["systemMessage"]
    assert "updatedInput" not in output


def test_malformed_pre_tool_json_fails_open() -> None:
    result = run_hook(
        "codex-pre-tool-use",
        {},
        env={"PLUGIN_ROOT": str(FLOW_ROOT)},
        raw_stdin="{not-json",
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "Flow helper resolver inactive" in output["systemMessage"]
    assert "updatedInput" not in output


def test_missing_plugin_root_fails_open() -> None:
    env = os.environ.copy()
    env.pop("PLUGIN_ROOT", None)
    result = subprocess.run(
        [str(HOOKS_ROOT / "codex-pre-tool-use")],
        input=json.dumps({"tool_input": {"cmd": "flow-sync pull"}}),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "Flow helper resolver inactive" in output["systemMessage"]
    assert "updatedInput" not in output


def test_shell_quotes_unusual_plugin_root(tmp_path: Path) -> None:
    plugin_root = tmp_path / "space ' quote $ dollar ` tick Юникод"
    shutil.copytree(FLOW_ROOT, plugin_root)
    command = "flow-sync pull"
    output = rewrite_pre_tool_use(
        {"tool_input": {"cmd": command}},
        plugin_root,
    )
    assert output is not None
    rewritten = output["hookSpecificOutput"]["updatedInput"]["cmd"]
    assert rewritten == canonical_prologue(plugin_root) + command
    subprocess.run(
        ["sh", "-n", "-c", rewritten],
        check=True,
        text=True,
        capture_output=True,
    )


@pytest.mark.parametrize(
    "command",
    ["my-flow-sync-wrapper", "echo flow-syncish", "git status --short"],
)
def test_similar_or_absent_helper_names_do_not_match(
    flow_plugin_root: Path,
    command: str,
) -> None:
    assert rewrite_pre_tool_use({"tool_input": {"cmd": command}}, flow_plugin_root) is None


def test_codex_session_uses_only_codex_adapter(flow_plugin_root: Path) -> None:
    context = render_session_context(
        {
            "PLUGIN_ROOT": str(flow_plugin_root),
            "CLAUDE_PLUGIN_ROOT": str(flow_plugin_root),
        }
    )
    assert "FLOW RUNTIME ACTIVE" in context
    assert "FLOW HARNESS: Codex" in context
    assert "FLOW HARNESS: Claude Code" not in context
    assert canonical_prologue(flow_plugin_root).strip() in context


def test_claude_session_uses_only_claude_adapter(flow_plugin_root: Path) -> None:
    context = render_session_context({"CLAUDE_PLUGIN_ROOT": str(flow_plugin_root)})
    assert "FLOW RUNTIME ACTIVE" in context
    assert "FLOW HARNESS: Claude Code" in context
    assert "FLOW HARNESS: Codex" not in context


@pytest.mark.parametrize(
    ("env", "adapter"),
    [
        ({"PLUGIN_ROOT": str(FLOW_ROOT)}, "FLOW HARNESS: Codex"),
        ({"CLAUDE_PLUGIN_ROOT": str(FLOW_ROOT)}, "FLOW HARNESS: Claude Code"),
    ],
)
def test_session_start_handler_emits_shared_context(
    env: dict[str, str],
    adapter: str,
) -> None:
    result = run_hook("session-start", {"hook_event_name": "SessionStart"}, env=env)
    assert result.returncode == 0
    output = json.loads(result.stdout)
    specific = output["hookSpecificOutput"]
    assert specific["hookEventName"] == "SessionStart"
    assert "FLOW RUNTIME ACTIVE" in specific["additionalContext"]
    assert adapter in specific["additionalContext"]


def test_session_start_handler_fails_open_without_plugin_root() -> None:
    env = os.environ.copy()
    env.pop("PLUGIN_ROOT", None)
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    result = subprocess.run(
        [str(HOOKS_ROOT / "session-start")],
        input=json.dumps({"hook_event_name": "SessionStart"}),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "Flow runtime adapter inactive" in output["systemMessage"]
    assert "additionalContext" not in output


@pytest.mark.parametrize("source", ["startup", "resume", "clear", "compact"])
def test_session_start_lifecycle_is_registered(source: str) -> None:
    config = json.loads((HOOKS_ROOT / "codex-hooks.json").read_text())
    matcher = config["hooks"]["SessionStart"][0]["matcher"]
    assert re.fullmatch(matcher, source)


def test_hook_configs_separate_codex_pre_tool_use() -> None:
    claude_config = json.loads((HOOKS_ROOT / "claude-hooks.json").read_text())
    codex_config = json.loads((HOOKS_ROOT / "codex-hooks.json").read_text())
    assert set(claude_config["hooks"]) == {"SessionStart"}
    assert set(codex_config["hooks"]) == {"SessionStart", "PreToolUse"}
    assert codex_config["hooks"]["PreToolUse"][0]["matcher"] == "^Bash$"


def test_manifests_select_harness_specific_hook_configs() -> None:
    claude_manifest = json.loads((FLOW_ROOT / ".claude-plugin" / "plugin.json").read_text())
    codex_manifest = json.loads((FLOW_ROOT / ".codex-plugin" / "plugin.json").read_text())
    assert (codex_manifest["name"], codex_manifest["version"]) == (
        claude_manifest["name"],
        claude_manifest["version"],
    )
    assert claude_manifest["hooks"] == "./hooks/claude-hooks.json"
    assert codex_manifest["hooks"] == "./hooks/codex-hooks.json"
    assert codex_manifest["skills"] == "./skills/"


def test_session_context_stays_below_codex_hook_limit(flow_plugin_root: Path) -> None:
    context = render_session_context(
        {
            "PLUGIN_ROOT": str(flow_plugin_root),
            "CLAUDE_PLUGIN_ROOT": str(flow_plugin_root),
        }
    )
    assert len(context.encode()) // 4 < 2_500


def test_hook_python_sources_parse_as_python_39() -> None:
    sources = [HOOKS_ROOT / "_runtime.py", HOOKS_ROOT / "session-start", HOOKS_ROOT / "codex-pre-tool-use"]
    for source_path in sources:
        ast.parse(
            source_path.read_text(),
            filename=str(source_path),
            feature_version=(3, 9),
        )


def test_hook_handlers_are_executable() -> None:
    assert os.access(HOOKS_ROOT / "session-start", os.X_OK)
    assert os.access(HOOKS_ROOT / "codex-pre-tool-use", os.X_OK)
