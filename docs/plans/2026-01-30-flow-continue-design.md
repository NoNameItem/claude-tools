# Design: flow:continue — Quick Return to Active Task

**Task:** claude-tools-elf.3
**Date:** 2026-01-30

## Problem

A typical task requires at least 3 `flow:start` invocations (after `/clear` or new sessions). Each time, the user
must find and re-select the same task from the full tree. This wastes time and adds friction to the most common
workflow: returning to work already in progress.

The problem worsens with worktrees: after `/clear`, Claude Code returns to the repository root on `master`, losing
all worktree context.

## Solution

Three changes:

1. **New command `flow:continue`** + **skill `flow:continue-issue`** — fast return to an active task
2. **New skill `flow:init-worktree`** — project initialization extracted from `flow:start`
3. **Modify `flow:start`** — save branch name in task description; delegate worktree init to new skill

## flow:continue (command) / flow:continue-issue (skill)

The command `/flow:continue` invokes the skill `flow:continue-issue`.

### Trigger

User runs `/flow:continue` or `/flow:continue <task-id>` after `/clear` or in a new session to resume work.

### Arguments

- **`<task-id>`** (optional) — skip task selection, go straight to branch/worktree resolution for this task.
  Validates that the task exists and is `in_progress`. If not `in_progress` → error with suggestion to use `/flow:start`.
- **`--all`** — show all users' in_progress tasks, not just current user's.

### Algorithm

```
1. bd sync
2. If task-id argument provided:
   - Validate task exists and is in_progress → skip to step 4
   - If not in_progress → "Task is not in progress. Use /flow:start"
   - If not found → "Task not found"
3. Find leaf in_progress tasks (via script):
   - Filter by assignee = current user (default)
   - With --all flag: show all users' tasks
   - Selection:
     - 0 tasks → "No active tasks. Use /flow:start"
     - 1 task → show one-liner, ask: "Continue this task or start new? (new → exit, suggest /flow:start)"
     - N tasks → numbered list, pick by number. Option 'new' → exit, suggest /flow:start
4. Read Git: block from task description → extract branch name
   - No Git: block → "No branch found for this task. Use /flow:start"
5. Find branch (in priority order):
   a. git worktree list → worktree exists → cd there
   b. git branch --list → local branch → offer: checkout here or create worktree
   c. git branch -r → remote only → offer: checkout here or create worktree
   d. Branch not found anywhere → "Branch not found. Use /flow:start"
6. If new worktree created → invoke flow:init-worktree
7. Show task card (final output, visible when user starts working)
```

### Task list format

For multiple tasks — flat numbered list:

```
Задачи в работе:

1. [F] Оптимизация выбора задачи (claude-tools-elf.3) | P2 | #flow
2. [F] Git module (claude-tools-c7b) | P2 | #statuskit
3. [B] Fix login error (claude-tools-abc) | P1 | #statuskit

Выберите задачу или 'new' для запуска flow:start:
```

For a single task — one-liner with confirmation:

```
Задача в работе:

[F] Оптимизация выбора задачи (claude-tools-elf.3) | P2 | #flow

Продолжить работу над этой задачей? ('new' для запуска flow:start)
```

### Task card

Shown last, as the final skill output. Same box format as `flow:start`:

```
┌─ [Type] Title ────────────────────────────────────────────┐
│ ID / Priority / Status / Type / Labels                    │
├───────────────────────────────────────────────────────────┤
│ DESCRIPTION                                               │
├───────────────────────────────────────────────────────────┤
│ LINKS (Design, Plan)                                      │
├───────────────────────────────────────────────────────────┤
│ DEPENDENCIES                                              │
└───────────────────────────────────────────────────────────┘
```

### Finding leaf in_progress tasks

A new Python script (separate from `bd-tree.py`) reads `bd graph --all --json` from stdin and outputs only
leaf tasks with status `in_progress`. A task is "leaf" if none of its children are `in_progress`.

**Script interface:**

```bash
bd graph --all --json | python3 <skill-base-dir>/scripts/bd-continue.py [--all]
```

Without `--all`: filters by current git user (`git config user.name`). With `--all`: shows all users' tasks.

**Output format** (one task per line, parseable):

```
claude-tools-elf.3|feature|Оптимизация выбора задачи|P2|flow
claude-tools-c7b|feature|Git module|P2|statuskit
```

The skill formats this into the user-facing list.

## flow:init-worktree

Extracted from `flow:start` step 7.2. A standalone skill invoked after worktree creation in both
`flow:start` and `flow:continue`.

### Algorithm

1. Read `CLAUDE.md` and/or `README.md` for setup instructions
2. Inspect config files at worktree root (`pyproject.toml`, `package.json`, `Cargo.toml`, etc.)
3. If project type recognized — ask user to confirm initialization commands
4. If user confirms — run commands
5. If nothing recognized — skip silently

### Invocation

Both `flow:start` and `flow:continue` call this skill after creating a new worktree.
Not invoked when entering an existing worktree (already initialized) or on regular checkout.

## Changes to flow:start

### Save branch in task description

After creating or selecting a branch (step 8), write a `Git:` line to the task description:

```
Git: feature/claude-tools-elf.3-task-selection-optimization
```

Uses `bd update <id> --description` with the full description preserved, adding/updating the `Git:` block.
Same pattern as `Design:` and `Plan:` links already used in descriptions. Run `bd sync` after update to
propagate the branch info to other sessions.

### Delegate worktree initialization

Replace inline step 7.2 with invocation of `flow:init-worktree` skill.

## Scope boundaries

**flow:continue does NOT:**
- Create branches (no branch → exit with message)
- Change task status (already `in_progress`)
- Show full task tree (that's `flow:start`'s job)
- Create tasks

**flow:init-worktree does NOT:**
- Create worktrees (caller's responsibility)
- Decide whether to use worktree (caller's decision)

## Decomposition

1. Python script `bd-continue.py` — find leaf in_progress tasks
2. Skill `flow:init-worktree` — extracted from `flow:start` step 7.2
3. Modify `flow:start` — save `Git:` block, delegate init to new skill
4. Skill `flow:continue-issue` — new skill with full algorithm
5. Command `flow:continue` — invokes `flow:continue-issue`
6. Register command and skill in plugin.json
