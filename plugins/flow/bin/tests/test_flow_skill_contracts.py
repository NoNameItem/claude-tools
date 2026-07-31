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


def section(text: str, start: str, end: str) -> str:
    """The slice of `text` between the first `start` marker and the following `end` marker."""
    return text.split(start, 1)[1].split(end, 1)[0]


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


def test_review_comments_never_directs_ref_lookups_at_metadata_json() -> None:
    # Every phase after Phase 2 looks a ref up in the ledger (`flow-review-ledger get`,
    # `flow-comment-card --ledger`), never in the transient `metadata.json` the collector wrote.
    # This guard used to be scoped to the large-PR cap's selected subset specifically; the cap
    # (and its edge case) is gone (Task 7), but the underlying rule is general and must not regress.
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert not re.search(r"look\s+each\s+ref\s+up\s+in\s+`metadata\.json`", text)


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


def test_review_comments_checkpoints_each_irreversible_side_effect() -> None:
    """A filed `bd` task and a posted reply are irreversible and both loops are sequential, so
    deferring every `record` to 5.7a means a mid-batch failure loses the record of the refs that
    already succeeded — and the next round re-files the same follow-up or re-posts the same reply
    against a row that never learned what happened. Both loops must therefore record each ref as it
    lands, and 5.4's checkpoint must stay `open` (the task exists, the reply does not yet — and
    `open`/`done` is the whole status enum now, so there is no third "task filed" state), or a
    `done` row would settle a finding that was never answered on the platform."""
    text = REVIEW_COMMENTS_SKILL.read_text()
    follow_up = text.split("#### 5.4.", 1)[1].split("#### 5.5.", 1)[0]
    assert "checkpoint-" in follow_up, "5.4 must record each created task before the next `bd create`"
    assert '"status": "open"' in follow_up, "the 5.4 checkpoint stays `open` — the reply is not posted yet"
    assert "followup_task_id" in follow_up, "the checkpoint must carry the task id that prevents a duplicate"
    # The checkpoint only prevents a duplicate if something READS it back: `bd create` has no
    # idempotency key, so a `pending` row re-triaged as `follow-up` files a second task unless 5.4
    # looks up the stored id first. The write without the read is a no-op dressed as a fix.
    assert "flow-review-ledger get" in follow_up, "5.4 must read the row before creating a task"
    assert re.search(r"do not call `bd create`", follow_up), "5.4 must skip `bd create` when a task id already exists"
    reply = text.split("#### 5.7. Reply on the platform", 1)[1].split("#### 5.7a", 1)[0]
    assert "checkpoint-" in reply, "5.7 must record each ref as its reply is accepted"
    assert reply.count("flow-review-ledger record") >= 1, "5.7's checkpoint must call `record`"


def test_review_comments_5_7a_states_the_null_merge_rule() -> None:
    # `record` merges a decisions entry the way JSON merge does: an ABSENT key is a no-op, an
    # explicit `null` CLEARS the field. 5.7a's own example depends on the clear (`C1` carries
    # `"followup_task_id": null` to drop the id an earlier `follow_up` round filed), so the prose
    # must state that rule -- not the stale "record writes the field only when the entry supplies
    # a non-null id", which would make the example inert and leave a stale task id on the row.
    text = REVIEW_COMMENTS_SKILL.read_text()
    merge_rule_section = text.split("#### 5.7a", 1)[1].split("#### 5.8", 1)[0]
    # Markdown emphasis markers sit inside the sentence (`**only** when ...`), so a plain
    # substring guard never matches the prose it means to forbid -- match around them.
    assert not re.search(r"only\W{0,4}when the entry supplies a non-null id", merge_rule_section)
    assert re.search(r"\bclears\b", merge_rule_section), "5.7a must say that an explicit null clears the field"
    assert re.search(r"\bomit", merge_rule_section), "5.7a must say that an omitted key leaves the value unchanged"


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


def test_done_purges_the_ledger_only_once_the_pr_is_terminal() -> None:
    """The purge destroys durable review memory with no backup and no copy in the repo, so it must
    key on the one signal that says the review is over: the PR's own state. Branch deletion is the
    wrong gate in BOTH directions — a branch is routinely kept on purpose after a merge (history,
    re-reading the review), which would strand a settled ledger forever, and a branch deleted while
    the PR is still open would license purging live memory, after which the next
    `flow:review-comments` re-imports every settled finding and can duplicate replies and follow-up
    tasks. Step 1 therefore has to capture `.state`, and Step 8 has to gate on it."""
    text = (FLOW_ROOT / "skills" / "done" / "SKILL.md").read_text()
    assert "PR_STATE" in text, "Step 1 must capture the PR state the purge gate reads"
    assert "skip the purge" in text, "the purge must be skipped while the PR is still open"
    # A CLOSED PR is REOPENABLE, so purging it is an irreversible choice made on the user's behalf:
    # a reopened PR re-imports every settled finding without its decisions or follow-up ids. Only
    # `MERGED` may purge unattended; `CLOSED` must ask. A gate that lumps the two together (the
    # first shape of this fix) silently destroys the ledger of a PR whose review can still resume.
    step_8 = text.split("8. **Purge the PR's review ledger**", 1)[1].split("**Error handling:**", 1)[0]
    assert "**`MERGED`** → purge" in step_8, "a merged PR purges unattended"
    assert re.search(r"\*\*`CLOSED`\*\*\s*→\s*\*\*ask\*\*", step_8), "a closed PR must ask before purging"
    assert "(yes/no)" in step_8, "the CLOSED prompt must be plain text"
    assert "reopen" in step_8, "the prompt must say why: a closed PR can be reopened"
    assert "never on branch deletion" in text or "never branch deletion" in text, (
        "the gate must be stated as PR state, not branch deletion"
    )
    assert "only if step 6 actually deleted the local branch" not in text, "the branch-delete gate must be gone"


def test_review_comments_states_the_real_working_set_rule() -> None:
    """Phase 2's prose is what the agent reasons from when the tool's output surprises it, so a
    stale rule there can reintroduce the very bug the code just closed. Membership is no longer
    "non-terminal status" alone, and (Task 7) it is no longer the raw `resolved` boolean either —
    `reconcile` now recomputes a `platform_state` axis (`live`/`resolved`/`absent`) every round, and
    membership is `status == "open"` AND `platform_state == "live"`. A thread the platform reports
    as resolved leaves the working set while its `status` may stay `open`, and the old claim that
    resolution "moves it to `done`" is wrong in exactly the case that matters (a degraded resolution
    side-query)."""
    text = (FLOW_ROOT / "skills" / "review-comments" / "SKILL.md").read_text()
    assert "every row in a non-terminal status:" not in text, "the working-set rule must also name `resolved`"
    assert '`platform_state == "live"`' in text
    assert "moves it to `done` without a reply" not in text, "resolution no longer changes the status"


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


def test_review_comments_every_ledger_get_carries_a_locator() -> None:
    # `flow-review-ledger get` has no implicit current-PR context: without `--meta` (or
    # `--url`/`--number`) `resolve_unit` yields ("", None) and `ledger_path` exits 2 before the row
    # is ever read. A documented command that cannot run as written fails on EVERY invocation, so
    # check the whole file rather than one phase -- the Phase 3 example is correct and would mask a
    # broken sibling under a plain substring check.
    # `--ref` is what distinguishes an INVOCATION from prose naming the subcommand ("analysed via
    # `flow-review-ledger get`"), which needs no flags and must not fail this test.
    text = REVIEW_COMMENTS_SKILL.read_text()
    for match in re.finditer(r"flow-review-ledger get\s+--ref\b[^`\n]*", text):
        command = match.group(0)
        assert "--meta" in command or "--url" in command, f"`{command.strip()}` has no locator flag"


def test_review_comments_5_7a_reacts_to_a_failed_record() -> None:
    # `record` exits non-zero when a decisions ref has no row: those transitions were NOT made
    # durable, so the finding keeps a working status and re-surfaces next round -- after its reply
    # was already posted. Nothing reads the JSON payload, so the exit code is the only signal, and
    # the prose must tell the agent to act on it instead of assuming the round was recorded.
    text = REVIEW_COMMENTS_SKILL.read_text()
    record_section = text.split("#### 5.7a", 1)[1].split("#### 5.8", 1)[0]
    assert re.search(r"non-zero|exit\s+code", record_section, re.IGNORECASE), "5.7a must check `record`'s exit code"


def test_review_comments_has_no_deleted_status_and_explains_platform_resolution() -> None:
    # (Task 7 correction) `reconcile` does NOT emit a `deleted` status — `_ledger.STATUSES` is only
    # `("open", "done")`. "Gone from the platform" is the `platform_state` axis (`absent`), tallied
    # in `counts` as `absent_upstream`, never a third status. Prose that calls the working set
    # "every non-`done` row" is still wrong (status alone no longer decides membership — see
    # `platform_state`), and a `counts` schema missing `absent_upstream` sends the agent looking for
    # a key that does not exist. Resolving a thread by hand also settles its row without the agent
    # doing anything, via `platform_state == "resolved"`, not a status change.
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert re.search(r"counts:\{[^}]*absent_upstream", text), "the reconcile counts schema must list `absent_upstream`"
    assert not re.search(r"every\s+non-`?done`?\s+row", text), "status alone does not decide membership"
    assert re.search(r"resolve", text, re.IGNORECASE), "prose must explain that resolving a thread settles its row"


# --- Task 7: SKILL.md follows the model (open/done status, platform_state, resurfaced, the
#             `record` thread_mark guard, the collector's exit 4) --------------------------


def test_review_comments_has_no_large_pr_cap() -> None:
    """The ledger removed the cap's reason to exist: a round no longer re-imports settled
    findings, so it carries only what is new or re-opened. Leaving the cap in would keep the
    review-loop convergence hole (unselected rows left open) that the loop gate now closes."""
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert "analyze all, or select a subset" not in text
    assert "Very Large Number of Comments" not in text
    assert "large-PR cap" not in text


def test_review_comments_states_the_two_axis_working_set_rule() -> None:
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert '`status == "open"` and `platform_state == "live"`' in text


def test_review_comments_phase_3_separates_undelivered_from_resurfaced() -> None:
    """A non-null decision used to be declared "re-surfaced because its thread advanced", which
    is false for a row whose action never landed — that row needs delivering, not re-litigating."""
    phase_3 = section(REVIEW_COMMENTS_SKILL.read_text(), "### Phase 3", "### Phase 4")
    assert "resurfaced" in phase_3
    assert re.search(r"do not re-?litigate", phase_3, re.IGNORECASE)


def test_review_comments_triage_has_no_skip_outcome() -> None:
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert "fix / won't-fix / follow-up?" in text
    assert "invariant 3" not in text.lower()


def test_review_comments_requires_a_reason_only_where_it_can_be_published() -> None:
    """A reason exists in order to be posted. Requiring one for a GitHub review-body summary
    charges the user for prose nobody will ever read."""
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert re.search(r"reason.{0,80}(iff|only (when|where)).{0,80}reply target", text, re.IGNORECASE | re.DOTALL)


def test_review_comments_records_an_aborted_action_as_open_with_its_decision() -> None:
    """Keeping the decision costs nothing and gives the next round context; the status stays
    `open` because nothing was delivered."""
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert "pending" not in text
    assert "`status: open`, `decision: fix`" in text


def test_review_comments_handles_a_collector_abort() -> None:
    text = REVIEW_COMMENTS_SKILL.read_text()
    assert "exit 4" in text or "exits non-zero" in text
    assert "ledger was not touched" in text


# --- Task 8: review-loop converges on an empty working set, not head advancement alone -------


def test_review_loop_requires_an_empty_working_set_to_converge() -> None:
    """Head advancement alone is not soundness. Removing the cap deleted the loudest case (a
    subset round that pushed nothing while unselected rows stayed open), but a round can still
    end with an unchanged head and outstanding work: a row whose action did not land stays
    `open` carrying its decision. Calling that "converged" stops the loop with work left."""
    text = (FLOW_ROOT / "skills" / "review-loop" / "SKILL.md").read_text()
    assert re.search(r"working set", text, re.IGNORECASE)
    assert re.search(r"(empty working set|working set is empty)", text, re.IGNORECASE)
    assert re.search(r"head.{0,60}and.{0,60}working set", text, re.IGNORECASE | re.DOTALL)


def test_review_loop_working_set_check_reads_post_round_ledger_state() -> None:
    """The `counts.working == 0` gate must read the ledger AFTER Phase 5's `record` checkpoints
    of the round just run, not the working set `reconcile` reported at the START of that round in
    Phase 2 -- `reconcile`'s payload is Phase 5's INPUT, not its outcome, so checking it would
    silently reintroduce the exact bug this task's own self-review caught: declaring convergence
    (or non-convergence) from a round's opening backlog instead of what it actually delivered."""
    text = (FLOW_ROOT / "skills" / "review-loop" / "SKILL.md").read_text()
    assert re.search(r"Phase\s*5.{0,20}input,\s*not\s+its\s+outcome", text, re.IGNORECASE | re.DOTALL), (
        "must explicitly reject Phase 2's reconcile payload as the emptiness source"
    )
    assert re.search(r"after\s+Phase\s*5.{0,20}`record`", text, re.IGNORECASE | re.DOTALL), (
        "must state the working-set query happens after Phase 5's record checkpoints"
    )
    assert "flow-review-ledger stats" in text


# --- Whole-branch review Important 1: review-loop must not route control flow through the
#     Phase 3 "process all?" gate Task 7 deleted from review-comments -------------------------


def test_review_loop_does_not_reference_a_deleted_phase_3_confirmation() -> None:
    """Task 7 removed review-comments' Phase 3 "process all N? yes/select/no" gate outright —
    review-comments' own Phase 3 now states there is no such gate. review-loop's control-points
    prose and its terminator list must not still point at it: a user following this skill's
    documented exit would wait forever for a prompt that no longer appears, and the stated
    safety property ("never processes without your go-ahead") would be false, since the first
    real confirmation is now the per-card triage in Phase 4 -- after analysis has already run."""
    text = (FLOW_ROOT / "skills" / "review-loop" / "SKILL.md").read_text()
    assert not re.search(r'no["“]\s+at\s+`?flow:review-comments`?\s+phase\s*3', text, re.IGNORECASE), (
        "must not describe a round-level 'no' answer at review-comments Phase 3 as an exit"
    )
    assert not re.search(r'phase\s*3\s*\(["“]process all', text, re.IGNORECASE), (
        "must not name Phase 3 ('process all N?') as a review-loop control point"
    )
    # The real control points: per-card triage in Phase 4, and the 5.6 push confirmation.
    assert re.search(r"phase\s*4.{0,80}per-card triage", text, re.IGNORECASE | re.DOTALL), (
        "must name Phase 4 per-card triage as a control point"
    )
    assert re.search(r"5\.6.{0,40}push confirmation|push confirmation.{0,40}5\.6", text, re.IGNORECASE), (
        "must still name the 5.6 push confirmation as a control point"
    )
