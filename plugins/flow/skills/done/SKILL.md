---
name: done
description: Complete and verify a beads task — confirm the git branch, close the task, clean up the local implementation plan, recursively offer to close parents, then sync. Use when work is finished and verified and you want to close out the task.
allowed-tools: Bash(bd:*) Bash(git:*) Bash(gh:*) Bash(flow-current-task:*) Bash(flow-in-worktree) Bash(flow-link-doc:*) Bash(flow-require-bd) Bash(flow-sync:*) Bash(flow-review-ledger) Bash(flow-review-ledger:*) Bash(cat:*) Bash(grep:*) Bash(head:*) Bash(tail:*) Bash(cut:*) Bash(tr:*) Bash(wc:*) Bash(echo:*) Bash(test:*) Bash(ls:*) Bash(cd:*) Bash(jq:*)
---

# Flow: Done

## Overview

**Core principle:** Ask before cascading.

This skill handles task completion: close task, clean up plan files, check parents recursively, sync. Always asks before closing parent tasks - even when "obviously" all children are closed.

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 1. **Branch Check** | Validate git branch + PR | Feature + no PR → stop; Feature + PR → ask |
| 2. Find Task | Get in_progress leaf | Ask if multiple |
| 3. Close | `bd close {task-id}` | Use bd, not SQL |
| 4. **Plan Cleanup** | Find and remove plan file | Ask: delete / archive / keep |
| 5. **Check Parent** | Recursive parent check | With confirmation |
| 6. **Ask** | Before closing parent | Even if "obvious" |
| 7. **Sync** | `flow-sync push` | Always, at end |
| 8. **Cleanup** | Delete branch/worktree | Only if branch matches task; ask first |

**Key behavior:** Always ask before closing parents. Always check PR on feature branches. Always clean up plan files. Always run flow-sync push. Offer cleanup after sync.

## Workflow

Follow these steps **in order**. Do not skip steps.

### 0. Require supported bd

```bash
flow-require-bd
```

If this exits non-zero, **STOP**: print its stderr message and run no further commands. flow requires `bd >= 1.0.0` — see `plugins/flow/README.md`, section "bd requirements and migration".

### 1. Collect state

One pass, no questions, no side effects. Gather every fact step 3's scenario needs before printing
anything.

**Branch and repository mode:**

```bash
CURRENT_BRANCH=$(git branch --show-current)
git remote   # empty → local-only mode; any output → remote mode
```

**Base branch and mergedness.** This is the safety check's criterion (step 2), so get it right:

```bash
# remote mode: fetch first, compare against the remote base
git fetch --quiet
BASE=$(git symbolic-ref refs/remotes/origin/HEAD | sed 's|refs/remotes/||')
# local-only mode: first existing of master, main
MERGED_TREE=$(git merge-tree --write-tree "$BASE" "$CURRENT_BRANCH")
BASE_TREE=$(git rev-parse "$BASE^{tree}")
# equal → the branch adds nothing to the base → merged (survives squash and rebase)
```

Two rules go with it:
- **The base comes from the remote, after a fetch** — never from a local `master`/`main` that may
  lag behind (no `git pull` since the PR merged). A stale local base makes the criterion lie and
  the safety check evict the user for no reason.
- **`gh` is not invoked at all when `git remote` is empty.** In local-only mode there is no
  platform to ask; its absence is not "no PR" and is not grounds to stop.

`git merge-tree --write-tree` requires git >= 2.38. If it is unavailable, say so, print the branch
and the base you could not compare, and ask the user to confirm the work is merged. **Never fall
back to `git branch --merged`** — it reports false after a squash merge, which is exactly the case
this check exists for.

**PR state** (remote mode only, no `gh` call in local-only mode):

```bash
gh pr view --json state,url,number 2>/dev/null || echo "NO_PR"
```

Capture `PR_URL` (`.url`), `PR_NUMBER` (`.number`) and `PR_STATE` (`.state`) when present — step 5
needs the first two to address this PR's review ledger and the third to decide whether purging it
is safe.

**Task.** Resolve in this order:
1. **Session context** — `flow:done` normally follows `flow:start`/`flow:continue` in the same
   session, so the task is already known. Verify it against the branch before using it.
2. **The branch** — after a `/clear`: match the task id in the branch name against the `Git:` lines
   of candidate tasks (`bd show`), as `flow:continue` does.
3. **`flow-find-leaf`** — last resort only, when neither of the above resolves.

If context and branch disagree, show both and ask **before** printing the scenario. This is the
only question about task identity the skill may ask. Never resolve the task by eyeballing
`bd list --status=in_progress`.

**Parent chain:** `bd show {task-id}` upwards — id, type (`epic` or not), open-children count for
each ancestor.

**Plan file.** Two sources, check in order:

- **Source A — task description link:** `bd show {task-id}`, look for a `Plan:` line (also
  matches `Plan (label):`); extract the file path.
- **Source B — untracked/modified files**, when Source A found nothing, across **both** the
  pre-v5 and superpowers 5.x+ locations:
  ```bash
  git ls-files --others --modified -- 'docs/plans/' 'docs/superpowers/plans/'
  ```
  Do **not** add `--exclude-standard`. In repos that gitignore the plans directory, untracked plan
  files would otherwise be hidden. Safety here comes from git itself: `--others --modified`
  surfaces only untracked or unstaged files, never clean committed ones — so committed plans are
  never offered for deletion, whichever directory they live in.

Filter results by filename containing "impl" or "plan" (case-insensitive) and semantically
matching the task title. Multiple candidates or no candidates are both facts to carry into the
scenario, not something to ask about here.

**Worktree:** `flow-in-worktree` — exit 0 if we are in a worktree.
**Remote branch:** `git branch -r | grep "$CURRENT_BRANCH"`.
**Ledger:** present when a `PR_NUMBER` was captured above — the PR's `flow:review-comments`
memory, stored under the OS cache dir, never in the repo.

### 2. Safety check: is the work merged?

**If step 1 found the branch not merged into the base:**

**STOP** and inform the user:

> "Branch `{branch-name}` has not been merged into `{base}`.
>
> Use `superpowers:finishing-a-development-branch` to properly complete this work (handles merge/PR/cleanup and task closure together)."

Exit. Do not continue the workflow — nothing is closed, nothing is deleted, nothing is synced.

**If the git-version guard from step 1 fired** (no `git merge-tree --write-tree` available), ask
the user directly to confirm the branch is merged before continuing. Do not silently treat an
unconfirmable state as merged, and do not fall back to `git branch --merged`.

**If the branch is merged:** continue silently to step 3. No output yet.

### 3. Scenario and the single question

Print one block: a header of facts, a numbered `Сделаю` list, a `Не буду` list, and the single
question. Numbering is continuous across both lists so a correction can be short ("всё кроме 4").

```
Задача claude-tools-elf.59 — flow:done: сократить число подтверждений
Ветка  feature/claude-tools-elf.59-flow-done → влита в origin/master (squash, PR #138 MERGED)

Сделаю:
  1. закрою задачу claude-tools-elf.59
  2. удалю план docs/superpowers/plans/2026-09-01-flow-done-consolidation.md
  3. удалю worktree .worktrees/feature-claude-tools-elf.59-flow-done
  4. удалю локальную ветку (через -D: squash-мердж, -d откажет)
  5. удалю ветку на origin
  6. удалю review ledger PR #138 (PR смержен, ревью закрыто)
  7. синхронизирую beads (flow-sync push)

Не буду:
  8. закрывать эпик claude-tools-elf — все дети закрыты, но эпики пополняются

Выполнять? («да», или скажи, что изменить)
```

**Defaults for the nine checklist rows:**

| Item | Default | Appears when |
|---|---|---|
| Close the task | do | always |
| Plan file | delete | a plan was found |
| Worktree | delete | we are in a worktree |
| Local branch | delete, `-D` under squash | mergedness confirmed |
| Remote branch | delete | remote mode, branch exists |
| Ledger | purge when `MERGED`; leave when `CLOSED` or `OPEN` | PR known, ledger exists |
| Container parent | close | all children closed, type ≠ `epic` |
| Epic parent | do not close | all children closed, type `epic` |
| `flow-sync push` | do | always |

Epics are excluded from automatic closing because they are long-lived and keep gaining children.

**Mandatory sweep.** The nine rows above are a checklist. Each must either appear as a numbered
line or be omitted for an explicitly named reason. A skipped row is now a silent action or a silent
omission — not merely an unasked question.

**"Не буду" lists only deliberate refusals** — the epic, the ledger of a live PR, the branch when
mergedness is unconfirmed. What is simply absent from the environment (no remote, no plan, not in a
worktree) is not printed at all: the scenario states decisions, not an inventory.

### 4. Handle the answer

- **Approval** ("да", "ок") → go to step 5. No further questions.
- **Correction** ("да, но локальную ветку оставь", "всё кроме 4", "закрой и эпик") → apply the
  change, reprint the **whole** scenario in the same format and numbering with the changed lines
  marked, and ask again. Unlimited iterations — a correction to a correction reprints again.
- **Refusal** ("нет") → do nothing at all, including closing the task. Report that nothing changed
  and stop.
- **Unclear correction** → ask about *that item only*, then reprint the full scenario and ask
  normally.

The scenario is reprinted in full rather than as a diff: a correction can move an item between
"Сделаю" and "Не буду", and what matters at that point is the resulting state — a diff does not
show that the correction was understood.

### 5. Execute

Fixed order — beads before git, ledger last:

1. `bd close {task-id}`
2. Container parents, bottom-up (never the epic — see step 3)
3. Plan: `rm` (or `mv` to `docs/archive/`) + `flow-link-doc {task-id} Plan ""` — only when the task
   description held the `Plan:` link that is now being removed
4. `flow-sync push`
5. Leave the worktree → `git worktree remove <path>` → `git checkout <base>` → `git pull` →
   `git branch -d|-D <branch>` (`-D` only when the scenario said so, i.e. mergedness was confirmed
   under squash) → `git push origin --delete <branch>` (if the remote branch exists)
6. `flow-review-ledger purge --url "$PR_URL" --number "$PR_NUMBER"` — only when the scenario listed
   the ledger for purging (`MERGED`); a `CLOSED` or `OPEN` PR's ledger is left alone, per step 3

Beads precede git: the git part can fail on a dirty worktree, and by then the closed task must
already be recorded and synced. The ledger runs last, after branch deletion is attempted: `purge`
is irreversible and keeps no backup.

**Errors do not block.** Every item in this list runs regardless of whether an earlier one failed.
A failed item produces a line in the summary (step 6) and execution continues to the next item —
this holds for **any** git or tooling failure encountered here, not only ones this skill happens to
name, so no failure needs to match a specific description to count as non-blocking.

**One coupling:** if `git worktree remove` fails, deleting the local branch is skipped (we are
still on it) — a summary line, not a silent omission.

### 6. Summary

List the scenario items with their actual outcome, and name every divergence explicitly:

```
Выполнено:
  1. ✓ задача claude-tools-elf.59 закрыта
  2. ✓ план удалён
  3. ✗ worktree не удалён: содержит незакоммиченные изменения
  4. — локальная ветка не удалена (worktree занят)
  5. ✓ ветка на origin удалена
  6. ✓ ledger PR #138 удалён
  7. ✓ beads синхронизированы

Осталось вручную: git worktree remove --force .worktrees/feature-claude-tools-elf.59-flow-done
```

The approval was given once and in advance — to a list, not to each action as it happened — so the
summary is obliged to show where the promise was not kept.

## Scope Boundaries

### This Skill DOES:
✅ Check git branch
✅ Find in_progress leaf task
✅ Close task with bd close
✅ Find plan file (linked in description OR untracked in `docs/plans/` / `docs/superpowers/plans/`)
✅ Ask user: delete / archive / keep plan file
✅ Remove `Plan:` link from description after delete/archive
✅ Check parents recursively
✅ Ask before closing each parent
✅ Run flow-sync push at end
✅ Offer to clean up branch and worktree (Step 8)
✅ Purge the PR's persistent review ledger during cleanup (Step 8)
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

**Scope note:** On feature branches without PR, this skill STOPS and refers to finishing-a-development-branch. On feature branches WITH PR, it asks user before proceeding. Cleanup (Step 8) is non-blocking and only applies when the current branch matches the closed task.

## Red Flags - STOP

If you're thinking any of these, STOP and follow the workflow:

- "All children closed → close parent"
- "Branch check unnecessary"
- "flow-sync push is obvious (skip it)"
- "Use SQL for efficiency"
- "Parent obviously should close"
- "Being helpful by auto-closing cascade"
- "Feature branch → always block"
- "PR exists → auto-proceed"
- "Cleanup is obvious, just delete everything"
- "Skip cleanup, user can do it manually"
- "Branch doesn't match but I'll clean up anyway"
- "Force-delete is fine, PR was merged"
- "Plan cleanup is not part of the workflow"
- "No Plan: link → no plan to clean up"
- "Auto-delete the plan, user obviously doesn't need it"
- "Plan file is outside my scope"

**All of these mean: Follow workflow. Check branch AND PR. Ask before proceeding. Always check for plan files (linked AND unlinked). Run flow-sync push. Offer cleanup only if branch matches task.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "All children closed → close parent" | Ask first. User might add more children or want to review. |
| "Branch check unnecessary" | Feature branch needs different workflow. Always check. |
| "flow-sync push is obvious" | Obvious steps get skipped. Make it explicit. |
| "Use SQL for efficiency" | bd close has logging, events, validation. Use it. |
| "Parent obviously should close" | Obvious to you ≠ user wants it. Ask. |
| "Being helpful by auto-closing" | Asking IS being helpful. Assuming isn't. |
| "Feature branch → always block" | Check for PR first. If PR exists, ask user. |
| "PR exists → auto-proceed" | Still ask user. PR exists ≠ user wants to close here. |
| "Cleanup is obvious, just delete" | Ask first. User might want to keep the branch. |
| "Skip cleanup, not my job" | Step 8 is part of the workflow. Offer it. |
| "Plan cleanup is not part of completing" | Step 4 IS part of the workflow. Plan files are task artifacts. |
| "No Plan: link → skip plan search" | Always search `docs/plans/` and `docs/superpowers/plans/` for untracked files too. Plans aren't always linked. |
| "Auto-delete the plan, it's obvious" | Always ask. User might want to archive or keep for reference. |
| "Plan file is outside my scope" | Plan files are task artifacts. Cleaning them up IS in scope (Step 4). |
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
- Didn't run flow-sync push

### ✅ GOOD: Ask before closing parent

```
User: "Task done, flow:done"
Agent: [Checks branch: master, OK to proceed]
       [Closes task claude-tools-abc.3]

       Parent task claude-tools-abc now has all children closed.

       Close it too? (yes/no)

User: yes
Agent: [Closes parent]
       [Runs flow-sync push]

       ✓ Closed claude-tools-abc.3
       ✓ Closed claude-tools-abc (parent)
       ✓ Synced with remote

       Done.
```

**Correct because:**
- Checked branch first
- Asked before closing parent
- Ran flow-sync push
- Clear confirmation

### ❌ BAD: Auto-delete plan without asking

```
User: "flow:done"
Agent: [Closes task]
       [Sees Plan: link in description]
       [Deletes plan file automatically]
       [Removes Plan: link from description]
       Done!
```

**Problems:**
- Didn't ask user what to do with plan
- No archive option offered
- Violated consultation principle

### ❌ BAD: Ignores untracked plan file

```
User: "flow:done"
Agent: [Closes task]
       [No Plan: link in description → skips plan cleanup entirely]
       [Doesn't check docs/plans/ or docs/superpowers/plans/ for untracked files]
       Done!
```

**Problem:** Plan file exists as untracked in `docs/superpowers/plans/` but agent only checked description.

### ✅ GOOD: Plan cleanup with linked plan

```
User: "flow:done"
Agent: [Checks branch: master, OK]
       [Closes task claude-tools-abc]

       Plan file found: `docs/superpowers/plans/2026-02-06-abc-impl-plan.md`

       What to do with it?
       1. Delete
       2. Archive (move to docs/archive/)
       3. Keep as is

User: 2
Agent: [Moves to docs/archive/]
       [Removes Plan: link from description]
       [Checks parent, has open children]
       [Runs flow-sync push]

       ✓ Closed claude-tools-abc
       ✓ Plan archived to docs/archive/
       ✓ Synced with remote

       Done.
```

**Correct because:**
- Found plan via description link
- Asked user before acting
- Offered all three options
- Updated description after archive

### ✅ GOOD: Plan cleanup with unlinked plan

```
User: "flow:done"
Agent: [Checks branch: master, OK]
       [Closes task claude-tools-xyz "Quota module"]
       [No Plan: link in description]
       [Checks docs/plans/ and docs/superpowers/plans/ for untracked files]
       [Finds: quota-module-impl-plan.md (untracked, matches task title)]

       Plan file found: `docs/superpowers/plans/quota-module-impl-plan.md`

       What to do with it?
       1. Delete
       2. Archive (move to docs/archive/)
       3. Keep as is

User: 1
Agent: [Deletes file]
       [Checks parent, has open children]
       [Runs flow-sync push]

       ✓ Closed claude-tools-xyz
       ✓ Plan deleted
       ✓ Synced with remote

       Done.
```

**Correct because:**
- No link in description but still searched docs/plans/ and docs/superpowers/plans/
- Found untracked file matching task title
- Asked user before deleting
- No description update needed (wasn't linked)

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
       [Runs flow-sync push]

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
       [Runs flow-sync push]

       You are on branch `feature/claude-tools-elf.6-delete-branches-worktrees`.

       Delete branch and associated resources?
         - Worktree: .worktrees/feature-claude-tools-elf.6-delete-branches-worktrees
         - Local branch: feature/claude-tools-elf.6-delete-branches-worktrees
         - Remote branch: origin/feature/claude-tools-elf.6-delete-branches-worktrees
         - Review ledger for PR #123

       (yes/no)

User: yes
Agent: [cd to main repo root]
       [git worktree remove .worktrees/feature-...]
       [git checkout master]
       [git pull]
       [git branch -d feature/claude-tools-elf.6-...]
       [git push origin --delete feature/claude-tools-elf.6-...]
       [PR state is MERGED → flow-review-ledger purge --url "$PR_URL" --number "$PR_NUMBER"]

       ✓ Worktree removed
       ✓ Switched to master
       ✓ Local branch deleted
       ✓ Remote branch deleted
       ✓ Review ledger purged

       Done.
```

**Correct because:**
- Checked branch matches task ID
- Listed all cleanup targets
- Asked before deleting
- Executed in correct order (worktree → checkout → delete → purge ledger, and the purge fired because the PR is MERGED — not because the branch happened to be gone)

### ❌ BAD: Auto-cleanup without asking

```
Agent: [Closes task]
       [Runs flow-sync push]
       [Immediately deletes branch and worktree]
```

**Problem:** Didn't ask before cleanup. User might want to keep the branch.

### ✅ GOOD: Branch doesn't match — skip cleanup silently

```
Agent: [On master branch]
       [Closes task claude-tools-elf.6]
       [Runs flow-sync push]

       ✓ Closed claude-tools-elf.6
       ✓ Synced with remote

       Done.
```

**Correct because:** Branch "master" doesn't contain task ID "elf.6", so cleanup is silently skipped.

### ❌ BAD: Skip flow-sync push

```
User: "flow:done"
Agent: [Closes task]
       [Asks about parent, closes]
       Done!
```

**Problem:** Skipped flow-sync push at end.

### ✅ GOOD: Always flow-sync push

```
User: "flow:done"
Agent: [Checks branch]
       [Closes task]
       [Asks about parent, closes if yes]
       [Runs flow-sync push]

       ✓ Synced with remote

       Done.
```

**Correct because:**
- flow-sync push always run at end
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

### Plan File Linked but Already Deleted

```
Task description has Plan: docs/superpowers/plans/old-plan.md
File does not exist on disk.

Plan file referenced in description not found: docs/superpowers/plans/old-plan.md
(already deleted or moved)

Removing stale Plan: link from description.
```

### Multiple Untracked Plan Files Match

```
Found multiple plan file candidates in docs/plans/ or docs/superpowers/plans/:
1. quota-module-impl-plan.md (untracked)
2. quota-implementation-plan.md (untracked)

Which file is the implementation plan for this task? (1, 2, or "none")
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

No more parents. Running flow-sync push...
```

### Parent Has Open Sibling

```
Closed claude-tools-abc.1

Parent claude-tools-abc still has open children:
- claude-tools-abc.2 (open)

Not asking to close parent (has open children).

Running flow-sync push...
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

**Run flow-sync push ALWAYS.** At end, no exceptions.

**Offer cleanup.** If branch matches task, show what will be deleted and ask. Non-blocking — failure doesn't undo the close.

Obvious logic requires MORE structure, not less.
