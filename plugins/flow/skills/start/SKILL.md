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
| 1. Find | `bd ready` or search | Let user choose |
| 2. Show | Display description | Context BEFORE commitment |
| 3. Branch | Check branch type | Generic vs Feature |
| 4. Ask | RECOMMEND or NEUTRAL | Tone matters |
| 5. Update | `bd update` | Only after confirmation |
| 6. Create | `git checkout -b` | If requested |

**Branch Tone Guide:**
- Generic (main/master/develop) → **RECOMMEND** creating feature branch
- Feature → **NEUTRAL** ask to continue or create new

## Workflow

Follow these steps **in order**. Do not skip steps.

### 1. Find Available Tasks

**Without argument:**
```bash
bd ready
```
Show in_progress leaf tasks + ready children. Let user choose.

**With argument (task ID or search text):**
```bash
bd list --status=open | grep <argument>
```
Search by ID or text. If multiple matches, show all and let user choose.

### 2. Show Task Description FIRST

**Before any actions**, display:
- Task title and ID
- Full description
- Design link if present (look for `Design: docs/plans/...`)
- Plan link if present (look for `Plan: docs/plans/...`)
- Dependencies (blocks/blocked-by)

**User needs context BEFORE committing to task.**

### 3. Check Git Branch

```bash
git branch --show-current
```

Identify branch type:
- **Generic:** main, master, develop, trunk
- **Feature:** anything else

### 4. Ask About Branch (with appropriate tone)

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

### 5. Update Task Status

**Only after user confirms everything:**
```bash
bd update <task-id> --status=in_progress
```

Or if user is claiming:
```bash
bd update <task-id> --claim
```

### 6. Create Branch (if requested)

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
Agent: Found task claude-tools-c7b (Git module):

       **Git module** (P2 feature)
       Create module that displays:
       - Current directory (project name)
       - Branch and its status
       - Number of changes (staged/unstaged)
       - Hash and age of last commit

       You're currently on `master` (main development branch).
       I recommend creating a feature branch for this work to keep
       master clean and make it easier to create PRs later.

       Would you like me to create a new branch `claude-tools-c7b`?
```

**Correct because:**
- Shows full context first
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

## When Task Already in_progress

If task status is already `in_progress`:
1. Mention it: "Task is already in progress, continuing..."
2. Still show description (user might not remember)
3. Still check branch and ask
4. Don't update status (already correct)

## When No Tasks Available

If `bd ready` shows nothing:
1. Explain situation
2. Suggest alternatives:
   - `bd list --status=open` (see all open)
   - `bd blocked` (see what's blocked and why)
   - `bd create` (create new task)

## The Bottom Line

Always follow the workflow. Consultation is not overhead - it's the service.

Show context first, let users choose, recommend appropriately, then act.
