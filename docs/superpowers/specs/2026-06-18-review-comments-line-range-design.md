# Design: fix multi-line range capture in `flow:review-comments`

- **Task:** claude-tools-elf.17
- **Date:** 2026-06-18
- **Status:** SHELVED — bug not reproducible (see Investigation outcome). Revisit if it recurs.
- **Scope:** `plugins/flow/skills/review-comments/SKILL.md` (prompt-only; no scripts)

## Investigation outcome (2026-06-18) — SHELVED

TDD-for-skills RED testing could not reproduce the reported bug against the current
`SKILL.md`. Five faithful subagent runs (haiku, matching the production collection/analysis
model) all behaved correctly:

- **Phase 2, GitHub (clean + noisy, single-line dominant):** `start_line` retained for every
  range comment (32–45, 45–60, 120–137); `outdated` correct in the non-contaminated run.
- **Phase 2, GitLab (`position.line_range`):** `start_line` retained for the range.
- **Phase 4 ×3 (35-line reviewed block, crux line at the top):** each subagent read the whole
  range (`1–127` / `57–127` / `57–127`) and found the root cause — none collapsed to ±20
  around the end line.

Conclusion: the current prompts already keep the range and read the whole block, so the
spec'd fix has no failing test to justify it (writing-skills Iron Law). Bug shelved as not
reproducible.

Caveats: tests were simulations with canned API JSON, not live `gh`/`glab` runs at production
scale (30+ comments, full API noise). One narrow, untested gap remains — **outdated
multi-line comments** (GitHub `line`/`start_line` both null; GitLab `new_line` null): the
rules only fall back to a single `original_line`/`old_line`, losing the range. Low value,
since outdated comments are judged against current code.

The design below is retained as the plan to apply **if** the bug is reproduced later.

## Problem

In `flow:review-comments`, a review comment attached to a **range of lines** (a multi-line
block) is treated as a comment on a **single line** — the last line of the range. The
range's start is lost, so:

1. **Collection (Phase 2):** the `start_line` of the range never reaches the METADATA — only
   the end `line` survives.
2. **Analysis (Phase 4):** the analysis subagent reads context `±20` lines around that single
   end line instead of around the whole block, so it judges the comment without the full
   context it refers to.

The bug exists on **both platforms** (GitHub and GitLab). The GitLab support added in
claude-tools-elf.16 copied the same collection prompt and Phase 4 template, so it carries the
same defect.

## Root cause

Pure prompt defect in `SKILL.md` — the skill is prompt-driven (a haiku subagent does the
fetch + parse); there is no helper script involved.

- **Phase 2, METADATA rules (≈ lines 248–256):** list rules for `platform`, `comment_id`,
  `discussion_id`, `body`, `thread`, `already_replied` — but say **nothing** about
  `start_line` / `line`.
- **Phase 2, METADATA example (≈ line 238):** the only example is single-line
  (`"start_line": null, "line": 22`). There is no range example, so the subagent's only signal
  is the `null` one → it emits `start_line: null` even for ranges.
- **Phase 2, parse blocks (GitHub ≈ line 195, GitLab ≈ lines 205–206):** mention `start_line` /
  `line_range` only for the *display string*, not for the structured METADATA fields, and the
  GitLab path does not name the concrete sub-fields.
- **Phase 4, analysis prompt (≈ lines 303, 311–312):** renders `Lines: {start_line}-{line}`
  and `sed -n '{start-20},{end+20}p'`. With `start_line` already dropped in Phase 2, this
  collapses to reading `±20` around the single end line.

## Goal / success criteria

- Multi-line comments retain their full `start_line..line` range through Phase 2 into METADATA,
  on both GitHub and GitLab.
- Phase 4 reads and analyzes the **whole block** (`start_line-20 .. line+20`) and frames the
  comment as referring to the entire range, not the last line.
- Single-line comments are unchanged (`start_line: null`, `line` = the line).
- No changes to scripts, the Phase 4 grouping rule, reply logic, or any other behavior.

## Approach

**Approach C — explicit prompt instructions + a populated range example + a subagent
self-check.** Keeps the existing prompt-driven design (the same pattern elf.16 uses); the
self-check is cheap insurance against the subagent drifting between TABLE and METADATA.

Alternatives considered and rejected:

- **A (clarification only):** same as C without the self-check. C is A plus a near-free
  safety net, so we take C.
- **B (deterministic `jq` extraction):** extract structured fields via `gh api --jq` /
  `glab api | jq`. Most robust, but a large Phase 2 rewrite with two divergent JSON shapes and
  more maintenance; departs from the skill's "let the subagent parse" design. Not worth it for
  this bug.

## Detailed changes

All edits are in `plugins/flow/skills/review-comments/SKILL.md`.

### 1. Phase 2 — collection: explicit range extraction (both platforms)

**1a. Add `start_line` / `line` to the "Rules for METADATA JSON" list**, defining the fields
and naming the exact API source per platform:

- `start_line` — first line of a multi-line range; `null` for single-line comments.
- `line` — last line of the range (or the single line for single-line comments).
- **GitHub:** `start_line` ← API `start_line`; `line` ← API `line`. For outdated comments
  (`line == null`): `start_line` ← `original_start_line`; `line` ← `original_line`.
- **GitLab:** range → `start_line` ← `position.line_range.start.new_line`; `line` ←
  `position.line_range.end.new_line`. Single → `start_line: null`; `line` ←
  `position.new_line`. Outdated (`new_line == null`): use the matching `.old_line` fields
  (`position.line_range.start.old_line` / `.end.old_line`, or `position.old_line` for single).

**1b. Add a populated range example to the METADATA block**, alongside the existing
single-line one, so the subagent has a pattern for both shapes — e.g.:

```json
{"platform": "github", "id": 23456, "ref": "U2", "user": "username", "is_bot": false, "path": "projects.py", "start_line": 32, "line": 45, "body": "...", "outdated": false, "already_replied": false, "comment_id": 23456, "discussion_id": null, "thread": []}
```

**1c. Tie the display-string instructions to the same fields.** In the GitHub parse block
(≈ line 195) and the GitLab parse block (≈ lines 205–206), make the `file:42-58` range string
derive from the same `start_line` / `line` values written to METADATA, naming the concrete
GitLab sub-fields (`position.line_range.start.new_line` / `.end.new_line`).

**1d. Self-check (the C part).** Add an instruction near the end of the subagent prompt: before
returning, verify that every TABLE row showing `a-b` has a METADATA item with
`start_line == a` and `line == b`, and every single-line row has `start_line == null` with
`line` equal to that number; reconcile any mismatch before returning.

### 2. Phase 4 — analysis: read & frame the whole block (both platforms)

- **Render `Lines` explicitly** in the per-comment prompt: range → `start_line–line (N-line
  block)`; single → `line`.
- **Fix the read template:** range → `sed -n '{start_line-20},{line+20}p' {path}` (or the Read
  tool covering `start_line-20 .. line+20`); single → `{line-20},{line+20}`.
- **Add framing:** "The comment refers to the ENTIRE range `start_line..line`, not just the
  last line — read and analyze the whole block."

## Decisions & non-goals

- **Outdated ranges:** captured best-effort via the `original_*` / `old_line` fields. Phase 4
  still reads *current* code to judge whether the issue is fixed, so the original line numbers
  are only approximate anchors — acceptable.
- **No changes** to the Phase 4 grouping rule, reply logic, commit/push flow, or any `bin/`
  script.
- **Single-line behavior** is unchanged.

## Verification

Skills are markdown prompts, so there are no unit tests for prose (the flow `bin/tests` suite
covers only the Python helpers).

- Review the diff for correctness and internal consistency (TABLE example ↔ METADATA example ↔
  rules ↔ Phase 4 template).
- Optional live dry-run: run `/flow:review-comments` on a PR/MR that has a real multi-line
  comment and confirm the METADATA carries `start_line..line` and Phase 4 reads the full block.
