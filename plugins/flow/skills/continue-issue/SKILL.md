---
name: continue-issue
description: Use when returning to work after /clear or new session. Fast return to an active in_progress task — finds task, resolves branch/worktree, shows task card. Use flow:start for new task selection.
---

# Flow: Continue

<STOP-AND-READ>

## ⛔ BEFORE DOING ANYTHING

**READ this ENTIRE skill FIRST. Do NOT run any commands yet.**

**Violation check — if ANY of these are true, STOP and apologize:**
- [ ] I already ran `bd sync` → VIOLATION. Apologize, start over.
- [ ] I already ran `bd list` → VIOLATION. Apologize, start over.
- [ ] I already ran `bd show` → VIOLATION. Apologize, start over.
- [ ] I said "Let me check your tasks" → About to violate. STOP.

**If you checked any box: Tell the user you violated the skill, apologize, and start over from Step 1 below.**

**Required action NOW:**
1. Read this entire skill (don't skim)
2. Create TodoWrite checklist from the steps
3. ONLY THEN execute Step 1

</STOP-AND-READ>

## Overview

**Core principle:** Speed with safety.

This skill is the fast path for returning to work. Unlike `flow:start` which offers full task tree and branch creation, `flow:continue` assumes the task is already set up — it just reconnects you to it.

**What this skill does:**
- Finds your active (in_progress) leaf tasks
- Reads the saved branch name from task description
- Finds the branch locally or in worktree
- Switches to it
- Shows the task card

**What this skill does NOT do:**
- Create branches (no branch → exit with message)
- Change task status (already in_progress)
- Show full task tree (that's flow:start)
- Create tasks

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 1. Sync | `bd sync` | Get latest task data |
| 2. Find tasks | Run `bd-continue.py` script | Leaf in_progress tasks |
| 3. Select | Auto or user picks | 1 task = confirm, N = pick |
| 4. Extract branch | Read `Git:` from description | No Git: → exit |
| 5. Find branch | worktree → local → remote | Priority order |
| 6. Switch | cd or checkout | Depends on where branch is |
| 7. Init | `flow:init-worktree` | Only if new worktree created |
| 8. Card | Show task card | Final output |

## Arguments

The command `/flow:continue` accepts:

- **`<task-id>`** (optional) — skip task selection, go straight to branch resolution.
  Validates task exists and is `in_progress`. If not → error with suggestion to use `/flow:start`.
- **`--all`** — show all users' in_progress tasks, not just current user's.

## Workflow

Follow these steps **in order**. Do not skip steps.

### 1. Sync

```bash
bd sync
```

### 2. Find Active Tasks

**If task-id argument provided:**

```bash
bd show <task-id> --json
```

Validate:
- Task exists → continue
- Task not found → "Задача `<task-id>` не найдена. Используйте `/flow:start`."
- Task not `in_progress` → "Задача `<task-id>` не в работе (статус: `<status>`). Используйте `/flow:start`."

Skip to Step 4.

**If no task-id argument:**

Run the continue script:
```bash
bd graph --all --json | python3 <skill-base-dir>/../starting-task/scripts/bd-continue.py [--all]
```

Pass `--all` if user passed `--all` flag.

Parse output lines. Each line is: `id|issue_type|title|priority|label`

### 3. Select Task

**0 tasks found:**

```
Нет активных задач. Используйте `/flow:start` для начала работы над новой задачей.
```

Exit skill.

**1 task found:**

```
Задача в работе:

[F] Оптимизация выбора задачи (claude-tools-elf.3) | P2 | #flow

Продолжить работу над этой задачей? ('new' для запуска /flow:start)
```

If user says 'new' → "Используйте `/flow:start`." Exit skill.

**N tasks found:**

```
Задачи в работе:

1. [F] Оптимизация выбора задачи (claude-tools-elf.3) | P2 | #flow
2. [F] Git module (claude-tools-c7b) | P2 | #statuskit
3. [B] Fix login error (claude-tools-abc) | P1 | #statuskit

Выберите задачу или 'new' для запуска /flow:start:
```

User selects by number or task ID. If 'new' → exit.

**For task selection: use plain text, NOT AskUserQuestion.**

### 4. Extract Branch Name

Read the task description and find the `Git:` line:

```bash
bd show <task-id> --json
```

Parse the JSON, extract `description` field, find line starting with `Git:`.

**If `Git:` line found** → extract branch name (everything after `Git: `, trimmed).

**If no `Git:` line:**

```
Ветка не найдена в описании задачи. Задача была создана до flow:continue.
Используйте `/flow:start <task-id>` для настройки ветки.
```

Exit skill.

### 5. Find Branch

Search for the branch in priority order:

**a. Check worktrees:**
```bash
git worktree list
```

If a worktree uses this branch → extract path, go to step 6a.

**b. Check local branches:**
```bash
git branch --list "<branch-name>"
```

If found → go to step 6b.

**c. Check remote branches:**
```bash
git branch -r --list "origin/<branch-name>"
```

If found → go to step 6b.

**d. Branch not found anywhere:**

```
Ветка `<branch-name>` не найдена ни локально, ни на удалённом сервере.
Используйте `/flow:start <task-id>` для создания новой ветки.
```

Exit skill.

### 6. Switch to Branch

#### 6a. Worktree exists

```bash
cd <worktree-path>
```

> "Перешёл в worktree `<worktree-path>`."

Skip to Step 8 (no init needed — worktree already existed).

#### 6b. Local or remote branch

Check if already in a worktree:
```bash
pwd | grep -q "\.worktrees/" && echo "IN_WORKTREE=true" || echo "IN_WORKTREE=false"
```

**If IN_WORKTREE=true:**

```bash
git checkout <branch-name>
```

Or for remote:
```bash
git checkout -b <branch-name> origin/<branch-name>
```

> "Переключился на ветку `<branch-name>`."

Skip to Step 8.

**If IN_WORKTREE=false — offer worktree option:**

```
Как открыть ветку `<branch-name>`?

1. Здесь (обычный checkout)
2. В worktree (для параллельной работы)
```

**Option 1 (checkout):**
```bash
git checkout <branch-name>
# or for remote:
git checkout -b <branch-name> origin/<branch-name>
```

Skip to Step 8.

**Option 2 (worktree):**
```bash
WORKTREE_DIR=".worktrees/$(echo '<branch-name>' | tr '/' '-')"
git worktree add "$WORKTREE_DIR" <branch-name>
cd "$WORKTREE_DIR"
```

For remote branch that doesn't exist locally:
```bash
git worktree add "$WORKTREE_DIR" -b <branch-name> origin/<branch-name>
cd "$WORKTREE_DIR"
```

Proceed to Step 7 (init new worktree).

### 7. Initialize Worktree (if newly created)

**Only if a new worktree was created in Step 6b (Option 2).**

Invoke the `flow:init-worktree` skill using the Skill tool.

### 8. Show Task Card

Display the task in detailed box format (same as `flow:start`):

```bash
bd show <task-id>
```

Format as:

```
┌─ [Type] Title ────────────────────────────────────────────┐
│ ID: <task-id>                                             │
│ Priority: <priority>  Status: <status>  Type: <type>      │
│ Labels: #label1 #label2                                   │
├───────────────────────────────────────────────────────────┤
│ DESCRIPTION                                               │
│ <description without Git:/Design:/Plan: lines>            │
├───────────────────────────────────────────────────────────┤
│ LINKS                                                      │
│ Git: <branch-name>                                        │
│ Design: docs/plans/...                                    │
│ Plan: docs/plans/...                                      │
├───────────────────────────────────────────────────────────┤
│ DEPENDENCIES                                              │
│ Depends on:                                               │
│   → claude-tools-xxx: Some task (status)                  │
└───────────────────────────────────────────────────────────┘
```

This is the final output. The user sees it and starts working.

## Red Flags

- "I'll also create the branch if it's missing" → Out of scope. Exit with message.
- "Let me change the task status" → Already in_progress. Don't touch.
- "I'll show the full task tree" → flow:continue is fast path. Use flow:start for tree.
- "I'll skip the Git: check and just search for branches" → Git: line is the source of truth.
- "bd ready is a quick way to find tasks" → Use bd-continue.py script.
- "AskUserQuestion for task selection" → Plain text. Numbers don't work in structured UI.

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "I'll create the missing branch" | Out of scope. Suggest `/flow:start`. |
| "Task not in_progress, I'll start it" | Not your job. Suggest `/flow:start`. |
| "I'll show the full tree for context" | This is the fast path. Tree = `/flow:start`. |
| "Git: line is unreliable, search branches" | Git: is the source of truth. No Git: → exit. |
| "User is in a hurry, skip confirmation" | 1 task still needs confirmation. N tasks need selection. |
| "I'll run bd ready instead of the script" | Script gives exact format needed. |
| "I'll also sync at the end" | No mutations → no sync needed. |

## Examples

### ✅ GOOD: Single task, fast return

```
User: /flow:continue

Agent: [runs bd sync]
       [runs bd-continue.py]

       Задача в работе:

       [F] Оптимизация выбора задачи (claude-tools-elf.3) | P2 | #flow

       Продолжить работу над этой задачей? ('new' для запуска /flow:start)

User: да

Agent: [reads Git: from description → feature/claude-tools-elf.3-task-selection-optimization]
       [finds worktree at .worktrees/feature-claude-tools-elf.3-...]
       [cd to worktree]

       Перешёл в worktree `.worktrees/feature-claude-tools-elf.3-task-selection-optimization`.

       ┌─ [F] Оптимизация выбора задачи ───────────────────────┐
       │ ID: claude-tools-elf.3                                 │
       │ Priority: P2  Status: in_progress  Type: feature       │
       │ Labels: #flow                                          │
       ├────────────────────────────────────────────────────────┤
       │ DESCRIPTION                                            │
       │ Упростить выбор задачи в flow:starting-task.           │
       ├────────────────────────────────────────────────────────┤
       │ LINKS                                                  │
       │ Git: feature/claude-tools-elf.3-task-selection-...     │
       │ Design: docs/plans/2026-01-30-flow-continue-design.md  │
       └────────────────────────────────────────────────────────┘
```

### ✅ GOOD: Direct task-id argument

```
User: /flow:continue elf.3

Agent: [runs bd sync]
       [validates claude-tools-elf.3 is in_progress → OK]
       [reads Git: → feature/claude-tools-elf.3-task-selection-optimization]
       [finds branch locally]
       [offers checkout or worktree]
       ...
```

### ✅ GOOD: No Git: line in description

```
User: /flow:continue

Agent: [finds task claude-tools-old]

       Ветка не найдена в описании задачи. Задача была создана до flow:continue.
       Используйте `/flow:start claude-tools-old` для настройки ветки.
```

### ❌ BAD: Creates branch when missing

```
Agent: No branch found. Let me create one for you...
```

**Problem:** flow:continue does NOT create branches. That's flow:start's job.
