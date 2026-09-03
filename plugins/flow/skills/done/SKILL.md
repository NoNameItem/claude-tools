---
name: done
description: Complete and verify a beads task — collect branch, task, parent, plan, and cleanup state, present one scenario for a single approval, then close the task, clean up the plan, close eligible parents, and sync. Use when work is finished and verified and you want to close out the task.
allowed-tools: Bash(bd:*) Bash(git:*) Bash(gh:*) Bash(flow-current-task) Bash(flow-current-task:*) Bash(flow-find-leaf) Bash(flow-find-leaf:*) Bash(flow-in-worktree) Bash(flow-link-doc:*) Bash(flow-require-bd) Bash(flow-sync:*) Bash(flow-review-ledger) Bash(flow-review-ledger:*) Bash(cat:*) Bash(grep:*) Bash(head:*) Bash(tail:*) Bash(cut:*) Bash(tr:*) Bash(wc:*) Bash(echo:*) Bash(test:*) Bash(ls:*) Bash(cd:*) Bash(jq:*) Bash(rm:*)
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
| 2. **Safety check: is the work merged?** | `PR_STATE == MERGED` confirms outright; else compare trees with `git merge-tree` | First match wins: `MERGED` confirms; else equal trees confirm silently; else `OPEN` stops, pointing to `finishing-a-development-branch`; else ask |
| 3. **Scenario and the single question** | Print Сделаю / Не буду and ask once | Everything the run will do is in this one block |
| 4. **Handle the answer** | Approve / correct / refuse | Correction reprints the full scenario and asks again |
| 5. **Execute** | Fixed order: beads, plan, sync, git, ledger | Errors don't block, except item 1 not closing the task — a child reopened, the re-read failed, or `bd close` failed — which skips parents and the plan; each becomes a summary line |
| 6. **Summary** | Report the actual outcome per item | Names every divergence from the approved scenario |

**Key behavior:** One scenario covers everything — parent closing, the plan's fate, branch/worktree/remote deletion, the ledger. Epics are not closed unless the user asks. `flow-sync push` always runs. Mergedness is decided by git — tree equality against the PR's own target branch — except when `PR_STATE == MERGED`, which settles it outright even over a stale tree mismatch; a live `OPEN` PR still stops the run.

## Four rules the steps refer to

These four decide most of what follows. They are stated once here; the steps name them instead of
re-arguing them.

**R1 · A premise the run cannot verify is refused, never assumed.** A lookup, a re-read or a
comparison that *fails* is not a quiet "no": an unreachable platform is not "no PR", a `bd show`
that errors is not "no open children", an unreadable remote tip is not "the branch is gone". Every
such failure refuses the action it was gating and names itself as the reason. This does not conflict
with "errors do not block" (step 5) — that rule governs a failure that *ends* an action, which is
reported and stepped over; R1 governs a failure that would let an action proceed on an unchecked
premise.

**R2 · An irreversible action re-checks its premise immediately before acting.** The scenario is
built from a snapshot taken before the approval, and the approval takes as long as it takes: another
session closes an issue, a collaborator pushes, a formatter rewrites a file. So `bd close`, the
plan's `rm`, and every branch or worktree deletion re-read what licensed them at the moment they
run, and skip themselves — with a summary line — when it no longer holds. R1 governs those re-reads
too: one that fails refuses the action.

**R3 · A default is not a prohibition.** Every row the scenario files under "Не буду" by default —
an epic parent, a tracked plan, a task with open children, several plan candidates — moves into
"Сделаю" on a correction, and step 5 then performs it like any other approved item. The skill's
judgement is a starting point, not a veto.

**R4 · Mergedness gates the branch, never the task.** Step 2's verdict gates exactly four rows:
worktree, local branch, remote branch, ledger. Closing the task, closing parents, the plan's fate
and `flow-sync push` belong to the task and proceed under an unconfirmed verdict too. Wherever this
skill refuses "every deletion", it means those four rows and not the plan.

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
else
  # scoped to THIS branch, and its output is read — an exit status alone says only
  # that the platform answered, not that the branch has no PR
  PR_LIST=$(gh pr list --head "$CURRENT_BRANCH" --state all --limit 10 \
              --json state,url,number,baseRefName 2>/dev/null)
  if [ $? -ne 0 ]; then
    PR_STATE=UNKNOWN    # the lookup itself failed — auth, rate limit, network
  elif [ "$(echo "$PR_LIST" | jq 'length')" -eq 0 ]; then
    PR_STATE=NO_PR      # gh reached the platform; this branch simply has no PR
  else
    # an OPEN PR outranks any closed or merged one for the same branch: it is the
    # state that must stop the run, and `--limit 1` alone could hand back a closed
    # one created later
    PR_ONE=$(echo "$PR_LIST" | jq -c '[.[] | select(.state == "OPEN")][0] // .[0]')
    PR_STATE=$(echo "$PR_ONE" | jq -r .state)
    PR_URL=$(echo "$PR_ONE" | jq -r .url)
    PR_NUMBER=$(echo "$PR_ONE" | jq -r .number)
    PR_BASE=$(echo "$PR_ONE" | jq -r .baseRefName)
  fi
fi
```

`PR_URL` and `PR_NUMBER` are what step 5 needs to address this PR's review ledger; `PR_STATE`
decides whether purging it — and whether deleting the remote branch — is safe; `PR_BASE` is the
first base candidate below.

**A failed lookup is not "no PR" (R1).** `gh pr view` exits non-zero both when no PR exists and
when the call fails, so `|| echo NO_PR` reads a network blip as "no PR" — and an unset `PR_STATE`
trivially satisfies "not `OPEN`", which would license `git push "$REMOTE" --delete` on a branch whose
PR is live, closing it. Hence the second call, and hence reading what it *returns*: `gh pr list` also
exits 0 while printing a live PR, so a status-only check would mislabel a blipped branch as `NO_PR`.
Empty array → `NO_PR`, non-empty → that PR's own state, non-zero exit → `UNKNOWN`, which refuses the
remote-branch row exactly as `OPEN` does (step 3) and falls through to the next base candidate rather
than yielding an empty base.

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
  # remote mode: resolve the remote, fetch it, then compare against the remote base
  REMOTE=$(git remote | head -1)   # usually origin — never assume the name
  # resolve REMOTE *before* fetching: a bare `git fetch` takes the current branch's
  # upstream remote and falls back to `origin`, so in a repository whose only remote
  # is named otherwise it fetches nothing, or fails outright — and every comparison
  # below then runs on stale remote-tracking refs
  git fetch --prune --quiet "$REMOTE"
  FETCH_OK=$?   # non-zero → the remote-tracking refs below are whatever was already cached
  # --prune: without it a candidate deleted on the remote keeps its refs/remotes ref,
  # and the show-ref checks below accept a base that no longer exists
  BASE_LOCAL=""
  # every candidate must name a branch the remote actually has, and must not be
  # CURRENT_BRANCH itself — a base equal to the branch compares it with itself and
  # reports "merged" unconditionally; one that fails either test falls through to
  # the NEXT candidate, never straight to master/main
  # 1. the PR/MR's own target branch — where this work was supposed to land
  if [ -n "$PR_BASE" ] && [ "$PR_BASE" != "null" ] && [ "$PR_BASE" != "$CURRENT_BRANCH" ] \
     && git show-ref --verify --quiet "refs/remotes/$REMOTE/$PR_BASE"; then
    BASE_LOCAL="$PR_BASE"
  fi
  # 2. the remote's HEAD symref, restored from the server when it is missing
  if [ -z "$BASE_LOCAL" ]; then
    git symbolic-ref --quiet "refs/remotes/$REMOTE/HEAD" >/dev/null || git remote set-head "$REMOTE" --auto >/dev/null 2>&1
    symref=$(git symbolic-ref --quiet "refs/remotes/$REMOTE/HEAD")
    candidate="${symref#refs/remotes/$REMOTE/}"
    if [ -n "$candidate" ] && [ "$candidate" != "$CURRENT_BRANCH" ] \
       && git show-ref --verify --quiet "refs/remotes/$REMOTE/$candidate"; then BASE_LOCAL="$candidate"; fi
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
  # equal → the branch adds nothing to the base → merged (survives squash and rebase,
  # but decays once the base edits the same lines — step 2 checks PR_STATE first)
  WORKTREE_DIRTY=$(git status --porcelain --untracked-files=all)
  # non-empty → the working copy holds content that exists nowhere else (gates the worktree row)
fi
```

Nine rules go with it. Each is argued in "Why these checks" at the end of this file; the numbers
below are the anchors.

1. **Each candidate is validated where it is chosen**, and a bad one falls through to the *next*
   candidate — never straight to `master`/`main`, and never to `NO_BASE`.
2. **The base comes from the remote, after a fetch** — never a local `master`/`main` that may lag
   behind.
3. **The PR's own target comes first**, because a subtask branch is opened against its *feature*
   branch. On GitLab the same value is `glab mr view <iid> --output json --jq .target_branch`.
4. **`git symbolic-ref` is only the second candidate.** `refs/remotes/<remote>/HEAD` is frequently
   absent, so `git remote set-head "$REMOTE" --auto` is tried before the chain gives up on it.
5. **No source of a base may hand back the branch itself** — the guard belongs on every source, not
   only on the upstream, where it is merely most obvious.
6. **No base asks the user** (step 2) and STOPs only if that goes nowhere. The `if` exists so
   `merge-tree` never runs against an empty ref.
7. **A branch that never committed anything satisfies `MERGED_TREE == BASE_TREE` too**, and no git
   command tells the two apart — nor needs to.
8. **The tree comparison is the *local* signal; `PR_STATE == MERGED` outranks it**, because
   `merge-tree` re-runs against the base as it stands *now* and its answer decays.
9. **`WORKTREE_DIRTY` gates the worktree row**, and the local-branch row through it.
   `--untracked-files=all` is required. The plan this same scenario deletes does not count as
   content to lose; a *refused* plan row does.

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

**Exactly four questions may precede the scenario**, and no others. Two are about task identity:
context and branch disagreeing (show both, ask which), and `flow-find-leaf` returning more than one
candidate (show its list, ask which). Never resolve the task by eyeballing
`bd list --status=in_progress`. The other two belong to step 2: which branch is the base, when step 1
found none (`NO_BASE`), and whether the work is merged, when nothing settles it (ladder case 4). All
four are asked and answered **before** the scenario is printed, so none of them weakens "one
scenario, one approval" — they supply facts the scenario is assembled from, and the assembled
scenario still gets exactly one approval.

**Branch match:** does `CURRENT_BRANCH` actually belong to the resolved task?

```bash
flow-current-task {task-id} || echo "BRANCH_MISMATCH"
```

Run this check regardless of how the task was resolved above — `flow-find-leaf`, the last resort,
has had no chance yet to be checked against the branch at all. Like mergedness, this fact gates the
four branch rows and nothing else (R4).

**The cleanup rows are not gated on the task's own closing row** (R4). A task kept open by
`in_progress` children whose own branch is merged is the normal decomposition case, and its finished
worktree and branches should still be cleaned up. The opposite arrangement — a feature branch the
subtask branches are stacked *on* — needs no extra gate: it is by construction not merged, so either
its PR is `OPEN` (step 2 case 3 stops the run) or the tree comparison does not match (case 4 asks).

**Parent chain:** `bd show {task-id}` upwards — id, type (`epic` or not), and open-children count
for each ancestor. **Count the children this run will close as already closed**, since the counts
must describe the state step 5 acts in, not collection time: counted literally, a parent whose last
open child is the very task being closed could never qualify and the container-parent row would
never fire. So exclude every lower ancestor this scenario already lists for closing, and exclude the
task itself — but **only when its own closing row actually lands in "Сделаю"**. A task whose row
defaulted to "Не буду" is not closing, and counting it as closed would promise a parent closure whose
premise is already known to be false.

**Task status and children.** The same `bd show {task-id}` call carries the task's own `status` and
children — read both, no extra round-trip, for **every** resolution source, not only the last
resort. Step 3 turns them into scenario state: `in_progress` children send the "Close the task" row
to "Не буду" naming them; a task that is not itself `in_progress` is not refused, its status goes in
the header.

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

**A tracked plan is not deleted by default.** A `Plan:` link (Source A) may point at a committed
file, and Source B surfaces committed files too once they are modified. Two facts decide the row —
whether git tracks the file, and whether it is still on disk:

```bash
git ls-files --error-unmatch -- "$PLAN" >/dev/null 2>&1 && PLAN_TRACKED=yes
test -e "$PLAN" || PLAN_GONE=yes   # tracked in the index, already deleted from the working copy
PLAN_HASH=$(git hash-object -- "$PLAN" 2>/dev/null)   # step 5 re-checks the file is still this one
```

**`git ls-files` reads the index, not the disk:** a file whose deletion is not committed yet still
reports as tracked. `PLAN_GONE=yes` is therefore not the tracked case at all — there is nothing to
`rm`, and the stale `Plan:` link **is** removed, exactly as the edge case "Plan File Linked but
Already Gone" says. Never print "план закоммичен" over a file that is not there, and never leave the
task pointing at a file that no longer exists.

`PLAN_TRACKED=yes` with the file present → the plan stays in git, and its row goes to "Не буду"
(step 3, R3). Local modifications change nothing: a modified tracked plan is just as committed. `rm`
therefore applies **only to untracked** plan files — the reasoning is in "Why these checks".

Filter results by filename containing "impl" or "plan" (case-insensitive) and semantically
matching the task title. No candidates: nothing to carry forward. **More than one candidate:**
also not something to ask about here — carry the full list into the scenario, where step 3
defaults to touching none of them (see step 3's defaults table).

**Worktree:** `flow-in-worktree` — exit 0 if we are in a worktree.
**Remote branch:** `git branch -r --list "$REMOTE/$CURRENT_BRANCH"` — non-empty means it exists.
Match the full ref, never `git branch -r | grep "$CURRENT_BRANCH"`: an unanchored grep reports
`feature/x` as present because `origin/feature/x-2` exists.
**Branch tips**, for step 5's re-validation to compare against:
```bash
LOCAL_TIP=$(git rev-parse "$CURRENT_BRANCH")
# remote mode only:
# capture ls-remote's own status, not a pipeline's last command: `$?` after
# `ls-remote | cut` is cut's status and reads 0 even when the lookup failed
REMOTE_TIP_RAW=$(git ls-remote --exit-code --heads "$REMOTE" "$CURRENT_BRANCH")
REMOTE_TIP_STATUS=$?   # 0 found · 2 no such ref · anything else: the lookup itself failed
REMOTE_TIP=$(echo "$REMOTE_TIP_RAW" | cut -f1)
```
A `REMOTE_TIP_STATUS` of **2** means the remote branch does not exist — the remote-branch row simply
never appears (the `git branch -r --list` check above already agrees). Anything **other than 0 or 2**
means the lookup failed, so this run has no remote tip at all: carry that status into step 5, whose
re-validation reports it as a failed lookup rather than as a moved tip, and never as a completed
cleanup. Without it an unreadable capture would leave `REMOTE_TIP` empty and masquerade as a tip that
moved, naming a commit that never existed.
`git ls-remote` prints `<oid>\t<ref>`, so the `cut -f1` is what pulls the OID out — the raw line is
neither a comparable value nor a usable lease.

**`REMOTE_TIP` must equal `LOCAL_TIP` for the remote-branch row to be offered at all.** Mergedness
is established by comparing the base with the **local** branch; the remote tip is never passed to
`merge-tree` and so is never examined by it. A remote branch that had already diverged before this
run started — a collaborator pushed to it — is therefore unmerged content that the verdict says
nothing about, and step 5's re-validation would not catch it either: that check only proves the tip
has not moved *since collection*. Unequal tips send the row to "Не буду" (step 3).

**Equality, not ancestry — and the over-refusal is deliberate.** A *local* tip ahead of the remote
also fails this test, though deleting the remote ref would lose nothing there. That refusal is
visible in the scenario and a correction moves it (R3), whereas an ancestry test would add a branch
to distinguish the rarer case from the one that matters.
**Ledger:** present when a `PR_NUMBER` was captured above — the PR's `flow:review-comments`
memory, stored under the OS cache dir, never in the repo.

### 2. Safety check: is the work merged?

The cases below are evaluated **in order, and the first match decides** — not a partition to pick
from freely, because more than one of step 1's signals can hold at once. Each case yields a
mergedness verdict — **confirmed**, **unconfirmed** or **not applicable** — which gates exactly the
four rows R4 names.

**If step 1 found `BRANCH_MISMATCH`** (the current branch is not the resolved task's branch — a
generic branch like `master`, or an unrelated feature branch): checked **first**, ahead of `NO_BASE`,
because the two are independent signals that can fire together and this one outranks. Mergedness is
**not applicable** here — the comparison would describe that branch's relationship to the base, not
this task's — so whatever step 1 computed is discarded and never reported as a verdict. No base
question is asked, since neither purpose a base serves applies (nothing to establish, nothing to
check out). The run continues to step 3 without asking anything: the task still closes and syncs,
because the work may have landed by another route and refusing here would make the skill unusable
from `master`; every branch/worktree/remote/ledger row is refused, and the header states outright
that mergedness was not checked.

**If step 1 printed `NO_BASE`** (reached only when the branch does match the task — `BRANCH_MISMATCH`
above is checked first and, when it fires, makes this question moot): no PR target, no remote HEAD
symref even after `git remote set-head --auto`, no distinct upstream, no `master`, no `main` — the
chain exhausted what it can infer, but the user knows the answer — so ask, in plain text, which
branch is the base, and wait for it.

**Separate the two things a base is for**, because `PR_STATE` can settle one of them on its own:

- *Establishing mergedness.* Case 1 of the ladder below confirms on `PR_STATE == MERGED` alone,
  with no comparison and therefore no base. So when the PR is `MERGED`, the missing base does **not**
  leave mergedness unknown, and the message must not claim it does.
- *Having somewhere to stand in step 5.* `git worktree remove` and `git branch -D` both need the run
  to check out something other than the branch being deleted, and `BASE_LOCAL` is that target. This
  need is real regardless of `PR_STATE`, which is why the question is still asked.

Word the question for whichever of the two applies. If the user declines to name a base while
`PR_STATE == MERGED`, do not stop: mergedness stands, so the task, the parents, the plan and the
sync proceed, and only the rows that need a checkout target — the worktree and the local branch —
go to "Не буду" with that reason. A refusal stops the run only when mergedness is also unsettled. Plain text, never a structured dialog: a structured dialog auto-submits its pre-selected
option after the AFK timeout (`CLAUDE_AFK_TIMEOUT_MS`, default 60s; `claude-tools-6q4`), and a base
question is exactly the kind of answer that must not be guessed by a timeout.

> "Не смог определить базовую ветку: ни цели PR, ни HEAD-симссылки у remote `{remote}`, ни upstream
> ветки, ни `master`, ни `main`.
>
> Без базы проверка влитости невозможна, а на ней держатся все удаления. Какая ветка базовая?"

When `PR_STATE == MERGED`, replace the second line — влитость уже подтверждена состоянием PR, and
the base is wanted only as a checkout target:

> "Влитость подтверждена состоянием PR, но без базовой ветки некуда переключиться, чтобы удалить
> worktree и локальную ветку. Какая ветка базовая?"

Validate the answer before using it — it must resolve to a real ref **and must not be
`CURRENT_BRANCH`**, which is the same guard the inferred candidates carry in step 1 and fails the
same way: a base equal to the branch reports "merged" unconditionally. An answer naming the current
branch — a name copied out of the prompt without thinking, most likely — is rejected like any other
unusable answer, saying why, and the question is asked once more.
`git show-ref --verify --quiet "refs/remotes/$REMOTE/<answer>"` in remote mode, or
`git show-ref --verify --quiet "refs/heads/<answer>"` in local-only mode. Bind the answer to a shell
variable and reference it **quoted** everywhere; never paste it into a command unquoted — a branch
name may contain shell metacharacters.

**The quoting here is legibility, not the untrusted-data rule** — see "Why these checks".

- **Valid answer** → set the base from it exactly as step 1 would have: `BASE_LOCAL` is the answer,
  and `BASE_REF` is `"$REMOTE/$BASE_LOCAL"` in remote mode, `"$BASE_LOCAL"` in local-only mode.
  Then resume step 1's mergedness comparison from `git merge-tree --write-tree` using this base, and
  continue into this step's normal case analysis below exactly as if step 1 had resolved the base on
  its own. The rest of the run proceeds unchanged from there.
- **The answer names no existing ref** → say so, and ask once more.
- **Still nothing usable** (the user declines, or the second answer resolves nothing either) →
  **STOP**, exactly as before: nothing is closed, deleted, or synced. Never guess a base to get past
  this.

**If the branch matches the task:** the tree comparison alone is not the final word — `git
merge-tree` re-runs against the base **as it stands now**, and once the base has moved over the
same lines the branch touched, an already-merged branch reads as a conflict (see the "Nine rules"
above). `PR_STATE` records a fact about the past and does not decay that way. Apply this four-case
ladder, evaluated top to bottom — the **first** case that matches decides the verdict:

1. **`PR_STATE == MERGED`** → verdict **confirmed**, no matter what the tree comparison found. The
   platform is asserting a historical fact — this branch was merged into the PR's target — and that
   target is the first base candidate step 1 resolves, so it is normally the very base being
   compared against. No git arithmetic overrides it. When the PR's target no longer resolves on the
   remote (deleted after the merge), step 1 falls through to a later candidate and the comparison
   then runs against a substitute base — this case still confirms off `PR_STATE` alone, which needs
   no base at all, but the tree-mismatch note below may then reflect that substitution rather than
   anything about the branch.

   **If additionally `MERGED_TREE != BASE_TREE`** (when a tree comparison ran at all — under the
   git-version guard there is nothing to compare, and this note does not apply): the branch has
   content the base does not, most often commits pushed after the merge. Do not refuse — the
   verdict stays confirmed — but the scenario header must say so, on its own line:

   > Внимание: PR смержен, но в ветке есть изменения, которых нет в базе

   so the user sees it before the single approval. This is surfaced, not refused: PR state is a
   fact about the past, tree equality is a fact about now, and the two disagreeing is information
   the user needs, not a reason to strand the run.

2. **`MERGED_TREE == BASE_TREE`** (and case 1 did not already match, **and `FETCH_OK` was 0**) →
   verdict **confirmed** — continue silently to step 3. No output yet.

   **A failed fetch disqualifies this case, and only this case.** With `FETCH_OK` non-zero the
   remote-tracking refs are whatever was cached before the run, so `BASE_REF` may be arbitrarily old
   and tree equality then says the branch matches a base that no longer exists in that form — a
   confirmed verdict resting on a comparison the run could not actually refresh. Fall through to case
   4 and ask, with the reason named:

   > Не удалось обновить `{remote}` (fetch завершился ошибкой), поэтому сравнение с базой шло по
   > устаревшим ссылкам. Работа действительно влита?

   Case 1 is deliberately unaffected: `PR_STATE` comes from the platform, not from a
   remote-tracking ref, so a merged PR still confirms mergedness even when the fetch failed. The
   local-only branch of step 1 never fetches at all and sets no `FETCH_OK`, so this rule does not
   apply there.

   A branch that never committed anything lands in this case too, and that is correct: its tip is
   reachable from the base, so deleting its refs cannot lose a commit. Whatever such a branch was
   for may still be sitting uncommitted in the working copy — that is a separate risk, carried by
   the worktree row alone and guarded by `WORKTREE_DIRTY` in step 3, never by a mergedness verdict.

3. **`PR_STATE == OPEN`** (and neither case above matched) → verdict **not merged** — **STOP** and
   inform the user:

   > "Branch `{branch-name}` has not been merged into `{base}`.
   >
   > Use `superpowers:finishing-a-development-branch` to properly complete this work (handles merge/PR/cleanup and task closure together)."

   Exit. Do not continue the workflow — nothing is closed, nothing is deleted, nothing is synced. A
   live PR means the work has not landed; asking the user to override that would be wrong.

4. **Otherwise** — `PR_STATE` is `NO_PR`, `UNKNOWN`, a `CLOSED` PR whose tree did not match, or the
   git-version guard from step 1 fired (no `git merge-tree --write-tree` available): none of the
   signals confirm or refute the merge. This is the single "cannot confirm from the signals"
   branch — the git-version guard used to be handled as a case of its own; it is now just one of
   the reasons this case fires. Ask the user directly to confirm the branch is merged, in **plain
   text**, and wait for the answer:

   > "Не могу подтвердить влитость ветки `{branch-name}` в `{base}` по имеющимся сигналам ({reason:
   > нет `git merge-tree`, PR не смержен по данным платформы, состояние PR не удалось выяснить, или
   > сравнение с базой неоднозначно}). Подтвердите, что работа влита? (yes/no)"

   Plain text, never a structured dialog: a structured dialog auto-submits its pre-selected option
   after the AFK timeout (`CLAUDE_AFK_TIMEOUT_MS`, default 60s; `claude-tools-6q4`), and this is
   exactly the kind of answer that must not be guessed by a timeout, same as the base question
   above.

   - **"да" / "yes"** → continue to step 3 with mergedness **unconfirmed**. A verbal claim permits
     closing the task, closing eligible parents, handling the plan and running `flow-sync push` —
     none of which destroys anything — but **it never counts as the check**: the worktree, the
     local branch, the remote branch and the ledger all go to "Не буду", with a reason that names
     the actual cause rather than a fixed phrase — "влитость не подтверждена (нет `git
     merge-tree`)" when the guard fired, "влитость не подтверждена (сравнение с базой
     неоднозначно — база сместилась)" when a tree comparison ran but conflicted or otherwise
     disagreed with the platform, and the equivalent naming `NO_PR`/`UNKNOWN`/`CLOSED` when that is
     why case 4 fired instead. The plan is deliberately not in that list: its fate follows the
     task, not the branch.
   - **"нет" / anything not an affirmative** → treat it exactly like a failed safety check: **STOP**
     with the same message as case 3 above, and exit.

   Do not silently treat an unconfirmable state as merged, and do not fall back to
   `git branch --merged`.

### 3. Scenario and the single question

Print one block: a header of facts, a numbered `Сделаю` list, a `Не буду` list, and the single
question. Numbering is continuous across both lists so a correction can be short ("всё кроме 4").

```
Задача claude-tools-elf.59 — flow:done: сократить число подтверждений
Ветка  feature/claude-tools-elf.59-flow-done → влита в origin/master (PR #138 MERGED)

Сделаю:
  1. закрою задачу claude-tools-elf.59
  2. удалю план docs/superpowers/plans/2026-09-01-flow-done-consolidation.md
  3. удалю worktree .worktrees/feature-claude-tools-elf.59-flow-done
  4. удалю локальную ветку (через -D — форму мерджа мы не определяем, -d может отказать)
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
| Merged, remote mode | `Ветка  feature/… → влита в origin/master (PR #138 MERGED)` |
| Merged, local-only | `Ветка  feature/… → влита в master (локальный репозиторий, PR/remote нет)` |
| `PR_STATE == MERGED` but `MERGED_TREE != BASE_TREE` (case 1's second line) | `Ветка  feature/… → влита в origin/master (PR #138 MERGED)` then, on its own line, `Внимание: PR смержен, но в ветке есть изменения, которых нет в базе` |
| `BRANCH_MISMATCH` | `Ветка  master — не относится к задаче {task-id}; влитость не проверялась` |
| Case 4, user answered "да" (git < 2.38, one of several causes) | `Ветка  feature/… — влитость не подтверждена (нет git merge-tree, подтверждена на словах)` |

**Defaults for the nine checklist rows:**

| Item | Default | Appears when |
|---|---|---|
| Close the task | do — **Не буду**, default only, when the task still has `in_progress` children | always |
| Plan file | delete when untracked; **leave in git** when tracked (clean or modified); **none** when several candidates match | a plan was found |
| Worktree | delete | we are in a worktree, the branch matches the task, mergedness is confirmed, and `WORKTREE_DIRTY` is empty |
| Local branch | delete, always `-D` | mergedness confirmed, the branch matches the task, and — when we are in a worktree — that worktree is being removed |
| Remote branch | delete | remote mode, branch exists, branch matches the task, mergedness confirmed, `REMOTE_TIP == LOCAL_TIP`, and `PR_STATE` is known and not `OPEN` (`UNKNOWN` refuses like `OPEN`) |
| Ledger | purge when `MERGED`; leave when `CLOSED` or `OPEN` | PR known, ledger exists, the branch matches the task, and mergedness is confirmed |
| Container parent | close | no open children remain once this run's closures are counted, type ≠ `epic` |
| Epic parent | do not close — default only, overridable by a correction | same condition, type `epic` |
| `flow-sync push` | do | always |

**The task's own children gate its own closing row** (R3), read from the same `bd show {task-id}`
call step 1 already makes for the parent chain: `in_progress` children mean the task is not done, so
its row goes to "Не буду" naming them. A task that is not itself `in_progress` (already closed, or
never started) is not refused on that account — the fact goes in the scenario header instead.

Five gates guard the four branch-gated rows (worktree, local branch, remote branch, ledger), and
each has its own named refusal in "Не буду". Two apply to all four: the branch belongs to the task
(step 1's `flow-current-task` check), and mergedness is **confirmed** (step 2's verdict —
"unconfirmed" refuses just as firmly as "not merged" would have stopped). Three are row-specific —
two of them on the remote branch, which is the row with the most ways to go wrong: its PR's state is
known and not `OPEN`, and `REMOTE_TIP == LOCAL_TIP`; and `WORKTREE_DIRTY` is empty, for the
worktree. **The plan row is not among them** — see below.

**Only two things change the plan's default, and mergedness is neither** (R4): several candidates
matched (below), or git tracks the file (step 1).

**A tracked plan stays in git**, modified or not, with the reason `план закоммичен — удалять его
надо отдельным PR, а не здесь`. Like the epic row this is a default (R3), and a correction moving it
into "Сделаю" has a cost worth stating on the reprint: the working copy goes dirty, so the worktree
row — and the local branch with it — will very likely end up as a failure line in the summary.

**Branch rows are never gated on the commit graph beyond the tree comparison.** Once
`MERGED_TREE == BASE_TREE` the branch's tip is reachable from the base, so no commit can be lost;
`git rev-list --count "$BASE_REF..$CURRENT_BRANCH"` must never refuse a row (see "Why these checks").

**The worktree's gate is the working copy, not the commit graph.** It is the one row that can
destroy content existing nowhere else, and `WORKTREE_DIRTY` answers that directly: empty → nothing
to lose; non-empty → "Не буду" with the reason `в рабочей копии есть незакоммиченные изменения`,
listing them. That `git worktree remove` also refuses on a dirty tree (Edge Cases) is a second line
of defence, not the design — this skill never passes `--force`, and the summary never *recommends*
discarding content the approval did not cover.

**A refused worktree takes the local branch with it.** When we are sitting in the worktree and it
is not being removed, HEAD is still on the branch and `git branch -d` cannot run — step 5 already
couples the two at execution time. The scenario must say so up front rather than promise a
deletion the run cannot perform: the local-branch row goes to "Не буду" with the reason naming the
worktree.

**Epics are excluded from automatic closing** because they are long-lived and keep gaining
children — a default (R3), and "закрой и эпик" moves the row into "Сделаю".

**Open-children counts already include this run's closures.** Step 1 counted them that way, so a
container parent whose last open child is the task being closed appears under "Сделаю" with the
reason spelled out — `закрою родителя claude-tools-elf — других открытых детей нет (эта задача
закрывается здесь же)`. Step 5 re-reads each parent before closing it (R2), so the promise and the
action are evaluated against the same state.

**Several plan candidates get no default deletion** (R3): the row lists every candidate and touches
none of them. Deleting the wrong plan file is not recoverable from the summary.

**The remote branch is gated on the PR's state too.** A branch tree can equal the base while its
PR is still `OPEN` — the content landed through another PR, a cherry-pick or a rebase. On GitHub,
`git push "$REMOTE" --delete <branch>` **closes that PR**: an irreversible external action that the
line "удалю ветку на origin" does not announce and the single approval was never asked about. So
with an `OPEN` PR the remote-branch row goes to "Не буду" with the reason named — `не буду удалять
ветку на origin — PR #{n} открыт, удаление ветки его закроет`. The two rules about the same PR
point the same way: an `OPEN` PR keeps both its ledger and its branch.

**A diverged remote tip refuses that row too.** When `REMOTE_TIP != LOCAL_TIP` the remote branch
carries commits the mergedness check never saw (step 1), so the row goes to "Не буду" with the
reason `не буду удалять ветку на origin — на ней есть коммиты, которых нет локально, влитость для
них не проверялась`.

**`UNKNOWN` refuses that row exactly as `OPEN` does** (R1), with its own reason — `не буду удалять
ветку на origin — состояние PR не удалось выяснить ({причина}), удаление могло бы закрыть живой PR` —
never a quiet pass through "not `OPEN`". The ledger row needs no extra rule: it purges on `MERGED`
alone, and `UNKNOWN` is not `MERGED`.

**The ledger's gate is the PR's state, never branch deletion.** Only `MERGED` purges; on `CLOSED`
and `OPEN` skip the purge — a closed PR can be reopened and an open one is still taking review, while
branch survival says nothing about either (see "Why these checks").

**When step 1 found `BRANCH_MISMATCH`:** the four branch-gated rows above never move to "Сделаю",
regardless of what exists. Each one that actually exists (a worktree we happen to be sitting in, a
local or remote branch, a ledger) appears instead under "Не буду" with the reason "ветка не
относится к задаче {task-id}" — a real resource that could be mistaken for deletable is a
deliberate refusal, not something to omit silently.

**Mandatory sweep.** The nine rows above are a checklist. Each must either appear as a numbered
line or be omitted for an explicitly named reason. A skipped row is now a silent action or a silent
omission — not merely an unasked question.

**"Не буду" lists only deliberate refusals**, each with its own reason. The full set:

| Row(s) refused | Because |
|---|---|
| The task itself | it still has `in_progress` children (R3) |
| The epic parent | epics are not closed automatically (R3) |
| The plan | several candidates match, or git tracks it (R3) |
| The remote branch | its PR is `OPEN` or `UNKNOWN`, or its tip differs from the local one |
| The ledger | the PR is `CLOSED`, `OPEN` or `UNKNOWN` |
| The worktree — and the local branch with it | the working copy is dirty |
| All four branch-gated rows | `BRANCH_MISMATCH` — "ветка не относится к задаче {task-id}" |
| All four branch-gated rows | mergedness unconfirmed — step 2's case 4, with the cause it named (R4: the plan is not among them) |

What is simply **absent** from the environment (no remote, no plan, not in a worktree) is not
printed at all: the scenario states decisions, not an inventory.

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

1. `bd close {task-id}` — **only when the scenario lists it under "Сделаю"**. **Re-read
   `bd show {task-id}` immediately before the close** (R2): a child that is `in_progress` now means
   **do not run `bd close`**, and a re-read that *fails* refuses it the same way (R1). The summary
   names which of the two happened, and items 2 and 3 are skipped along with it, since both act on
   the premise that this task closed. A correction that moved the row into "Сделаю" despite known
   `in_progress` children is the user overriding this knowingly, and the rule still stands: the
   re-read then only reports. When the scenario left the row in "Не буду", items 2 and 3 do not run
   either, each with its own "не тронуто" summary line, distinct from the failure case below.
2. Container parents, bottom-up — and the epic **only** when the approved scenario listed it under
   "Сделаю" (R3). Re-read `bd show {parent-id}` immediately before each `bd close` (R2): the task is
   now actually closed, so the count the scenario promised is the count that must be observed here. A
   child opened in the meantime leaves the parent open; so does a re-read that fails (R1) — but the
   summary must keep the two causes distinguishable, because "the eligibility re-read failed" and "a
   child was open" call for different follow-ups.
3. Plan: `rm` whenever the scenario lists the plan for deletion — this
   fires regardless of which source found the file (linked or untracked). **Re-check both facts
   step 1 captured immediately before the `rm`** — `git ls-files --error-unmatch` for tracked, and
   `git hash-object` against `PLAN_HASH` for content. A file that became tracked, or whose content
   changed while the scenario awaited approval, is left alone with a summary line naming which of
   the two happened: an editor, a formatter or another session can write to a plan that is about to
   be deleted, and `rm` would take that new content with it. A plan git tracks — clean
   or modified — was filed under "Не буду" in step 3 and is left alone, unless a correction moved
   that row into "Сделаю"; then it is deleted like any other approved item. A plan already gone from
   the working copy has nothing to delete, tracked or not. **The link is cleared only when the plan
   is actually gone from the working copy after this item** — deleted just now (untracked by
   default, or tracked after a correction moved its row into "Сделаю"), or already absent at
   collection time — and only if the task description held a `Plan:` line to begin with:
   `flow-link-doc {task-id} Plan ""` then removes the now-stale link. A plan left in git on the
   default path still points at a file that exists, so its `Plan:` link stays — clearing it
   unconditionally on every plan row, tracked or not, would be wrong. A plan found only as an
   untracked file (Source B in step 1) never had a link to remove, so this never fires for it
   either way.
4. `flow-sync push`, with its stderr captured. **A clean exit does not confirm the sync succeeded:**
   `flow-sync push` is best-effort and exits 0 even when the dolt commit, pull or push failed,
   reporting the problem only on stderr (`plugins/flow/AGENTS.md`, "flow-sync is best-effort").
   So read the stderr, not the exit code, and let step 6's line say what it said. Still
   non-blocking — a failed sync never stops the rest.
5. **Re-validate first, while HEAD is still the task's branch — before the `cd`, the worktree
   removal, the checkout or either deletion** (R2). This is not redundant with step 1's `UNKNOWN`
   rule: that one guards a lookup that *failed at collection time*, this one a lookup that
   *succeeded and then went stale*. Different failures, both refused.
   - Re-run step 1's two-call PR lookup, **naming the branch explicitly** rather than relying on the
     checked-out branch: `gh pr view "$CURRENT_BRANCH" --json state,url,number,baseRefName`, falling
     back to `gh pr list --head "$CURRENT_BRANCH" --state all --limit 10 --json
     state,url,number,baseRefName`, **read the same way step 1 reads it** — non-zero exit →
     `UNKNOWN`, empty array → `NO_PR`, otherwise that PR's own state with an `OPEN` entry outranking
     any closed or merged one. Never the collapsed `gh pr view || echo NO_PR` form, and never the
     list's exit status alone — a lookup that fails now must stay distinguishable from "no PR", and
     this is the call that gates all four destructive rows. The branch is named explicitly because the rest of this item moves HEAD (the `cd`,
     the checkout), so "the current branch" stops meaning the task's branch partway through — a bare
     `gh pr view` run after that point would resolve the wrong branch's PR, or, in worktree mode
     after the `cd`, the main repo root's own checked-out branch, a different branch again.
   - Re-read the tips step 1 captured, against `LOCAL_TIP` and, in remote mode, `REMOTE_TIP`: the
     local tip, `git rev-parse "$CURRENT_BRANCH"`, and, in remote mode, the remote tip, with the
     **same `--exit-code` form step 1 used** — `git ls-remote --exit-code --heads "$REMOTE"
     "$CURRENT_BRANCH"` — capturing its status before any pipe, since `$?` after `ls-remote | cut`
     is `cut`'s status and reads 0 even when the lookup failed.
   - **Re-read the base too**, in remote mode: `git fetch --prune --quiet "$REMOTE"` again, then
     `git rev-parse "$BASE_REF^{tree}"`, compared against the `BASE_TREE` step 1 captured. Mergedness
     was computed from *both* sides — `merge-tree` performs a real merge of the branch and the base —
     so a snapshot of the branch alone does not establish that the verdict still holds. The fetch
     failing here is treated like the base having moved: the comparison could not be refreshed, so it
     cannot vouch for anything.
   - The verdict gates **all four** destructive rows — worktree, local branch, remote branch,
     ledger — not only the remote push:
     - fresh `PR_STATE == OPEN`, or the lookup fails (`UNKNOWN`) → the remote branch and the ledger
       purge (item 6) are skipped, each with its own summary failure line naming the reason: the
       branch's PR was opened or reopened, or its state could no longer be determined, while the
       scenario awaited approval or corrections.
     - the local tip no longer matches `LOCAL_TIP` → the local branch and the worktree are skipped,
       with a summary line naming the new commit. Mergedness was established against the old tip and
       says nothing about the new one.
     - the base tree no longer matches `BASE_TREE`, or the re-fetch failed → the base moved (or could
       not be re-read) while the scenario awaited approval, so the tree comparison that established
       mergedness no longer describes reality. **`PR_STATE == MERGED` still carries it** — that is
       case 1 of step 2's ladder, a historical fact about the platform which no movement of the base
       can undo, and the run continues. Otherwise all four rows — worktree, both branches, ledger —
       are skipped, each with a summary line naming the moved base. An emergency rollback done by
       reset and force-push rather than by a revert commit is the realistic way to reach this.
     - the remote-tip re-read **exits 2** (no such ref) → this is not a moved tip, it is the remote
       branch already being gone — GitHub's auto-delete-on-merge is the ordinary cause (see "Remote
       Branch Already Deleted" below). There is no new commit to name, so the push is skipped and
       recorded as that same ordinary, non-blocking "already deleted" line, never as a failure.
     - the remote-tip re-read **fails any other way** (exit 128 and friends — no network, no auth, the
       remote gone) → the branch's state is unknown, not absent. Empty output alone cannot tell the two
       apart, which is why the `--exit-code` form is required: measured on git 2.47, an absent ref
       exits **2**, a found one **0**, and an unreachable remote **128**, while all three print nothing
       usable to stdout. Treat it exactly like the failed PR lookup above (R1) — skip the remote
       branch **and** the ledger purge, each with a summary failure line naming the failed lookup.
       Step 1's capture obeys the same rule: a `REMOTE_TIP_STATUS` that was neither 0 nor 2 leaves no
       lease value to push with either.
     - the remote-tip re-read resolves to a **different OID** than `REMOTE_TIP` → this is the moved-tip
       case: the remote branch is skipped, with a summary line naming the new commit, exactly like a
       moved local tip.

   **Then leave the worktree:** when `flow-in-worktree` said we are in one, `cd` to the main repo
   root (the parent of `.worktrees/`) before anything else below. Removing the worktree you are
   standing in makes every command after it fail. For whichever rows the re-validation above did not
   already skip: `git worktree remove <path>` → `git checkout "$BASE_LOCAL"`. **Check out
   `BASE_LOCAL`, never `BASE_REF`:** `git checkout origin/master` detaches HEAD and the `git pull`
   right after it fails with "You are not currently on a branch".

   `git pull --ff-only "$REMOTE" "$BASE_LOCAL"` (**remote mode only** — a local-only repository has
   no upstream to pull from) and
   `git branch -D <branch>` (only when the scenario listed the local branch — mergedness confirmed,
   the branch matches the task, and re-validation did not skip it; and always `-D`, never `-d`: tree
   equality already proves the tip adds nothing to the base, and `-d` would refuse right after a
   squash merge) **run only when the checkout succeeded** — a local exception to "errors do not
   block", the same shape as item 1's `bd close` exception and detailed with it below. This is
   independent of the re-validation block above: either rule alone can skip the local branch, and
   both are checked.

   **The pull names its operands and refuses to merge.** Step 1 chooses `BASE_LOCAL` by checking
   that the *remote* has that branch; it never looks at the local branch's tracking configuration.
   So a local branch of that name with no upstream, or one tracking a different remote, makes a bare
   `git pull` either fail or merge some other ref into the base branch — a persistent branch this
   run has no business writing to. Naming `"$REMOTE" "$BASE_LOCAL"` removes the guesswork, and
   `--ff-only` turns the remaining bad case into a refusal instead of a merge commit.

   Delete the remote branch — when the scenario listed it and re-validation above did not skip
   it — with a **lease** rather than a bare `--delete`, so the check and the deletion are one atomic
   operation instead of a read followed by a write:
   `git push --force-with-lease="refs/heads/$CURRENT_BRANCH:$REMOTE_TIP" "$REMOTE" --delete
   "$CURRENT_BRANCH"`, where `$REMOTE_TIP` is the OID step 1 captured and the re-validation above
   confirmed is still current. Verified on
   git 2.47: with a stale OID the push is rejected with `! [rejected] (delete) -> <branch> (stale
   info)` and the ref survives; with the current OID the ref is deleted. Treat a lease rejection as a
   summary failure line like any other refused deletion. Use `$REMOTE` from step 1 at every push
   site: the remote is not always called `origin`.
6. `flow-review-ledger purge --url "$PR_URL" --number "$PR_NUMBER"` — only when the scenario listed
   the ledger for purging (`MERGED`) **and** item 5's re-validation did not skip it (a fresh
   `PR_STATE == OPEN`, or a lookup that fails, skips the purge along with the remote branch); a
   `CLOSED` or `OPEN` PR's ledger is left alone, per step 3

Beads precede git: the git part can fail on a dirty worktree, and by then the closed task must
already be recorded and synced. The ledger runs last, after branch deletion is attempted: `purge`
is irreversible and keeps no backup.

**Errors do not block — with two exceptions.** Every item in this list runs regardless of whether an
earlier one failed. A failed item produces a line in the summary (step 6) and execution continues to
the next item — this holds for **any** git or tooling failure encountered here, not only ones this
skill happens to name, so no failure needs to match a specific description to count as
non-blocking.

**The first exception: item 1 not closing the task stops the beads half.** Items 2 and 3 both act
on the premise that the task is closed. Item 1 can leave that premise false in three ways — the
pre-close re-read showed an `in_progress` child; the re-read itself failed; or `bd close` ran and
failed — and all three skip items 2 and 3, each with its own summary line naming which one it was.
Items 4 (sync), 5 (git) and 6 (ledger) are unaffected: they depend on the branch's state, not the
task's. The scenario having left item 1 in "Не буду" is not a failure but skips items 2 and 3 for the
identical reason — the premise never became true.

**The second exception: a failed checkout (item 5) stops the pull and the local branch delete.**
`git pull` and `git branch -D` both act on the premise that HEAD moved off the task's branch and onto
`BASE_LOCAL` — the pull needs a real branch checked out to merge into, and deleting a branch we might
still be standing on is refused by git anyway. If `git checkout "$BASE_LOCAL"` failed (the base is
checked out elsewhere, or the tree is dirty), that premise is false, so `git pull` and
`git branch -D` are **skipped**, each with its own summary line naming the failed checkout as the
reason. The worktree removal, the remote-branch delete and the ledger purge are unaffected: they do
not depend on where HEAD ends up. This exception and item 5's re-validation block are independent —
either one alone can skip the local branch, and both must be checked.

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

Осталось вручную: посмотрите git status в .worktrees/feature-claude-tools-elf.59-flow-done,
закоммитьте или застэшьте нужное; если содержимое точно не нужно — git worktree remove --force .worktrees/feature-claude-tools-elf.59-flow-done
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
✅ Determine mergedness through git (`git merge-tree`) by default, with a `MERGED` `PR_STATE` overriding a stale tree mismatch and an `OPEN` one stopping the run — not mere PR existence
✅ Find in_progress leaf task (session context → branch → `flow-find-leaf`)
✅ Close task with bd close, unless the task itself still has `in_progress` children (default refusal, overridable by a correction)
✅ Find plan file (linked in description OR untracked in `docs/plans/` / `docs/superpowers/plans/`)
✅ Remove `Plan:` link from description after delete
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
❌ Close the task itself by default when it still has `in_progress` children — that row goes in "Не буду" with the reason named, unless a correction says otherwise
❌ Invoke `gh` without a remote — local-only mode has no platform to check
❌ Search for branches beyond the current one
❌ Delete the worktree, the local branch, the remote branch or the ledger when mergedness is unconfirmed — a verbal "да" answered to step 2's case 4 (no `git merge-tree`, an inconclusive comparison, `NO_PR`, `UNKNOWN`, or a `CLOSED` PR whose tree did not match) is not the check; the plan is not on that list, it follows the task
❌ Remove a worktree holding uncommitted or untracked content — that is `git status --porcelain`, never a commit count
❌ Delete the remote branch while its PR is `OPEN`, or while its state is unknown because the `gh` lookup failed — either could close a live PR
❌ Delete a plan file that git tracks, modified or not, by default — it stays in git unless a correction says otherwise; only untracked plans are removed on the default path
❌ Close container parents or touch the plan when item 1 did not close the task — whether a child was found `in_progress` at the re-read, the re-read failed, or `bd close` failed; all three leave the premise both items assume false
❌ Clean up branches for parent tasks (cascade closures)
❌ Block task closure if cleanup fails

**Scope note:** The safety check (step 2) stops when no base can be determined, and when the
branch belongs to the task, its tree doesn't match the base's, and `PR_STATE == OPEN`. A `MERGED`
PR_STATE overrides a tree mismatch instead of stopping; any other state (`NO_PR`, `UNKNOWN`, a
`CLOSED` PR whose tree didn't match, or no tree comparison at all) asks the user rather than
stopping outright. A hard stop points to `superpowers:finishing-a-development-branch`. Cleanup (worktree, local branch, remote
branch, ledger) lives inside the single scenario (step 3) and applies only when the branch matches
the closed task **and** mergedness is confirmed; the remote branch additionally requires that the
PR's state is known and not `OPEN` and that its tip still equals the local one, and the worktree that
its working copy is clean. The plan is
outside this set — it belongs to the task and is handled whenever the task closes, unless git tracks
the file, in which case it stays in git. Cleanup is non-blocking; the one thing that
does block is item 1 not closing the task — a child found `in_progress` at the pre-close re-read, a
failed re-read, or a failed `bd close` — which skips the parent and plan items that assume it closed.

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
       Ветка  feature/claude-tools-elf.59-flow-done → влита в origin/master (PR #138 MERGED)

       Сделаю:
         1. закрою задачу claude-tools-elf.59
         2. удалю план docs/superpowers/plans/2026-09-01-flow-done-consolidation.md
         3. удалю worktree .worktrees/feature-claude-tools-elf.59-flow-done
         4. удалю локальную ветку (через -D — форму мерджа мы не определяем, -d может отказать)
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
         3. удалю локальную ветку (через -D — форму мерджа мы не определяем, -d может отказать)
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
        origin/master's; gh pr view reports the PR is still OPEN]
       [Step 2: branch matches the task; the ladder's case 1 and case 2 don't match, case 3 does
        (`PR_STATE == OPEN`) — STOP before printing any scenario]

       Branch `feature/claude-tools-test.1-sample` has not been merged into `origin/master`.

       Use `superpowers:finishing-a-development-branch` to properly complete this work (handles
       merge/PR/cleanup and task closure together).
```

**Correct because:**
- `PR_STATE == OPEN` is what forces the unconditional stop — a live PR means the work has not
  landed. A `NO_PR`, `UNKNOWN`, or `CLOSED`-but-mismatched branch would instead ask the user to
  confirm the merge (case 4) rather than stop outright, and a `MERGED` PR would confirm regardless
  of what the tree comparison found (case 1)
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

Осталось вручную: посмотрите git status в .worktrees/feature-claude-tools-abc-login,
закоммитьте или застэшьте нужное; если содержимое точно не нужно — git worktree remove --force .worktrees/feature-claude-tools-abc-login
```

### Remote Branch Already Deleted

Since step 5's re-validation block re-reads the remote tip before touching anything, an **empty**
`git ls-remote --exit-code` there already catches the common case — **exit 2**, not empty output,
which no longer distinguishes anything on its own — so the push is skipped outright and recorded
here, without ever running (see step 5, item 5). What follows is now the narrow race left over: the
ref existed at that re-read and vanished before the push landed.

```
git push --force-with-lease="refs/heads/feature/claude-tools-abc-login:$REMOTE_TIP" origin --delete feature/claude-tools-abc-login
error: unable to delete 'feature/claude-tools-abc-login': remote ref does not exist
```

Measured on git 2.47: the lease form fails identically to the old bare `git push origin --delete`
form against an already-absent ref — same error text, same non-zero exit. Non-blocking — GitHub's
auto-delete-on-merge likely already removed it. One summary line, no question:

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
Ветка  feature/claude-tools-abc-login → влита в origin/master (PR #141 MERGED)

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
asks which branch is the base before it can start:

```
Не смог определить базовую ветку: ни цели PR, ни HEAD-симссылки у remote `origin`, ни upstream
ветки, ни `master`, ни `main`.

Без базы проверка влитости невозможна, а на ней держатся все удаления. Какая ветка базовая?
```

A valid answer (checked against a real ref) resumes step 1's mergedness comparison with it and the
run continues into step 2's normal case analysis, unchanged from there. An answer naming no ref
gets one more try; if that also resolves nothing, the run **STOPs** exactly as before — nothing
closed, deleted, or synced.

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
that exists — a plan already deleted from the working copy is not this case, and its stale link is
removed as usual. Only untracked plans are deleted on the default path — a correction can still move
this row into "Сделаю", at the cost of a dirty tree and, with it, the worktree row.

### The Task Did Not Close

Three different causes, one downstream effect. The pre-close re-read showed a child that is
`in_progress` now; or the re-read itself failed, leaving eligibility unverifiable; or `bd close` ran
and failed — bd was locked by another writer, or the id no longer resolves. The summary line names
which one, because the user's next move differs: a reopened child means the work genuinely is not
done, a failed re-read means try again, a failed `bd close` means look at bd. Items 2 and
3 of step 5 are skipped in all three cases: a container parent qualifies only because its last open child just closed,
and the plan is deleted because the work it planned is done. Neither premise holds. Git cleanup and
the ledger are unaffected — they depend on the branch, not on the task:

```
Выполнено:
  1. ✗ задача claude-tools-elf.59 не закрыта: bd close failed (database is locked)
     (варианты той же строки: «у задачи снова есть in_progress подзадача claude-tools-elf.59.2»,
      «не удалось перечитать bd show claude-tools-elf.59 — право на закрытие не подтверждено»)
  2. — план не тронут (задача не закрылась)
  3. ✓ worktree удалён
  4. ✓ локальная ветка удалена
  5. ✓ ветка на origin удалена
  6. ✓ ledger PR #138 удалён
  7. ✓ beads синхронизированы
  8. — родитель claude-tools-elf не закрыт (задача не закрылась)
```

The numbering follows the **scenario**, not step 5's execution order: the parent was line 8 of the
approved block, so it keeps that number here even though execution reached it second. One summary
line per scenario item, never two merged into one — that is what lets the user check promised
against done on the same number.

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
rather than as a question. This holds whether or not git still tracks the file: `git ls-files` reads
the index, so an uncommitted deletion still reports as tracked, and that is **not** the
"план закоммичен" refusal (step 1).

```
Выполнено:
  2. ✓ ссылка Plan: удалена (файл уже отсутствовал на диске)
```

### Several `Git:` Lines on One Task

A task recorded more than one branch (`flow:start` step 8.1's `--append`, for a parallel workstream
in another project or PR). The scenario is built for `CURRENT_BRANCH` only, as today
(`claude-tools-elf.51`) — the task's other recorded branches are neither compared nor touched.

## Why these checks

Everything here is reasoning, not instruction — the steps above carry the rules themselves. It is
recorded so a later reader can tell a considered constraint from an accidental one before removing
it. Numbers 1-9 are the base-resolution rules of step 1.

**1. Each candidate is validated where it is chosen.** A target branch deleted after its own merge,
or a dangling HEAD symref, must not shadow a perfectly good later candidate. Validating once at the
end of the chain instead turns a repository whose default branch is neither `master` nor `main` into
`NO_BASE` and stops the run for nothing.

**2. The base comes from the remote.** A local `master` that has not been pulled since the PR merged
makes the criterion lie, and the safety check then evicts the user for no reason.

**3. The PR's own target comes first — the reason is stacked branches.** A subtask branch is
routinely opened against its feature branch; compared against the repository's default branch it
reads "not merged" until the whole feature lands, and the safety check would refuse exactly the
tasks that get closed most often. The PR/MR target is the precise answer to "where was this work
supposed to land".

**4. `git symbolic-ref` is only the second candidate.** `refs/remotes/<remote>/HEAD` is frequently
absent or not a symbolic ref (`fatal: ref refs/remotes/origin/HEAD is not a symbolic ref` — this
repository has no such ref at all), the default branch may carry any name, and the remote is not
always `origin`. `git remote set-head --auto` asks the server which branch is default, so it is
tried before giving up; the `master` → `main` pair is a last-ditch convention, not a definition.

**5. No source of a base may hand back the branch itself.** A base equal to `CURRENT_BRANCH` makes
`merge-tree` compare the branch with itself and report "merged" unconditionally — a confirmed verdict
for work that landed nowhere. All three inferring sources can produce it. The upstream is the obvious
one (`@{upstream}` usually *is* `$REMOTE/$CURRENT_BRANCH`). The remote's HEAD symref names the task
branch whenever the remote's default *is* that branch — the ordinary state of a repository holding
one branch. And a PR's target carries the same name as the current branch when the PR comes from a
fork: the head is `fork:branch`, the base is the upstream's branch of that name, and in the fork
`refs/remotes/$REMOTE/<base>` resolves back to our own. The conventional `master`/`main` candidate
needs no guard — a task branch named `master` is a branch mismatch, and step 2 refuses every branch
row there regardless.

**6. No base asks rather than improvises.** An empty base makes `merge-tree` error out and every
guard below it meaningless — and those guards are what stand between the run and irreversible
deletions. The `if` also keeps the user from seeing two `fatal:` lines instead of step 2's question.

**7. A branch that never committed anything is indistinguishable from a merged one, and needs no
distinguishing.** Its tip *is* the base's tip as of creation — an ancestor of the base, exactly like
a fast-forward or merge-commit merge. `git rev-list --count`, `git merge-base --is-ancestor` and
`git for-each-ref --contains` agree in every one of those states. A ref reachable from the base can
be deleted without losing a commit, by construction. What *can* be lost is uncommitted content in
the working copy, which `WORKTREE_DIRTY` measures directly.

**8. The tree comparison decays; `PR_STATE` does not.** `git merge-tree --write-tree` performs a
real three-way merge against the base **as it stands now**. Measured on git 2.47: right after a
squash merge, `MERGED_TREE == BASE_TREE`; once the base later edits the same lines the branch
touched, `merge-tree` exits 1 with `CONFLICT (content)` and a differing tree; once the base deletes a
file the branch touched, `CONFLICT (modify/delete)`. Both read as "not merged" on a branch that did
merge. `PR_STATE` records a fact about the past, so step 2's ladder checks it first.

**9. `--untracked-files=all` is required, and gitignored files still do not count.** Plain
`git status` collapses a brand-new directory to a single `dir/` entry, and an untracked note inside
it must count as content to lose. The subtraction for the plan exists because an untracked plan in a
non-gitignored `docs/plans/` would make the working copy dirty all by itself and refuse the cleanup
it is part of; when the plan row is *refused*, nothing is going to delete those files, so they count
as dirt again. Ignored files are excluded deliberately: they are disposable by construction — the
plan files themselves live in a gitignored directory and are meant to vanish with the worktree.

**A tracked plan stays in git.** `rm` on a tracked file dirties the working tree immediately before
`git worktree remove`, which then refuses (this skill never passes `--force`), and the content is in
history anyway — so a real removal buys nothing and still costs its own commit, PR, merge and
`flow:done` run. Deleting a *modified* tracked plan leaves the same `D` entry in `git status`.

**Branch rows are never gated on the commit graph.** Counting
`git rev-list --count "$BASE_REF..$CURRENT_BRANCH"` distinguishes none of the states in 7 above, so
refusing a row on it would report "влитость не подтверждена" on a demonstrably merged branch in every
repository that does not squash-merge.

**The ledger's gate is the PR's state, never branch deletion.** A branch is routinely kept on purpose
after a merge — for history, or to re-read what happened in review — so its survival must not keep a
settled PR's ledger alive forever; conversely a successful `git branch -d` says nothing about whether
the PR is still taking review.

**Deleting the remote branch closes an open PR.** On GitHub `git push "$REMOTE" --delete <branch>`
closes the PR attached to it: an irreversible external action that the line "удалю ветку на origin"
does not announce and the single approval was never asked about.

**The base question's quoting is legibility, not the untrusted-data rule.** The answer is typed by
the person who started this run, in their own terminal, against their own repository — there is no
second party, and an answer containing `$(...)` is that person running a command on themselves. The
rule that governs reviewer text, PR-author-controlled branch names and `bd` content elsewhere in flow
does not extend here; a reviewer should not file this as an injection site. What quoting buys is the
ordinary case: a branch legitimately named with a `$` in it expands to nothing and the run reports
the wrong ref as missing.

## The Bottom Line

Always follow the workflow.

**Collect before deciding.** Branch, mergedness, task, parents, plan, worktree, and ledger are all
gathered in one pass, before anything is printed or decided.

**The safety check is mergedness, and a merged PR settles it.** A `MERGED` PR state confirms
outright and cleanup proceeds regardless of what `git merge-tree`'s tree comparison finds — that
comparison decays once the base moves over the same lines. What a PR's mere *existence*, or any
other state, does not settle is anything at all: an open or closed-unmerged PR is not evidence the
work landed.

**One scenario, one approval.** Everything the run will do, and everything it deliberately won't,
is in that one block. A correction reprints it whole and asks again — nothing executes on a partial
answer.

**The summary must show divergences.** The approval was given once, in advance, to a list — the
summary is obliged to report every item that didn't go as promised.

Obvious logic requires MORE structure, not less.
