---
name: done
description: Complete and verify a beads task — confirm the git branch, close the task, clean up the local implementation plan, recursively offer to close parents, then sync. Use when work is finished and verified and you want to close out the task.
allowed-tools: Bash(bd:*) Bash(git:*) Bash(gh:*) Bash(flow-current-task:*) Bash(flow-find-leaf) Bash(flow-find-leaf:*) Bash(flow-in-worktree) Bash(flow-link-doc:*) Bash(flow-require-bd) Bash(flow-sync:*) Bash(flow-review-ledger) Bash(flow-review-ledger:*) Bash(cat:*) Bash(grep:*) Bash(head:*) Bash(tail:*) Bash(cut:*) Bash(tr:*) Bash(wc:*) Bash(echo:*) Bash(test:*) Bash(ls:*) Bash(cd:*) Bash(jq:*)
---

# Flow: Done

## Overview

**Core principle:** Decide everything up front, show it once, approve it once.

This skill collects every fact about the task, the branch, its parents, its plan, and its cleanup
targets before printing anything, then presents one scenario — what it will do and what it will
deliberately leave undone — for a single approval. Nothing executes before that approval, and a
correction reprints the whole scenario rather than being applied silently.

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 1. **Collect state** | Branch, mergedness, task, parents, plan, worktree, ledger | One pass, no questions, no side effects |
| 2. **Safety check: is the work merged?** | Compare trees with `git merge-tree` | Not merged → stop, point to `finishing-a-development-branch` |
| 3. **Scenario and the single question** | Print Сделаю / Не буду and ask once | Everything the run will do is in this one block |
| 4. **Handle the answer** | Approve / correct / refuse | Correction reprints the full scenario and asks again |
| 5. **Execute** | Fixed order: beads, plan, sync, git, ledger | Errors don't block; each becomes a summary line |
| 6. **Summary** | Report the actual outcome per item | Names every divergence from the approved scenario |

**Key behavior:** One scenario covers everything — parent closing, the plan's fate, branch/worktree/remote deletion, the ledger. Epics are never closed by default. `flow-sync push` always runs. Mergedness, not PR existence, is the safety-check signal.

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
if [ -n "$(git remote)" ]; then
  # remote mode: fetch first, compare against the remote base
  git fetch --quiet
  BASE=$(git symbolic-ref refs/remotes/origin/HEAD | sed 's|refs/remotes/||')
else
  # local-only mode: first existing of master, main
  BASE=$(git show-ref --verify --quiet refs/heads/master && echo master || echo main)
fi
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

**Branch match:** does `CURRENT_BRANCH` actually belong to the resolved task?

```bash
flow-current-task {task-id} || echo "BRANCH_MISMATCH"
```

Run this check regardless of how the task was resolved above — including when it came from
`flow-find-leaf`, the last-resort case, which has had no chance yet to be checked against the
branch at all. This fact gates every deletion candidate below (worktree, local branch, remote
branch, ledger) in step 3; it never gates task closure, the parent chain, the plan, or the sync —
those apply to the task regardless of which branch we happen to be on.

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

**If step 1 found `BRANCH_MISMATCH`** (the current branch is not the resolved task's branch — e.g.
a generic branch like `master`, or an unrelated feature branch): the mergedness check describes
that branch's relationship to the base, not this task's, so it says nothing safety-relevant here —
skip it. Continue to step 3 without asking anything: the scenario will still close the task and
sync, but every branch/worktree/remote/ledger candidate is refused, not offered (see step 3).

**If the branch matches the task and step 1 found it not merged into the base:**

**STOP** and inform the user:

> "Branch `{branch-name}` has not been merged into `{base}`.
>
> Use `superpowers:finishing-a-development-branch` to properly complete this work (handles merge/PR/cleanup and task closure together)."

Exit. Do not continue the workflow — nothing is closed, nothing is deleted, nothing is synced.

**If the git-version guard from step 1 fired** (no `git merge-tree --write-tree` available), ask
the user directly to confirm the branch is merged before continuing. Do not silently treat an
unconfirmable state as merged, and do not fall back to `git branch --merged`.

**If the branch matches the task and is merged:** continue silently to step 3. No output yet.

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
| Worktree | delete | we are in a worktree, and the branch matches the task |
| Local branch | delete, `-D` under squash | mergedness confirmed, and the branch matches the task |
| Remote branch | delete | remote mode, branch exists, and the branch matches the task |
| Ledger | purge when `MERGED`; leave when `CLOSED` or `OPEN` | PR known, ledger exists, and the branch matches the task |
| Container parent | close | all children closed, type ≠ `epic` |
| Epic parent | do not close | all children closed, type `epic` |
| `flow-sync push` | do | always |

Epics are excluded from automatic closing because they are long-lived and keep gaining children.

**The ledger's gate is the PR's state, never branch deletion.** A branch is routinely kept on
purpose after a merge — for history, or to re-read what happened in review — so its survival must
not keep a settled PR's ledger alive forever; conversely a successful `git branch -d` says nothing
about whether the PR is still taking review. Only `MERGED` purges; `CLOSED` and `OPEN` leave it,
because a closed PR can still be reopened and a still-open one is still taking review.

**When step 1 found `BRANCH_MISMATCH`:** the four branch-gated rows above never move to "Сделаю",
regardless of what exists. Each one that actually exists (a worktree we happen to be sitting in, a
local or remote branch, a ledger) appears instead under "Не буду" with the reason "ветка не
относится к задаче {task-id}" — a real resource that could be mistaken for deletable is a
deliberate refusal, not something to omit silently.

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
3. Plan: `rm` (or `mv` to `docs/archive/`) whenever the scenario lists the plan for deletion — this
   fires regardless of which source found the file (linked or untracked). Then, **only if** the
   task description held a `Plan:` line, `flow-link-doc {task-id} Plan ""` to remove the now-stale
   link. A plan found only as an untracked file (Source B in step 1) never had a link to remove, so
   the second half never fires for it.
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
✅ Collect all state — branch, mergedness, task, parents, plan, worktree, ledger — before deciding anything
✅ Determine mergedness through git (`git merge-tree`), not PR existence
✅ Find in_progress leaf task (session context → branch → `flow-find-leaf`)
✅ Close task with bd close
✅ Find plan file (linked in description OR untracked in `docs/plans/` / `docs/superpowers/plans/`)
✅ Remove `Plan:` link from description after delete/archive
✅ Check parents recursively; close non-epic containers whose children are all closed
✅ Print one scenario — Сделаю / Не буду — and ask the single question
✅ Execute the scenario after one approval
✅ Run flow-sync push at end
✅ Purge the PR's persistent review ledger when the scenario says so
✅ Delete local branch, remote branch, worktree when the scenario says so
✅ Switch to default branch and pull after cleanup

### This Skill Does NOT:
❌ Git operations unrelated to cleanup (commit, push, merge, etc.) — including committing the plan file's own deletion/move; the branch cleanup step (or the user's next workflow) handles git state
❌ Create branches
❌ Start next task (use flow:start)
❌ Update PRs or issues
❌ Run tests or builds
❌ Ask per action — everything is decided once, in the scenario
❌ Close epics by default — they go in "Не буду"; the user closes them explicitly
❌ Invoke `gh` without a remote — local-only mode has no platform to check
❌ Search for branches beyond the current one
❌ Clean up branches for parent tasks (cascade closures)
❌ Block task closure if cleanup fails

**Scope note:** The safety check (step 2) stops when the branch's tree doesn't match the base's,
regardless of PR state, and points to `superpowers:finishing-a-development-branch`. Cleanup
(worktree, local branch, remote branch, ledger) lives inside the single scenario (step 3) and
applies only when the branch matches the closed task; it is non-blocking.

## Red Flags - STOP

If you're thinking any of these, STOP and follow the workflow:

- "The PR is merged, I'll just close the task and skip the scenario" → The scenario is how the user
  approves everything at once. Skipping it means acting without approval, not saving a step.
- "There's no PR, so the work isn't finished" → A PR is not the signal. Compare the trees. A
  repository without remotes has no PR by construction and can still be fully merged.
- "All children are closed, so the epic is done too" → Epics keep gaining children. They go in
  "Не буду"; the user closes them explicitly.
- "The user says it's already merged and there's no remote anyway — I'll take their word for it" →
  Never substitute a verbal claim for the check. `git merge-tree` works with or without a remote;
  run it.
- "The PR is OPEN, but the branch matches the task, so the bundled cleanup line covers deleting it
  anyway" → Mergedness gates the whole run, not just the ledger. Not merged means STOP at step 2 —
  no scenario gets printed at all.
- "This failure isn't one the skill names by example, but 'errors don't block' covers it anyway" →
  It does, explicitly, for any git or tooling failure encountered in step 5 — that's stated outright,
  not something to infer by analogy from a shorter list.
- "flow-sync push obviously runs, I don't need to put it in the scenario" → Obvious steps are
  exactly the ones a scenario exists to make visible. It's always the last numbered line.
- "Branch doesn't match the task, but I'll clean up anyway" → A mismatched branch's resources go
  into "Не буду" with a named reason, never into "Сделаю".
- "They answered yes with a change — that's approval enough, apply it and finish" → A correction is
  not an approval. Reprint the whole scenario and ask again.

**All of these mean: collect state first, let git decide mergedness, print exactly one scenario, get one approval, and reprint on any correction.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "The PR is merged, I'll skip the scenario and just close things" | The scenario is how the user approves everything at once — it isn't an extra step to route around. |
| "There's no PR, so the work isn't finished" | A PR is not the signal. Compare the trees (`git merge-tree`). A repository without remotes has no PR by construction and can still be fully merged. |
| "All children closed → the epic is done too" | Epics keep gaining children. They go in "Не буду"; the user closes them explicitly. |
| "They said yes with a change, I'll just apply it" | Reprint the scenario and ask again. The second confirmation is the guarantee the correction was understood. |
| "The user says it's already merged, take their word for it" | Nothing in the skill accepts a verbal assertion as evidence. `git merge-tree` works without a remote — run it. |
| "PR is OPEN, but cleanup was already bundled into one yes" | Mergedness, not PR state, gates cleanup. An unmerged branch never reaches step 3 at all. |
| "flow-sync push is obvious, it doesn't need a line" | Obvious steps are exactly what the scenario exists to make explicit. It's in every scenario, always. |
| "Use SQL directly for efficiency" | `bd close` has logging, events, and validation. Use it. |
| "Branch doesn't match, clean up anyway" | Only clean up when the branch matches the task. A mismatched resource is a named refusal, not silent cleanup. |
| "No Plan: link → skip the plan search" | Always search `docs/plans/` and `docs/superpowers/plans/` for untracked files too — plans aren't always linked. |
| "This specific failure isn't listed, but 'non-blocking' covers it" | It's explicit: any git or tooling failure during execution is non-blocking, not just the ones named as examples. |

## Examples

### ✅ GOOD: Full scenario approved

```
User: "PR merged, flow:done"
Agent: [Step 0: flow-require-bd OK]
       [Step 1: collects branch, mergedness via git merge-tree, task, parents, plan, worktree,
        remote branch, ledger — no output yet]
       [Step 2: branch matches the task and is merged into origin/master — continue silently]

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

User: да
Agent: [Step 5: executes 1-7 in fixed order — beads, plan, sync, git, ledger]

       Выполнено:
         1. ✓ задача claude-tools-elf.59 закрыта
         2. ✓ план удалён
         3. ✓ worktree удалён
         4. ✓ локальная ветка удалена
         5. ✓ ветка на origin удалена
         6. ✓ ledger PR #138 удалён
         7. ✓ beads синхронизированы

       Готово.
```

**Correct because:**
- All state was collected silently before anything was printed
- One block covers every action, including the deliberate epic refusal
- The single question was asked once and answered once
- The summary reports the actual outcome of every scenario item

### ✅ GOOD: Correction reprints the whole scenario

```
User: "flow:done"
Agent: [collects state, safety check passes]

       Задача claude-tools-elf.6 — удалить ветки и worktree
       Ветка  feature/claude-tools-elf.6-delete-branches-worktrees → влита в origin/master (PR #123 MERGED)

       Сделаю:
         1. закрою задачу claude-tools-elf.6
         2. удалю worktree .worktrees/feature-claude-tools-elf.6-delete-branches-worktrees
         3. удалю локальную ветку
         4. удалю ветку на origin
         5. удалю review ledger PR #123 (PR смержен, ревью закрыто)
         6. синхронизирую beads (flow-sync push)

       Выполнять? («да», или скажи, что изменить)

User: да, но локальную ветку оставь
Agent: [applies the correction, reprints the whole scenario with continuous numbering, asks again
        — nothing has executed yet]

       Задача claude-tools-elf.6 — удалить ветки и worktree
       Ветка  feature/claude-tools-elf.6-delete-branches-worktrees → влита в origin/master (PR #123 MERGED)

       Сделаю:
         1. закрою задачу claude-tools-elf.6
         2. удалю worktree .worktrees/feature-claude-tools-elf.6-delete-branches-worktrees
         3. удалю ветку на origin
         4. синхронизирую beads (flow-sync push)

       Не буду:
         5. удалять локальную ветку — оставлена по вашей просьбе

       Выполнять? («да», или скажи, что изменить)

User: да
Agent: [Step 5: executes the corrected scenario]

       Выполнено:
         1. ✓ задача claude-tools-elf.6 закрыта
         2. ✓ worktree удалён
         3. ✓ ветка на origin удалена
         4. ✓ beads синхронизированы

       Готово.
```

**Correct because:**
- The correction was applied, not just acknowledged
- The whole scenario was reprinted with continuous numbering, not shown as a diff
- A second question followed — the correction still needed its own approval
- Execution only started after the second "да"

### ✅ GOOD: Local-only repository — no PR lines

```
User: "flow:done"
Agent: [Step 1: git remote is empty → local-only mode; gh is never invoked; base is the first
        existing of master/main; mergedness comes from git merge-tree alone]

       Задача claude-tools-5vg.3 — офлайн-скрипт импорта
       Ветка  feature/claude-tools-5vg.3-import-script → влита в master (локальный репозиторий, PR/remote нет)

       Сделаю:
         1. закрою задачу claude-tools-5vg.3
         2. удалю план docs/plans/2026-08-20-import-script-plan.md
         3. удалю локальную ветку
         4. синхронизирую beads (flow-sync push)

       Выполнять? («да», или скажи, что изменить)

User: да
Agent: [executes — there are no remote-branch or ledger lines to run]

       Выполнено:
         1. ✓ задача claude-tools-5vg.3 закрыта
         2. ✓ план удалён
         3. ✓ локальная ветка удалена
         4. ✓ beads синхронизированы

       Готово.
```

**Correct because:**
- No `gh pr view` call happened — the repository has no remote
- Mergedness came from comparing trees against the local base, not from a PR
- The scenario has no remote-branch or ledger lines because those facts are absent from the
  environment, not because they went unasked

### ✅ GOOD: Safety check stops an unmerged branch

```
User: "flow:done"
Agent: [Step 1: collects state; mergedness check finds the branch's tree differs from
        origin/master's]
       [Step 2: branch matches the task and is NOT merged — STOP before printing any scenario]

       Branch `feature/claude-tools-test.1-sample` has not been merged into `origin/master`.

       Use `superpowers:finishing-a-development-branch` to properly complete this work (handles
       merge/PR/cleanup and task closure together).
```

**Correct because:**
- The stop is based on comparing trees, not on PR state — an OPEN or even absent PR would have
  stopped the run the same way
- Nothing is closed, deleted, or synced before the stop
- No scenario is printed — printing one would imply something is already waiting for approval

## Edge Cases

### Worktree Remove Fails

```
git worktree remove .worktrees/feature-claude-tools-abc-login
Error: '.worktrees/feature-claude-tools-abc-login' contains modified or
untracked files, use --force to delete.
```

Non-blocking, and coupled: since we're still checked out there, the local branch delete is skipped
too. Both show up as summary lines, not a question:

```
Выполнено:
  3. ✗ worktree не удалён: содержит незакоммиченные изменения
  4. — локальная ветка не удалена (worktree занят)

Осталось вручную: git worktree remove --force .worktrees/feature-claude-tools-abc-login
```

### Remote Branch Already Deleted

```
git push origin --delete feature/claude-tools-abc-login
error: unable to delete 'feature/claude-tools-abc-login': remote ref does not exist
```

Non-blocking — GitHub's auto-delete-on-merge likely already removed it. One summary line, no
question:

```
Выполнено:
  5. ✓ ветка на origin удалена (уже была удалена — вероятно, автоматически при мердже)
```

### No In-Progress Tasks

`flow-find-leaf` is the last-resort task resolver in step 1 — it only runs when neither session
context nor the branch identifies a task. If it finds nothing either, there is no task to build a
scenario for:

```
Не найдено ни одной задачи in_progress.

Проверьте статус: bd list --status=in_progress
```

### Git Older Than 2.38

`git merge-tree --write-tree` is unavailable, so step 1 cannot compute mergedness on its own. This
is the one case, besides task-identity conflicts, where the skill asks a direct question before the
scenario:

```
`git merge-tree --write-tree` недоступен (нужен git >= 2.38) — не могу сам проверить, влита ли
ветка `feature/claude-tools-abc-login` в `origin/master`.

Подтвердите, что работа влита в базовую ветку? (yes/no)
```

Never fall back to `git branch --merged` here — it reports false after a squash merge, which is
exactly the case this check exists for.

### Session Context and Branch Disagree About the Task

Session context says the task is `claude-tools-elf.6`, but `CURRENT_BRANCH`'s `Git:` line matches
`claude-tools-elf.9` instead. Both are shown and the user is asked before anything else — the only
question about task identity the skill may ask, because the rest of the run depends on getting it
right:

```
Контекст сессии указывает на claude-tools-elf.6, а текущая ветка соответствует задаче
claude-tools-elf.9 (по её Git: записи).

Какую задачу закрываем — elf.6 или elf.9?
```

### Several `Git:` Lines on One Task

A task recorded more than one branch (`flow:start` step 8.1's `--append`, for a parallel workstream
in another project or PR). The scenario is built for `CURRENT_BRANCH` only, as today
(`claude-tools-elf.51`) — the task's other recorded branches are neither compared nor touched.

## The Bottom Line

Always follow the workflow.

**Collect before deciding.** Branch, mergedness, task, parents, plan, worktree, and ledger are all
gathered in one pass, before anything is printed or decided.

**The safety check is mergedness, not a PR.** `git merge-tree` compares trees. A PR's existence or
state settles nothing about whether the branch actually reached the base.

**One scenario, one approval.** Everything the run will do, and everything it deliberately won't,
is in that one block. A correction reprints it whole and asks again — nothing executes on a partial
answer.

**The summary must show divergences.** The approval was given once, in advance, to a list — the
summary is obliged to report every item that didn't go as promised.

Obvious logic requires MORE structure, not less.
