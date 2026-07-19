"""Static contracts for Flow's shared (harness-neutral) skill bodies.

These tests guard the migration away from Claude-specific vocabulary
(TodoWrite, Skill tool, subagent dispatch syntax) in skills that are shared
across harnesses, and guard the Bash grant shape for the extracted flow-*
helpers. `sonar-sync` is the sole named exception (not yet migrated).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

FLOW_ROOT = Path(__file__).resolve().parents[2]
MIGRATED = {
    path
    for path in (FLOW_ROOT / "skills").glob("*/SKILL.md")
    if path.parent.name not in {"sonar-sync", "review-comments", "create-codex-agents"}
}
FORBIDDEN = (
    "TodoWrite",
    "Skill tool",
    "subagent_type",
    'model="haiku"',
    'model="sonnet"',
    'model="opus"',
)


@pytest.mark.parametrize("skill", sorted(MIGRATED))
def test_migrated_skill_body_uses_semantic_actions(skill: Path) -> None:
    body = skill.read_text().split("---", 2)[-1]
    assert not [term for term in FORBIDDEN if term in body]


def test_every_skill_has_one_physical_skill_md() -> None:
    physical = list((FLOW_ROOT / "skills").glob("*/SKILL.md"))
    assert len(physical) == len({path.parent.name for path in physical})
    assert not [path for path in physical if path.is_symlink() or path.parent.is_symlink()]
    assert not list(FLOW_ROOT.glob("skills-*/*/SKILL.md"))


def test_all_executable_helpers_use_reserved_prefix() -> None:
    executable = [path for path in (FLOW_ROOT / "bin").iterdir() if path.is_file() and os.access(path, os.X_OK)]
    assert all(path.name.startswith("flow-") for path in executable)


FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
INLINE = re.compile(r"`([^`\n]+)`")
HELPER = re.compile(r"(?<![A-Za-z0-9_-])(flow-[a-z0-9][a-z0-9-]*)")
SHELL_END = "|;&)"


def command_snippets(body: str) -> list[str]:
    fenced = FENCE.findall(body)
    without_fences = FENCE.sub("", body)
    return fenced + INLINE.findall(without_fences)


def helper_forms(body: str) -> set[tuple[str, str]]:
    forms: set[tuple[str, str]] = set()
    for snippet in command_snippets(body):
        for line in snippet.splitlines():
            for match in HELPER.finditer(line):
                rest = line[match.end() :].lstrip()
                form = "bare" if not rest or rest[0] in SHELL_END else "args"
                forms.add((match.group(1), form))
    return forms


def allowed_tools(text: str) -> set[str]:
    frontmatter = text.split("---", 2)[1]
    match = re.search(r"^allowed-tools:\s*(.+)$", frontmatter, re.MULTILINE)
    return set() if match is None else set(match.group(1).split())


def test_helper_parsing_is_not_vacuous() -> None:
    # Guards against a mis-transcribed FENCE/INLINE/HELPER regex silently
    # matching nothing, which would make the forbidden-term and grant tests
    # pass vacuously. If this fails, the parsing regexes are broken.
    sample = "Run `flow-sync pull` and the bare `flow-actor`."
    forms = helper_forms(sample)
    assert ("flow-sync", "args") in forms
    assert ("flow-actor", "bare") in forms


@pytest.mark.parametrize("skill", sorted(MIGRATED))
def test_helper_forms_have_exact_claude_grants(skill: Path) -> None:
    text = skill.read_text()
    grants = allowed_tools(text)
    assert "Bash(flow-*)" not in grants
    for helper, form in helper_forms(text.split("---", 2)[-1]):
        expected = f"Bash({helper})" if form == "bare" else f"Bash({helper}:*)"
        assert expected in grants, f"{skill.parent.name}: missing {expected}"


@pytest.mark.parametrize("skill", sorted(MIGRATED))
def test_helpers_remain_literal_bare_names(skill: Path) -> None:
    body = skill.read_text().split("---", 2)[-1]
    assert "../../bin/flow-" not in body
    assert "/plugins/flow/bin/flow-" not in body
    assert not re.search(r"flow-\$|flow-\{", body)


def test_frontmatter_exception_is_only_sonar_sync() -> None:
    assert {"sonar-sync"} == {
        path.parent.name
        for path in (FLOW_ROOT / "skills").glob("*/SKILL.md")
        if path not in MIGRATED and path.parent.name not in {"review-comments", "create-codex-agents"}
    }
