---
name: start
description: Use when starting a work session or when user asks to begin working on a beads task. Handles task selection, branch management, and context display. Use after /clear, at session start, or when switching tasks.
---

# Flow: Start Task

<STOP-AND-READ>

## ⛔ BEFORE DOING ANYTHING

**READ this ENTIRE skill FIRST. Do NOT run any commands yet.**

**Violation check — if ANY of these are true, STOP and apologize:**
- [ ] I already ran `bd ready` → VIOLATION. Apologize, start over.
- [ ] I already ran `bd list` → VIOLATION. Apologize, start over.
- [ ] I already ran `bd show` → VIOLATION. Apologize, start over.
- [ ] I said "Let me wait for content to load" → About to violate. STOP.
- [ ] I'm "preparing" or "getting ready" → About to violate. STOP.

**If you checked any box: Tell the user you violated the skill, apologize, and start over from Step 1 below.**

**Required action NOW:**
1. Read this entire skill (don't skim)
2. Create TodoWrite checklist from the steps
3. ONLY THEN execute Step 1

</STOP-AND-READ>

## Overview

**Core principle:** Consultation over assumption.

This skill guides starting work on beads tasks through explicit consultation steps. Users choose tasks, see context first, and decide on branch strategy - even when choices seem "obvious."

## 🚨 CRITICAL: Follow This Exact Process

**Step 1 - Run this EXACT command:**
```bash
bd graph --all --json
```

**FORBIDDEN - These commands are WRONG:**
- ❌ `bd ready` - doesn't provide parent-child relationships
- ❌ `bd list` - doesn't show dependencies
- ❌ `bd show` - only shows single task, not graph

**Required output format (MUST match exactly):**
```
1. [E] StatusKit (claude-tools-5dl) | P1 · in_progress | #statuskit
   ├─ 1.1 [T] Distribution (claude-tools-5dl.1) | P2 · open | #statuskit
   ├─ 1.2 [F] Git module (claude-tools-c7b) | P2 · open | #statuskit
   └─ 1.3 [F] Beads module (claude-tools-5d1) | P2 · open | #statuskit
```

**FORBIDDEN - These formats are WRONG:**
- ❌ `[● P1] [epic] claude-tools-xxx: Title` (old bd ready format)
- ❌ `1. [E] StatusKit [P1] (IN_PROGRESS)` (wrong metadata order)
- ❌ `claude-tools-5dl [EPIC] StatusKit (in_progress) ⭐1` (CanonicalTaskTree - not our format)
- ❌ `● StatusKit` (bullet points without numbers)
- ❌ Any format that doesn't match the example above EXACTLY

**For task selection:**
- ✅ Use plain text output (allows user to type `1.2` or `1.1.1`)
- ❌ DO NOT use `AskUserQuestion` tool (cannot handle hierarchical numbers)

**If you used any FORBIDDEN command or wrong format:**
STOP. Start over from Step 1.

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 1. Tree | `bd graph --all --json` | Build hierarchical display |
| 2. Select | Let user choose by number/ID | User agency |
| 3. Show | Display in box format | Context BEFORE commitment |
| 4. Branch | Check branch type | Generic vs Feature |
| 5. Search | Find existing branches | Reuse before create |
| 6. Ask | RECOMMEND or NEUTRAL | Tone matters |
| 7. Update | `bd update` | Only after confirmation |
| 8. Create | `git checkout -b` | If requested |

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

**✓ Validation Checkpoint - Verify Before Proceeding:**
- [ ] I ran `bd graph --all --json` (exact command, not bd ready/list/show)
- [ ] I parsed "Issues" and "Dependencies" from JSON
- [ ] I built hierarchical numbering: `1.`, `1.1`, `1.2` (not bullet points)
- [ ] I used format: `[E] Title (ID) | P1 · status | #labels` (exact format)
- [ ] I displayed tree with `├─` and `└─` connectors
- [ ] I'm asking for selection with PLAIN TEXT (not AskUserQuestion tool)

If any checkbox is unchecked: STOP. Go back to Step 1.

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

### 5. Search for Existing Branches

**Search for branches containing the task ID:**
```bash
git branch -a | grep -E "(fix|chore|feature)/{task-id}"
```

This searches both local and remote (origin) branches, filtering for branches that match our naming convention (prefix + full task-id).

**Filter results:**
- Remove `remotes/origin/HEAD` entries
- Extract branch names (strip `remotes/origin/` prefix)
- Deduplicate (if same branch exists locally and remotely, prefer local)

**If matching branches found:**
- Present options to checkout existing branch OR create new one
- If multiple branches found, show all options
- Include branch names and location (local/remote) in the suggestion

**If no matching branches found:**
- Proceed to create new branch with appropriate prefix

**Determine branch prefix from task type:**
- bug → `fix/`
- chore → `chore/`
- feature → `feature/`
- task → `feature/`
- epic → `feature/` (epics use feature prefix)
- **Unknown type:** default to `feature/` and warn user

**Generate brief name:**
- Take 2-3 key words from task title
- Convert to lowercase
- Replace spaces with hyphens
- Example: "Fix authentication timeout" → "authentication-timeout"

**Final format:** `{prefix}{task-id}-{brief-name}`

Examples:
- bug task `claude-tools-abc` "Fix login error" → `fix/claude-tools-abc-login-error`
- feature task `claude-tools-xyz` "Add dark mode" → `feature/claude-tools-xyz-dark-mode`
- chore task `claude-tools-123` "Update dependencies" → `chore/claude-tools-123-update-dependencies`

### 6. Ask About Branch (with appropriate tone)

**Three scenarios to handle:**

#### Scenario A: Existing Branches Found

**If one branch found:**

> "Found existing branch for this task: `{branch-name}` (local/remote)
>
> Would you like to:
> 1. Checkout existing branch: `{branch-name}`
> 2. Create new branch: `{prefix}{task-id}-{brief-name}`"

**If multiple branches found:**

> "Found multiple branches for this task:
> - `{branch-1}` (local)
> - `{branch-2}` (remote)
>
> Would you like to:
> 1. Checkout: `{branch-1}` (most recent/local preferred)
> 2. Checkout: `{branch-2}`
> 3. Create new branch: `{prefix}{task-id}-{brief-name}`"

**Why prioritize existing:** Avoid duplicate branches, continue existing work.

**Priority for multiple branches:**
- Prefer local over remote (faster checkout)
- Prefer branches matching current task type prefix
- Show most recent first (by commit date)

#### Scenario B: No Existing Branches + Generic Branch → RECOMMEND

Use strong, specific recommendation:

> "You're currently on `{branch}` (main development branch). **I recommend creating a separate branch** for this work to keep main clean and make it easier to create PRs later.
>
> Would you like me to create branch `{prefix}{task-id}-{brief-name}`?"

**Why recommend:** Generic branches should stay stable.

#### Scenario C: No Existing Branches + Feature Branch → NEUTRAL

Use neutral, informational tone:

> "You're currently on feature branch `{branch}`.
>
> Would you like to continue work on this branch, or create a new branch `{prefix}{task-id}-{brief-name}`?"

**Why neutral:** User might be working on related features, or might want isolation - don't assume.

### 7. Update Task Status

**Only after user confirms everything:**
```bash
bd update <task-id> --status=in_progress
```

Or if user is claiming:
```bash
bd update <task-id> --claim
```

### 8. Create or Checkout Branch (if requested)

**If user chose existing branch:**
```bash
git checkout <existing-branch-name>
```

Or if remote branch:
```bash
git checkout -b <local-branch-name> origin/<remote-branch-name>
```

**If user chose to create new branch:**
```bash
git checkout -b <prefix><task-id>-<brief-name>
```

Follow user's preference from step 6.

## Red Flags - STOP

If you're thinking any of these, STOP and follow the workflow:

**Skill loading violations (MOST CRITICAL):**
- "Let me wait for content to load" → Content IS loaded. Read it NOW.
- "I'll prepare while reading" → NO. Read FIRST, act SECOND.
- "Let me get the task list" → STOP. Did you read the skill? What command does it say?
- "I'll start gathering context" → Gathering context IS the skill. Follow it.

**Command violations:**
- "bd ready is good enough"
- "bd list gives me the same information"
- "I'll use bd show to get task details"
- "These commands are basically equivalent"

**Display violations:**
- "Tree structure is close enough" (needs numbering too!)
- "This format is more readable"
- "User will understand what I mean"

**Tool violations:**
- "AskUserQuestion is more user-friendly"
- "Structured UI is better than plain text"
- "This makes selection easier"

**Workflow violations:**
- "Creating a feature branch is obviously right"
- "User said they're in a hurry"
- "I'll choose a good task for them"
- "Description can go in summary at the end"
- "This is being helpful"

**Branch naming violations:**
- "No need to search existing branches"
- "Searching branches is too slow"
- "I'll skip the prefix for simple tasks"
- "feature/ works for all task types"
- "Brief name is optional"
- "Task ID alone is clear enough"

**All of these mean: Go back to CRITICAL section. Follow exact process.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Let me wait for content to load" | Content IS loaded. You're stalling before violating. Read the skill NOW. |
| "I'll get the task list while reading" | NO. Read skill FIRST. Commands come AFTER understanding. |
| "I'm just preparing" | Preparing = running commands = violation. Read skill first. |
| "bd ready is a quick way to see tasks" | It's the WRONG way. Skill says bd graph --all --json. Read it. |
| "I'll start gathering context" | Context gathering IS the skill's job. Don't freelance. Follow steps. |
| "bd ready shows the same tasks" | It doesn't show parent-child relationships. Use bd graph --all --json. |
| "bd list is simpler" | Simpler isn't correct. Need full dependency graph. |
| "AskUserQuestion is more user-friendly" | Can't handle hierarchical numbers (1.2, 1.1.1). Use plain text. |
| "Tree structure without numbering is fine" | Numbering enables selection by position. Required. |
| "This format is more readable" | Format must match spec exactly. Users expect consistency. |
| "CanonicalTaskTree is a good format" | Not our format. Use: `1. [E] Title (ID) \| P1 · status` |
| "I'll use a format I know works" | Skill specifies exact format. Don't improvise. |
| "Creating branch is obviously right" | Right for this user, this time? Ask. |
| "User said they're in a hurry" | Consultation is part of the service, not overhead. |
| "I'll choose a good task for them" | User agency matters. Show options, let them choose. |
| "Description in summary is enough" | User needs context BEFORE starting, not after. |
| "Asking slows things down" | Making assumptions and backtracking is slower. |
| "This is just being efficient" | Assuming isn't efficient - it's risky. |
| "No existing branches to search" | Always search. Prevents duplicate branches. |
| "Searching branches is slow" | Takes 1 second. Creating duplicate branch wastes hours. |
| "I can skip prefix for simple tasks" | All branches need prefixes. Consistent naming matters. |
| "feature/ works for everything" | Wrong. Use fix/ for bugs, chore/ for chores. |
| "Brief name is optional" | Required. Format: prefix + task-id + brief-name. |
| "Task ID alone is clear enough" | Brief name helps identify branch at a glance. |
| "Simple grep -i is fine" | Wrong. Use grep -E with prefix pattern to avoid partial matches. |
| "No need to deduplicate branches" | Wrong. Same branch on local and remote should show once. |
| "Unknown task type should fail" | Wrong. Default to feature/ and warn user. |
| "Remote branch is same as local" | Wrong. Prefer local (faster), show both with location. |
| "Show all matching branches equally" | Wrong. Prioritize: local > remote, matching prefix > other. |

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

       Would you like me to create branch `feature/claude-tools-c7b-git-module`?
```

**Correct because:**
- Shows hierarchical tree first
- Lets user select by number
- Shows full context in box format
- Searches for existing branches first
- Uses correct prefix (feature/ for feature type)
- Uses full format: prefix + task-id + brief-name
- Recommends (not creates) for generic branch
- Gives user choice
- Uses appropriate tone

### ✅ GOOD: Existing branch found

```
User: "start bug task claude-tools-abc"
Agent: [shows task description box for bug task]

       Found multiple branches for this task:
       - `fix/claude-tools-abc-login-error` (local)
       - `fix/claude-tools-abc-auth-fix` (remote)

       Would you like to:
       1. Checkout: `fix/claude-tools-abc-login-error` (local preferred)
       2. Checkout: `fix/claude-tools-abc-auth-fix`
       3. Create new branch: `fix/claude-tools-abc-authentication-timeout`
```

**Correct because:**
- Searched with proper grep pattern (only matching our convention)
- Presents existing branches with location (local/remote)
- Shows local branch first (priority)
- Still offers option to create new
- Uses correct prefix (fix/ for bug type)
- Deduplicated branches (no duplicates if same branch exists locally and remotely)

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
