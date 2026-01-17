---
name: start
description: Use when starting a work session or when user asks to begin working on a beads task. Handles task selection, branch management, and context display. Use after /clear, at session start, or when switching tasks.
---

# Flow: Start Task

## Overview

**Core principle:** Consultation over assumption.

This skill guides starting work on beads tasks through explicit consultation steps. Users choose tasks, see context first, and decide on branch strategy - even when choices seem "obvious."

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 1. Tree | `bd graph --all --json` | Build hierarchical display |
| 2. Select | Let user choose by number/ID | User agency |
| 3. Show | Display in box format | Context BEFORE commitment |
| 4. Branch | Check branch type | Generic vs Feature |
| 5. Ask | RECOMMEND or NEUTRAL | Tone matters |
| 6. Update | `bd update` | Only after confirmation |
| 7. Create | `git checkout -b` | If requested |

**Branch Tone Guide:**
- Generic (main/master/develop) → **RECOMMEND** creating feature branch
- Feature → **NEUTRAL** ask to continue or create new

## Workflow

Follow these steps **in order**. Do not skip steps.

### 1. Build and Display Task Tree

**Get all task data:**
```bash
bd graph --all --json
```

**Build hierarchical tree:**
1. Parse JSON to get Issues and Dependencies
2. Build parent-child relationships from dependencies where `type == "parent-child"`
3. Filter tasks (show open/in_progress, hide closed/blocked)
4. Sort each level by: status (in_progress → open → deferred) then priority (P0 → P4)
5. Number hierarchically: `1.`, `1.1`, `1.2`, `1.1.1`, etc.

**Display format:**
```
[Type] Title (ID) | Priority · Status | #labels
```

**Type letters:**
- `[E]` = epic
- `[F]` = feature
- `[T]` = task
- `[B]` = bug
- `[C]` = chore

**Tree structure:**
```
1. [E] StatusKit (claude-tools-5dl) | P1 · in_progress | #statuskit
   ├─ 1.1 [T] Distribution (claude-tools-5dl.1) | P2 · open | #statuskit
   ├─ 1.2 [F] Git module (claude-tools-c7b) | P2 · open | #statuskit
   └─ 1.3 [F] Beads module (claude-tools-5d1) | P2 · open | #statuskit

2. [F] External feature (claude-tools-xyz) | P2 · open
```

**Filtering rules:**
- **Show:** status = `open` or `in_progress`
- **Hide:** status = `closed` or `blocked` (unless has unblocked descendants)
- **Show deferred:** only if they have unblocked children

**With search argument:**
Filter tree to show only matching tasks and their ancestors/descendants.

**If no tasks available:**
```
Нет доступных задач для работы.

Причины:
- Все задачи закрыты
- Все открытые задачи заблокированы
- Все задачи отложены (deferred)

Что вы хотите сделать?
1. bd blocked - посмотреть заблокированные задачи
2. bd list --status=deferred - посмотреть отложенные
3. new - создать новую задачу
```

### 2. Get User's Task Selection

User can select by:
- **Hierarchical number:** `1`, `1.2`, `1.1.2`
- **Task ID:** `claude-tools-c7b`
- **Create new:** `new` or `create`

Map selection to task ID and proceed.

### 3. Show Task Description FIRST

**Before any actions**, display task in detailed box format:

```
┌─ [Type] Title ────────────────────────────────────────────┐
│ ID: <task-id>                                             │
│ Priority: <priority>  Status: <status>  Type: <type>      │
│ Labels: #label1 #label2                                   │
├───────────────────────────────────────────────────────────┤
│ DESCRIPTION                                               │
│ <full task description>                                   │
│                                                            │
├───────────────────────────────────────────────────────────┤
│ LINKS                                                      │
│ Design: docs/plans/...                                    │
│ Plan: docs/plans/...                                      │
│                                                            │
├───────────────────────────────────────────────────────────┤
│ DEPENDENCIES                                              │
│ Depends on:                                               │
│   → claude-tools-xxx: Some task (closed)                  │
│                                                            │
│ Blocks:                                                   │
│   → claude-tools-yyy: Another task (open)                 │
└───────────────────────────────────────────────────────────┘
```

**Include sections only if present:**
- Metadata (always)
- Description (if present)
- Links (if description contains `Design:` or `Plan:` lines)
- Dependencies (if present)

**If task is already in_progress:**
```
┌─ [F] Git module ──────────────────────────────────────────┐
│ ⚠️  Задача уже в работе (in_progress)                     │
│                                                            │
│ ID: claude-tools-c7b                                      │
...
```

**User needs context BEFORE committing to task.**

### 4. Check Git Branch

```bash
git branch --show-current
```

Identify branch type:
- **Generic:** main, master, develop, trunk
- **Feature:** anything else

### 5. Ask About Branch (with appropriate tone)

#### Generic Branch → RECOMMEND

Use strong, specific recommendation:

> "You're currently on `{branch}` (main development branch). **I recommend creating a feature branch** for this work to keep main clean and make it easier to create PRs later.
>
> Would you like me to create a new branch `{task-id}` or `{task-id}-{brief-name}`?"

**Why recommend:** Generic branches should stay stable.

#### Feature Branch → NEUTRAL

Use neutral, informational tone:

> "You're currently on feature branch `{branch}`.
>
> Would you like to continue work on this branch, or create a new branch for this task?"

**Why neutral:** User might be working on related features, or might want isolation - don't assume.

### 6. Update Task Status

**Only after user confirms everything:**
```bash
bd update <task-id> --status=in_progress
```

Or if user is claiming:
```bash
bd update <task-id> --claim
```

### 7. Create Branch (if requested)

```bash
git checkout -b <branch-name>
```

Follow user's preference from step 4.

## Red Flags - STOP

If you're thinking any of these, STOP and follow the workflow:

- "Creating a feature branch is obviously right"
- "User said they're in a hurry"
- "I'll choose a good task for them"
- "I'll handle the obvious parts"
- "Description can go in summary at the end"
- "This is being helpful"

**All of these mean: Follow the consultation workflow above.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Creating branch is obviously right" | Right for this user, this time? Ask. |
| "User said they're in a hurry" | Consultation is part of the service, not overhead. |
| "I'll choose a good task for them" | User agency matters. Show options, let them choose. |
| "Description in summary is enough" | User needs context BEFORE starting, not after. |
| "Asking slows things down" | Making assumptions and backtracking is slower. |
| "This is just being efficient" | Assuming isn't efficient - it's risky. |

## Examples

### ❌ BAD: Assumes and acts

```
User: "start the git module task"
Agent: I've created branch claude-tools-c7b and marked the task in_progress.
       [shows task details in summary]
```

**Problems:**
- Created branch without asking
- No recommendation (generic branch)
- Description shown after actions
- No user choice

### ✅ GOOD: Consults before acting

```
User: "start the git module task"
Agent: Доступные задачи:

       1. [E] StatusKit (claude-tools-5dl) | P1 · in_progress | #statuskit
          ├─ 1.1 [T] Distribution (claude-tools-5dl.1) | P2 · open | #statuskit
          ├─ 1.2 [F] Git module (claude-tools-c7b) | P2 · open | #statuskit
          └─ 1.3 [F] Beads module (claude-tools-5d1) | P2 · open | #statuskit

       2. [F] External feature (claude-tools-xyz) | P2 · open

       Выберите задачу (по номеру или ID), или введите 'new' для создания новой:

User: 1.2

Agent: ┌─ [F] Git module ──────────────────────────────────────────┐
       │ ID: claude-tools-c7b                                      │
       │ Priority: P2  Status: open  Type: feature                 │
       │ Labels: #statuskit #python                                │
       ├───────────────────────────────────────────────────────────┤
       │ DESCRIPTION                                               │
       │ Create module that displays:                             │
       │ - Current directory (project name)                        │
       │ - Branch and its status                                   │
       │ - Number of changes (staged/unstaged)                     │
       │ - Hash and age of last commit                             │
       ├───────────────────────────────────────────────────────────┤
       │ DEPENDENCIES                                              │
       │ Depends on:                                               │
       │   → claude-tools-5dl: StatusKit (in_progress)             │
       └───────────────────────────────────────────────────────────┘

       You're currently on `master` (main development branch).
       I recommend creating a feature branch for this work to keep
       master clean and make it easier to create PRs later.

       Would you like me to create a new branch `claude-tools-c7b`?
```

**Correct because:**
- Shows hierarchical tree first
- Lets user select by number
- Shows full context in box format
- Recommends (not creates) for generic branch
- Gives user choice
- Uses appropriate tone

### ❌ BAD: Time pressure bypass

```
User: "start git module, I'm in a hurry"
Agent: [creates branch immediately without asking]
```

**Problem:** "In a hurry" is not a reason to skip consultation.

### ✅ GOOD: Consults despite pressure

```
User: "start git module, I'm in a hurry"
Agent: [shows task description]

       You're on `master`. I recommend creating a feature branch.

       Quick question: Should I create branch `claude-tools-c7b`?
       (Takes 2 seconds)
```

**Correct because:**
- Acknowledges hurry (quick question)
- Still consults
- Follows workflow

## Edge Cases

### When Task Already in_progress

If task status is already `in_progress`:
1. Show warning in task display box: `⚠️  Задача уже в работе (in_progress)`
2. Still show full description (user might not remember)
3. Still check branch and ask
4. Don't update status (already correct)

### When No Tasks Available

If filtering leaves no tasks to show:
```
Нет доступных задач для работы.

Причины:
- Все задачи закрыты
- Все открытые задачи заблокированы
- Все задачи отложены (deferred)

Что вы хотите сделать?
1. bd blocked - посмотреть заблокированные задачи
2. bd list --status=deferred - посмотреть отложенные
3. new - создать новую задачу

Ваш выбор:
```

### When Search Found Nothing

If search argument provided but no matches found:
```
Поиск "<search-term>" не нашел задач.

Доступные задачи:
[show full tree without filter]

Выберите задачу (по номеру или ID), или введите 'new' для создания новой:
```

### When Multiple Graphs Exist

If `bd graph --all --json` returns multiple graphs:
- Merge all graphs into one tree
- Use sequential root numbering across all graphs
- Example: Graph 1 roots = `1.`, `2.`, Graph 2 roots = `3.`, `4.`

## The Bottom Line

Always follow the workflow. Consultation is not overhead - it's the service.

Show context first, let users choose, recommend appropriately, then act.
