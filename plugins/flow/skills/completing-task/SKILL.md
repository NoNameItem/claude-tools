---
name: completing-task
description: Use after completing and verifying a task. Checks git branch (feature → suggests finishing-a-development-branch), closes task, recursively checks parents with confirmation, runs bd sync. Handles task completion workflow for beads.
---

# Flow: Done

## Overview

**Core principle:** Ask before cascading.

This skill handles task completion: close task, check parents recursively, sync. Always asks before closing parent tasks - even when "obviously" all children are closed.

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 1. **Branch Check** | Validate git branch + PR | Feature + no PR → stop; Feature + PR → ask |
| 2. Find Task | Get in_progress leaf | Ask if multiple |
| 3. Close | `bd close {task-id}` | Use bd, not SQL |
| 4. **Check Parent** | Recursive parent check | With confirmation |
| 5. **Ask** | Before closing parent | Even if "obvious" |
| 6. **Sync** | `bd sync` | Always, at end |
| 7. **Cleanup** | Delete branch/worktree | Only if branch matches task; ask first |

**Key behavior:** Always ask before closing parents. Always check PR on feature branches. Always run bd sync. Offer cleanup after sync.

## Workflow

Follow these steps **in order**. Do not skip steps.

### 1. Check Git Branch (MANDATORY FIRST STEP)

```bash
git branch --show-current
```

**If generic branch** (main, master, develop, trunk):
Continue to step 2.

**If feature branch detected** (`feature/*`, `fix/*`, `chore/*`, or any non-generic):

Check if PR exists for current branch:

```bash
gh pr view --json state,url 2>/dev/null || echo "NO_PR"
```

**If NO PR exists:**

**STOP** and inform user:

> "You're on feature branch `{branch-name}` with no PR.
>
> Use `superpowers:finishing-a-development-branch` to properly complete this work (handles merge/PR/cleanup and task closure together)."

Then exit. Do not continue workflow.

**If PR exists (any state: open, merged, closed):**

**ASK** user:

> "You're on feature branch `{branch-name}`.
>
> PR exists: {url} (state: {state})
>
> Proceed to close task on this branch? (yes/no)"

- **If yes:** Continue to step 2.
- **If no:** Stop and suggest `superpowers:finishing-a-development-branch` if needed.

### 2. Find In-Progress Leaf Task

```bash
bd list --status=in_progress
```

Filter for leaf tasks (no open children).

**If multiple found:** Ask which task is complete.
**If none found:** Inform "No in_progress leaf tasks. Check with `bd list --status=in_progress`"

### 3. Close Task

```bash
bd close {task-id}
```

**Use bd close.** Do NOT use direct SQL.

Confirm task closed.

### 4. Check Parent Recursively (with Confirmation)

After closing task, check if it has a parent:

```bash
bd show {task-id}
```

Look for parent relationship.

**If task has parent:**

```bash
bd show {parent-id}
```

Count open children.

**If parent has NO open children** (all closed):

**Ask user:**

> "Parent task `{parent-id}` now has all children closed.
>
> Close it too? (yes/no)"

**If user says yes:**
- Close parent with `bd close {parent-id}`
- Set current task to parent
- Repeat step 4 (recurse up)

**If user says no:**
- Stop recursion
- Proceed to step 6

**If parent has open children:**
- Stop recursion (parent cannot be closed yet)
- Proceed to step 6

**If task has no parent:**
- Proceed to step 6

### 5. Repeat Recursion

Continue checking grandparents, great-grandparents, etc. until:
- User says "no" to closing a parent, OR
- Parent has open children, OR
- No more parents exist

**Always ask at each level.** Do NOT auto-close parents.

### 6. Run bd sync (MANDATORY)

```bash
bd sync
```

Always run at end, regardless of how many tasks closed.

Confirm sync completed.

### 7. Cleanup Branch and Worktree

**Non-blocking:** If cleanup fails, the task is already closed and synced. Cleanup failure is not critical.

#### 7.1. Validate current branch matches the task

```bash
CURRENT_BRANCH=$(git branch --show-current)
```

Check if `$CURRENT_BRANCH` contains the closed task's ID. **If not — skip cleanup silently.** The user ran `flow:done` from an unrelated branch (e.g. master).

#### 7.2. Detect what exists

Gather cleanup targets:

- **Worktree:** `pwd | grep -q "\.worktrees/"` — are we in a worktree?
- **Remote branch:** `git branch -r | grep "$CURRENT_BRANCH"` — does remote branch exist?
- Local branch is always present (we're on it).

#### 7.3. Show branch name and ask once

Display the current branch explicitly and list what will be deleted:

```
You are on branch `feature/claude-tools-elf.6-delete-branches-worktrees`.

Delete branch and associated resources?
  - Worktree: .worktrees/feature-claude-tools-elf.6-delete-branches-worktrees
  - Local branch: feature/claude-tools-elf.6-delete-branches-worktrees
  - Remote branch: origin/feature/claude-tools-elf.6-delete-branches-worktrees

(yes/no)
```

Show only items that exist. If no worktree, omit the worktree line. If no remote branch, omit the remote line.

#### 7.4. If yes — execute in order

1. **If in worktree:** `cd` to the main repo root (parent of `.worktrees/`)
2. **Remove worktree:** `git worktree remove <path>` (if in worktree)
3. **Detect default branch:**
   ```bash
   DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD | sed 's|refs/remotes/origin/||')
   ```
   Fallback: try `master`, then `main`.
4. **Switch to default branch:** `git checkout $DEFAULT_BRANCH`
5. **Pull merged changes:** `git pull`
6. **Delete local branch:** `git branch -d <branch>` (safe delete; use `-D` only if PR confirmed merged)
7. **Delete remote branch:** `git push origin --delete <branch>` (if remote exists)

**Error handling:**
- Worktree remove fails (uncommitted changes): Show error, suggest `git worktree remove --force` or manual cleanup. Don't block.
- Remote branch already deleted (GitHub auto-delete): Catch the error and continue.
- Branch delete fails (unmerged changes): `git branch -d` will refuse. Show warning. Offer `git branch -D` only if PR state is MERGED.

#### 7.5. If no — skip, done

No cleanup performed. User can clean up manually later.

## Scope Boundaries

### This Skill DOES:
✅ Check git branch
✅ Find in_progress leaf task
✅ Close task with bd close
✅ Check parents recursively
✅ Ask before closing each parent
✅ Run bd sync at end
✅ Offer to clean up branch and worktree (Step 7)
✅ Delete local branch, remote branch, worktree (after confirmation)
✅ Switch to default branch and pull after cleanup

### This Skill Does NOT:
❌ Git operations unrelated to cleanup (commit, push, merge, etc.)
❌ Create branches
❌ Start next task (use flow:start)
❌ Update PRs or issues
❌ Run tests or builds
❌ Auto-close parents without asking
❌ Auto-proceed on feature branches without asking
❌ Force-delete without confirmation
❌ Search for branches beyond the current one
❌ Clean up branches for parent tasks (cascade closures)
❌ Block task closure if cleanup fails

**Scope note:** On feature branches without PR, this skill STOPS and refers to finishing-a-development-branch. On feature branches WITH PR, it asks user before proceeding. Cleanup (Step 7) is non-blocking and only applies when the current branch matches the closed task.

## Red Flags - STOP

If you're thinking any of these, STOP and follow the workflow:

- "All children closed → close parent"
- "Branch check unnecessary"
- "bd sync is obvious (skip it)"
- "Use SQL for efficiency"
- "Parent obviously should close"
- "Being helpful by auto-closing cascade"
- "Feature branch → always block"
- "PR exists → auto-proceed"
- "Cleanup is obvious, just delete everything"
- "Skip cleanup, user can do it manually"
- "Branch doesn't match but I'll clean up anyway"
- "Force-delete is fine, PR was merged"

**All of these mean: Follow workflow. Check branch AND PR. Ask before proceeding. Run bd sync. Offer cleanup only if branch matches task.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "All children closed → close parent" | Ask first. User might add more children or want to review. |
| "Branch check unnecessary" | Feature branch needs different workflow. Always check. |
| "bd sync is obvious" | Obvious steps get skipped. Make it explicit. |
| "Use SQL for efficiency" | bd close has logging, events, validation. Use it. |
| "Parent obviously should close" | Obvious to you ≠ user wants it. Ask. |
| "Being helpful by auto-closing" | Asking IS being helpful. Assuming isn't. |
| "Feature branch → always block" | Check for PR first. If PR exists, ask user. |
| "PR exists → auto-proceed" | Still ask user. PR exists ≠ user wants to close here. |
| "Cleanup is obvious, just delete" | Ask first. User might want to keep the branch. |
| "Skip cleanup, not my job" | Step 7 is part of the workflow. Offer it. |
| "Branch doesn't match, clean up anyway" | Only clean up if branch contains the closed task's ID. |
| "Force-delete, PR was merged" | Use safe delete (`-d`) first. Only offer `-D` if `-d` fails AND PR is MERGED. |

## Examples

### ❌ BAD: Auto-close parent

```
User: "Task done, flow:done"
Agent: [Closes task]
       [Checks parent, sees all children closed]
       [Automatically closes parent without asking]
       Done!
```

**Problems:**
- Didn't check branch
- Auto-closed parent without asking
- Didn't run bd sync

### ✅ GOOD: Ask before closing parent

```
User: "Task done, flow:done"
Agent: [Checks branch: master, OK to proceed]
       [Closes task claude-tools-abc.3]

       Parent task claude-tools-abc now has all children closed.

       Close it too? (yes/no)

User: yes
Agent: [Closes parent]
       [Runs bd sync]

       ✓ Closed claude-tools-abc.3
       ✓ Closed claude-tools-abc (parent)
       ✓ Synced with remote

       Done.
```

**Correct because:**
- Checked branch first
- Asked before closing parent
- Ran bd sync
- Clear confirmation

### ❌ BAD: Feature branch proceed without checking PR

```
User: "Done with this feature, flow:done"
Agent: [On feature/add-auth branch]
       [Closes task without checking for PR]
```

**Problem:** Proceeded on feature branch without checking PR status.

### ✅ GOOD: Feature branch with no PR

```
User: "Done with this feature, flow:done"
Agent: [Checks branch: feature/add-auth]
       [Checks PR: no PR exists]

       You're on feature branch `feature/add-auth` with no PR.

       Use `superpowers:finishing-a-development-branch` to properly
       complete this work (handles merge/PR/cleanup and task closure together).
```

**Correct because:**
- Checked branch
- Checked PR status
- Stopped when no PR exists
- Suggested correct workflow

### ✅ GOOD: Feature branch with PR exists

```
User: "PR merged, flow:done"
Agent: [Checks branch: feature/add-auth]
       [Checks PR: exists, merged]

       You're on feature branch `feature/add-auth`.

       PR exists: https://github.com/org/repo/pull/123 (state: MERGED)

       Proceed to close task on this branch? (yes/no)

User: yes
Agent: [Continues to step 2, finds task, closes it]
       [Runs bd sync]

       ✓ Closed claude-tools-xyz
       ✓ Synced with remote

       Done.
```

**Correct because:**
- Checked branch
- Checked PR status
- Asked user before proceeding
- User confirmed, so continued workflow
- Did not assume - asked first

### ✅ GOOD: Cleanup after task close

```
User: "PR merged, flow:done"
Agent: [Checks branch: feature/claude-tools-elf.6-delete-branches-worktrees]
       [Checks PR: exists, merged]
       [Asks user, user says yes]
       [Closes task claude-tools-elf.6]
       [Checks parent: has open children, skip]
       [Runs bd sync]

       You are on branch `feature/claude-tools-elf.6-delete-branches-worktrees`.

       Delete branch and associated resources?
         - Worktree: .worktrees/feature-claude-tools-elf.6-delete-branches-worktrees
         - Local branch: feature/claude-tools-elf.6-delete-branches-worktrees
         - Remote branch: origin/feature/claude-tools-elf.6-delete-branches-worktrees

       (yes/no)

User: yes
Agent: [cd to main repo root]
       [git worktree remove .worktrees/feature-...]
       [git checkout master]
       [git pull]
       [git branch -d feature/claude-tools-elf.6-...]
       [git push origin --delete feature/claude-tools-elf.6-...]

       ✓ Worktree removed
       ✓ Switched to master
       ✓ Local branch deleted
       ✓ Remote branch deleted

       Done.
```

**Correct because:**
- Checked branch matches task ID
- Listed all cleanup targets
- Asked before deleting
- Executed in correct order (worktree → checkout → delete)

### ❌ BAD: Auto-cleanup without asking

```
Agent: [Closes task]
       [Runs bd sync]
       [Immediately deletes branch and worktree]
```

**Problem:** Didn't ask before cleanup. User might want to keep the branch.

### ✅ GOOD: Branch doesn't match — skip cleanup silently

```
Agent: [On master branch]
       [Closes task claude-tools-elf.6]
       [Runs bd sync]

       ✓ Closed claude-tools-elf.6
       ✓ Synced with remote

       Done.
```

**Correct because:** Branch "master" doesn't contain task ID "elf.6", so cleanup is silently skipped.

### ❌ BAD: Skip bd sync

```
User: "flow:done"
Agent: [Closes task]
       [Asks about parent, closes]
       Done!
```

**Problem:** Skipped bd sync at end.

### ✅ GOOD: Always bd sync

```
User: "flow:done"
Agent: [Checks branch]
       [Closes task]
       [Asks about parent, closes if yes]
       [Runs bd sync]

       ✓ Synced with remote

       Done.
```

**Correct because:**
- bd sync always run at end
- Explicit confirmation

## Edge Cases

### Multiple In-Progress Tasks

```
Found 2 in_progress leaf tasks:
1. claude-tools-abc: Feature X
2. claude-tools-def: Feature Y

Which task is complete? (enter 1 or 2, or task ID)
```

### No In-Progress Tasks

```
No in_progress leaf tasks found.

Check task status with:
  bd list --status=in_progress
```

### Deep Hierarchy (3 levels)

```
Closed claude-tools-abc.2.1

Parent claude-tools-abc.2 now has all children closed.
Close it too? (yes/no)

[User: yes]

Closed claude-tools-abc.2

Parent claude-tools-abc now has all children closed.
Close it too? (yes/no)

[User: yes]

Closed claude-tools-abc

No more parents. Running bd sync...
```

### Parent Has Open Sibling

```
Closed claude-tools-abc.1

Parent claude-tools-abc still has open children:
- claude-tools-abc.2 (open)

Not asking to close parent (has open children).

Running bd sync...
```

### Cleanup: Worktree Remove Fails

```
git worktree remove .worktrees/feature-claude-tools-abc-login
Error: '.worktrees/feature-claude-tools-abc-login' contains modified or
untracked files, use --force to delete.

⚠️ Worktree has uncommitted changes. You can:
  - git worktree remove --force .worktrees/feature-...
  - Or clean up manually later.

Continuing with branch deletion...
```

### Cleanup: Remote Branch Already Deleted

```
git push origin --delete feature/claude-tools-abc-login
error: unable to delete 'feature/claude-tools-abc-login': remote ref does not exist

Remote branch already deleted (possibly by GitHub auto-delete on PR merge).
Continuing...
```

### Cleanup: Branch Delete Refuses (Unmerged)

```
git branch -d feature/claude-tools-abc-login
error: The branch 'feature/claude-tools-abc-login' is not fully merged.

⚠️ Branch has unmerged changes.
PR state is MERGED — safe to force-delete.

Force-delete with `git branch -D`? (yes/no)
```

## The Bottom Line

Always follow the workflow.

**Check branch FIRST.** Feature branch + no PR → stop. Feature branch + PR → ask user.

**Ask before closing parents.** Even when "obviously" all children closed.

**Run bd sync ALWAYS.** At end, no exceptions.

**Offer cleanup.** If branch matches task, show what will be deleted and ask. Non-blocking — failure doesn't undo the close.

Obvious logic requires MORE structure, not less.
