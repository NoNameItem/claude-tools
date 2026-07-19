"""Tests for flow-codex-agent-setup / _codex_agents.py (optional Codex profile setup).

Security-sensitive helper: it must never leak or read unrelated `.codex` state (notably
`.codex/config.toml`, which can hold machine-local credentials), never overwrite an existing
file, never follow a symlink out of the project root, and must treat any ambiguous identity
as a global reason to create nothing (uniqueness of the three required names cannot be
proven). These tests exercise real filesystem behavior (real tmp dirs, real subprocesses,
real git worktrees) rather than mocking the classification logic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

BIN = Path(__file__).parent.parent
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import _codex_agents  # noqa: E402  (import after BIN is on sys.path — sibling-module pattern)
from _codex_agents import create_profiles, inspect_project  # noqa: E402

# NOTE: this module deliberately does not `from conftest import run_helper`. With
# `plugins/flow/bin/tests/__init__.py` present, pytest's "prepend" import mode loads
# conftest.py as `tests.conftest` (not bare `conftest`), so that import fails for every
# test module in this directory today — a pre-existing repo-wide regression from
# `plugins/flow/bin/tests/__init__.py` (added in a prior, unrelated commit), not something
# introduced by or in scope for this change. `run_setup` below inlines the same
# subprocess-based helper so this file collects and runs correctly on its own.


def _run_helper(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a bin/ helper via the current interpreter; return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(BIN / name), *args],
        capture_output=True,
        text=True,
        check=False,
    )


# --- shared test helpers -----------------------------------------------------------------


def run_setup(command: str, project_root: Path, request_obj: dict[str, object] | None = None) -> dict[str, object]:
    """Run the CLI end-to-end via subprocess; return the parsed JSON stdout.

    The request JSON is written to a throwaway temp file OUTSIDE `project_root` (mirroring
    the skill's own "write outside `.codex/`" rule) so a test project always starts from
    exactly the files the test itself created.
    """
    args = [command, "--project-root", str(project_root)]
    request_path = None
    if request_obj is not None:
        fd, request_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as stream:
            json.dump(request_obj, stream)
        args += ["--request-json", request_path]
    try:
        result = _run_helper("flow-codex-agent-setup", *args)
        assert result.stdout, f"no stdout; stderr was: {result.stderr}"
        return json.loads(result.stdout)
    finally:
        if request_path is not None:
            Path(request_path).unlink(missing_ok=True)


def request(*profiles: tuple[str, str, str]) -> dict[str, object]:
    return {"profiles": [{"tier": tier, "model": model, "reasoning": reasoning} for tier, model, reasoning in profiles]}


def make_request_for_all_profiles() -> dict[str, object]:
    return request(
        ("fast", "account-fast", "low"),
        ("balanced", "account-balanced", "medium"),
        ("strongest", "account-strong", "high"),
    )


def compatible_profile(name: str, model: str, reasoning: str) -> str:
    """Render a fully Flow-compatible profile for whichever tier owns `name`."""
    tier = next(t for t, n in _codex_agents.PROFILE_NAMES.items() if n == name)
    return _codex_agents.render_profile(tier, model, reasoning)


def profile_data(tier: str) -> dict[str, object]:
    """A baseline Flow-compatible field set for `tier`, for mutation in contract tests."""
    return {
        "name": _codex_agents.PROFILE_NAMES[tier],
        "description": _codex_agents.DESCRIPTIONS[tier],
        "model": "account-model",
        "model_reasoning_effort": "low",
        "developer_instructions": _codex_agents.DEVELOPER_INSTRUCTIONS,
    }


def write_profile(project_root: Path, filename: str, data: dict[str, object]) -> Path:
    agents = project_root / ".codex" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{key} = {json.dumps(value)}\n" for key, value in data.items())
    path = agents / filename
    path.write_text(text)
    return path


def make_symlink_component(tmp_path: Path, link_name: str, target: Path) -> None:
    link = tmp_path / link_name
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)


# --- Step 2 tests (verbatim from the task brief) ------------------------------------------


def test_empty_project_previews_three_profiles(tmp_path: Path) -> None:
    result = run_setup(
        "preview",
        tmp_path,
        request(
            ("fast", "account-fast", "low"),
            ("balanced", "account-balanced", "medium"),
            ("strongest", "account-strong", "high"),
        ),
    )
    assert [item["name"] for item in result["missing"]] == [
        "flow-fast",
        "flow-balanced",
        "flow-strongest",
    ]
    assert not (tmp_path / ".codex").exists()


def test_profile_identity_comes_from_toml_name(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    (agents / "unexpected.toml").write_text(compatible_profile("flow-fast", "custom", "xhigh"))
    result = run_setup("inspect", tmp_path)
    assert result["profiles"]["flow-fast"]["status"] == "compatible"


def test_create_never_overwrites_a_concurrent_file(tmp_path: Path) -> None:
    plan = make_request_for_all_profiles()
    run_setup("preview", tmp_path, plan)
    target = tmp_path / ".codex" / "agents" / "flow-fast.toml"
    target.parent.mkdir(parents=True)
    target.write_text('name = "someone-else"\n')
    result = run_setup("create", tmp_path, plan)
    assert target.read_text() == 'name = "someone-else"\n'
    assert result["profiles"]["flow-fast"]["status"] == "conflict"
    assert {item["name"] for item in result["created"]} == {
        "flow-balanced",
        "flow-strongest",
    }


@pytest.mark.parametrize("link_name", [".codex", ".codex/agents", ".codex/agents/flow-fast.toml"])
def test_symlinked_target_is_rejected(tmp_path: Path, link_name: str) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    make_symlink_component(tmp_path, link_name, outside)
    result = run_setup("create", tmp_path, make_request_for_all_profiles())
    assert result["created"] == []
    assert "symlink" in json.dumps(result["conflicts"]).lower()


def test_duplicate_internal_name_conflicts_only_that_profile(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    text = compatible_profile("flow-fast", "custom", "low")
    (agents / "one.toml").write_text(text)
    (agents / "two.toml").write_text(text)
    result = run_setup("inspect", tmp_path)
    assert result["profiles"]["flow-fast"]["status"] == "conflict"
    assert result["profiles"]["flow-balanced"]["status"] == "missing"


def test_required_filename_with_another_name_is_a_conflict(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    (agents / "flow-fast.toml").write_text('name = "other-agent"\n')
    result = run_setup("inspect", tmp_path)
    assert result["profiles"]["flow-fast"]["status"] == "conflict"


@pytest.mark.parametrize(
    ("model", "reasoning"),
    [
        ("", "low"),
        ("account-model", ""),
        ("account-model", "unsupported"),
    ],
)
def test_invalid_requested_values_are_rejected(
    tmp_path: Path,
    model: str,
    reasoning: str,
) -> None:
    result = run_setup("preview", tmp_path, request(("fast", model, reasoning)))
    assert result["missing"] == []
    assert result["profiles"]["flow-fast"]["status"] == "invalid"


def test_compatible_contract_allows_user_model_edits(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    (agents / "flow-fast.toml").write_text(compatible_profile("flow-fast", "user-edited-model", "ultra"))
    result = run_setup("inspect", tmp_path)
    assert result["profiles"]["flow-fast"]["status"] == "compatible"


@pytest.mark.parametrize(
    "mutation",
    [
        {"description": "different"},
        {"developer_instructions": "broaden the task"},
        {"sandbox_mode": "danger-full-access"},
    ],
)
def test_non_model_contract_changes_conflict(
    tmp_path: Path,
    mutation: dict[str, str],
) -> None:
    write_profile(tmp_path, "flow-fast.toml", profile_data("fast") | mutation)
    result = run_setup("inspect", tmp_path)
    assert result["profiles"]["flow-fast"]["status"] == "conflict"


def test_ambiguous_malformed_toml_blocks_all_creation(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    (agents / "broken.toml").write_text("name = [not valid TOML\n")
    result = run_setup("create", tmp_path, make_request_for_all_profiles())
    assert result["created"] == []
    assert result["global_conflicts"]


def test_malformed_toml_with_required_name_blocks_only_that_profile(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    (agents / "broken.toml").write_text('name = "flow-fast"\nmodel = [broken\n')
    result = run_setup("inspect", tmp_path)
    assert result["profiles"]["flow-fast"]["status"] == "conflict"
    assert result["profiles"]["flow-balanced"]["status"] == "missing"


def test_inspection_never_reads_unrelated_codex_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('sonar_token = "do-not-read"\n')
    original = Path.read_text

    def guarded_read(path: Path, *args: object, **kwargs: object) -> str:
        if path == config:
            msg = "must not read .codex/config.toml"
            raise AssertionError(msg)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    inspect_project(tmp_path)


def test_linked_worktree_warns_and_preserves_unrelated_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    worktree = tmp_path / "linked"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Flow Test",
            "-c",
            "user.email=flow@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(source), "worktree", "add", "-q", str(worktree)], check=True)
    gitignore = worktree / ".gitignore"
    gitignore.write_text(".local-only\n")
    config = worktree / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('machine_token = "unchanged"\n')
    user_agent = tmp_path / "home" / ".codex" / "agents" / "personal.toml"
    user_agent.parent.mkdir(parents=True)
    user_agent.write_text('name = "personal"\n')
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    before = {path: path.read_bytes() for path in (gitignore, config, worktree / ".git", user_agent)}

    result = create_profiles(worktree, make_request_for_all_profiles())

    assert result["linked_worktree"] is True
    assert all(path.read_bytes() == content for path, content in before.items())
