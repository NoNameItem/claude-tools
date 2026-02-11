---
name: starting-task
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

**Step 1 - Run the tree builder script:**
```bash
# Without argument — full tree
bd graph --all --json | python3 <skill-base-dir>/scripts/bd-tree.py

# With task ID argument — subtree rooted at that task
bd graph --all --json | python3 <skill-base-dir>/scripts/bd-tree.py --root <task-id>
```

**If a task ID argument was provided** (e.g., user invoked `/flow:start 5dl`), pass it with `--root`. The script will:
- Find the task by exact ID or suffix match (e.g., `5dl` matches `claude-tools-5dl`)
- Show only its subtree with the found task as root `1.`
- If not found, show a warning and fall back to the full tree

The script outputs a properly formatted hierarchical tree with emoji type indicators and bold formatting for highest-priority tasks. Example output:

**1. 📦 [E] StatusKit (claude-tools-5dl) | P1 · in_progress | #statuskit**
├─ 1.1 📋 [T] Distribution (claude-tools-5dl.1) | P2 · open | #statuskit
├─ 1.2 🚀 [F] Git module (claude-tools-c7b) | P2 · open | #statuskit
└─ 1.3 🚀 [F] Beads module (claude-tools-5d1) | P2 · open | #statuskit

**Script options:**
- `-s "term"` — filter by search term
- `-n 10` — limit to first N root tasks
- `--collapse` — show only roots with child count `[+N]`
- `--root <id>` — show subtree rooted at task (exact ID or suffix match)

**For task selection:**
- ✅ Use plain text output (allows user to type `1.2` or `1.1.1`)
- ❌ DO NOT use `AskUserQuestion` tool (cannot handle hierarchical numbers)

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 0. Sync | `bd sync` + check worktree | Get tasks from all branches |
| 1. Tree | `bd graph --all --json \| python3 <skill-base-dir>/scripts/bd-tree.py [--root <id>]` | Script builds tree (subtree if --root) |
| 2. Select | Let user choose by number/ID | User agency |
| 3. Show | `bd show <id> --json \| python3 <skill-base-dir>/scripts/bd-card.py` | Context BEFORE commitment |
| 4. Branch | Check branch type | Generic vs Feature |
| 5. Search | Find existing branches | Reuse before create |
| 5.5. Auto | Check auto-resolve cases | Skip question if obvious |
| 6. Ask | `AskUserQuestion` with options matrix | Branch + worktree in one question |
| 7. Update | `bd update` | Only after confirmation |
| 7.1. Sync | `bd sync` | Persist status change |
| 7.2. Init | Detect project, confirm, run | Only after worktree creation |
| 8. Create | `git checkout -b` or `git worktree add` | Based on user's choice |
| 8.1. Git Info | `bd update` + `bd sync` | Save branch name for flow:continue |

**Branch Tone Guide:**
- Generic (main/master/develop) → **RECOMMEND** creating feature branch
- Feature → **NEUTRAL** ask to continue or create new

## Workflow

Follow these steps **in order**. Do not skip steps.

### 0. Environment Detection & Sync

**Run at skill start:**

```bash
# Sync tasks from all branches
bd sync

# Check if already in a worktree
pwd | grep -q "\.worktrees/" && echo "IN_WORKTREE=true" || echo "IN_WORKTREE=false"
```

`bd sync` ensures you see tasks created in other branches. Store `IN_WORKTREE` for Step 6.

### 1. Build and Display Task Tree

**Run the tree builder script:**
```bash
# Without argument — full tree
bd graph --all --json | python3 <skill-base-dir>/scripts/bd-tree.py

# With task ID argument (from /flow:start <id>) — subtree
bd graph --all --json | python3 <skill-base-dir>/scripts/bd-tree.py --root <task-id>
```

**If a task ID argument was provided**, always use `--root`. The script finds the task by exact ID or suffix (e.g., `5dl` matches `claude-tools-5dl`). If not found, it shows a warning and the full tree.

The script handles:
- Parsing JSON and building parent-child relationships
- Filtering (shows open/in_progress, hides closed/blocked)
- Sorting (in_progress → open → deferred, then by priority)
- Hierarchical numbering (`1.`, `1.1`, `1.2`)
- Tree connectors (`├─`, `└─`)
- Subtree extraction with `--root` (found task becomes root `1.`)

**Script options:**
- `bd graph --all --json | python3 <skill-base-dir>/scripts/bd-tree.py -s "search"` — filter by term
- `bd graph --all --json | python3 <skill-base-dir>/scripts/bd-tree.py --collapse` — show roots only with `[+N]`
- `bd graph --all --json | python3 <skill-base-dir>/scripts/bd-tree.py --root <id>` — subtree rooted at task

**If script shows no tasks:**
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

**✓ Validation Checkpoint:**
- [ ] I ran the script (not bd ready/list/show directly)
- [ ] I'm asking for selection with PLAIN TEXT (not AskUserQuestion tool)

**Display the tree output as plain Markdown text, NOT in a code block.** Code blocks (`` ```text ... ``` ``) don't render Markdown — `**bold**` shows as literal asterisks and emoji lose color. Plain text in Claude Code renders as monospace, so tree connector alignment is preserved.

### 2. Get User's Task Selection

User can select by:
- **Hierarchical number:** `1`, `1.2`, `1.1.2`
- **Task ID:** `claude-tools-c7b`
- **Create new:** `new` or `create`

Map selection to task ID and proceed.

**After selection, check for open children:**
- If selected task **has open children** → re-run script with `--root <selected-task-id>` to show subtree, let user pick again
- If selected task **has no open children** → proceed to Step 3 (Show Task Description)

### 3. Show Task Description FIRST

**Before any actions**, display task details using the card script:

```bash
bd show <task-id> --json | python3 <skill-base-dir>/scripts/bd-card.py
```

Output the script result in a ``` code block to preserve monospace alignment.

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

### 5.5. Auto-Resolve Check

**Before showing the question**, check two auto-resolve cases. If either matches, skip Steps 6-8 entirely and go to Step 7.

**Case 1: Current branch matches task branch.**
Check if current branch name matches pattern `(fix|feature|chore)/{task-id}`:
```bash
git branch --show-current | grep -qE "(fix|feature|chore)/{task-id}" && echo "AUTO_RESOLVE=current_branch"
```

If matched: skip to Step 7, report:
> "Вы уже на ветке `{current-branch}`, продолжаем."

**Case 2: Worktree exists for a task branch.**
Check if any worktree uses a branch matching the task ID:
```bash
git worktree list | grep -E "(fix|feature|chore)/{task-id}"
```

If matched: extract the worktree path (first column of `git worktree list` output), `cd` into it, skip to Step 7, report:
> "Переключился в worktree `{worktree-path}`."

These two cases are mutually exclusive (git doesn't allow a branch to be checked out in both main directory and a worktree simultaneously).

**If neither case matches**, proceed to Step 6.

### 6. Ask About Branch and Worktree (single AskUserQuestion)

**Use `AskUserQuestion` tool** to present branch and worktree options in one question. The options depend on context (existing branches, IN_WORKTREE, branch type).

#### Option Matrix

**IN_WORKTREE=false, 0 existing branches:**

| # | Label | Description (generic branch) | Description (feature branch) |
|---|-------|------------------------------|------------------------------|
| 1 | Создать ветку (checkout) | `{branch-name}` — checkout в текущем каталоге (Recommended) | `{branch-name}` — checkout в текущем каталоге |
| 2 | Создать ветку (worktree) | `{branch-name}` — в отдельном worktree для параллельной работы | `{branch-name}` — в отдельном worktree для параллельной работы |
| 3 | Остаться на {branch} | Не рекомендуется — {branch} лучше держать чистым | Продолжить работу в текущей ветке |

**IN_WORKTREE=false, 1+ existing branches:**

Use the most probable existing branch (prefer local over remote). If 2+ branches found, mention others in option descriptions: "Также найдены: `branch-2`, `branch-3`".

| # | Label | Description (generic branch) | Description (feature branch) |
|---|-------|------------------------------|------------------------------|
| 1 | Checkout здесь | `{existing-branch}` — checkout в текущем каталоге (Recommended) | `{existing-branch}` — checkout в текущем каталоге |
| 2 | Checkout в worktree | `{existing-branch}` — в отдельном worktree для параллельной работы | `{existing-branch}` — в отдельном worktree для параллельной работы |
| 3 | Остаться на {branch} | Не рекомендуется — {branch} лучше держать чистым | Продолжить работу в текущей ветке |

**IN_WORKTREE=true (no worktree options):**

| # | Label | Description (generic branch) | Description (feature branch) |
|---|-------|------------------------------|------------------------------|
| 1 | Создать ветку / Checkout | `{branch-name}` — checkout в текущем worktree (Recommended) | `{branch-name}` — checkout в текущем worktree |
| 2 | Остаться на {branch} | Не рекомендуется — {branch} лучше держать чистым | Продолжить работу в текущей ветке |

#### Option Ordering

- **Recommended option is always first** (add "(Recommended)" to label on generic branches).
- **"Остаться на текущей" is always last.**
- On generic branches: creating/checking out a branch is recommended, staying is marked as not recommended.
- On feature branches: neutral tone, no explicit recommendation.

#### AskUserQuestion Format

```
AskUserQuestion(
  questions=[{
    "question": "Как продолжить работу с веткой для задачи {task-id}?",
    "header": "Branch",
    "options": [<options from matrix above>],
    "multiSelect": false
  }]
)
```

#### Other (Free-Form Input)

User can type arbitrary text via the automatic "Other" option. The LLM interprets user intent, extracting:
- Branch name (if specified)
- Method: checkout here / worktree

If the method is not clear from the text, ask a follow-up `AskUserQuestion` with 2 options: "Checkout здесь" / "В worktree".

### 7. Update Task Status

**Only after user confirms everything:**
```bash
bd update <task-id> --status=in_progress
```

Or if user is claiming:
```bash
bd update <task-id> --claim
```

### 7.1. Sync Changes

**Run only if `bd update` or `bd claim` was executed in Step 7** (skip if task was already in_progress).

```bash
bd sync
```

Persist the status change to git immediately.

### 7.2. Initialize Project Environment (worktree only)

**Skip this step if user did NOT choose a worktree option in Step 6.**

After creating a worktree, invoke the `flow:init-worktree` skill using the Skill tool.

This skill will:
1. Read CLAUDE.md/README.md for setup instructions
2. Detect project type from config files
3. Propose initialization commands with confirmation
4. Run commands if user confirms

See `flow:init-worktree` skill for full algorithm.

### 8. Create or Checkout Branch (based on Step 6 choice)

**Create branch (checkout here):**
```bash
git checkout -b <prefix><task-id>-<brief-name>
```

**Create branch (worktree):**
```bash
WORKTREE_DIR=".worktrees/$(echo '<branch-name>' | tr '/' '-')"
git worktree add "$WORKTREE_DIR" -b <branch-name>
cd "$WORKTREE_DIR"
```

**Checkout existing (here):**
```bash
git checkout <existing-branch-name>
```
Or if remote branch:
```bash
git checkout -b <local-branch-name> origin/<remote-branch-name>
```

**Checkout existing (worktree):**
```bash
WORKTREE_DIR=".worktrees/$(echo '<existing-branch>' | tr '/' '-')"
git worktree add "$WORKTREE_DIR" <existing-branch>
cd "$WORKTREE_DIR"
```

**Stay on current branch:**
No branch action, proceed to Step 8.1.

### 8.1. Save Branch Info

**After branch is created or checked out**, save the branch name in the task description so `flow:continue` can find it later.

**Read current description:**
```bash
bd show <task-id> --json
```

Extract the `description` field. Then append or update the `Git:` line:

- If description already has a `Git:` line → replace it
- If no `Git:` line → append to end of description

**Update description:**
```bash
bd update <task-id> --description "<full-description-with-git-line>"
```

The `Git:` line format:
```
Git: feature/claude-tools-elf.3-task-selection-optimization
```

Same pattern as existing `Design:` and `Plan:` links in descriptions.

**Then sync to propagate:**
```bash
bd sync
```

**Skip this step if:**
- User chose to continue on existing branch without creating a new one (branch was already in the description from a previous `/flow:start`)
- Check if the branch in the description matches the current branch — if so, no update needed

## Red Flags - STOP

If you're thinking any of these, STOP and follow the workflow:

**Skill loading violations (MOST CRITICAL):**
- "Let me wait for content to load" → Content IS loaded. Read it NOW.
- "I'll prepare while reading" → NO. Read FIRST, act SECOND.
- "Let me get the task list" → STOP. Did you read the skill? Run the script.

**Command violations:**
- "bd ready is good enough" → Use the script
- "I'll build the tree myself" → Script does this. Don't reinvent.
- "I'll format differently" → Script output is the correct format

**Tool violations:**
- "AskUserQuestion for task selection" → Use plain text for TASK selection (hierarchical numbers). Use AskUserQuestion for BRANCH selection only.
- "Plain text for branch selection" → Use AskUserQuestion for branch selection. Plain text was the old way.

**Workflow violations:**
- "Creating a feature branch is obviously right"
- "User said they're in a hurry"
- "I'll choose a good task for them"
- "Description can go in summary at the end"

**Branch naming violations:**
- "No need to search existing branches"
- "I'll skip the prefix for simple tasks"
- "feature/ works for all task types"

**Worktree violations:**
- "I'll ask about worktree separately after branch choice" → Worktree is embedded in Step 6 options. One question, not two.
- "Already in worktree, I'll offer worktree option" → Never offer worktree when IN_WORKTREE=true.

**Auto-resolve violations:**
- "I'll skip auto-resolve and always ask" → Check Step 5.5 first. Don't ask when answer is obvious.
- "I'll auto-resolve without telling the user" → Always report what was auto-resolved.

**Init violations:**
- "I'll run init inline instead of calling the skill" → Always use flow:init-worktree
- "Step 7.2 applies to regular checkout too" → Worktree only

**All of these mean: Go back to CRITICAL section. Follow exact process.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Let me wait for content to load" | Content IS loaded. Read the skill NOW. |
| "I'll get the task list while reading" | NO. Read skill FIRST. Commands come AFTER. |
| "bd ready is a quick way to see tasks" | Wrong. Use the script: `bd graph --all --json \| python3 <skill-base-dir>/scripts/bd-tree.py` |
| "I'll build the tree myself" | Script does this correctly. Don't reinvent. |
| "AskUserQuestion for task selection" | Can't handle hierarchical numbers (1.2, 1.1.1). Use plain text for TASKS, AskUserQuestion for BRANCHES. |
| "Creating branch is obviously right" | Right for this user, this time? Ask. |
| "User said they're in a hurry" | Consultation is part of the service, not overhead. |
| "I'll choose a good task for them" | User agency matters. Show options, let them choose. |
| "No existing branches to search" | Always search. Prevents duplicate branches. |
| "I can skip prefix for simple tasks" | All branches need prefixes. Consistent naming matters. |
| "feature/ works for everything" | Wrong. Use fix/ for bugs, chore/ for chores. |
| "I'll ask about worktree separately" | Worktree is an option in Step 6 AskUserQuestion. One question, not two. |
| "I'll offer worktree in a worktree" | Never offer worktree when IN_WORKTREE=true. Show only 2 options. |
| "I'll skip auto-resolve" | Always check Step 5.5. Don't ask when the answer is obvious. |
| "I'll handle init inline" | Use the flow:init-worktree skill. Don't duplicate logic. |
| "Step 7.2 for regular checkout too" | No. Regular checkout already has deps installed. Worktree only. |

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

       **1. 📦 [E] StatusKit (claude-tools-5dl) | P1 · in_progress | #statuskit**
          ├─ 1.1 📋 [T] Distribution (claude-tools-5dl.1) | P2 · open | #statuskit
          ├─ 1.2 🚀 [F] Git module (claude-tools-c7b) | P2 · open | #statuskit
          └─ 1.3 🚀 [F] Beads module (claude-tools-5d1) | P2 · open | #statuskit

       2. 🚀 [F] External feature (claude-tools-xyz) | P2 · open

       Выберите задачу (по номеру или ID), или введите 'new' для создания новой:

User: 1.2

Agent: [runs bd show claude-tools-c7b --json | python3 <skill-base-dir>/scripts/bd-card.py]

       ```
       ┌─ Feature ──────────────────────────────────────────────────────────────────┐
       │ Git module                                                                 │
       ...
       └────────────────────────────────────────────────────────────────────────────┘
       ```

       [Calls AskUserQuestion with:]
       Question: "Как продолжить работу с веткой для задачи claude-tools-c7b?"
       Options:
         1. "Создать ветку (checkout) (Recommended)" — feature/claude-tools-c7b-git-module — checkout в текущем каталоге
         2. "Создать ветку (worktree)" — feature/claude-tools-c7b-git-module — в отдельном worktree
         3. "Остаться на master" — Не рекомендуется — master лучше держать чистым
```

**Correct because:**
- Shows hierarchical tree first (plain text, not AskUserQuestion)
- Lets user select task by number
- Shows full context in box format
- Uses AskUserQuestion for branch selection (not free text)
- Recommended option is first with "(Recommended)" on generic branch
- "Остаться" is last with warning tone
- Worktree option included (not in worktree)
- Uses correct prefix and full format

### ✅ GOOD: Existing branch found

```
User: "start bug task claude-tools-abc"
Agent: [shows task description box for bug task]

       [Calls AskUserQuestion with:]
       Question: "Как продолжить работу с веткой для задачи claude-tools-abc?"
       Options:
         1. "Checkout здесь (Recommended)" — fix/claude-tools-abc-login-error — checkout в текущем каталоге. Также найдена: fix/claude-tools-abc-auth-fix (remote)
         2. "Checkout в worktree" — fix/claude-tools-abc-login-error — в отдельном worktree. Также найдена: fix/claude-tools-abc-auth-fix (remote)
         3. "Остаться на master" — Не рекомендуется — master лучше держать чистым
```

**Correct because:**
- Uses AskUserQuestion (not free text)
- Uses most probable branch (local preferred) in options 1-2
- Mentions other found branches in descriptions
- Recommended option first on generic branch
- Worktree option included
- "Остаться" last with warning

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

       [Calls AskUserQuestion — same options as normal, takes 1 click]
```

**Correct because:**
- AskUserQuestion is faster than typing (1 click vs typing)
- Still consults — doesn't skip the question
- Follows workflow

## Edge Cases

### When Task Already in_progress

If task status is already `in_progress`:
1. Still show full description via script (user might not remember)
2. Still check branch and ask
3. Don't update status (already correct)

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

### When User Already in Worktree

If `IN_WORKTREE=true` (detected in Step 0):
- **Do NOT offer worktree options** (avoid nesting)
- Step 6 AskUserQuestion shows only 2 options (no worktree variant) — see IN_WORKTREE=true matrix
- If user wants a new worktree, suggest: "Вернитесь в основной проект и запустите /flow:start оттуда"

## The Bottom Line

Always follow the workflow. Consultation is not overhead - it's the service.

Show context first, let users choose, recommend appropriately, then act.
