---
name: done
description: Complete and verify a beads task — collect branch, task, parent, plan, and cleanup state, present one scenario for a single approval, then close the task, clean up the plan, close eligible parents, and sync. Use when work is finished and verified and you want to close out the task.
allowed-tools: Bash(bd:*) Bash(git:*) Bash(gh:*) Bash(flow-current-task) Bash(flow-current-task:*) Bash(flow-find-leaf) Bash(flow-find-leaf:*) Bash(flow-in-worktree) Bash(flow-link-doc:*) Bash(flow-require-bd) Bash(flow-sync:*) Bash(flow-review-ledger) Bash(flow-review-ledger:*) Bash(cat:*) Bash(grep:*) Bash(head:*) Bash(tail:*) Bash(cut:*) Bash(tr:*) Bash(wc:*) Bash(echo:*) Bash(test:*) Bash(ls:*) Bash(cd:*) Bash(jq:*) Bash(rm:*) Bash(mv:*) Bash(mkdir:*)
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
| 1. **Collect state** | Branch, mergedness, task, parents, plan, worktree, ledger | One pass, no questions; the only writes are `git fetch` and restoring the remote's HEAD symref |
| 2. **Safety check: is the work merged?** | Compare trees with `git merge-tree` | Not merged → stop, point to `finishing-a-development-branch` |
| 3. **Scenario and the single question** | Print Сделаю / Не буду and ask once | Everything the run will do is in this one block |
| 4. **Handle the answer** | Approve / correct / refuse | Correction reprints the full scenario and asks again |
| 5. **Execute** | Fixed order: beads, plan, sync, git, ledger | Errors don't block, except a failed `bd close`, which skips parents and the plan; each becomes a summary line |
| 6. **Summary** | Report the actual outcome per item | Names every divergence from the approved scenario |

**Key behavior:** One scenario covers everything — parent closing, the plan's fate, branch/worktree/remote deletion, the ledger. Epics are not closed unless the user asks. `flow-sync push` always runs. Mergedness against the PR's own target branch, not PR existence, is the safety-check signal.

## Workflow

Follow these steps **in order**. Do not skip steps.

### 0. Require supported bd

```bash
flow-require-bd
```

If this exits non-zero, **STOP**: print its stderr message and run no further commands. flow requires `bd >= 1.0.0` — see `plugins/flow/README.md`, section "bd requirements and migration".

### 1. Collect state

One pass, no questions. The only external effects are the `git fetch` below and, when the remote's
HEAD symref is missing, `git remote set-head --auto` — both touch remote-tracking refs and nothing
else: no working tree, no branch, no task is changed here. Gather every fact step 3's scenario needs
before printing anything.

**Branch and repository mode:**

```bash
CURRENT_BRANCH=$(git branch --show-current)
git remote   # empty → local-only mode; any output → remote mode
```

**PR state** (remote mode only, no `gh` call in local-only mode). This runs **before** the base
block below, which uses the PR's target branch as its first base candidate.

```bash
PR_JSON=$(gh pr view --json state,url,number,baseRefName 2>/dev/null)
if [ -n "$PR_JSON" ]; then
  PR_STATE=$(echo "$PR_JSON" | jq -r .state)
  PR_URL=$(echo "$PR_JSON" | jq -r .url)
  PR_NUMBER=$(echo "$PR_JSON" | jq -r .number)
  PR_BASE=$(echo "$PR_JSON" | jq -r .baseRefName)
elif gh pr list --state all --limit 1 --json number >/dev/null 2>&1; then
  PR_STATE=NO_PR        # gh reached the platform; this branch simply has no PR
else
  PR_STATE=UNKNOWN      # the lookup itself failed — auth, rate limit, network
fi
```

`PR_URL` and `PR_NUMBER` are what step 5 needs to address this PR's review ledger; `PR_STATE`
decides whether purging it — and whether deleting the remote branch — is safe; `PR_BASE` is the
first base candidate below.

**A failed lookup is not "no PR".** `gh pr view` exits non-zero both when no PR exists and when the
call fails, so the exit status alone cannot tell them apart, and `|| echo NO_PR` silently reads a
network blip as "no PR". That mistake is not cosmetic: an unset `PR_STATE` trivially satisfies "not
`OPEN`", and the run would then `git push "$REMOTE" --delete` a branch whose PR is live — which
closes that PR. Hence the second call: `gh pr list` exits 0 and prints `[]` when the platform was
reached and there is no PR, and non-zero when the lookup failed. `UNKNOWN` refuses the remote-branch
row exactly as `OPEN` does (step 3), and falls through to the next base candidate below rather than
yielding an empty base.

**Base branch and mergedness.** This is the safety check's criterion (step 2), so get it right.
The block below produces **two distinct values, never interchangeable**:

- `BASE_REF` — the **comparison base** (`origin/master` in remote mode), used by `merge-tree`
  and `rev-parse`;
- `BASE_LOCAL` — the **checkout target** (`master`), the local branch name step 5 checks out.

Checking out `BASE_REF` detaches HEAD and makes the following `git pull` fail with "You are not
currently on a branch"; comparing against `BASE_LOCAL` in remote mode compares against a possibly
stale local ref. Keep them apart.

```bash
if [ -n "$(git remote)" ]; then
  # remote mode: fetch first, compare against the remote base
  git fetch --quiet
  REMOTE=$(git remote | head -1)   # usually origin — never assume the name
  BASE_LOCAL=""
  # every candidate must name a branch the remote actually has; one that does not
  # falls through to the NEXT candidate, never straight to master/main
  # 1. the PR/MR's own target branch — where this work was supposed to land
  if [ -n "$PR_BASE" ] && [ "$PR_BASE" != "null" ] && git show-ref --verify --quiet "refs/remotes/$REMOTE/$PR_BASE"; then
    BASE_LOCAL="$PR_BASE"
  fi
  # 2. the remote's HEAD symref, restored from the server when it is missing
  if [ -z "$BASE_LOCAL" ]; then
    git symbolic-ref --quiet "refs/remotes/$REMOTE/HEAD" >/dev/null || git remote set-head "$REMOTE" --auto >/dev/null 2>&1
    symref=$(git symbolic-ref --quiet "refs/remotes/$REMOTE/HEAD")
    candidate="${symref#refs/remotes/$REMOTE/}"
    if [ -n "$candidate" ] && git show-ref --verify --quiet "refs/remotes/$REMOTE/$candidate"; then BASE_LOCAL="$candidate"; fi
  fi
  # 3. this branch's own upstream — but never the branch itself
  if [ -z "$BASE_LOCAL" ]; then
    upstream=$(git rev-parse --abbrev-ref "@{upstream}" 2>/dev/null)
    candidate="${upstream#$REMOTE/}"
    if [ -n "$candidate" ] && [ "$candidate" != "$CURRENT_BRANCH" ] && git show-ref --verify --quiet "refs/remotes/$REMOTE/$candidate"; then
      BASE_LOCAL="$candidate"
    fi
  fi
  # 4. the conventional names, in order
  if [ -z "$BASE_LOCAL" ] && git show-ref --verify --quiet "refs/remotes/$REMOTE/master"; then BASE_LOCAL=master; fi
  if [ -z "$BASE_LOCAL" ] && git show-ref --verify --quiet "refs/remotes/$REMOTE/main"; then BASE_LOCAL=main; fi
  BASE_REF="$REMOTE/$BASE_LOCAL"
else
  # local-only mode: same fallback chain over local heads
  BASE_LOCAL=""
  if git show-ref --verify --quiet refs/heads/master; then BASE_LOCAL=master; fi
  if [ -z "$BASE_LOCAL" ] && git show-ref --verify --quiet refs/heads/main; then BASE_LOCAL=main; fi
  BASE_REF="$BASE_LOCAL"
fi

if [ -z "$BASE_LOCAL" ]; then
  echo "NO_BASE"
else
  MERGED_TREE=$(git merge-tree --write-tree "$BASE_REF" "$CURRENT_BRANCH")
  BASE_TREE=$(git rev-parse "$BASE_REF^{tree}")
  # equal → the branch adds nothing to the base → merged (survives squash and rebase)
  WORKTREE_DIRTY=$(git status --porcelain --untracked-files=all)
  # non-empty → the working copy holds content that exists nowhere else (gates the worktree row)
fi
```

Eight rules go with it:
- **Each candidate is validated where it is chosen, and a bad one falls through to the next.** A
  candidate is accepted only if `refs/remotes/$REMOTE/<name>` exists; otherwise the chain continues
  with the following candidate, never straight to `master`/`main` and never to `NO_BASE`. A target
  branch deleted after its own merge, or a dangling HEAD symref, must not shadow a perfectly good
  later candidate — in a repository whose default branch is neither `master` nor `main`, validating
  once at the end of the chain turns either of those into `NO_BASE` and stops the run for nothing.
- **The base comes from the remote, after a fetch** — never from a local `master`/`main` that may
  lag behind (no `git pull` since the PR merged). A stale local base makes the criterion lie and
  the safety check evict the user for no reason.
- **The PR's own target comes first, and the reason is stacked branches.** A subtask branch is
  routinely opened against its **feature** branch, not against the repository's default branch;
  compared against the default branch it reads "not merged" until the whole feature lands, and the
  safety check would then refuse to close exactly the tasks that get closed most often. The PR/MR
  target is the precise answer to "where was this work supposed to land": the feature branch for a
  subtask, the default branch for a feature. On GitLab the same value is
  `glab mr view <iid> --output json --jq .target_branch`.
- **`git symbolic-ref` is only the second candidate, not the answer.** `refs/remotes/<remote>/HEAD`
  is frequently absent or not a symbolic ref (`fatal: ref refs/remotes/origin/HEAD is not a
  symbolic ref` — this repository has no such ref at all), the default branch may carry **any**
  name, and the remote is not always called `origin`. `git remote set-head "$REMOTE" --auto` asks
  the server which branch is default and restores the symref, so it is tried before giving up on
  it; the `master` → `main` pair is a last-ditch convention, not the definition of a base.
- **The branch's own upstream is a candidate only when it is not the branch itself.**
  `git rev-parse --abbrev-ref "@{upstream}"` usually returns `$REMOTE/$CURRENT_BRANCH` — using that
  as the base would compare the branch with itself and report "merged" unconditionally. It is
  useful only where the upstream was deliberately pointed at another branch, hence the guard.
- **No base means STOP** (`NO_BASE`, handled in step 2). An empty base would make `merge-tree`
  error out and every guard below it meaningless — and those guards are what stand between the run
  and irreversible deletions. Never improvise a base, and never proceed without one. Hence the
  `if`: with no base the comparison block does not run at all, so the user sees the step 2 message
  and not two `fatal:` lines from `merge-tree` and `rev-parse` against an empty ref.
- **A branch that never committed anything satisfies `MERGED_TREE == BASE_TREE` too, and no git
  command tells the two apart.** Such a branch's tip *is* the base's tip as of creation — an
  ancestor of the base, exactly like a fast-forward merge or a merge-commit merge. These are the
  same commit graph, so no counting or ancestry query separates them (`git rev-list --count`,
  `git merge-base --is-ancestor`, `git for-each-ref --contains` all agree in every one of those
  states). They do not need separating: a ref reachable from the base can be deleted without
  losing a commit, by construction. What *can* be lost is uncommitted content in the working copy,
  and `WORKTREE_DIRTY` measures exactly that.
- **`WORKTREE_DIRTY` gates the worktree row** — directly, and the local-branch row through it,
  because HEAD stays in a worktree that is not removed (step 3). It is the direct signal for the
  only irreversible loss this skill can cause on its own: removing a working copy that holds the
  sole copy of some work. `--untracked-files=all` is required — plain `git status` collapses a
  brand-new directory to a single `dir/` entry, and an untracked note inside it must count as
  content to lose. **One subtraction:** files the scenario itself lists for deletion — that is, the
  plan — do not count. They are named in the scenario and covered by the same single approval, and
  step 5 deletes the plan before it touches the worktree. Without this, an untracked plan in a
  non-gitignored `docs/plans/` would make the working copy dirty all by itself and refuse the
  cleanup it is part of. When the plan row is *refused* — several candidates matched, or git tracks
  the file — those files count as dirt again, because nothing is going to delete them. A modified
  tracked plan is exactly that case: it is refused, so it keeps the worktree row out of "Сделаю"
  like any other uncommitted change.

`git merge-tree --write-tree` requires git >= 2.38. If it is unavailable, say so, print the branch
and the base you could not compare, and ask the user to confirm the work is merged — step 2 defines
what each answer permits. **Never fall back to `git branch --merged`** — it reports false after a
squash merge, which is exactly the case this check exists for.

**Task.** Resolve in this order:
1. **Session context** — `flow:done` normally follows `flow:start`/`flow:continue` in the same
   session, so the task is already known. Verify it against the branch before using it.
2. **The branch** — after a `/clear`: match the task id in the branch name against the `Git:` lines
   of candidate tasks (`bd show`), as `flow:continue` does.
3. **`flow-find-leaf`** — last resort only, when neither of the above resolves:
   ```bash
   bd graph --all --json | flow-find-leaf
   ```
   Invoked without `--all`, as above, it prints only **my** and **unassigned** in_progress leaf
   tasks — two groups, `Мои задачи ({actor}):` and `Unassigned:`, each under its own header line,
   numbered continuously across both. (Other users' tasks appear only under `--all`, or when no
   identity can be resolved at all, in which case the helper falls back to showing everyone.)
   Empty output means none exist (see Edge Cases, "No In-Progress Tasks"). **Exactly one numbered
   candidate → resolves silently, same as the other two sources.** Two or more → reproduce its
   output verbatim and ask which number, before printing the scenario.

Two situations may require a question about task identity, both **before** printing the scenario:
context and branch disagreeing (show both, ask which), and `flow-find-leaf` returning more than one
candidate (show its list, ask which). These are the only questions the skill may ask about task
identity. Never resolve the task by eyeballing `bd list --status=in_progress`.

**Branch match:** does `CURRENT_BRANCH` actually belong to the resolved task?

```bash
flow-current-task {task-id} || echo "BRANCH_MISMATCH"
```

Run this check regardless of how the task was resolved above — including when it came from
`flow-find-leaf`, the last-resort case, which has had no chance yet to be checked against the
branch at all. This fact gates every deletion candidate below (worktree, local branch, remote
branch, ledger) in step 3; it never gates task closure, the parent chain, the plan, or the sync —
those apply to the task regardless of which branch we happen to be on.

**Parent chain:** `bd show {task-id}` upwards — id, type (`epic` or not), and open-children count
for each ancestor. **Count the children this run will close as already closed:** exclude the task
being closed, and exclude every lower ancestor this same scenario already lists for closing. The
counts must describe the state step 5 acts in (the task is closed at 5.1, parents at 5.2), not the
state at collection time — counted literally, a parent whose last open child is the very task being
closed could never qualify, and the container-parent row would never fire at all.

**Plan file.** Two sources, check in order:

- **Source A — task description link:** `bd show {task-id}`, look for a `Plan:` line (also
  matches `Plan (label):`); extract the file path.
- **Source B — untracked/modified files**, when Source A found nothing, across **both** the
  pre-v5 and superpowers 5.x+ locations:
  ```bash
  git ls-files --others --modified -- 'docs/plans/' 'docs/superpowers/plans/'
  ```
  Do **not** add `--exclude-standard`. In repos that gitignore the plans directory, untracked plan
  files would otherwise be hidden. `--others --modified` surfaces untracked files and modified
  tracked ones; which of them may actually be deleted is settled by the tracked check below, not by
  the search.

**A tracked plan is never deleted.** A `Plan:` link (Source A) may point at a committed file, and
Source B surfaces committed files too once they are modified. The question is only whether git
tracks the file:

```bash
git ls-files --error-unmatch -- "$PLAN" >/dev/null 2>&1 && PLAN_TRACKED=yes
```

`PLAN_TRACKED=yes` → the plan stays in git, and its row goes to "Не буду" (step 3). Two reasons,
both concrete: `rm`/`mv` on a tracked file dirties the working tree immediately before
`git worktree remove`, which then refuses (this skill never passes `--force`); and the content is in
history anyway, so a real removal buys nothing and still costs its own commit, PR, merge and
`flow:done` run. Local modifications change none of that — a modified tracked plan is just as
committed, and deleting it leaves the same `D` entry in `git status`. `rm`/`mv` therefore applies
**only to untracked** plan files.

Filter results by filename containing "impl" or "plan" (case-insensitive) and semantically
matching the task title. No candidates: nothing to carry forward. **More than one candidate:**
also not something to ask about here — carry the full list into the scenario, where step 3
defaults to touching none of them (see step 3's defaults table).

**Worktree:** `flow-in-worktree` — exit 0 if we are in a worktree.
**Remote branch:** `git branch -r --list "$REMOTE/$CURRENT_BRANCH"` — non-empty means it exists.
Match the full ref, never `git branch -r | grep "$CURRENT_BRANCH"`: an unanchored grep reports
`feature/x` as present because `origin/feature/x-2` exists.
**Ledger:** present when a `PR_NUMBER` was captured above — the PR's `flow:review-comments`
memory, stored under the OS cache dir, never in the repo.

### 2. Safety check: is the work merged?

Exactly one of the cases below applies. Each says both what happens to the run and what the
resulting mergedness verdict is — **confirmed**, **unconfirmed**, or **not applicable** — because
step 3 gates the worktree, the local branch, the remote branch and the ledger on that verdict. The
plan is **not** gated on it — the plan belongs to the task, not to the branch (step 3).

**If step 1 printed `NO_BASE`** (no PR target, no remote HEAD symref even after
`git remote set-head --auto`, no distinct upstream, no `master`, no `main`): **STOP**. There is
nothing to compare against, and this comparison guards every deletion the run could make.

> "Не смог определить базовую ветку: ни цели PR, ни HEAD-симссылки у remote `{remote}`, ни upstream
> ветки, ни `master`, ни `main`.
>
> Без базы проверка влитости невозможна, а на ней держатся все удаления — ничего не делаю. Скажите,
> какая ветка базовая (или создайте `refs/remotes/{remote}/HEAD`), и запустите `/flow:done` снова."

Exit. Nothing is closed, deleted, or synced. Never guess a base to get past this.

**If step 1 found `BRANCH_MISMATCH`** (the current branch is not the resolved task's branch — e.g.
a generic branch like `master`, or an unrelated feature branch): the mergedness check describes
that branch's relationship to the base, not this task's, so it says nothing safety-relevant here —
**whatever step 1's comparison returned is discarded** (verdict: not applicable; never report it as
one). Continue to step 3 without asking anything: the
scenario still closes the task and syncs — the work may well have landed by another route, and
refusing here would make the skill unusable from `master` — but every branch/worktree/remote/ledger
candidate is refused, not offered (see step 3), and the header states outright that mergedness was
not checked.

**If the branch matches the task and step 1 found it not merged into the base:**

**STOP** and inform the user:

> "Branch `{branch-name}` has not been merged into `{base}`.
>
> Use `superpowers:finishing-a-development-branch` to properly complete this work (handles merge/PR/cleanup and task closure together)."

Exit. Do not continue the workflow — nothing is closed, nothing is deleted, nothing is synced.

**If the git-version guard from step 1 fired** (no `git merge-tree --write-tree` available), ask
the user directly to confirm the branch is merged, and wait for the answer:

- **"да" / "yes"** → continue to step 3 with mergedness **unconfirmed**. A verbal claim permits
  closing the task, closing eligible parents, handling the plan and running `flow-sync push` —
  none of which destroys anything — but **it never counts as the check**: the worktree, the local
  branch, the remote branch and the ledger all go to "Не буду" with the reason "влитость не
  подтверждена (нет `git merge-tree`)". The plan is deliberately not in that list: its fate
  follows the task, not the branch.
- **"нет" / anything not an affirmative** → treat it exactly like a failed safety check: **STOP**
  with the same message as the not-merged case above, and exit.

Do not silently treat an unconfirmable state as merged, and do not fall back to
`git branch --merged`.

**If the branch matches the task and step 1 found `MERGED_TREE == BASE_TREE`:** verdict
**confirmed** — continue silently to step 3. No output yet.

A branch that never committed anything lands in this case too, and that is correct: its tip is
reachable from the base, so deleting its refs cannot lose a commit. Whatever such a branch was for
may still be sitting uncommitted in the working copy — that is a separate risk, carried by the
worktree row alone and guarded by `WORKTREE_DIRTY` in step 3, never by a mergedness verdict.

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

**The header's second line states exactly what is known about the branch** — it never claims a
check that did not run:

| Situation | Second header line |
|---|---|
| Merged, remote mode | `Ветка  feature/… → влита в origin/master (squash, PR #138 MERGED)` |
| Merged, local-only | `Ветка  feature/… → влита в master (локальный репозиторий, PR/remote нет)` |
| `BRANCH_MISMATCH` | `Ветка  master — не относится к задаче {task-id}; влитость не проверялась` |
| git < 2.38, user answered "да" | `Ветка  feature/… — влитость не подтверждена (нет git merge-tree, подтверждена на словах)` |

**Defaults for the nine checklist rows:**

| Item | Default | Appears when |
|---|---|---|
| Close the task | do | always |
| Plan file | delete when untracked; **leave in git** when tracked (clean or modified); **none** when several candidates match | a plan was found |
| Worktree | delete | we are in a worktree, the branch matches the task, mergedness is confirmed, and `WORKTREE_DIRTY` is empty |
| Local branch | delete, `-D` under squash | mergedness confirmed, the branch matches the task, and — when we are in a worktree — that worktree is being removed |
| Remote branch | delete | remote mode, branch exists, branch matches the task, mergedness confirmed, and `PR_STATE` is known and not `OPEN` (`UNKNOWN` refuses like `OPEN`) |
| Ledger | purge when `MERGED`; leave when `CLOSED` or `OPEN` | PR known, ledger exists, the branch matches the task, and mergedness is confirmed |
| Container parent | close | no open children remain once this run's closures are counted, type ≠ `epic` |
| Epic parent | do not close — default only, overridable by a correction | same condition, type `epic` |
| `flow-sync push` | do | always |

Four gates guard the four branch-gated rows (worktree, local branch, remote branch, ledger), and
each has its own named refusal in "Не буду". Two apply to all four: the branch belongs to the task
(step 1's `flow-current-task` check), and mergedness is **confirmed** (step 2's verdict —
"unconfirmed" refuses just as firmly as "not merged" would have stopped). Two apply to a single
row each: the PR's state is known and not `OPEN`, for the remote branch; and `WORKTREE_DIRTY` is
empty, for the worktree. **The plan row is not among them** — see below.

**The plan's fate does not depend on mergedness.** The plan belongs to the task, not to the
branch: it is deleted or archived whenever the task closes, including under an unconfirmed
verdict. Two things change its default, neither of them mergedness: several candidates matched
(below), or the file is tracked (step 1). So wherever this skill refuses "every deletion"
for an unconfirmed verdict, it means those four rows and not the plan.

**A tracked plan stays in git**, whether or not it has local modifications. Its row goes to
"Не буду" with the reason `план закоммичен — удалять его надо отдельным PR, а не здесь`. `rm`/`mv`
would dirty the tree right before `git worktree remove` refuses on it, and a real removal costs a
whole PR → merge → `flow:done` cycle for a file whose content is in history either way. Only an
untracked plan is deleted (or archived) by default.

Like the epic, this is a **default, not a prohibition**: a correction can move the row into
"Сделаю", and then step 5 deletes the file — the user may well intend to commit that deletion
themselves. Say what it costs when reprinting the scenario: the working copy goes dirty, so the
worktree row (and the local branch with it) will very likely end up as a failure line in the
summary.

**Branch rows are never gated on the commit graph beyond the tree comparison.** Once
`MERGED_TREE == BASE_TREE`, the branch's tip is reachable from the base, so deleting the local or
remote ref loses no commit — this is equally true of a fast-forward merge, a merge-commit merge and
a branch that never committed at all, which are the same graph (step 1). Counting
`git rev-list --count "$BASE_REF..$CURRENT_BRANCH"` distinguishes none of them and must never
refuse a row: doing so reports "влитость не подтверждена" on a demonstrably merged branch in every
repository that does not squash-merge.

**The worktree's gate is the working copy, not the commit graph.** The worktree row is the one row
that can destroy content existing nowhere else, and `git status --porcelain --untracked-files=all`
answers that directly: empty → nothing to lose; non-empty → the row goes to "Не буду" with the
reason `в рабочей копии есть незакоммиченные изменения`, listing them. The plan this same scenario
is deleting does not count as such content (step 1), so a repository that keeps plans untracked in
a non-ignored directory still gets its worktree cleaned up. That `git worktree remove`
also refuses on a dirty tree (Edge Cases) is a second line of defence behind this check, not the
design — the skill never passes `--force`.

**A refused worktree takes the local branch with it.** When we are sitting in the worktree and it
is not being removed, HEAD is still on the branch and `git branch -d` cannot run — step 5 already
couples the two at execution time. The scenario must say so up front rather than promise a
deletion the run cannot perform: the local-branch row goes to "Не буду" with the reason naming the
worktree.

Epics are excluded from automatic closing because they are long-lived and keep gaining children.
That is a **default, not a prohibition**: the user knows whether their epic is done, so a correction
("закрой и эпик") moves the epic row into "Сделаю", and once the reprinted scenario is approved
step 5.2 closes it like any other parent.

**Open-children counts already include this run's closures.** Step 1 counted them that way, so a
container parent whose last open child is the task being closed appears under "Сделаю" with the
reason spelled out — `закрою родителя claude-tools-elf — других открытых детей нет (эта задача
закрывается здесь же)`. Step 5 closes the task first and re-reads the parent immediately before
closing it, so the promise and the action are evaluated against the same state.

**Several plan candidates get no default deletion.** When step 1's search returns more than one
matching file, the scenario's plan row lists every candidate and defaults to touching none of
them — filed under "Не буду" with the candidate list as the reason. Deleting the wrong plan file
is not recoverable from the summary; the user names the right one as a correction.

**The remote branch is gated on the PR's state too.** A branch tree can equal the base while its
PR is still `OPEN` — the content landed through another PR, a cherry-pick or a rebase. On GitHub,
`git push "$REMOTE" --delete <branch>` **closes that PR**: an irreversible external action that the
line "удалю ветку на origin" does not announce and the single approval was never asked about. So
with an `OPEN` PR the remote-branch row goes to "Не буду" with the reason named — `не буду удалять
ветку на origin — PR #{n} открыт, удаление ветки его закроет`. The two rules about the same PR
point the same way: an `OPEN` PR keeps both its ledger and its branch.

**`UNKNOWN` refuses that row exactly as `OPEN` does.** When step 1 could not reach the platform, the
skill does not know whether a live PR is attached to this branch, and the deletion that would close
it is irreversible. An unknown state is therefore a refusal with its own reason — `не буду удалять
ветку на origin — состояние PR не удалось выяснить ({причина}), удаление могло бы закрыть живой
PR` — never a quiet pass through "not `OPEN`". The ledger row needs no extra rule: it purges on
`MERGED` alone, and `UNKNOWN` is not `MERGED`.

**The ledger's gate is the PR's state, never branch deletion.** A branch is routinely kept on
purpose after a merge — for history, or to re-read what happened in review — so its survival must
not keep a settled PR's ledger alive forever; conversely a successful `git branch -d` says nothing
about whether the PR is still taking review. Only `MERGED` purges; on `CLOSED` and `OPEN`
skip the purge, because a closed PR can still be reopened and a still-open one is still taking
review.

**When step 1 found `BRANCH_MISMATCH`:** the four branch-gated rows above never move to "Сделаю",
regardless of what exists. Each one that actually exists (a worktree we happen to be sitting in, a
local or remote branch, a ledger) appears instead under "Не буду" with the reason "ветка не
относится к задаче {task-id}" — a real resource that could be mistaken for deletable is a
deliberate refusal, not something to omit silently.

**Mandatory sweep.** The nine rows above are a checklist. Each must either appear as a numbered
line or be omitted for an explicitly named reason. A skipped row is now a silent action or a silent
omission — not merely an unasked question.

**"Не буду" lists only deliberate refusals.** The full set: the epic (unless a correction moved it
into "Сделаю"); the ledger of a `CLOSED`, `OPEN` or `UNKNOWN` PR; the remote branch when its PR is
`OPEN` or its state is `UNKNOWN`; every branch-gated row (worktree, local branch,
remote branch, ledger) when `BRANCH_MISMATCH` was found, each with the reason "ветка не относится к
задаче {task-id}"; those same four rows (worktree, local branch, remote branch, ledger) when
mergedness is unconfirmed — git < 2.38 answered "да" — with that reason, the plan **not** being one
of them; the worktree when the working copy is dirty, and with it the local branch, since we are
still standing on that branch; the plan when several candidates match; and the plan when git tracks
it. What is simply
absent from the environment (no remote, no plan, not in a worktree) is not printed at all: the
scenario states decisions, not an inventory.

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
2. Container parents, bottom-up — and the epic **only** when the approved scenario listed it under
   "Сделаю" (a correction put it there; step 3's default leaves it open). Re-read
   `bd show {parent-id}` immediately before each `bd close`: the task is now actually closed, so the
   count the scenario promised is the count that must be observed here. If a child was opened in the
   meantime, leave the parent open and say so in the summary rather than closing it anyway.
3. Plan: `rm` (or, when the scenario says archive, `mkdir -p docs/archive/` then `mv` into it)
   whenever the scenario lists the plan for deletion — this
   fires regardless of which source found the file (linked or untracked). A plan git tracks — clean
   or modified — was filed under "Не буду" in step 3 and is left alone, unless a correction moved
   that row into "Сделаю"; then it is deleted like any other approved item. Then, **only if** the
   task description held a `Plan:` line, `flow-link-doc {task-id} Plan ""` to remove the now-stale
   link. A plan found only as an untracked file (Source B in step 1) never had a link to remove, so
   the second half never fires for it.
4. `flow-sync push`, with its stderr captured. **A clean exit does not confirm the sync succeeded:**
   `flow-sync push` is best-effort and exits 0 even when the dolt commit, pull or push failed,
   reporting the problem only on stderr (`plugins/flow/AGENTS.md`, "flow-sync is best-effort").
   So read the stderr, not the exit code, and let step 6's line say what it said. Still
   non-blocking — a failed sync never stops the rest.
5. **Leave the worktree first:** when `flow-in-worktree` said we are in one, `cd` to the main repo
   root (the parent of `.worktrees/`) before anything else in this item. Removing the worktree you
   are standing in makes every command after it fail. Then:
   `git worktree remove <path>` → `git checkout "$BASE_LOCAL"` →
   `git pull` (**remote mode only** — a local-only repository has no upstream to pull from and the
   command would fail on every such cleanup) → `git branch -d|-D <branch>` (`-D` only when the
   scenario said so, i.e. mergedness
   was confirmed under squash) → `git push "$REMOTE" --delete <branch>` (only when the scenario
   listed the remote branch — it exists, and its PR state is known and not `OPEN`). Use `$REMOTE`
   from step 1 at every push site: the remote is not always called `origin`.
   **Check out `BASE_LOCAL`, never `BASE_REF`:** `git checkout origin/master` detaches HEAD and the
   `git pull` right after it fails with "You are not currently on a branch".
6. `flow-review-ledger purge --url "$PR_URL" --number "$PR_NUMBER"` — only when the scenario listed
   the ledger for purging (`MERGED`); a `CLOSED` or `OPEN` PR's ledger is left alone, per step 3

Beads precede git: the git part can fail on a dirty worktree, and by then the closed task must
already be recorded and synced. The ledger runs last, after branch deletion is attempted: `purge`
is irreversible and keeps no backup.

**Errors do not block — with one exception.** Every item in this list runs regardless of whether an
earlier one failed. A failed item produces a line in the summary (step 6) and execution continues to
the next item — this holds for **any** git or tooling failure encountered here, not only ones this
skill happens to name, so no failure needs to match a specific description to count as
non-blocking.

**The exception: a failed `bd close` (item 1) stops the beads half.** Items 2 and 3 both act on the
premise that the task is closed — a container parent qualifies only because its last open child just
closed, and the plan is deleted because the work it planned is done. If item 1 failed, that premise
is false, so items 2 and 3 are **skipped** and each gets its own summary line naming the reason.
Git cleanup (item 5) and the ledger (item 6) are unaffected: they depend on the branch's state, not
on the task's, and stay independent and non-blocking. Item 4 still runs — syncing whatever beads
state does exist costs nothing and loses nothing.

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

**The sync line reports what `flow-sync push` said, not that it exited.** With empty stderr it is
`✓ beads синхронизированы`; with anything on stderr it becomes
`✗ beads не синхронизированы: {stderr}` and, when the message is only a warning,
`⚠ beads синхронизированы частично: {stderr}`. Printing the ✓ unconditionally would report a
success the exit code never established (step 5, item 4).

**A skipped item is a line too.** When `bd close` failed and items 2-3 were skipped, they appear as
`— родитель не закрыт (задача не закрылась)` and `— план не тронут (задача не закрылась)`, never
as silent absences.

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
✅ Switch to the local default branch, and pull after cleanup in remote mode

### This Skill Does NOT:
❌ Git operations unrelated to cleanup (commit, push, merge, etc.) — including committing the plan file's own deletion/move; the branch cleanup step (or the user's next workflow) handles git state
❌ Create branches
❌ Start next task (use flow:start)
❌ Update PRs or issues
❌ Run tests or builds
❌ Ask per action — everything is decided once, in the scenario
❌ Close epics by default — they go in "Не буду" unless the user asks for it in a correction
❌ Invoke `gh` without a remote — local-only mode has no platform to check
❌ Search for branches beyond the current one
❌ Delete the worktree, the local branch, the remote branch or the ledger when mergedness is unconfirmed — a verbal "да" on a too-old git is not the check; the plan is not on that list, it follows the task
❌ Remove a worktree holding uncommitted or untracked content — that is `git status --porcelain`, never a commit count
❌ Delete the remote branch while its PR is `OPEN`, or while its state is unknown because the `gh` lookup failed — either could close a live PR
❌ Delete a plan file that git tracks, modified or not, by default — it stays in git unless a correction says otherwise; only untracked plans are removed on the default path
❌ Close container parents or touch the plan after a failed `bd close` — both assume the task is closed
❌ Clean up branches for parent tasks (cascade closures)
❌ Block task closure if cleanup fails

**Scope note:** The safety check (step 2) stops when no base can be determined, and when the
branch belongs to the task but its tree doesn't match the base's — regardless of PR state — and
points to `superpowers:finishing-a-development-branch`. Cleanup (worktree, local branch, remote
branch, ledger) lives inside the single scenario (step 3) and applies only when the branch matches
the closed task **and** mergedness is confirmed; the remote branch additionally requires that the
PR's state is known and not `OPEN`, and the worktree that its working copy is clean. The plan is
outside this set — it belongs to the task and is handled whenever the task closes, unless git tracks
the file, in which case it stays in git. Cleanup is non-blocking; the one thing that
does block is a failed `bd close`, which skips the parent and plan items that assume it succeeded.

## Red Flags - STOP

If you're thinking any of these, STOP and follow the workflow:

- "The PR is merged, I'll just close the task and skip the scenario" → The scenario is how the user
  approves everything at once. Skipping it means acting without approval, not saving a step.
- "There's no PR, so the work isn't finished" → A PR is not the signal. Compare the trees. A
  repository without remotes has no PR by construction and can still be fully merged.
- "All children are closed, so the epic is done too" → Epics keep gaining children. They go in
  "Не буду" by default; the user closes them explicitly, by moving that row into "Сделаю" in a
  correction — and then step 5.2 does close it.
- "The user says it's already merged and there's no remote anyway — I'll take their word for it" →
  Never substitute a verbal claim for the check. `git merge-tree` works with or without a remote;
  run it.
- "The PR is OPEN, but the branch matches the task, so the bundled cleanup line covers deleting it
  anyway" → No. When the branch belongs to the task, an unmerged branch stops the run at step 2 and
  no scenario is printed at all; and even a merged branch with an `OPEN` PR keeps its remote branch
  and its ledger — deleting the branch on origin closes the PR.
- "The branch isn't the task's, but the comparison says merged, so cleanup is fine" → Under
  `BRANCH_MISMATCH` that result is discarded — the verdict is "not applicable". The header says
  mergedness was not checked, the task still closes, and the worktree, the branches and the ledger
  are named refusals.
- "The user confirmed the merge because git is too old — that's mergedness confirmed" → It is not.
  That "да" permits closing, the plan, parents and the sync; it never permits deleting the
  worktree, the local or remote branch, or the ledger.
- "The branch has no commits of its own, so I can't confirm it's merged — refuse everything" → A
  tip reachable from the base is exactly what a fast-forward and a merge-commit merge look like
  too; the graphs are identical and deleting such a ref loses no commit. The only thing at risk is
  uncommitted content in the working copy: check `git status --porcelain`, and refuse the worktree
  row alone.
- "This failure isn't one the skill names by example, but 'errors don't block' covers it anyway" →
  It does, explicitly, for any git or tooling failure encountered in step 5 — that's stated outright,
  not something to infer by analogy from a shorter list.
- "flow-sync push obviously runs, I don't need to put it in the scenario" → Obvious steps are
  exactly the ones a scenario exists to make visible. It's always the last numbered line.
- "Branch doesn't match the task, but I'll clean up anyway" → A mismatched branch's resources go
  into "Не буду" with a named reason, never into "Сделаю".
- "They answered yes with a change — that's approval enough, apply it and finish" → A correction is
  not an approval. Reprint the whole scenario and ask again.
- "`gh pr view` returned nothing, so there's no PR and the remote branch is free to delete" → Its
  exit status says only that the call failed. Until `gh pr list` confirms the platform was reached,
  the state is `UNKNOWN`, and deleting the branch could close a live PR — refuse the row and name
  the reason.
- "The branch isn't in origin/master yet, so it isn't merged" → The base is the **PR's target**
  first, not the repository default. A subtask branch merged into its feature branch is merged;
  comparing it against the default branch would refuse every stacked task until the whole feature
  lands.
- "The plan is committed, but the scenario deletes plans — `rm` it" → Not one git tracks, modified
  or not. It stays in git: the deletion would dirty the tree just before `git worktree remove`, and
  removing it for real needs its own PR for content that is already in history.
- "`bd close` failed, but errors don't block — close the parent anyway" → The parent qualifies only
  because its last open child just closed. If it didn't, items 2 and 3 are skipped, each with its
  own summary line. Git cleanup still runs.
- "`flow-sync push` exited 0, so beads are synced" → It exits 0 even when the push failed and says
  so only on stderr. Read the stderr and report what it said.

**All of these mean: collect state first, let git decide mergedness, print exactly one scenario, get one approval, and reprint on any correction.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "The PR is merged, I'll skip the scenario and just close things" | The scenario is how the user approves everything at once — it isn't an extra step to route around. |
| "There's no PR, so the work isn't finished" | A PR is not the signal. Compare the trees (`git merge-tree`). A repository without remotes has no PR by construction and can still be fully merged. |
| "All children closed → the epic is done too" | Epics keep gaining children. They go in "Не буду" by default — but an explicit correction moves the epic into "Сделаю", and then it is closed. |
| "They said yes with a change, I'll just apply it" | Reprint the scenario and ask again. The second confirmation is the guarantee the correction was understood. |
| "The user says it's already merged, take their word for it" | Nothing in the skill accepts a verbal assertion as evidence. `git merge-tree` works without a remote — run it. |
| "PR is OPEN, but cleanup was already bundled into one yes" | An unmerged branch of this task never reaches step 3 at all. And an `OPEN` PR keeps both its ledger and its remote branch — `git push "$REMOTE" --delete` would close the PR. |
| "Branch isn't the task's, so let me at least check whether it's merged" | The check is not run in that case, the header says mergedness was not checked, and the worktree, branches and ledger are named refusals. |
| "Git is too old, but the user said it's merged — good enough to delete the branch" | It is good enough to close, sync and handle the plan; never to delete the worktree, the branches or the ledger. |
| "No commits of its own, so I'd better refuse the branch deletions too" | That is the same graph as a fast-forward or a merge commit — deleting the ref loses nothing. Refuse the worktree instead, and only when `git status --porcelain` is non-empty. |
| "flow-sync push is obvious, it doesn't need a line" | Obvious steps are exactly what the scenario exists to make explicit. It's in every scenario, always. |
| "flow-sync push returned 0, print ✓" | It is best-effort: 0 on a failed push too, with the reason on stderr. The summary line reports the stderr, not the exit code. |
| "gh failed, treat it as no PR" | A failed lookup is `UNKNOWN`, not `NO_PR`. It refuses the remote-branch deletion exactly as `OPEN` does. |
| "The repo's default branch is the base" | Only when nothing better resolves. The PR's own target comes first — that is what makes stacked subtask branches closable. |
| "A plan is a plan, delete it" | A tracked plan stays in git — modified counts as tracked. `rm` on it dirties the tree right before `git worktree remove` and needs its own PR to land. |
| "bd close failed, but the rest is independent" | Parents and the plan are not: both assume the task closed. They are skipped with named summary lines; git cleanup is unaffected. |
| "Use SQL directly for efficiency" | `bd close` has logging, events, and validation. Use it. |
| "Branch doesn't match, clean up anyway" | Only clean up when the branch matches the task. A mismatched resource is a named refusal, not silent cleanup. |
| "No Plan: link → skip the plan search" | Always search `docs/plans/` and `docs/superpowers/plans/` for untracked files too — plans aren't always linked. |
| "This specific failure isn't listed, but 'non-blocking' covers it" | It's explicit: any git or tooling failure during execution is non-blocking, not just the ones named as examples. |

## Examples

### ✅ GOOD: Full scenario approved

```
User: "PR merged, flow:done"
Agent: [Step 0: bd version guard passed]
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
- The plan is deleted because git does not track it — a tracked one would be a refusal instead
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

### ✅ GOOD: Subtask branch merged into its feature branch

```
User: "flow:done"
Agent: [Step 1: gh pr view returns state MERGED and baseRefName feature/claude-tools-elf.59-flow-done
        — the PR's own target, so that is the base; the repository default (master) is never
        consulted, and the feature branch it belongs to is still open]
       [Step 2: the branch's tree equals origin/feature/claude-tools-elf.59-flow-done's — merged]

       Задача claude-tools-elf.59.4 — база для проверки влитости
       Ветка  feature/claude-tools-elf.59.4-base → влита в origin/feature/claude-tools-elf.59-flow-done (цель PR #142, MERGED)

       Сделаю:
         1. закрою задачу claude-tools-elf.59.4
         2. удалю worktree .worktrees/feature-claude-tools-elf.59.4-base
         3. удалю локальную ветку (через -D: squash-мердж, -d откажет)
         4. удалю ветку на origin
         5. удалю review ledger PR #142 (PR смержен, ревью закрыто)
         6. синхронизирую beads (flow-sync push)

       Не буду:
         7. закрывать родителя claude-tools-elf.59 — открыты ещё .59.5 и .59.6

       Выполнять? («да», или скажи, что изменить)
```

**Correct because:**
- The base is the PR's target, not the repository's default branch — against `master` this branch
  would read "not merged" until the whole feature lands, and the safety check would refuse to close
  a task that is genuinely finished
- `git checkout "$BASE_LOCAL"` afterwards lands on the feature branch, which is where the next
  subtask starts from
- The parent stays open on its own merits (open siblings), not because of anything branch-related

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

This is git's own refusal, and it is the **second** line of defence: step 1's `WORKTREE_DIRTY`
normally keeps this row out of "Сделаю" in the first place, so reaching here means the working copy
went dirty between collection and execution. Non-blocking, and coupled: since we're still checked
out there, the local branch delete is skipped too. Both show up as summary lines, not a question:

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

Both answers are defined (step 2). **"yes"** → the run continues with mergedness **unconfirmed**:
the task closes, parents and the plan are handled, `flow-sync push` runs, and the four branch-gated
rows — worktree, local branch, remote branch, ledger — appear under "Не буду":

```
Ветка  feature/claude-tools-abc-login — влитость не подтверждена (нет git merge-tree, подтверждена на словах)

Сделаю:
  1. закрою задачу claude-tools-abc
  2. удалю план docs/superpowers/plans/2026-09-01-login-plan.md
  3. синхронизирую beads (flow-sync push)

Не буду:
  4. удалять worktree, локальную и удалённую ветки, ledger — влитость не подтверждена, проверить нечем
```

The plan is still deleted: it belongs to the task, and the task closes here.

**"no"** (or any non-affirmative answer) → identical to a failed safety check: the not-merged
message, and exit without closing, deleting or syncing anything.

Never fall back to `git branch --merged` here — it reports false after a squash merge, which is
exactly the case this check exists for.

### Uncommitted Work in the Worktree

The branch matches the task and the trees are equal, but `WORKTREE_DIRTY` is non-empty — modified
files, or untracked ones that were never committed anywhere. Removing the worktree would destroy
the only copy, so that row is refused, and the local branch with it (HEAD is still there):

```
Задача claude-tools-abc — вход по паролю
Ветка  feature/claude-tools-abc-login → влита в origin/master (squash, PR #141 MERGED)

Сделаю:
  1. закрою задачу claude-tools-abc
  2. удалю ветку на origin
  3. удалю review ledger PR #141 (PR смержен, ревью закрыто)
  4. синхронизирую beads (flow-sync push)

Не буду:
  5. удалять worktree — в рабочей копии есть незакоммиченные изменения (M src/login.py, ?? notes.md)
  6. удалять локальную ветку — worktree остаётся, мы всё ещё на этой ветке
```

A branch `flow:start` created and never committed on reaches this same case whenever its work is
still in the working copy: the tree comparison passes (that branch adds nothing to the base), and
the refusal comes from the dirty working copy, which is where the loss would actually happen — not
from a count of commits, which cannot tell that branch apart from a fast-forward or merge-commit
merge. With a clean working copy there is nothing to refuse: deleting a ref reachable from the base
loses no commit.

### Branch Does Not Belong to the Task

`flow:done` was run from `master` (or from another task's branch). Mergedness is not checked at all
— that branch's relationship to the base says nothing about this task — and every branch-gated
resource that actually exists is refused by name:

```
Задача claude-tools-elf.59 — flow:done: сократить число подтверждений
Ветка  master — не относится к задаче claude-tools-elf.59; влитость не проверялась

Сделаю:
  1. закрою задачу claude-tools-elf.59
  2. синхронизирую beads (flow-sync push)

Не буду:
  3. трогать ветку и ledger — ветка не относится к задаче claude-tools-elf.59
```

### No Base Branch Can Be Determined

The remote has no `HEAD` symref and neither `master` nor `main` exists (or, in local-only mode,
neither local branch exists). The mergedness criterion is what guards every deletion, so the run
does not start:

```
Не смог определить базовую ветку: ни цели PR, ни HEAD-симссылки у remote `origin`, ни upstream
ветки, ни `master`, ни `main`.

Без базы проверка влитости невозможна, а на ней держатся все удаления — ничего не делаю. Скажите,
какая ветка базовая (или создайте `refs/remotes/origin/HEAD`), и запустите `/flow:done` снова.
```

### The `gh` Lookup Failed

`gh pr view` returned nothing and `gh pr list` could not reach the platform either — an expired
token, a rate limit, a TLS timeout. The PR state is `UNKNOWN`, not `NO_PR`: there may well be a live
PR on this branch, and `git push "$REMOTE" --delete` would close it. The remote branch is refused by
name; everything not gated on the PR proceeds normally:

```
Не буду:
  4. удалять ветку на origin — состояние PR не удалось выяснить (gh: connection timed out),
     удаление могло бы закрыть живой PR
```

The ledger needs no separate rule — it purges on `MERGED` only, and `UNKNOWN` is not `MERGED`. Base
resolution falls through to the next candidate (the remote's HEAD symref) instead of yielding an
empty base.

### The Plan File Is Committed

The plan is tracked by git — whether it is clean or carries local edits. It is **not** deleted:

```
Не буду:
  5. удалять план docs/superpowers/plans/2026-09-01-flow-done-plan.md — план закоммичен,
     удалять его надо отдельным PR, а не здесь
```

`rm` on a tracked file would dirty the working tree in the same run that then calls
`git worktree remove` — which refuses on a dirty tree, since this skill never passes `--force` — and
a real removal would cost a PR, a merge and another `flow:done` for a file whose content is in
history regardless. Local modifications change nothing: a modified tracked plan is just as
committed, and `rm` leaves the same `D` entry. The `Plan:` link stays too: it still points at a file
that exists. Only untracked plans are deleted on the default path — a correction can still move
this row into "Сделаю", at the cost of a dirty tree and, with it, the worktree row.

### `bd close` Failed

The task did not close — bd was locked by another writer, or the id no longer resolves. Items 2 and
3 of step 5 are skipped: a container parent qualifies only because its last open child just closed,
and the plan is deleted because the work it planned is done. Neither premise holds. Git cleanup and
the ledger are unaffected — they depend on the branch, not on the task:

```
Выполнено:
  1. ✗ задача claude-tools-elf.59 не закрыта: bd close failed (database is locked)
  2. — родитель claude-tools-elf не закрыт (задача не закрылась)
  3. — план не тронут (задача не закрылась)
  4. ✓ beads синхронизированы
  5. ✓ worktree удалён, локальная ветка удалена
  6. ✓ ledger PR #138 удалён
```

### `flow-sync push` Reported a Problem on stderr

The helper exits 0 by contract (`plugins/flow/AGENTS.md`, "flow-sync is best-effort"), so the exit
code says nothing about whether the sync landed. Its stderr does, and the summary line reports that
instead of an unconditional ✓:

```
Выполнено:
  7. ✗ beads не синхронизированы: dolt push failed: remote rejected (non-fast-forward)
```

Still non-blocking: the rest of the run continues and the summary carries the message the user needs
to retry `flow-sync push` by hand.

### Session Context and Branch Disagree About the Task

Session context says the task is `claude-tools-elf.6`, but `CURRENT_BRANCH`'s `Git:` line matches
`claude-tools-elf.9` instead. Both are shown and the user is asked before anything else — one of the
two permitted questions about task identity (the other being `flow-find-leaf` returning several
candidates, step 1), because the rest of the run depends on getting it right:

```
Контекст сессии указывает на claude-tools-elf.6, а текущая ветка соответствует задаче
claude-tools-elf.9 (по её Git: записи).

Какую задачу закрываем — elf.6 или elf.9?
```

### Plan File Linked but Already Gone

The `Plan:` line points to a file that no longer exists on disk. The deletion is a no-op — there is
nothing to `rm` — but the stale `Plan:` link is still removed, and this appears in the summary
rather than as a question:

```
Выполнено:
  2. ✓ ссылка Plan: удалена (файл уже отсутствовал на диске)
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
