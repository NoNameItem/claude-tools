---
name: start
description: Start working on a beads task — select from the ready tree, create or switch the branch, init a worktree, and show the task card. Use when beginning a work session, after /clear, at session start, or when switching tasks. To resume an already in-progress task, use flow:continue.
allowed-tools: Bash(bd:*) Bash(git:*) Bash(flow-actor) Bash(flow-branch-for:*) Bash(flow-current-task:*) Bash(flow-find-branches) Bash(flow-find-branches:*) Bash(flow-find-worktree:*) Bash(flow-in-worktree) Bash(flow-link-doc) Bash(flow-link-doc:*) Bash(flow-require-bd) Bash(flow-sync:*) Bash(flow-task-card) Bash(flow-task-card:*) Bash(flow-task-tree) Bash(flow-task-tree:*) Bash(flow-worktree-dir:*) Bash(cat:*) Bash(grep:*) Bash(head:*) Bash(tail:*) Bash(cut:*) Bash(tr:*) Bash(wc:*) Bash(echo:*) Bash(test:*) Bash(ls:*) Bash(cd:*) Bash(jq:*) Skill TodoWrite
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
2. Track the workflow steps with the active harness's progress mechanism.
3. ONLY THEN execute Step 1

</STOP-AND-READ>

## Overview

**Core principle:** Consultation over assumption.

This skill guides starting work on beads tasks through explicit consultation steps. Users choose tasks, see context first, and decide on branch strategy - even when choices seem "obvious."

## 🚨 CRITICAL: Follow This Exact Process

**Step 1 - Run the tree builder script:**
```bash
# Without argument — full tree
bd graph --all --json | flow-task-tree

# With task ID argument — subtree rooted at that task
bd graph --all --json | flow-task-tree --root <task-id>
```

**If a task ID argument was provided** (e.g., user invoked `/flow:start 5dl`), pass it with `--root`. The script will:
- Find the task by exact ID or suffix match (e.g., `5dl` matches `claude-tools-5dl`)
- Show only its subtree with the found task as root `1\.`
- If not found, show a warning and fall back to the full tree

The script outputs a properly formatted hierarchical tree with emoji type indicators and bold formatting for highest-priority tasks. Example output:

**1\. 📦 [E] StatusKit (claude-tools-5dl) | P1 · in_progress | #statuskit**
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
- ❌ DO NOT use a structured multiple-choice dialog for selection (it can't do hierarchical numbers, and it auto-submits on the AFK timeout — claude-tools-6q4)

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 0. Sync | `flow-sync pull` + check worktree | Get latest tasks (other machines) |
| 1. Tree | `bd graph --all --json \| flow-task-tree [--root <id>]` | Script builds tree (subtree if --root) |
| 2. Select | Let user choose by number/ID | User agency |
| 3. Show | `bd show <id> --json \| flow-task-card` | Context BEFORE commitment, reproduce in reply |
| 4. Branch | Check branch type | Generic vs Feature |
| 5. Search | Find existing branches | Reuse before create |
| 5.5. Auto | Check auto-resolve cases | Skip question if obvious |
| 6. Ask | Plain-text numbered prompt; wait for reply | Branch + worktree in one question |
| 7. Update | `bd update --status=in_progress -a actor` | Confirm first; ask before taking someone else's task |
| 7.1. Sync | `flow-sync push` | Persist status change |
| 7.2. Init | Detect project, confirm, run | Only after worktree creation |
| 8. Create | `git checkout -b` or `git worktree add` | Based on user's choice |
| 8.1. Git Info | `flow-link-doc … Git … --append` + `flow-sync push` | Append branch (append-if-new) for flow:continue |

**Branch Tone Guide:**
- Generic (main/master/develop) → **RECOMMEND** creating feature branch
- Feature → **NEUTRAL** ask to continue or create new

## Workflow

Follow these steps **in order**. Do not skip steps.

### 0. Environment Detection & Sync

**Run at skill start:**

```bash
# Require a supported bd (>= 1.0.0); STOP the skill if not satisfied
flow-require-bd
```

If `flow-require-bd` exits non-zero, **STOP** — print its message and run nothing else (it requires `bd >= 1.0.0`; see `plugins/flow/README.md`, "bd requirements and migration"). Keep it in its own block so a failed guard cannot fall through to the commands below.

Only if the guard passed:

```bash
# Pull latest tasks from the shared store (other machines)
flow-sync pull

# Check if already in a worktree
flow-in-worktree && echo "IN_WORKTREE=true" || echo "IN_WORKTREE=false"
```

`flow-sync pull` brings task changes from other machines. Store `IN_WORKTREE` for Step 6.

### 1. Build and Display Task Tree

**Run the tree builder script:**
```bash
# Without argument — full tree
bd graph --all --json | flow-task-tree

# With task ID argument (from /flow:start <id>) — subtree
bd graph --all --json | flow-task-tree --root <task-id>
```

**If a task ID argument was provided**, always use `--root`. The script finds the task by exact ID or suffix (e.g., `5dl` matches `claude-tools-5dl`). If not found, it shows a warning and the full tree.

The script handles:
- Parsing JSON and building parent-child relationships
- Filtering (shows open/in_progress, hides closed/blocked)
- Sorting (in_progress → open → deferred, then by priority)
- Hierarchical numbering (`1\.`, `1.1`, `1.2`)
- Tree connectors (`├─`, `└─`)
- Subtree extraction with `--root` (found task becomes root `1\.`)

**Script options:**
- `bd graph --all --json | flow-task-tree -s "search"` — filter by term
- `bd graph --all --json | flow-task-tree --collapse` — show roots only with `[+N]`
- `bd graph --all --json | flow-task-tree --root <id>` — subtree rooted at task

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
- [ ] I'm asking for selection with PLAIN TEXT (numbered prompt, never a structured dialog)

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
bd show <task-id> --json | flow-task-card
```

After running the script, reproduce its **full output verbatim** inside a fenced ``` code block in your reply — **every line** from the top border `┌─` to the bottom border `└─`, none dropped. The card must appear in your message text — that is the only place the user reliably sees it. Do not summarize, truncate, or reformat it.

**User needs context BEFORE committing to task.**

### 4. Check Git Branch

```bash
git branch --show-current
```

Identify branch type:
- **Generic:** main, master, develop, trunk
- **Feature:** anything else

### 5. Search for Existing Branches

**Search for existing branches:**
```bash
flow-find-branches <task-id>
```
Each line is `<branch>\t<location>` (`location` ∈ local/remote/worktree); results are already de-duplicated (a branch is listed once, worktree > local > remote). Empty output = no existing branch; proceed to create one.

**If matching branches found:**
- Present options to checkout existing branch OR create new one
- If multiple branches found, show all options
- Include branch names and location (local/remote/worktree) in the suggestion

**If no matching branches found:**
- Proceed to create new branch with appropriate prefix

**Compute the branch name:**
```bash
flow-branch-for <task-id>
```
This prints `<prefix><task-id>-<brief-name>` using the task's type (bug→`fix/`, chore→`chore/`, task/feature/epic→`feature/`, unknown→`feature/` + stderr warning) and a slug of its title. Capture it:
```bash
BRANCH=$(flow-branch-for <task-id>)
```

### 5.5. Auto-Resolve Check

**Before showing the question**, check two auto-resolve cases. If either matches, skip Steps 6-8 entirely and go to Step 7.

**Case 1: Current branch matches task branch.**
Check if current branch name matches pattern `(fix|chore|feature|docs)/{task-id}`:
```bash
flow-current-task {task-id} && echo "AUTO_RESOLVE=current_branch"
```
Exact match — a subtask branch (`{task-id}.N-…`) no longer false-positives against the parent ID.

If matched: skip to Step 7, report:
> "Вы уже на ветке `{current-branch}`, продолжаем."

**Case 2: Worktree exists for a task branch.**
Check if any worktree uses a branch matching the task ID:
```bash
WT=$(flow-find-worktree {task-id} | head -1)
test -n "$WT" && echo "AUTO_RESOLVE=worktree path=$WT"
```
Anchored match — like Case 1, a subtask branch (`{task-id}.N-…`) no longer false-positives against the parent ID.

If matched (`$WT` non-empty): `cd "$WT"`, skip to Step 7, report:
> "Переключился в worktree `{worktree-path}`."

These two cases are mutually exclusive (git doesn't allow a branch to be checked out in both main directory and a worktree simultaneously).

**If neither case matches**, proceed to Step 6.

### 6. Ask About Branch and Worktree (plain text — then wait)

Ask in **plain text**, then **end your turn and wait** for the user's answer (a number, or free-form text — prose is inherently free-form). Do **not** use a structured multiple-choice dialog: it auto-submits its pre-selected option after the AFK idle timeout (`CLAUDE_AFK_TIMEOUT_MS`, default 60s), which here would create a branch/worktree and change task state **without consent** (claude-tools-6q4). A no-response is **not** consent — never create a branch, worktree, or mutate task/repo state until the user answers. If the turn is force-continued without an answer (an AFK/no-response fallback), briefly restate that you're waiting and take no action.

Which options to show depends on context (`IN_WORKTREE`, existing branches, branch type). Carry these invariants:

- **Offer the worktree option only when `IN_WORKTREE=false`** (never nest worktrees).
- **Generic branch** (main/master/develop/trunk): recommend creating/checking out the feature branch (mark it `— рекомендую`); put "остаться на `{branch}`" **last** with a warning (`{branch} держим чистым`).
- **Feature branch:** neutral tone, no explicit recommendation (drop the `рекомендую` / `не рекомендую` markers).
- **Existing branches found** (`flow-find-branches` returned matches): use the most probable one as the primary option (prefer local over remote) and surface the rest inline (`также найдены: …`).

#### Templates

**`IN_WORKTREE=false`, no existing branch, generic branch:**

```
Как продолжить работу с веткой для задачи {task-id}?

1. Создать `{branch-name}` здесь (checkout) — рекомендую
2. Создать `{branch-name}` в отдельном worktree (параллельная работа)
3. Остаться на `{branch}` — не рекомендую, {branch} держим чистым

Выберите вариант (номер) или опишите своими словами.
```

**`IN_WORKTREE=false`, existing branch(es) found, generic branch:**

```
Для задачи {task-id} уже есть ветка.

1. Checkout `{existing-branch}` здесь — рекомендую
2. Checkout `{existing-branch}` в отдельном worktree (параллельная работа)
3. Остаться на `{branch}` — не рекомендую, {branch} держим чистым

также найдены: `{branch-2}`, `{branch-3}`
Выберите вариант (номер) или опишите своими словами.
```

**`IN_WORKTREE=true` (no worktree option):**

```
Как продолжить работу с веткой для задачи {task-id}?

1. Создать/checkout `{branch-name}` здесь — рекомендую
2. Остаться на `{branch}` — не рекомендую, {branch} держим чистым

Выберите вариант (номер) или опишите своими словами.
```

On a **feature branch**, present the same options in a neutral tone (no `рекомендую` / `не рекомендую`).

Free-form answers are supported natively (prose). Interpret the user's intent — branch name and method (checkout here / worktree). If the method is unclear, ask one more plain-text question (`1. Checkout здесь / 2. В worktree`) and wait.

### 7. Update Task Status

Run the update only after the user confirmed the branch choice in Step 6 (or after the Step 5.5 auto-resolve report).

Fetch the task JSON and read its `assignee` field (Step 3 piped the JSON into `flow-task-card`, which does not show assignee — fetch it here), then resolve your actor name:

```bash
bd show <task-id> --json
flow-actor
```

Pick exactly one branch:

**a. `flow-actor` prints nothing (no identity available)** — run the update without `-a` (never pass an empty assignee); skip the assignee comparison and the takeover question:

```bash
bd update <task-id> --status=in_progress
```

**b. `assignee` is empty or already equals your actor name:**

```bash
bd update <task-id> --status=in_progress -a "$(flow-actor)"
```

If the assignee was empty, report: "Назначил задачу на вас."

**c. `assignee` is someone else** — ask in plain text:

```
Задача назначена на `<assignee>`. Переназначить на вас? (yes/no)
```

- yes → run:

  ```bash
  bd update <task-id> --status=in_progress -a "$(flow-actor)"
  ```

  Report: "Переназначил задачу на вас."
- no → stop; suggest picking another task.

Do NOT use `bd update --claim` — it fails when the task is already claimed, even by you. The explicit `-a` form is idempotent.

### 7.1. Sync Changes

**Run only if `bd update` was executed in Step 7** (skip if status and assignee were already correct).

```bash
flow-sync push
```

Push the status change to the shared store immediately.

### 7.2. Initialize Project Environment (worktree only)

**Skip this step if user did NOT choose a worktree option in Step 6.**

After creating a worktree, invoke `flow:init-worktree` through the active harness's skill mechanism.

This skill will:
1. Read CLAUDE.md/README.md for setup instructions
2. Detect project type from config files
3. Propose initialization commands with confirmation
4. Run commands if user confirms

See `flow:init-worktree` skill for full algorithm.

### 8. Create or Checkout Branch (based on Step 6 choice)

**Create branch (checkout here):**
```bash
git checkout -b "$BRANCH"
```

**Create branch (worktree):**
```bash
WORKTREE_DIR=$(flow-worktree-dir "$BRANCH")
git worktree add "$WORKTREE_DIR" -b "$BRANCH"
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
WORKTREE_DIR=$(flow-worktree-dir "<existing-branch>")
git worktree add "$WORKTREE_DIR" <existing-branch>
cd "$WORKTREE_DIR"
```

**Stay on current branch:**
No branch action, proceed to Step 8.1.

### 8.1. Save Branch Info

**After branch is created or checked out**, record the branch in the task description so `flow:continue` can find it later. A task may span **several** branches (one per project/PR), so this **appends** rather than overwrites.

```bash
flow-link-doc <task-id> Git "$(git branch --show-current)" --append
```

`--append` adds the branch as a new `Git:` line and is a **no-op if that branch is already recorded** — so re-running `/flow:start` on an existing branch changes nothing (this replaces the old "skip if unchanged" check). Use the actual checked-out branch (`git branch --show-current`) rather than `$BRANCH` — on the checkout-existing and existing-worktree paths the user may have selected a branch different from the computed candidate. All other link lines (Design/Plan and any other `Git:` branches) are preserved.

**Adding a second branch to a task?** The task description (from Step 3 / the task card) already lists any existing `Git:` lines. If one is a *different* branch (a parallel workstream in another project/PR), ask the user in **plain text** for an optional label (the project name, e.g. `statuskit`, `flow`) so `flow:continue` can tell the branches apart, then:

```bash
flow-link-doc <task-id> Git "$(git branch --show-current)" --append --label "<project>"
```

Do **not** use a structured dialog for the label question — plain text only. A blank answer is fine: run the plain `--append` (omit `--label`) and the line stays unlabeled. Never block — the label is optional.

**Then sync to propagate:**
```bash
flow-sync push
```

Always run it — `--append` self-deduplicates by branch name, so there is no "skip if unchanged" case.

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
- "A structured dialog is faster than typing" → Never for any flow prompt. It auto-submits on the AFK timeout (claude-tools-6q4). Plain-text numbered prompts only — for BOTH task and branch selection.
- "No answer for 60s means the user is away — proceed" → No. Wait. Never create a branch/worktree or mutate state on a no-response.

**Workflow violations:**
- "Creating a feature branch is obviously right"
- "User said they're in a hurry"
- "I'll choose a good task for them"
- "Description can go in summary at the end"
- "The card is already displayed" → It is not. The card is visible only if YOU reproduced it verbatim in a code block in your reply.

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
| "bd ready is a quick way to see tasks" | Wrong. Use the script: `bd graph --all --json \| flow-task-tree` |
| "I'll build the tree myself" | Script does this correctly. Don't reinvent. |
| "A structured dialog for selection is nicer" | It auto-submits on the AFK timeout (claude-tools-6q4) and can't do hierarchical numbers. Plain text for tasks AND branches. |
| "Creating branch is obviously right" | Right for this user, this time? Ask. |
| "User said they're in a hurry" | Consultation is part of the service, not overhead. |
| "I'll choose a good task for them" | User agency matters. Show options, let them choose. |
| "Running the script is enough to show the card" | No. Reproduce the script output verbatim in a fenced code block in your reply. |
| "No existing branches to search" | Always search. Prevents duplicate branches. |
| "I can skip prefix for simple tasks" | All branches need prefixes. Consistent naming matters. |
| "feature/ works for everything" | Wrong. Use fix/ for bugs, chore/ for chores. |
| "--claim is shorter" | It fails on re-claim, even by you. Use the explicit `-a` form. |
| "I'll ask about worktree separately" | Worktree is an option in the Step 6 prompt. One question, not two. |
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

       **1\. 📦 [E] StatusKit (claude-tools-5dl) | P1 · in_progress | #statuskit**
          ├─ 1.1 📋 [T] Distribution (claude-tools-5dl.1) | P2 · open | #statuskit
          ├─ 1.2 🚀 [F] Git module (claude-tools-c7b) | P2 · open | #statuskit
          └─ 1.3 🚀 [F] Beads module (claude-tools-5d1) | P2 · open | #statuskit

       2. 🚀 [F] External feature (claude-tools-xyz) | P2 · open

       Выберите задачу (по номеру или ID), или введите 'new' для создания новой:

User: 1.2

Agent: [runs bd show claude-tools-c7b --json | flow-task-card]

       ```
       ┌─ Feature ──────────────────────────────────────────────────────────────────┐
       │ Git module                                                                 │
       ...
       └────────────────────────────────────────────────────────────────────────────┘
       ```

       Как продолжить работу с веткой для задачи claude-tools-c7b?

       1. Создать `feature/claude-tools-c7b-git-module` здесь (checkout) — рекомендую
       2. Создать `feature/claude-tools-c7b-git-module` в отдельном worktree (параллельная работа)
       3. Остаться на `master` — не рекомендую, master держим чистым

       Выберите вариант (номер) или опишите своими словами.
       [ends turn, waits for the answer]
```

**Correct because:**
- Shows hierarchical tree first (plain text)
- Lets user select task by number
- Shows full context in box format
- Asks the branch question in plain text, then waits (immune to the AFK timeout)
- Recommended option is first, marked `— рекомендую` on generic branch
- "Остаться" is last with warning tone
- Worktree option included (not in worktree)
- Uses correct prefix and full format

### ✅ GOOD: Existing branch found

```
User: "start bug task claude-tools-abc"
Agent: [shows task description box for bug task]

       Для задачи claude-tools-abc уже есть ветка.

       1. Checkout `fix/claude-tools-abc-login-error` здесь — рекомендую
       2. Checkout `fix/claude-tools-abc-login-error` в отдельном worktree (параллельная работа)
       3. Остаться на `master` — не рекомендую, master держим чистым

       также найдена: `fix/claude-tools-abc-auth-fix` (remote)
       Выберите вариант (номер) или опишите своими словами.
```

**Correct because:**
- Asks in plain text, then waits (immune to the AFK timeout)
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

       [asks the same plain-text branch question as normal, then waits for the answer]
```

**Correct because:**
- A numbered prompt is quick to answer (type one digit)
- Still consults — doesn't skip the question
- Follows workflow

## Edge Cases

### When Task Already in_progress

If task status is already `in_progress`:
1. Still show full description via script (user might not remember)
2. Still check branch and ask
3. If `assignee` is empty, still run the Step 7 update (backfills assignee on legacy tasks); skip the update only when status is `in_progress` AND `assignee` is already you (or when no identity is available — nothing to backfill then)

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
- Example: Graph 1 roots = `1\.`, `2\.`, Graph 2 roots = `3\.`, `4\.`

### When User Already in Worktree

If `IN_WORKTREE=true` (detected in Step 0):
- **Do NOT offer worktree options** (avoid nesting)
- Step 6 shows only 2 options (no worktree variant) — see the IN_WORKTREE=true template
- If user wants a new worktree, suggest: "Вернитесь в основной проект и запустите /flow:start оттуда"

## The Bottom Line

Always follow the workflow. Consultation is not overhead - it's the service.

Show context first, let users choose, recommend appropriately, then act.
