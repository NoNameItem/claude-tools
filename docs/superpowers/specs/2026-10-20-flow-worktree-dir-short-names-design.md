# flow-worktree-dir — name worktree directories from the task, without the type and project prefixes

**Task:** claude-tools-elf.28
**Date:** 2026-10-20
**Status:** design approved (2026-10-21) — not yet implemented

Mockups: none — the change is a CLI helper and the directory names it prints; the IDE sidebar it
serves is the user's own tool, not something flow renders.

## Problem

Worktree directories are named from the full branch with `/` → `-`, e.g.
`.worktrees/feature-claude-tools-elf.23-review-comments-claude-code-web`. The user reads these in
the IDE sidebar (PyCharm, and a second editor) to find the worktree whose spec or plan they want to
open. The sidebar shows roughly the first 33 characters; it can be scrolled horizontally or widened,
and the goal is that this is needed **as rarely as possible**.

Today the visible part is mostly `feature-claude-tools-`, identical on every flow worktree:

```
feature-claude-tools-elf.23-review…
feature-claude-tools-elf.28-flow-…
fix-claude-tools-elf.17-review-com…
```

The user's words (2026-10-20): the repeated `feature-claude-tools` "не сильно несут смысл, а
claude-tools вообще понятен из текущего проекта и несет ноль смысла". What identifies a worktree is
the task id and the start of the task title.

## Decision

### 1. The directory name is computed from the task, in parallel with the branch name

The user's decision (2026-10-20): both names are derived from the task; neither is derived from the
other.

| | Rule | Example for claude-tools-elf.28 |
|---|---|---|
| **Branch** | **unchanged** — `flow-branch-for`: `<type prefix>/<full task id>-<slug>` | `feature/claude-tools-elf.28-flow-worktree-dir-shorten-generated` |
| **Directory** | `.worktrees/<task id without the project prefix>-<slug>` | `.worktrees/elf.28-flow-worktree-dir-shorten-generated` |

- **Slug** — the same slug the branch uses: lowercase title, every run of non-`[a-z0-9]` → `-`,
  the first **5** words. The user kept 5 words (2026-10-20) rather than shortening the directory
  slug. The branch and directory slugs must come from **one** implementation, so the two names can
  never drift apart; today `slugify` and `MAX_WORDS` live inside `flow-branch-for`.
- **Empty slug** → the id alone: `.worktrees/elf.28` (mirrors `flow-branch-for`, which falls back to
  `<prefix><task-id>`).
- **Project prefix** — the bd issue prefix, read with `bd config get issue_prefix` (here
  `claude-tools`); the directory drops `<issue_prefix>-` from the start of the task id. *My call.*
  If the id does not start with `<issue_prefix>-`, or the prefix cannot be read (empty output, bd
  error), the directory keeps the **full** id and the helper writes a one-line warning to stderr,
  the same way `flow-branch-for` warns on an unknown type. A longer name is harmless; failing to
  create the worktree is not. *My call.*
- **Type prefix** (`feature-`, `fix-`, `chore-`) is not part of the directory name at all.

### 2. A hand-named branch: ask the user for the directory name

The user's decision (2026-10-20): when the branch was named by hand, the skill asks what to call the
worktree directory instead of naming it silently.

**"Hand-named"** — *my call on the test*: the branch differs from what `flow-branch-for <task-id>`
prints. This covers:

- `flow:start`, Step 6 answered in free form with a branch name of the user's own;
- `flow:start`, checkout-existing into a worktree, when the found branch is not the computed one;
- `flow:continue`, resuming a `Git:` branch into a worktree, when that branch is not the computed one.

It also catches a flow-made branch whose task was later retitled or retyped, so the computed name
moved on. Asking is harmless there, and the task-based name is the first option anyway.

The question is plain text (never a structured dialog — same AFK reason as every flow prompt,
claude-tools-6q4), asked right before the worktree is created, then the skill waits:

```
Ветка `<branch>` названа не по задаче. Как назвать папку worktree?

1. `<task-based dir>` — по задаче
2. Своё имя — напишите его

Выберите вариант (номер) или напишите имя.
```

`<task-based dir>` is the `flow-worktree-dir <task-id>` output as printed — it already starts with
`.worktrees/`, so the prompt adds no prefix of its own.

*My calls:* if the user already named the directory in their Step 6 free-form answer, that name is
used and the question is skipped; a typed name goes under `.worktrees/` with `/` → `-`. A name left
with no letter or digit (empty, `.`, `..`) is refused and the question asked, from either source:
it would put the worktree at `.worktrees` itself or above it.

This is also what handles a task with **several branches** (parallel per-project workstreams, one PR
each — spec `2026-07-07-flow-multi-design-and-branch-links-design.md`; the user expects each in its
own worktree). `flow-branch-for` gives one name per task, so every branch after the first is
hand-named, and the user gets to call its directory e.g. `elf.28-statuskit` instead of a bare `-2`.
No task has hit this yet: of 249 tasks, 71 record a branch, each exactly one `Git:` line
(2026-10-20).

### 3. `flow-worktree-dir` takes a task id and only computes the name

New interface — *my call*, since the directory is now a function of the task:

```
flow-worktree-dir <task-id>
Prints: .worktrees/<short id>-<slug>        (relative to the CWD, as today)
Exit:   0 ok | 1 task not found | 2 bd error
```

It reads the task with `bd show <task-id> --json` (honouring `BD_BIN`, like `flow-branch-for`) for
the title, and the issue prefix as in §1. It does **not** look at the filesystem or at git: whether
the name is free is git's to say (§4). The old `flow-worktree-dir <branch>` form goes away — its
only callers are the skill snippets in §5.

### 4. Collisions: branch and worktree in separate commands, retry on git's refusal

The user's decision (2026-10-20): a collision is unlikely enough that it does not justify
path-checking logic. Instead the branch is created by its own command, the worktree is added for the
existing branch, and a refusal because the path is taken is retried with `-2`, `-3`, ….

**Why the split is needed** (checked on git 2.47.0 in a scratch repo, 2026-10-20). With
`git worktree add <path> -b <new-branch>`, every refusal over an occupied path happens **after** git
has created the branch: the failed command leaves a stray branch, and re-running it fails on
"branch already exists". With the branch created first, `git worktree add <path> <branch>` refuses
without side effects, and the same command with `<path>-2` succeeds.

**Retry only on the two "path taken" refusals:**

| git output | Meaning | Action |
|---|---|---|
| `fatal: '<path>' already exists` | a live worktree, or any non-empty directory | retry with the next suffix |
| `fatal: '<path>' is a missing but already registered worktree; …` | a worktree whose directory was deleted by hand | retry with the next suffix |
| anything else (e.g. `'<branch>' is already used by worktree at '…'`) | not a name problem — a suffix cannot fix it | stop, show git's error |

Suffixes are tried in order — `<dir>-2`, `<dir>-3`, … — until `add` succeeds; the skill reports the
directory it ended up in. The same applies to a name the user typed in §2 (*my call*: one rule for
every name). An empty directory at the path is accepted by git silently and is simply used.

**If the skill stops** after the branch was created, that branch is not a stray: it is a normal
branch for the task, and the next `/flow:start` finds it (`flow-find-branches`) and offers to check
it out.

**Why a trailing suffix is acceptable.** In a ~33-character sidebar the `-2` is cut off. The user
accepted that (2026-10-20): the case is rare, and the sidebar can be scrolled or widened. The
realistic source of same-named directories — several branches of one task — goes through §2 and
gets a name of the user's choosing.

### 5. Skill call sites

| Skill | Snippet | Today |
|---|---|---|
| `flow:start` Step 8 | Create branch (worktree) | `git worktree add "$WORKTREE_DIR" -b "$BRANCH"` |
| `flow:start` Step 8 | Checkout existing (worktree) | `git worktree add "$WORKTREE_DIR" <existing-branch>` |
| `flow:continue` Step 7 | Option 2 (worktree) — local branch | `git worktree add "$WORKTREE_DIR" <branch-name>` |
| `flow:continue` Step 7 | Option 2 (worktree) — remote branch | `git worktree add "$WORKTREE_DIR" -b <branch-name> origin/<branch-name>` |

All four compute `WORKTREE_DIR=$(flow-worktree-dir <task-id>)` (or take the user's name from §2)
instead of `flow-worktree-dir <branch>`. Shapes:

```bash
# flow:start — create branch (worktree)
WORKTREE_DIR=$(flow-worktree-dir <task-id>) &&
  git branch "$BRANCH" &&
  git worktree add "$WORKTREE_DIR" "$BRANCH" &&
  cd "$WORKTREE_DIR"

# flow:continue — remote branch not yet local
WORKTREE_DIR=$(flow-worktree-dir <task-id>) &&
  git branch <branch-name> origin/<branch-name> &&
  git worktree add "$WORKTREE_DIR" <branch-name> &&
  cd "$WORKTREE_DIR"

# existing local branch (flow:start checkout-existing, flow:continue local)
WORKTREE_DIR=$(flow-worktree-dir <task-id>) &&
  git worktree add "$WORKTREE_DIR" <branch> &&
  cd "$WORKTREE_DIR"
```

- `git branch "$BRANCH"` starts from `HEAD`, exactly as `-b` did. `git branch X origin/X` sets up
  tracking of `origin/X` (verified in the scratch repo), as `-b X origin/X` did.
- On a §4 retry, only the `git worktree add … && cd …` part is re-run with the suffixed directory;
  the branch already exists.
- *My call:* the chain starts at the assignment. Unlike today's pure string mapping, the helper can
  fail (exit 1/2, empty stdout) when `bd show` fails or the task is not found. Run unguarded, git
  would get an empty path — `git worktree add "" -b <branch>` on git 2.47.0 creates the branch and
  aborts with `BUG: builtin/worktree.c:449: How come '' becomes empty after sanitization?` (found by
  the design review, 2026-10-20). On a helper failure the skill **stops**, shows the helper's
  stderr, and creates nothing. There is no fallback name: both skills have already read the task
  through bd earlier in the same run, so a failure here means bd broke mid-run.
- *My call:* `cd` runs only after a successful `add`, so a refusal never leaves the agent in someone
  else's worktree.
- The skill text next to the snippets carries the §4 retry rule and the "on any other failure, report
  and stop" rule.

**Grants.** `flow:start` already grants `Bash(flow-worktree-dir:*)` and `Bash(flow-branch-for:*)`.
`flow:continue` grants `Bash(flow-worktree-dir:*)` but **not** `flow-branch-for`, which §2 now needs
there — add `Bash(flow-branch-for:*)`.

### 6. What does not change

- **Branch names** — `flow-branch-for` output is byte-identical for every task.
- **Existing worktrees** stay as they are; only new worktrees get the new names (the user's decision,
  2026-10-20). No migration, no rename.
- **Worktrees created outside flow** (`add-claude-github-actions`, `exp-codex-nudge`, …) — flow does
  not name them (the user, 2026-10-20: "как-то так и называть").
- **Worktree lookup** is by branch, never by directory name, so `flow-find-worktree` (scans
  `git worktree list` for the task's branch), `flow-in-worktree` (`.worktrees/` in the CWD) and
  `flow:done` (removes the worktree it is in) keep working for old- and new-style directories alike.

## Goals

- New flow worktrees are named `<short id>-<slug>`, so the distinguishing part starts the name.
- Branch and directory are both computed from the task by one shared slug rule.
- A hand-named branch gets a directory name the user chose.
- A name collision never leaves a stray branch and never sends the agent into another worktree.

## Non-goals

- Renaming or migrating existing worktrees.
- Changing branch names, the slug length, or the type-prefix mapping.
- Naming worktrees that flow does not create.
- Checking the filesystem for free names ahead of git.
- Replacing flow's worktree handling with `bd worktree` — that is the separate spike
  claude-tools-elf.32.

## Anti-goals

- A directory name that drifts from the branch's slug because the two are computed by separate
  copies of the rule.
- A helper that hard-fails worktree creation because the issue prefix could not be read.

## Documentation

- `plugins/flow/README.md`, helper table: `flow-worktree-dir <id>` — "Compute the `.worktrees/`
  directory name for a task (short id + slug)".
- `plugins/flow/AGENTS.md` lists the helper by name only — no change needed.
- `flow:done` example output shows `.worktrees/feature-claude-tools-elf.59-flow-done`; update it to
  the new style (`.worktrees/elf.59-flow-done`) so the example matches what new runs produce.
  *My call* — cosmetic, but stale examples get copied.

## Testing

`plugins/flow/bin/tests/test_flow_worktree_dir.py` is rewritten around the task-id interface. The
`fake_bd` fixture in `conftest.py` serves canned `show`/`list` JSON and exits 0 with no output for
anything else, so it needs a way to answer `bd config get issue_prefix`.

Cases:

- prefix stripped: `claude-tools-elf.28` + title → `.worktrees/elf.28-<5-word slug>`;
- subtask ids keep their dots: `claude-tools-5dl.9.2` → `.worktrees/5dl.9.2-…`;
- id not starting with the prefix, and an unreadable prefix → full id, warning on stderr, exit 0;
- empty slug → `.worktrees/<short id>`;
- the directory slug equals the slug in `flow-branch-for`'s output for the same task;
- task not found → exit 1; bd error → exit 2; no argument → non-zero.

`flow-branch-for`'s existing tests must pass unchanged — they are the guard on "branch names do not
change".

`test_flow_skill_contracts.py` parses every fenced and inline snippet in SKILL.md line by line and
requires an exact grant for each helper form (`bare` → `Bash(flow-x)`, `args` → `Bash(flow-x:*)`).
`flow-worktree-dir <task-id>) &&` is the `args` form, already granted in both skills; the new
`flow-branch-for` use in `flow:continue` needs the grant from §5. Run the suite after editing the
snippets — it is the check that the grants still match.

The helpers must keep running under the macOS system interpreter (Python 3.9) — see
`2026-06-11-flow-bin-py39-compat-design.md`.

## Acceptance

- In this repo, `flow-worktree-dir claude-tools-elf.28` prints
  `.worktrees/elf.28-flow-worktree-dir-shorten-generated`.
- `flow-branch-for` prints the same name as before for every task.
- The four snippets in §5 create the branch separately (where they create one), chain from the
  assignment to the `cd`, and carry the §4 retry rule and the §2 question.
- `uv run pytest` (all three suites), `uv run ruff check`, `uv run ty check` pass.

`/flow:*` runs from the installed plugin release, not from this branch, so the new naming cannot be
seen through `/flow:start` until the plugin is released; verify by running the helper directly and
the snippets by hand in a scratch repo (occupied path → `-2`, no stray branch).

## Left to the builder

- Where the shared slug code lives (a new `_`-prefixed module in `plugins/flow/bin/`, the way
  `_git.py` is shared, or another arrangement), as long as `flow-branch-for` and `flow-worktree-dir`
  use the same one.
- Whether `flow-worktree-dir` names from the id as passed or as returned by `bd show` (skills always
  pass the full id).
- Whether to add a skill-contract test pinning the §5 snippets.
