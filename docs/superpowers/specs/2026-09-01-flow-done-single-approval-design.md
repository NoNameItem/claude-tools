# flow:done — one scenario, one approval

**Task:** claude-tools-elf.59
**Date:** 2026-09-01
**Status:** approved, pending implementation plan

## Problem

`flow:done` stops and asks at every step. A single ordinary run (closing `claude-tools-5vg.8`,
2026-08-28) collected three consecutive `yes` answers, none of which had a realistic alternative.

The deeper issue is not the count but the shape: the skill asks *while* it works, so each question
sees only its own local state. It cannot say what the whole run will do, and the user cannot answer
once for all of it. Mechanical agreement to a series of such questions also devalues the
confirmations that do carry a choice.

### Full inventory of confirmation points (SKILL.md, current)

| # | Location | Question | Fires when | Typical run |
|---|---|---|---|---|
| 1 | Step 1, l. 66–79 | "PR exists: {url} (state: {state}). Proceed to close task on this branch?" | feature branch + PR exists — **any state** | always |
| 2 | Step 2, l. 92 / 712 | "Which task is complete?" | more than one in_progress leaf | never in practice (see below) |
| 3 | Step 4.1, l. 137 / 741 | "Which file is the implementation plan?" | several plan candidates | rare |
| 4 | Step 4.2, l. 143–152 | "Plan file found. Delete / Keep" | plan found | when a plan exists |
| 5 | Steps 5–6, l. 180–230 | "Parent {id} now has all children closed. Close it too?" | parent has no open children — **recursively** | 0–N times |
| 6 | Step 8.3, l. 262–278 | "Delete branch and associated resources?" | branch matches task | always |
| 7 | Step 8.4 item 8, l. 300–308 | "PR #{n} is CLOSED... Delete the ledger?" | `PR_STATE=CLOSED` + ledger exists | rare |
| 8 | Step 8.4 error / l. 810 | "Force-delete with `git branch -D`?" | `git branch -d` refused — **always under squash merge** | always |

Not confirmations: "feature branch without PR" is a hard exit, and a failed `git worktree remove`
is a message that does not block.

**Ritual:** #1 in the `MERGED` state and #8. Both are decided by state known in advance — the work
is already in master, and `-d` is guaranteed to refuse under squash merge (CONTRIBUTING.md,
"Merge Strategy"). **Real choices:** #2, #3, #5, #7. **#4** has three options but one habitual
answer.

### Three findings the task description does not mention

**F1. Step 1 asks before the task is known.** The branch check runs at step 1; the task is only
found at step 2. So "Proceed to close task on this branch?" is asked without a task id, and
direction A of the task ("do not ask when the PR is MERGED *and* the branch matches the task being
closed, via `flow-current-task`") is not expressible in the current step order — that helper needs
the id.

**F2. Questions #2 and #3 never fire.** Step 2 is a bare `bd list --status=in_progress` plus the
prose instruction "Filter for leaf tasks", left to the model's judgement; the `flow-find-leaf`
helper that exists for exactly this is used only by `flow:continue`, which additionally resolves
the task deterministically from the `Git:` lines. In practice the model takes the task it has been
working on and asks nothing — which happens to be right, but is not reproducible, and would behave
differently after a `/clear`. This is the class of defect tracked as `claude-tools-elf.35`.

**F3. "Is there a PR" is the wrong signal for "is the work done".** The skill treats `gh pr view`
as the single source of truth. In a repository with **no remotes at all** (the user has one) `gh`
returns nothing, the skill reads `NO_PR` and exits to `superpowers:finishing-a-development-branch`
on every run — `flow:done` is unusable there by construction. The same false exit occurs on GitLab
repositories, where the MR exists but `gh` cannot see it (`claude-tools-elf.50`).

### Evidence: how to detect "merged" without a platform

`git branch --merged` and `git merge-base --is-ancestor` both report false after a squash merge,
which is this repository's only merge strategy. The reliable test is whether the branch still adds
anything to the base:

```bash
git merge-tree --write-tree <base> <branch>   # == git rev-parse <base>^{tree}  →  merged
```

Verified on git 2.47 against two models built with plumbing (2026-09-01):

| Model | merge-tree result | base tree | Verdict |
|---|---|---|---|
| squash merge: commit carrying `164558c`'s tree, different SHA, parent `master~1` | `93e260e1` | `93e260e1` | merged ✓ |
| unmerged: commit adding a new file on top of `master` | `0b3fafd6` | `93e260e1` | not merged ✓ |

It works with and without a remote, and survives squash and rebase.

`--write-tree` requires git >= 2.38. On an older git the criterion is unavailable: the skill
says so, prints the branch and base it could not compare, and asks the user to confirm the work
is merged before building the scenario. **The answer is defined in both directions.** "Yes" leaves
mergedness **unconfirmed**: it permits closing the task, closing eligible parents, handling the
plan and running `flow-sync push` — none of which destroys anything — but never counts as the
check, so the four branch-gated rows (worktree, local branch, remote branch, ledger) go to
"Не буду" with that reason. The plan is deliberately not among them: it belongs to the task, not to
the branch. "No" (or any non-affirmative answer) behaves exactly like a failed safety check: report
and exit, nothing closed, deleted or synced. It does not silently fall back to
`git branch --merged`, which is wrong under squash merge precisely when it matters.

### What the tree comparison does *not* distinguish, and why it need not

A branch that carries **no commits of its own** also satisfies `merge-tree == base^{tree}`: a
`flow:start` branch whose work was never committed looks exactly like a merged one. It cannot be
told apart, and it does not need to be.

It cannot: such a branch's tip is the base's tip as of creation — an ancestor of the base — which
is precisely the shape of a **fast-forward** merge and of a **merge-commit** merge. Same graph, so
no query separates them. Verified on git 2.47 against throwaway repositories (2026-09-01):

| Model | `merge-tree` vs base tree | `rev-list --count base..branch` |
|---|---|---|
| merge commit (`git merge --no-ff`) | equal | 0 |
| fast-forward merge | equal | 0 |
| squash merge | equal | 1 |
| branch never committed on | equal | 0 |

Keying anything on that count therefore misclassifies **every** merge-commit and fast-forward
merge as "not merged" — i.e. the criterion would work only in squash-merging repositories, while
this skill is explicitly general (see Out of scope: GitLab and other platforms).

It need not: a ref reachable from the base can be deleted without losing a commit, by construction.
Measured on the same models — `git rev-list --all --count` before and after `git branch -D` is
unchanged in all three zero-count shapes. So the branch rows carry no risk here at all.

The risk that motivated the question is real but lives elsewhere: **uncommitted content in the
working copy**, which only the worktree row can destroy. Its signal is direct —
`git status --porcelain --untracked-files=all` (`=all` because plain `git status` collapses a
brand-new directory to `dir/`, hiding an untracked file inside it). Empty → nothing to lose;
non-empty → the worktree row is refused by name, and with it the local branch, since HEAD is still
there. `git worktree remove` refusing on a dirty tree is a second line of defence behind that
check, not the design.

The scenario's own plan file is subtracted from that measurement: it is named in the scenario,
approved by the same answer, and deleted in D5's step 3 before the worktree is touched in step 5.
Otherwise an untracked plan in a non-gitignored plan directory would dirty every working copy by
itself and refuse the cleanup it belongs to. (In a repository that gitignores its plan directory
the question does not arise — `git status --porcelain` does not report ignored files, while the
plan search deliberately does, `--others` without `--exclude-standard`.) If the plan row is refused —
several candidates matched, or git tracks the file — those files count as content again: nothing is
deleting them.

## Design

### D1. Flow structure

Steps 1–8 are replaced by six:

| Step | Does | Stops? |
|---|---|---|
| 0 | `flow-require-bd` — unchanged | no |
| 1 | **Collect state** — branch, repository mode, task, mergedness, parents, plan, worktree, ledger | no |
| 2 | **Safety check** — work not merged into the base branch: report, suggest `superpowers:finishing-a-development-branch`, exit | exit |
| 3 | **Scenario** — print everything that will be done, ask the single question | yes, once |
| 4 | **Handle the answer** — approval → step 5; correction → rebuild scenario, back to step 3 | loop |
| 5 | **Execute** — fixed order, report per item | no |
| 6 | **Summary** — what was done, what failed | no |

Every confirmation that used to interrupt the run — parent closing, the plan's fate, branch and
worktree deletion, the ledger, the local branch's delete flag — becomes a line of the scenario
with a default.

The safety check of step 2 is kept deliberately: it is not ritual. Only its criterion changes, from
"a PR exists" to "the work reached the base branch" (F3).

### D2. State collection (step 1)

Collected in one pass and without questions; the only external effect is the `git fetch` of
D2.1, which updates remote-tracking refs and nothing else:

| Fact | How |
|---|---|
| Current branch | `git branch --show-current` |
| Repository mode | `git remote` — empty → local-only, else remote mode |
| Base branch | first that resolves: the PR/MR's own target (`gh pr view --json baseRefName`), then `git symbolic-ref --quiet refs/remotes/<remote>/HEAD` (restored with `git remote set-head <remote> --auto` when missing), then the branch's upstream when it is not the branch itself, then `<remote>/master`, then `<remote>/main`; local-only: first existing of local `master`, `main`. Yields two values — `BASE_REF` (`origin/master`, the comparison base) and `BASE_LOCAL` (`master`, the checkout target). None resolves → the run stops (D2.4) |
| **Mergedness** | `git merge-tree --write-tree <base> <branch>` == `git rev-parse <base>^{tree}` |
| PR state | `gh pr view --json state,url,number,baseRefName` — remote mode only; a failed lookup is `UNKNOWN`, not "no PR" (D2.6) |
| Task | session context → branch → `flow-find-leaf` |
| Parent chain | `bd show` upwards: id, type (`epic` or not), open-children count |
| Plan file | `Plan:` line in the description, else `git ls-files --others --modified` over the plan directories |
| Worktree | `flow-in-worktree` |
| Working copy | `git status --porcelain --untracked-files=all` — non-empty gates the worktree row, and only it |
| Remote branch | `git branch -r` |
| Ledger | present when a `PR_NUMBER` was obtained |

Three decisions differ from today's behaviour:

**D2.1. The base is the PR's own target first, and comes from the remote, not from the local ref.**
Comparing against a local `master` that lags (no `git pull` since the PR merged) makes the criterion
report "not merged" and the safety check evict the user for no reason. In remote mode: `git fetch`
first, then the chain below. In local-only mode the local branch is the only option.

The chain, first hit wins:

1. **the PR/MR's own target** — `gh pr view --json baseRefName` (GitLab:
   `glab mr view <iid> --output json --jq .target_branch`);
2. `git symbolic-ref --quiet refs/remotes/<remote>/HEAD`, restoring the symref with
   `git remote set-head <remote> --auto` when it is missing;
3. the branch's own upstream (`git rev-parse --abbrev-ref @{upstream}`), **only** when it names
   something other than the current branch — normally it names the branch itself, and a branch
   compared with itself is "merged" unconditionally;
4. `<remote>/master`, then `<remote>/main`.

Each candidate is validated against `refs/remotes/<remote>/<name>` **where it is chosen**, and one
the remote does not have falls through to the **next candidate** — not to `master`/`main` and not to
`NO_BASE`. Validating once at the end of the chain would make a deleted PR target, or a dangling HEAD
symref, stop the run in any repository whose default branch is named something else.

**The PR target leads because of stacked branches.** A subtask branch is opened against its
**feature** branch; measured against the repository's default branch it reads "not merged" until the
whole feature lands, so the safety check would refuse to close exactly the tasks that get closed
most often — a regression against the old skill, which only checked that a PR existed. The PR target
is the precise answer to "where was this work supposed to land": the feature branch for a subtask,
the default branch for a feature.

`git symbolic-ref refs/remotes/origin/HEAD` is only the **second candidate**: that ref is frequently
absent or not a symbolic ref (this repository has none at all:
`fatal: ref refs/remotes/origin/HEAD is not a symbolic ref`), the default branch may carry **any**
name, and the remote is not always named `origin` — hence the `git remote` lookup, the `set-head`
restore, and the `master` → `main` tail. **If nothing resolves, the run stops** (D2.4); an empty base
makes `merge-tree` error out, and that comparison is what guards every deletion.

Comparison base and checkout target are kept as separate values. `BASE_REF` (`origin/master`) goes
to `merge-tree` and `rev-parse`; `BASE_LOCAL` (`master`) is what step 5 checks out —
`git checkout origin/master` detaches HEAD and the `git pull` after it fails with "You are not
currently on a branch".

**D2.2. Mergedness comes from git; the PR only supplements it.** `merge-tree` works in both modes
and survives squash. The PR state is needed solely to decide about the remote branch and the
ledger. Side effect: the skill becomes usable in a repository without remotes (F3).

**D2.3. `gh` is not invoked in local-only mode.** Today it always runs and its empty answer is read
as "no PR", i.e. as grounds for exit. Now the absence of a platform simply means the scenario has
no PR-related lines.

**D2.6. A failed `gh` lookup is `UNKNOWN`, never "no PR".** `gh pr view` exits non-zero both when no
PR exists and when the call fails (auth, rate limit, a TLS timeout), so `|| echo NO_PR` reads a
network blip as "no PR" — and an unset `PR_STATE` then trivially satisfies the remote-branch row's
"not `OPEN`", licensing a `git push <remote> --delete` that closes a live PR. The two are separated
by a second call: `gh pr list` exits 0 and prints `[]` when the platform was reached and this branch
has no PR, non-zero when the lookup itself failed. `UNKNOWN` refuses the remote-branch row exactly as
`OPEN` does (D3), and falls through to D2.1's next base candidate rather than yielding an empty base.
The ledger needs no extra rule: it purges on `MERGED` alone.

**D2.4. No base branch is a question, never a guess.** When no candidate of D2.1's chain
resolves — no PR target, no HEAD symref even after `set-head --auto`, no distinct upstream, no
`master`/`main` — the skill says which candidates it tried and asks the user which branch is the
base. Guessing one would silently re-point the criterion that gates every deletion; stopping outright
would strand a whole class of repository, since D2.1's chain can only infer conventional names and a
local-only repo whose base is `trunk` or `develop` would never get past this point.

The answer is validated before use — it must resolve to a real ref (`git show-ref --verify` against
`refs/remotes/<remote>/<answer>` in remote mode, `refs/heads/<answer>` locally) and is referenced
quoted everywhere, since a branch name may carry shell metacharacters. A valid answer sets the base
and the run resumes the comparison from `merge-tree` as if D2.1 had resolved it; an answer naming no
ref is asked once more; a second failure, or a refusal, stops the run with nothing closed, deleted or
synced. Asking is a pre-scenario clarification, like the two task-identity questions — it does not
weaken "one scenario, one approval", which is about the scenario itself.

The comparison block is guarded by that resolution and does not run without a base, so the user sees
the question alone — not two `fatal:` lines from `merge-tree` and `rev-parse` against an empty ref,
printed before it.

**D2.5. Parent open-children counts are taken as of the moment they will be acted on.** The chain is
collected in step 1, but the task closes in step 5.1 and parents at 5.2 — so a count excludes the
task being closed and every lower ancestor the same scenario lists for closing. Read literally
(count the task as open), a container parent whose last open child is the task being closed could
never qualify and the row would be dead; read loosely, the rule would be unstated. Step 5 re-reads
`bd show <parent>` immediately before closing it, so the promise and the action see the same
state.

**Task resolution order** (F1, F2): the session context first — `flow:done` normally follows
`flow:start`/`flow:continue` in the same session, so the agent already knows the task; then the
branch (after a `/clear`), matching the task id in the branch name against the `Git:` lines; then
`flow-find-leaf` as the last resort. If context and branch disagree, both are shown and the user is
asked **before** the scenario; the same applies when `flow-find-leaf` itself returns more than one
candidate. These are the only two cases where a question about the task arises at all.

### D3. Scenario format and defaults (step 3)

One block: a header of facts, a numbered list of actions, a separate list of what is deliberately
*not* done, and the single question. Numbering is continuous so a correction can be short
("everything but 4").

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

| Item | Default | Appears when |
|---|---|---|
| Close the task | do | always |
| Plan file | **delete** when untracked; **leave in git** when tracked, clean or modified; **none** when several candidates match | a plan was found |
| Worktree | delete | we are in a worktree, branch matches the task, mergedness confirmed, working copy clean |
| Local branch | delete, always `-D` | mergedness confirmed, branch matches the task, and — in a worktree — that worktree is being removed |
| Remote branch | delete | remote mode, branch exists, branch matches the task, mergedness confirmed, PR state known and not `OPEN` |
| Ledger | purge when `MERGED`; **leave** when `CLOSED` or `OPEN` | PR known, ledger exists, branch matches the task, mergedness confirmed |
| Container parent | close | no open children remain once this run's closures are counted, type ≠ `epic` |
| Epic parent | **do not close** — default, overridable by a correction | same condition, type `epic` |
| `flow-sync push` | do | always |

Four gates guard the four branch-gated rows — worktree, local branch, remote branch, ledger — each
with its own named refusal in "Не буду". The plan row is **not** among them: the plan belongs to
the task, not to the branch, so it is handled whenever the task closes, including under an
unconfirmed verdict. Wherever this document refuses "every deletion" for an unconfirmed verdict, it
means those four rows.

- **the branch belongs to the task** (`flow-current-task <id>`). Otherwise mergedness is not checked
  at all — that branch's relationship to the base says nothing about this task — the header states
  that plainly, and worktree, local branch, remote branch and ledger all move to "Не буду" with the
  reason "ветка не относится к задаче". The task itself still closes and beads still sync: the work
  may have landed by another route, and refusing would make the skill unusable from `master`.
- **mergedness is confirmed** — an unconfirmed verdict (old git plus a verbal "да") refuses those
  four rows just as firmly as "not merged" would have stopped the run. Nothing else downgrades the
  verdict: once the trees are equal, a branch with no commits of its own is confirmed like any
  other, because its ref is reachable from the base and deleting it loses no commit.
- **the PR's state is known and not `OPEN`**, for the remote branch alone. A branch tree can equal
  the base while its PR is still open (content landed via another PR, a cherry-pick, a rebase), and
  `git push <remote> --delete` then **closes that PR** — an irreversible external action the line
  "удалю ветку на origin" does not announce. `UNKNOWN` (D2.6) refuses the row the same way and for
  the same reason: what cannot be ruled out may be a live PR. The two rules about the same PR must
  point the same way: an `OPEN` PR keeps both its ledger and its branch.
- **the working copy is clean**, for the worktree alone —
  `git status --porcelain --untracked-files=all` empty. This is the one row that can destroy
  content existing nowhere else, and this is the direct measurement of whether such content exists.
  A dirty working copy also takes the local-branch row with it: HEAD is still in that worktree, so
  `git branch -d` cannot run, and the scenario must not promise what execution will skip (D5's
  coupling, stated up front instead of discovered).

**Several plan candidates get no default deletion.** The plan row then lists every candidate and
defaults to touching none — filed under "Не буду" with the list as the reason. Deleting the wrong
plan file is not recoverable from the summary; the user names the right one as a correction.

**A tracked plan is not deleted by default**, clean or modified. A `Plan:` link can point at a committed
file, and the `--others --modified` search surfaces committed files too once they are edited.
A `Plan:` link may also point at a file already deleted from the working copy: `git ls-files` reads
the index, so it still reports tracked, but there is nothing to delete and only the stale link is
removed (D5's step 3). `rm` on a tracked file that is present dirties the working tree in the
same run that then calls
`git worktree remove` — which refuses on a dirty tree, since the skill never passes `--force` — and
removing it for real would cost a PR, a merge and another `flow:done` run for content that is in
history either way. Modification does not weaken that: a modified tracked plan is just as committed,
and `rm` leaves the same `D` entry. Its row goes to "Не буду" with that reason; `rm` applies
**only to untracked** plan files. A refused plan then counts as working-copy content again for the
worktree row, like any other uncommitted change. Like the epic, this is a **default, not a
prohibition**: a correction moves the row into "Сделаю" and D5's step 3 then deletes the file, at the
cost of a dirty tree and, through it, the worktree row.

Epics are excluded from automatic closing because they are long-lived and keep gaining children.
This is the **default, not a prohibition**: the user knows whether their epic is done, so a
correction ("закрой и эпик") moves that row into "Сделаю" and D5's step 2 then closes it. What the
default prevents is the skill closing an epic **on its own**. The cost of that error is on record: `claude-tools-5dl.9` was closed while `.9.2` and `.9.3`
were still open, and `bd graph` then dropped the edge to the epic and surfaced both children as
separate roots — the damage was noticed only through a visibly broken task tree.

Two rules replace the tests this text-only approach cannot have:

**D3.1. Mandatory sweep.** The nine rows above are a checklist: each must either appear as a line or
be omitted for an explicitly named reason. A skipped row now means a silent action or a silent
omission, not merely an unasked question.

**D3.2. "Не буду" lists only deliberate refusals** — the epic, unless a correction moved it into
"Сделаю"; the ledger of a `CLOSED`, `OPEN` or `UNKNOWN` PR; the remote branch when its PR is `OPEN`
or its state is `UNKNOWN`; the four branch-gated rows (worktree, local branch,
remote branch, ledger) when the branch does not belong to the task, and those same four when
mergedness is unconfirmed — the plan in neither case, its fate follows the task; the worktree when
the working copy is dirty, and the local branch with it; the plan when several candidates match, and
the plan when git tracks it.
What is simply absent from the environment (no remote, no plan, not in a worktree) is not printed at
all: the scenario states decisions, not an inventory.

`-D` is no longer a second question after `-d` refuses. Nor is the flag conditioned on the merge
form: step 1 establishes mergedness by tree equality, and no git command tells a squash merge from a
fast-forward or a merge commit at that point (D2.2). Tree equality alone already proves the tip adds
nothing to the base, so the branch is deleted with `-D` unconditionally — and the scenario says so up
front, rather than claiming a merge strategy nothing determined.

### D4. Handling the answer (step 4)

- **Approval** ("да", "ок") → execute, no further questions.
- **Correction** ("да, но локальную ветку оставь", "всё кроме 4", "закрой и эпик") → apply, reprint
  the **whole** scenario in the same format and numbering with changed lines marked, ask again.
  Unlimited iterations.
- **Refusal** ("нет") → do nothing at all, including closing the task; report that nothing changed.
- **Unclear correction** → ask about *that item only*, then reprint the scenario and ask normally.

The scenario is reprinted in full rather than as a diff: a correction can move items between
"Сделаю" and "Не буду", and what matters at that moment is the resulting state. The second
confirmation exists to guarantee the correction was understood — a diff does not show that.

### D5. Execution and errors (steps 5–6)

Fixed order — beads first, git second:

1. `bd close <task-id>`
2. container parents, bottom-up — and the epic only when the approved scenario listed it (D3)
3. plan: `rm` + `flow-link-doc <task> Plan ""` — **untracked** plans by
   default; a tracked one, clean or modified, stays in git unless a correction moved its row into
   "Сделаю" (D3)
4. `flow-sync push`, reading its **stderr**: the helper is best-effort and exits 0 even when the
   dolt commit/pull/push failed, reporting the problem only on stderr
   (`plugins/flow/AGENTS.md`, "flow-sync is best-effort"), so a clean exit does not by itself
   confirm the sync succeeded. The summary line reports what stderr said, not the exit code. Still
   non-blocking.
5. `cd` to the main repo root (leaving the worktree — removing the one you stand in makes every
   later command fail) → `git worktree remove` → `git checkout <BASE_LOCAL>` (the local branch
   name — checking out `BASE_REF`/`origin/master` detaches HEAD and breaks the pull) → `git pull`
   **in remote mode only** (a local-only repository has nothing to pull from) →
   `git branch -D` → `git push <remote> --delete` (only when the scenario listed it; `<remote>`
   is the detected remote, not a hard-coded `origin`)
6. `flow-review-ledger purge`
7. summary

Beads precedes git for the same reason as today's steps 7 and 8: the git part can fail on a dirty
worktree, and by then the closed task must already be recorded and synced. The ledger goes last,
after branch deletion is confirmed: `purge` is irreversible and keeps no backup.

Execution errors do not block. Each failed item produces a line in the summary and the rest
continues. One coupling: if `git worktree remove` fails, deleting the local branch is skipped (we
are still on it) — also a summary line.

**One carve-out: a failed item 1 stops the beads half.** Items 2 and 3 both act on the premise that
the task is closed — a container parent qualifies only because its last open child just closed, and
the plan is deleted because the work it planned is done. If `bd close` failed, that premise is false,
so items 2 and 3 are **skipped**, each with its own summary line naming the reason. Git cleanup
(item 5) and the ledger (item 6) are unaffected: they turn on the branch's state, not the task's, and
stay independent and non-blocking. Item 4 still runs — syncing whatever beads state exists costs
nothing.

The summary lists the scenario items with their actual outcome and names divergences explicitly:

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

## What this replaces in SKILL.md

Removed: step 1 as a PR gate, the separate questions 4.2, 5/6, 8.3 and the `-D` follow-up, the
`CLOSED` ledger question, and the "feature branch without PR" exit. Quick Reference, Red Flags,
Common Rationalizations and Examples are rewritten — they describe the "ask at every step" model
throughout and would otherwise contradict the body of the skill.

## Out of scope

- **GitLab (`glab`)** — `claude-tools-elf.50`. Generalising the criterion to git removes the false
  exit on GitLab repositories, and D2.1 names the `glab` equivalent of the base lookup, but no
  MR-specific scenario lines (state, ledger, remote-branch gating) appear.
- **Tasks with several `Git:` branches** — `claude-tools-elf.51`. The scenario is built for the
  current branch, as today.
- **Configurable defaults** (e.g. always keep plans) — the `delete` default plus a one-phrase
  correction covers it.
- **A `flow-done-plan` helper** — considered and rejected, see Alternatives.

## Alternatives considered

**B. A `flow-done-plan` helper plus execution in the skill.** State collection and scenario
assembly become a pure function of the environment, testable in `plugins/flow/bin/tests` like the
other helpers, with execution left in the skill so the helper can destroy nothing. Rejected: the
scenario depends on a large combination of environment states (mode, platform, mergedness, parent
types, plan sources, worktree), and a script covering all of them is brittle where a prose
checklist is adaptable. The risk accepted in exchange is scenario drift between runs; D3.1 and D3.2
are the mitigation.

**C. Hybrid** — a helper for the facts (mergedness, task-from-branch), assembly in the skill.
Rejected with B, for the same reason and with less benefit.

## Acceptance

The skill has no automated tests and executes from the installed plugin release, not from the
working copy, so acceptance is a manual checklist run after the release:

1. remote repository, squash-merged PR, work in a worktree → full scenario, answer "да", summary
   without divergences;
2. same case, answer "да, но локальную ветку оставь" → rebuilt scenario, branch survives;
3. branch not merged → safety check and the `finishing-a-development-branch` suggestion, nothing
   changed;
4. repository without remotes → scenario without PR, remote-branch and ledger items, mergedness
   determined via `merge-tree`;
5. parent epic with all children closed → line in "Не буду", epic still open;
6. `flow:done` run from `master` (branch does not belong to the task) → header says mergedness was
   not checked, task closes and syncs, worktree/branch/ledger rows are named refusals;
7. merged branch whose PR is still `OPEN` → the remote branch stays, with the reason named, and the
   PR is still open afterwards;
8. non-epic container parent whose only remaining open child is the task being closed → the parent
   appears under "Сделаю", and after the run both the task and the parent are closed while the epic
   above them is not. This is the one automatic action the design introduces on a task other than
   the one being closed, and cases 1–5 never exercise it: their parent was an epic every time.
9. branch that reached the base through a **merge commit** rather than a squash (equally: a
   fast-forward) → mergedness confirmed from the trees alone, and the worktree, both branches and
   the ledger appear under "Сделаю" rather than as refusals. No squash-merging fixture can see this
   path: there the branch's own commits are ancestors of the base, so any criterion that counts
   them calls a merged branch unmerged and the cleanup half of the run dies while cases 1–8 all
   still pass — which is exactly how the `rev-list --count` defect survived the first eight.
10. **stacked branch**: a subtask branch whose PR targeted its **feature** branch, merged there
    while the feature branch itself is still open and unmerged into the repository's default branch
    → the base is the PR's target (D2.1), mergedness is confirmed against it, the full cleanup
    scenario is offered, and `git checkout <BASE_LOCAL>` afterwards lands on the feature branch, not
    on `master`. Measured against the repository base instead, this branch reads "not merged" and
    the run stops at step 2 — refusing the single most common shape of task this skill closes.

Cases 1–3 and 5–6 run on this repository on the next task after the release; case 4 on the user's
local-only repository; case 7 on the next branch whose content lands through another PR; case 8 on
the next task that sits under a non-epic parent; case 10 on the next decomposed task whose subtask
branch targets its parent's feature branch — this repository does stack that way, so it needs no
special fixture. Case 9 has no home among these: this repository squash-merges only
(CONTRIBUTING.md, "Merge Strategy"), so it runs on the first non-squash repository `flow:done` is
used in, and until one turns up the only evidence for that path is the plumbing measurement in
"What the tree comparison does *not* distinguish" above. Every case above is assigned exactly
once.
