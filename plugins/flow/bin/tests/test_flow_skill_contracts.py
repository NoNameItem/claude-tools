"""Static contracts for Flow's shared (harness-neutral) skill bodies.

These tests guard the migration away from Claude-specific vocabulary
(TodoWrite, Skill tool, subagent dispatch syntax) in skills that are shared
across harnesses, and guard the Bash grant shape for the extracted flow-*
helpers. `sonar-sync` is the sole named exception (not yet migrated).
"""

# ruff: noqa: INP001  # bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

from __future__ import annotations

import json
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


REVIEW_DISPATCHES = (
    ("reviewer", "balanced", "read-only", "verdict JSON contract"),
    ("researcher", "balanced", "read-only", "site inventory and evidence contract"),
    ("implementer", "fast", "workspace-write", "OK/failure-description output contract"),
    ("skeptic", "balanced", "read-only", "clean-result output contract"),
)


def test_review_comments_declares_semantic_dispatch_contracts() -> None:
    body = (FLOW_ROOT / "skills" / "review-comments" / "SKILL.md").read_text()
    normalized_body = re.sub(r"\s+", " ", body)
    for role, tier, access, output_marker in REVIEW_DISPATCHES:
        assert role in body
        assert f"`{tier}`" in body
        assert access in body
        assert output_marker in normalized_body
    for term in ("subagent_type", 'model="haiku"', 'model="sonnet"', "Read tool", "Write tool"):
        assert term not in body


# --- create-codex-agents: purpose-built setup skill (Task 5) --------------------------------
#
# Excluded from MIGRATED (it legitimately names Codex configuration concepts) and from the
# sonar-sync-only frontmatter-exception check above, per the design. It still must: declare the
# setup helper's grants exactly (both the bare and args forms, regardless of which forms the
# prose happens to use), never hard-code an account-specific model slug (model IDs are always
# asked for, never guessed), and never name a concrete harness's file-editing tool (it must stay
# usable by any harness that can safely write project files).

CODEX_AGENTS_SKILL = FLOW_ROOT / "skills" / "create-codex-agents" / "SKILL.md"

FORBIDDEN_MODEL_SLUGS = (
    "gpt-3",
    "gpt-4",
    "gpt-5",
    "o1-",
    "o3-",
    "o4-",
    "codex-mini",
    "claude-3",
    "claude-opus",
    "claude-sonnet",
    "claude-haiku",
)

FORBIDDEN_HARNESS_FILE_TOOLS = (
    "write tool",
    "edit tool",
    "read tool",
    "apply_patch",
    "str_replace_editor",
    "notebookedit",
)


def test_create_codex_agents_skill_exists() -> None:
    assert CODEX_AGENTS_SKILL.is_file()


def test_create_codex_agents_declares_exact_helper_grants() -> None:
    # Deliberately does not reuse the generic `helper_forms` scan used for MIGRATED skills:
    # this skill's prose legitimately contains the Codex profile names `flow-fast` /
    # `flow-balanced` / `flow-strongest` as data values (not bin/ helper invocations), which
    # match the same `flow-[a-z0-9-]+` pattern the generic scanner treats as a command needing
    # its own grant. Check exactly what the design requires instead: both exact forms of the
    # one real helper this skill drives, and no unscoped wildcard.
    grants = allowed_tools(CODEX_AGENTS_SKILL.read_text())
    assert "Bash(flow-codex-agent-setup)" in grants
    assert "Bash(flow-codex-agent-setup:*)" in grants
    assert "Bash(flow-*)" not in grants


def test_create_codex_agents_has_no_hardcoded_model_slug() -> None:
    body = CODEX_AGENTS_SKILL.read_text().lower()
    hits = [slug for slug in FORBIDDEN_MODEL_SLUGS if slug in body]
    assert not hits, f"create-codex-agents hard-codes a model slug: {hits}"


def test_create_codex_agents_names_no_concrete_harness_file_tool() -> None:
    body = CODEX_AGENTS_SKILL.read_text().lower()
    hits = [name for name in FORBIDDEN_HARNESS_FILE_TOOLS if name in body]
    assert not hits, f"create-codex-agents names a concrete harness file tool: {hits}"


# --- Task 6: documentation contracts -----------------------------------------------------


def test_readme_documents_codex_runtime_contract() -> None:
    readme = (FLOW_ROOT / "README.md").read_text()
    for required in (
        "$flow:start",
        "/flow:start",
        "/hooks",
        "allow_managed_hooks_only",
        "flow:create-codex-agents",
        "Codex CLI 0.144.6",
        "codex -m",
        "one active Flow plugin version",
        "POSIX",
    ):
        assert required in readme


def test_old_allowed_tools_design_is_marked_superseded() -> None:
    text = (FLOW_ROOT.parents[1] / "docs/superpowers/specs/2026-07-07-flow-allowed-tools-audit-design.md").read_text()
    assert "Superseded for Codex" in text
    assert "2026-07-17-flow-codex-support-design.md" in text


# --- Task: persistent per-PR review ledger (claude-tools-elf.39) -----------------------------

REVIEW_COMMENTS_SKILL = FLOW_ROOT / "skills" / "review-comments" / "SKILL.md"


def test_review_comments_grants_and_drives_the_ledger() -> None:
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert "Bash(flow-review-ledger:*)" in allowed_tools(text)
    for invocation in (
        "flow-review-ledger reconcile --meta",
        "flow-review-ledger get --ref",
        "flow-review-ledger record",
        "flow-review-ledger stats",
    ):
        assert invocation in text, f"review-comments is missing `{invocation}`"


def test_review_comments_reads_rows_not_the_collector_document() -> None:
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert "row-{ref}.json" in text  # Phase 3 analyses a per-ref extract
    assert "flow-comment-card --ledger" in text
    # Whitespace-tolerant: `--meta` must not follow `flow-comment-card` even across a line wrap
    # or multiple spaces (the source prose wraps long lines, which a literal substring check misses).
    assert not re.search(r"flow-comment-card\s+--meta\b", text)
    # Phase 3 must not point a subagent at the whole collector document any more.
    # Whitespace-tolerant like the guard above: a line wrap must not defeat the check.
    assert not re.search(r"from\s+the\s+collector\s+output\s+at", text)


def test_review_comments_branches_on_kind_not_the_summary_sentinel() -> None:
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert "`kind`" in text
    assert not re.search(r'`path\s*==\s*"\(summary\)"`\s+or\s+`path`\s+is\s+null', text)


def test_review_comments_edge_case_points_at_the_ledger_not_metadata() -> None:
    # Phase 2 states the rule: every later phase looks refs up in the ledger, never in
    # metadata.json. The "Very Large Number of Comments" edge case must follow the same rule
    # for the subset it selects, instead of contradicting it.
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert not re.search(r"look\s+each\s+ref\s+up\s+in\s+`metadata\.json`", text)
    edge_case = text.split("Very Large Number of Comments", 1)[1].split("###", 1)[0]
    assert "the ledger" in edge_case
    assert "flow-review-ledger get" in edge_case


def test_review_comments_good_example_teaches_the_reconcile_flow() -> None:
    # The canonical "GOOD" example must not describe the pre-Task-10 flow (no reconcile step,
    # subagents reading metadata.json directly) — it should teach collect -> reconcile -> working
    # set -> per-ref row extract, consistent with Phase 2/3.
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert not re.search(r"each\s+subagent\s+reading\s+its\s+comment\s+from\s+metadata\.json", text)
    good_example = text.split("### GOOD:", 1)[1].split("### ", 1)[0]
    assert "reconcile" in good_example
    assert "flow-review-ledger get" in good_example


def test_review_comments_followup_description_reads_the_ledger_row() -> None:
    # 5.4's follow-up description must not read the reviewer's comment text from metadata.json
    # (transient collector output) -- it must point at the ledger row, like the rest of Phase 3-5.
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert not re.search(r"the\s+reviewer's\s+comment\s+text\s+read\s+from\s+`metadata\.json`", text)


def test_review_comments_captures_the_reply_id_for_thread_mark() -> None:
    # 5.7a sets thread_mark to "the id of the reply you just posted", but nothing in 5.7 tells
    # the agent to capture that id from the gh/glab response. Pin that 5.7 now does.
    text = REVIEW_COMMENTS_SKILL.read_text()
    phase_5_7 = text.split("#### 5.7. Reply on the platform", 1)[1].split("#### 5.7a", 1)[0]
    assert re.search(r"capture", phase_5_7, re.IGNORECASE)
    assert "thread_mark" in phase_5_7


def test_review_comments_decisions_example_always_carries_thread_mark() -> None:
    # `record` writes `thread_mark` only when the entry supplies it (flow-review-ledger:212), so a
    # `done` entry that omits it keeps its pre-reply mark: the reply the agent posts has a higher
    # id, `reopen_if_advanced` fires, and the settled finding re-opens every round. The canonical
    # example must teach the rule 5.7a states. A threadless row (GitHub's `kind == "summary"`)
    # carries an explicit `null`, so the key is present on every `done` entry without exception.
    text = REVIEW_COMMENTS_SKILL.read_text()
    block = text.split("$FLOW_RC_DIR/decisions.json", 1)[1].split("```json", 1)[1].split("```", 1)[0]
    decisions = json.loads(block)
    missing = sorted(
        ref for ref, entry in decisions.items() if entry.get("status") == "done" and "thread_mark" not in entry
    )
    assert missing == [], f"done entries without `thread_mark` (they will re-open): {missing}"


def test_review_comments_5_7a_states_the_null_merge_rule() -> None:
    # `record` merges a decisions entry the way JSON merge does: an ABSENT key is a no-op, an
    # explicit `null` CLEARS the field. 5.7a's own example depends on the clear (`C1` carries
    # `"followup_task_id": null` to drop the id an earlier `follow_up` round filed), so the prose
    # must state that rule -- not the stale "record writes the field only when the entry supplies
    # a non-null id", which would make the example inert and leave a stale task id on the row.
    text = REVIEW_COMMENTS_SKILL.read_text()
    section = text.split("#### 5.7a", 1)[1].split("#### 5.8", 1)[0]
    # Markdown emphasis markers sit inside the sentence (`**only** when ...`), so a plain
    # substring guard never matches the prose it means to forbid -- match around them.
    assert not re.search(r"only\W{0,4}when the entry supplies a non-null id", section)
    assert re.search(r"\bclears\b", section), "5.7a must say that an explicit null clears the field"
    assert re.search(r"\bomit", section), "5.7a must say that an omitted key leaves the value unchanged"


def test_review_comments_replies_to_the_ledger_thread_id() -> None:
    # The ledger row stores `thread_id` only (new_row + SNAPSHOT_FIELDS) — never `comment_id` or
    # `discussion_id`. A reply template keyed on those cannot be filled from `flow-review-ledger
    # get`, and metadata.json is off limits from Phase 2 on.
    text = REVIEW_COMMENTS_SKILL.read_text()
    phase = text.split("#### 5.7. Reply on the platform", 1)[1].split("#### 5.7a", 1)[0]
    assert "{thread_id}" in phase
    assert "{comment_id}" not in phase
    assert "{discussion_id}" not in phase
    # The no-reply-target case is GitHub's summary; discriminate it by `kind`, not a missing field
    assert not re.search(r"comment_id\s*==\s*null", text)


def test_review_comments_cap_gates_on_a_count_reconcile_emits() -> None:
    # reconcile prints counts {total, open, skipped, pending, done, working}. `counts.actionable`
    # is the COLLECTOR's key: gating on it reads a missing key and the large-PR cap never fires.
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert not re.search(r"counts\.actionable", text)
    assert "counts.working" in text


def test_review_comments_already_replied_does_not_mute_a_resurfaced_row() -> None:
    # `already_replied` is true exactly when the last replier was our own account — which is the
    # documented "a human posted an instruction in the thread" re-open case. A blanket
    # do-not-reply rule triages the re-surfaced row and then silently drops its reply.
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert not re.search(r"Do\s+NOT\s+reply\s+to\s+comments\s+where\s+`already_replied`\s+is\s+true", text)
    phase = text.split("#### 5.7. Reply on the platform", 1)[1].split("#### 5.7a", 1)[0]
    assert "already_replied" in phase
    assert "re-surfaced" in phase


def test_review_comments_platform_table_points_at_the_reconcile_output() -> None:
    # Phase 2 documents `reconcile`'s output shape, not the collector document's schema.
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert not re.search(r"Phase\s+2\s+`metadata\.json`\s+schema", text)


# --- Task 11: review-loop reports ledger stats, done purges the ledger -----------------------


def test_review_loop_drops_repeat_tracking_for_ledger_exclusion() -> None:
    text = (FLOW_ROOT / "skills" / "review-loop" / "SKILL.md").read_text()
    assert "повторно" not in text  # recurrence detection was cut; done rows never reach round output
    assert "Repeat-tracking is in-session memory" not in text
    assert "flow-review-ledger stats" in text
    assert "Bash(flow-review-ledger:*)" in allowed_tools(text)


def test_done_purges_the_ledger() -> None:
    text = (FLOW_ROOT / "skills" / "done" / "SKILL.md").read_text()
    assert "--json state,url,number" in text
    assert "flow-review-ledger purge" in text
    assert "Bash(flow-review-ledger:*)" in allowed_tools(text)


def test_readme_documents_the_ledger_helper() -> None:
    readme = (FLOW_ROOT / "README.md").read_text()
    assert "flow-review-ledger" in readme


# --- Follow-up: thread_mark null means threadless, not "is a summary" (claude-tools-elf.39) --


def test_review_comments_thread_mark_null_rule_is_scoped_to_threadless_rows() -> None:
    # A GitHub review-body summary (`kind == "summary"`) is threadless, so `thread_mark: null`
    # is correct for it. But a GitLab general discussion is ALSO `kind == "summary"` (see
    # gl_collect) while carrying a real thread and reply target — flow-review-ledger's
    # `reopen_if_advanced`/`new_row` key on `_ledger.last_reply_id`, not `kind`, precisely
    # because "summary" alone does not imply "no thread". The unscoped "a summary row/rows"
    # phrasing must not reappear here.
    text = REVIEW_COMMENTS_SKILL.read_text()
    # Whitespace-tolerant: a line wrap must not defeat the guard (this repo has shipped a
    # substring-only guard that a wrap silently evaded, twice).
    assert not re.search(r"a\s+summary\s+row\s+clears\s+`thread_mark`", text)
    assert not re.search(r"`null`\s*—\s*a\s+summary\s+has\s+no\s+thread", text)
    assert not re.search(r"`null`\s+is\s+for\s+summary\s+rows\s+only", text)
    # The corrected rule must be present: null means threadless, keyed on the thread, not `kind`.
    required_field_section = text.split("**`thread_mark` is a REQUIRED field", 1)[1].split("#### 5.8", 1)[0]
    assert re.search(r"\bthreadless\b", required_field_section)
    assert re.search(r"GitLab", required_field_section)
