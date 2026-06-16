# `flow-find-worktree`: Anchored, docs/-Aware Worktree Lookup for Step 5.5

**Task:** claude-tools-elf.15
**Date:** 2026-06-16
**Status:** Design

## Problem

`flow:start` Step 5.5 Case 2 ("a worktree already exists for this task") still resolves
the worktree with an inline grep in `plugins/flow/skills/start/SKILL.md`:

```bash
git worktree list | grep -E "(fix|feature|chore)/{task-id}"
```

Two defects, both inherited from the pre-`bin/`-helper era:

1. **Unanchored** — `{task-id}` matches a subtask branch too: querying `claude-tools-elf`
   false-positively hits a worktree on `feature/claude-tools-elf.9-…`. This is the same
   subtask false-positive the `flow-bin-helpers` refactor (claude-tools-uaj) eliminated
   everywhere else by anchoring the regex.
2. **Missing `docs/`** — the alternation omits the `docs/` branch type that
   `flow-current-task` and `flow-find-branches` now recognize.

Step 5.5 was deliberately *not* folded into `flow-find-branches` during the refactor:
Case 2 needs the worktree **path** (to `cd` into it), and `flow-find-branches` only emits
`<branch>\t<location>` — it parses the path internally but discards it.

Case 1 of the same step is already correct: it uses `flow-current-task {task-id}`, whose
anchored regex `^(?:fix|chore|feature|docs)/{task-id}(-.*)?$` is the model to follow here.

## Solution

Add a dedicated helper that returns the worktree path for a task id, reusing the exact
anchored, `docs/`-aware pattern. Both defects fall out of reusing that pattern. No change
to `flow-find-branches` or its contract.

### 1. New helper — `plugins/flow/bin/flow-find-worktree`

A standalone Python script in the style of `flow-find-branches` (same `git()` wrapper,
same `TYPES` constant, same exit-code discipline).

**Contract:**

- **Usage:** `flow-find-worktree <task-id>`
- **Behavior:** scan `git worktree list --porcelain`; print the path of every worktree
  whose checked-out branch matches `^{TYPES}/{re.escape(task_id)}(-.*)?$`, where
  `TYPES = (?:fix|chore|feature|docs)` — identical to `flow-find-branches`.
- **Output:** one absolute worktree path per line, sorted for determinism; empty output
  means no matching worktree.
- **Exit:** `0` always (empty output = none, mirroring `flow-find-branches`); `2` on a
  `git` error, with `git`'s stderr surfaced.

The `--porcelain` format pairs a `worktree <path>` line with a later `branch <ref>` line
per entry; the helper tracks the current `worktree` path and emits it when the paired
`branch` matches. (`flow-find-branches._scan_worktrees` already parses this block — it
just keeps the branch name instead of the path.)

**All matches, not just the first:** consistent with the `flow-find-*` family
(`flow-find-branches`/`-doc`/`-leaf`), which never silently drops a match. In practice a
task id has 0 or 1 worktree; the Step 5.5 consumer takes `head -1`.

Must remain Python 3.9-importable so `test_py39_compat.py` keeps passing (no `match`
statement, no 3.10+ syntax; `from __future__ import annotations` as in siblings).

### 2. Skill update — `plugins/flow/skills/start/SKILL.md` Step 5.5 Case 2

Replace the inline grep with the helper:

```bash
WT=$(flow-find-worktree {task-id} | head -1)
[ -n "$WT" ] && echo "AUTO_RESOLVE=worktree path=$WT"
```

Update the surrounding prose: the path now comes directly from the helper (drop the
"first column of `git worktree list` output" parsing instruction), and add a note that
matching is anchored and `docs/`-aware — mirroring the note already on Case 1. The
"switched into worktree" report (`"Переключился в worktree {worktree-path}"`) is unchanged.

### 3. Tests — `plugins/flow/bin/tests/test_flow_find_worktree.py`

New file mirroring `test_flow_find_branches.py`, using the `git_repo` fixture and
`run_helper`. Built test-first (TDD). Cases:

1. Worktree on a matching branch → prints that worktree's path (happy path).
2. Worktree on a subtask branch `feature/{id}.9-x`, query `{id}` → empty output. The core
   anti-false-positive regression test for this bug.
3. Worktree on a `docs/{id}-…` branch → matched (the `docs/` inclusion).
4. No matching worktree → empty output, exit 0.
5. A plain local/remote branch matching the id but with no worktree → not printed (only
   actual worktrees are surfaced).
6. `git worktree` failure → exit 2 with stderr surfaced, via a `git` shim
   (mirrors `test_flow_find_branches.test_worktree_git_failure_exits_2`).

## Scope

- New: `plugins/flow/bin/flow-find-worktree`,
  `plugins/flow/bin/tests/test_flow_find_worktree.py`.
- Edit: `plugins/flow/skills/start/SKILL.md` Step 5.5 Case 2 (command + prose).

**Out of scope (decided during brainstorming):**

- `flow:continue` Step 6a has a similar manual worktree-path parse, but it matches by an
  *exact branch name* read from the task description — it does not carry the subtask
  false-positive. Left untouched.
- No changes to `flow-find-branches` (Approach A — adding a ragged third path column —
  was rejected: it changes a documented contract and forces updates to the Step 5
  consumer and its tests for no consumer benefit here).
- No shared parsing module (Approach C); the bin/ helpers are deliberately standalone.

## Testing

- `uv run pytest plugins/flow/bin/tests/test_flow_find_worktree.py` — the six cases above.
- `test_py39_compat.py` continues to pass (new helper is 3.9-importable).
- Pre-commit: `ruff format` + `ruff check --fix` on the new Python files.
- The SKILL.md prose change has no automated test (repo has none for skill prose);
  verified by reading the edited step.
