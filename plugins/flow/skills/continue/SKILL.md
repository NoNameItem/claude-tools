---
name: continue
description: Fast return to an active in_progress beads task — find it, resolve its saved branch or worktree, and show the task card. Use when resuming work after /clear or a new session. To pick a new task instead, use flow:start.
allowed-tools: Bash(bd:*) Bash(git:*) Bash(flow-actor) Bash(flow-find-leaf) Bash(flow-find-leaf:*) Bash(flow-in-worktree) Bash(flow-require-bd) Bash(flow-sync:*) Bash(flow-task-card) Bash(flow-worktree-dir:*) Bash(cat:*) Bash(grep:*) Bash(head:*) Bash(tail:*) Bash(cut:*) Bash(tr:*) Bash(wc:*) Bash(echo:*) Bash(test:*) Bash(ls:*) Bash(cd:*) Bash(jq:*) Skill TodoWrite
---

# Flow: Continue

<STOP-AND-READ>

## ⛔ BEFORE DOING ANYTHING

**READ this ENTIRE skill FIRST. Do NOT run any commands yet.**

**Violation check — if ANY of these are true, STOP and apologize:**
- [ ] I already ran `flow-sync pull` → VIOLATION. Apologize, start over.
- [ ] I already ran `bd list` → VIOLATION. Apologize, start over.
- [ ] I already ran `bd show` → VIOLATION. Apologize, start over.
- [ ] I said "Let me check your tasks" → About to violate. STOP.

**If you checked any box: Tell the user you violated the skill, apologize, and start over from Step 1 below.**

**Required action NOW:**
1. Read this entire skill (don't skim)
2. Track the workflow steps with the active harness's progress mechanism.
3. ONLY THEN execute Step 1

</STOP-AND-READ>

## Overview

**Core principle:** Speed with safety.

This skill is the fast path for returning to work. Unlike `flow:start` which offers full task tree and branch creation, `flow:continue` assumes the task is already set up — it just reconnects you to it.

**What this skill does:**
- Finds active (in_progress) leaf tasks, grouped by assignee
- Assigns the task to you if it is unassigned (quietly) or assigned to someone else (after asking)
- Reads the saved branch name(s) from task description
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
| 0. Guard | `flow-require-bd` | Require bd >= 1.0.0 |
| 1. Sync | `flow-sync pull` | Get latest task data |
| 2. Find tasks | Run `flow-find-leaf` script | Grouped by assignee, reproduce verbatim |
| 3. Select | Auto or user picks | 1 task = confirm, N = pick |
| 4. Assignee | Compare with `flow-actor` | Empty → assign quietly; other's → ask |
| 5. Extract branch | Collect all `Git:` lines | 0 → exit; 1 → use it; >1 → ask which |
| 6. Find branch | worktree → local → remote | Priority order |
| 7. Switch | cd or checkout | Depends on where branch is |
| 8. Init | `flow:init-worktree` | Only if new worktree created |
| 9. Card | Show task card | Final output — reproduce in reply |

## Arguments

The command `/flow:continue` accepts:

- **`<task-id>`** (optional) — skip task selection, go straight to the assignee check and branch resolution.
  Validates task exists and is `in_progress`. If not → error with suggestion to use `/flow:start`.
- **`--all`** — show all users' in_progress tasks, grouped by assignee (default shows only your tasks and unassigned ones).

## Workflow

Follow these steps **in order**. Do not skip steps.

### 0. Require supported bd (version guard)

```bash
flow-require-bd
```

If this exits non-zero, **STOP**: print its stderr message and run no further commands. flow requires `bd >= 1.0.0` — see `plugins/flow/README.md`, section "bd requirements and migration".

### 1. Sync

```bash
flow-sync pull
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
bd graph --all --json | flow-find-leaf [--all]
```

Pass `--all` if user passed `--all` flag.

The script prints a display-ready grouped list with continuous numbering: your tasks → `Unassigned:` → other users (alphabetically, `--all` only). When no identity is available it behaves like `--all`. Reproduce the script output verbatim as plain text inside the Step 3 message (numbering comes from the script). Empty output = 0 tasks.

### 3. Select Task

**0 tasks found:**

```
Нет активных задач. Используйте `/flow:start` для начала работы над новой задачей.
```

Exit skill.

**1 task found:**

```
Задача в работе:

Мои задачи (artem.vasin):
1. [F] Оптимизация выбора задачи (claude-tools-elf.3) | P2 | #flow

Продолжить работу над этой задачей? ('new' для запуска /flow:start)
```

If user says 'new' → "Используйте `/flow:start`." Exit skill.

**N tasks found:**

```
Задачи в работе:

Мои задачи (artem.vasin):
1. [F] Оптимизация выбора задачи (claude-tools-elf.3) | P2 | #flow

Unassigned:
2. [F] Git module (claude-tools-c7b) | P2 | #statuskit
3. [B] Fix login error (claude-tools-abc) | P1 | #statuskit

Выберите задачу или 'new' для запуска /flow:start:
```

User selects by number or task ID. If 'new' → exit.

**For task selection: use plain text — never a structured multiple-choice dialog (it auto-submits on the AFK timeout; claude-tools-6q4).**

### 4. Check Assignee

Fetch the task once — this JSON is reused in Step 5 (if you already fetched it in Step 2's task-id branch, reuse that JSON instead of fetching again):

```bash
bd show <task-id> --json
```

Resolve your actor name:

```bash
flow-actor
```

If `flow-actor` prints nothing (no identity available), skip the rest of Step 4 — no assignee action — and proceed to Step 5. Never run `bd update -a` with an empty value.

Compare the task's `assignee` field with the actor:

- **`assignee` equals actor** → no action, proceed to Step 5 (fast path stays mutation-free).
- **`assignee` empty or null** → assign quietly:

  ```bash
  bd update <task-id> -a "$(flow-actor)"
  flow-sync push
  ```

  Report: "Назначил задачу на вас." Proceed to Step 5.
- **`assignee` is someone else** → ask in plain text (never a structured dialog):

  ```
  Задача назначена на `<assignee>`. Взять её себе? (yes/no)
  ```

  - yes → `bd update <task-id> -a "$(flow-actor)"`, then `flow-sync push`.
  - no → continue without changing assignee (pair work is fine). Proceed to Step 5.

Do NOT use `bd update --claim` — it fails when the task is already claimed, even by you, and it changes status, which is not this skill's job.

### 5. Extract Branch Name

From the Step 4 `bd show` JSON, extract the `description` field and collect **every** `Git:` line. Match both bare `Git:` and labeled `Git (label):` lines: the branch name is everything after the colon (trimmed); the label, if present, is the text inside the parentheses.

**If no `Git:` line** — the task predates branch tracking:

```
Ветка не найдена в описании задачи. Задача была создана до flow:continue.
Используйте `/flow:start <task-id>` для настройки ветки.
```

Exit skill.

**If exactly one `Git:` line** → use that branch. Proceed to Step 6.

**If more than one `Git:` line** → the task has parallel workstreams (one branch per project/PR). List them (with labels where present) and ask in **plain text** which to resume — never a structured dialog (it auto-submits on the AFK timeout). Then wait for the answer:

```
У задачи несколько веток:
1. feature/claude-tools-elf.18-statuskit (statuskit)
2. feature/claude-tools-elf.18-flow (flow)

Какую ветку продолжить? (номер)
```

Use the branch the user picks as `<branch-name>` for Step 6. Do not auto-pick a branch on a no-response.

### 6. Find Branch

Search for the branch in priority order:

**a. Check worktrees:**
```bash
git worktree list
```

If a worktree uses this branch → extract path, go to step 7a.

**b. Check local branches:**
```bash
git branch --list "<branch-name>"
```

If found → go to step 7b.

**c. Check remote branches:**
```bash
git branch -r --list "origin/<branch-name>"
```

If found → go to step 7b.

**d. Branch not found anywhere:**

```
Ветка `<branch-name>` не найдена ни локально, ни на удалённом сервере.
Используйте `/flow:start <task-id>` для создания новой ветки.
```

Exit skill.

### 7. Switch to Branch

#### 7a. Worktree exists

```bash
cd <worktree-path>
```

> "Перешёл в worktree `<worktree-path>`."

Skip to Step 9 (no init needed — worktree already existed).

#### 7b. Local or remote branch

Check if already in a worktree:
```bash
flow-in-worktree && echo "IN_WORKTREE=true" || echo "IN_WORKTREE=false"
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

Skip to Step 9.

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

Skip to Step 9.

**Option 2 (worktree):**
```bash
WORKTREE_DIR=$(flow-worktree-dir "<branch-name>")
git worktree add "$WORKTREE_DIR" <branch-name>
cd "$WORKTREE_DIR"
```

For remote branch that doesn't exist locally:
```bash
git worktree add "$WORKTREE_DIR" -b <branch-name> origin/<branch-name>
cd "$WORKTREE_DIR"
```

Proceed to Step 8 (init new worktree).

### 8. Initialize Worktree (if newly created)

**Only if a new worktree was created in Step 7b (Option 2).**

Invoke `flow:init-worktree` through the active harness's skill mechanism.

### 9. Show Task Card

Display the task card using the script:

```bash
bd show <task-id> --json | flow-task-card
```

After running the script, reproduce its **full output verbatim** inside a fenced ``` code block in your reply — **every line** from the top border `┌─` to the bottom border `└─`, none dropped. The card must appear in your message text — that is the only place the user reliably sees it. Do not summarize, truncate, or reformat it.

This is the final output. The user sees it and starts working.

## Red Flags

- "I'll also create the branch if it's missing" → Out of scope. Exit with message.
- "Let me change the task status" → Already in_progress. Don't touch (assignee in Step 4 is the only allowed mutation).
- "I'll skip the assignee check" → Step 4 is mandatory; it migrates legacy unassigned tasks.
- "I'll use a structured dialog for the takeover question" → Plain text yes/no.
- "I'll show the full task tree" → flow:continue is fast path. Use flow:start for tree.
- "I'll skip the Git: check and just search for branches" → Git: line is the source of truth.
- "bd ready is a quick way to find tasks" → Use flow-find-leaf script.
- "A structured dialog for task selection" → Plain text. Numbers don't work in a structured UI.
- "The card is already displayed" → It is not. The card is visible only if YOU reproduced it verbatim in a code block in your reply.

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "I'll create the missing branch" | Out of scope. Suggest `/flow:start`. |
| "Task not in_progress, I'll start it" | Not your job. Suggest `/flow:start`. |
| "I'll show the full tree for context" | This is the fast path. Tree = `/flow:start`. |
| "Git: line is unreliable, search branches" | Git: is the source of truth. No Git: → exit. |
| "User is in a hurry, skip confirmation" | 1 task still needs confirmation. N tasks need selection. |
| "I'll run bd ready instead of the script" | Script gives exact format needed. |
| "I'll also sync at the end" | Sync happens in Step 4 only when assignee changed; nothing else mutates. |
| "Assignee is someone else, I'll just take it" | Ask first — it may be pair work. |
| "Running the script is enough to show the card" | No. Reproduce the script output verbatim in a fenced code block in your reply. |

## Examples

### ✅ GOOD: Single task, fast return

```
User: /flow:continue

Agent: [runs flow-sync pull]
       [runs flow-find-leaf]

       Задача в работе:

       Мои задачи (artem.vasin):
       1. [F] Оптимизация выбора задачи (claude-tools-elf.3) | P2 | #flow

       Продолжить работу над этой задачей? ('new' для запуска /flow:start)

User: да

Agent: [runs bd show → assignee == artem.vasin → no assignee action]
       [reads Git: from description → feature/claude-tools-elf.3-task-selection-optimization]
       [finds worktree at .worktrees/feature-claude-tools-elf.3-...]
       [cd to worktree]

       Перешёл в worktree `.worktrees/feature-claude-tools-elf.3-task-selection-optimization`.

       [runs bd show claude-tools-elf.3 --json | flow-task-card]

       ```
       ┌─ Feature ──────────────────────────────────────────────────────────────────┐
       │ Оптимизация выбора задачи                                                 │
       ...
       └────────────────────────────────────────────────────────────────────────────┘
       ```
```

### ✅ GOOD: Direct task-id argument

```
User: /flow:continue elf.3

Agent: [runs flow-sync pull]
       [validates claude-tools-elf.3 is in_progress → OK]
       [assignee empty → bd update claude-tools-elf.3 -a "$(flow-actor)" + flow-sync push → "Назначил задачу на вас."]
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

### ✅ GOOD: Task with multiple branches

```
User: /flow:continue

Agent: [runs flow-sync pull, flow-find-leaf]
       [selects task; bd show → two Git: lines]

       У задачи несколько веток:
       1. feature/claude-tools-elf.18-statuskit (statuskit)
       2. feature/claude-tools-elf.18-flow (flow)

       Какую ветку продолжить? (номер)

User: 2

Agent: [resolves feature/claude-tools-elf.18-flow via Step 6, switches to it]

       Переключился на ветку `feature/claude-tools-elf.18-flow`.

       [shows task card]
```

### ❌ BAD: Creates branch when missing

```
Agent: No branch found. Let me create one for you...
```

**Problem:** flow:continue does NOT create branches. That's flow:start's job.
