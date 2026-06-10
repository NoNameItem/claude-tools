# flow:continue: Assignee-Based Task View with Per-User Grouping

**Task:** claude-tools-g27
**Date:** 2026-06-10
**Status:** Design

## Problem

`/flow:continue` without `--all` shows no tasks even when the current user has
in_progress work. The per-user filter in `plugins/flow/bin/flow-find-leaf`
compares git `user.name` (e.g. `artem.vasin`) against the issue `owner`, which
beads stores as an email (e.g. `nonameitem@me.com`). The namespaces never match,
so the filter excludes everything. Tasks with no owner are also silently dropped.

## Beads identity facts (verified)

| Field | Format | In `bd graph --json` | Set by |
|---|---|---|---|
| `owner` | email | yes | beads automatically (creator's git `user.email`) |
| `assignee` | actor name | yes (omitted when null) | `bd update -a` or `--claim` |
| `created_by` | actor name | yes | actor chain |

- Actor chain: `$BD_ACTOR` → git `user.name` → `$USER`.
- `bd update --claim` sets `assignee` to the actor name and status to
  in_progress, but **fails if the task is already claimed — even by the same
  user**. Not idempotent.
- `bd update -a <name>` succeeds unconditionally (including reassignment over
  someone else's claim).
- `owner` semantically means "creator", not "who works on it". The correct
  field for "my in-progress work" is `assignee`.

## Decisions

1. **Switch from `owner` to `assignee`.** Follow beads semantics: assignee is
   who works on the task.
2. **Grouped output instead of a hard filter.**
   - Without `--all`: my tasks + unassigned tasks.
   - With `--all`: everyone's, group order **mine → Unassigned → other users
     alphabetically**.
   - Identity unavailable (no BD_ACTOR, git user.name, or USER) → degrade to
     `--all` behavior.
3. **The script formats everything.** `flow-find-leaf` emits a display-ready
   grouped, continuously numbered list (precedent: `flow-task-tree`; models
   mangle formatting). Grouping applies only to `flow:continue` —
   `flow:start`'s tree output is unchanged.
4. **No `--claim`.** It fails on re-claiming one's own task. All assignment
   uses the idempotent explicit form `bd update <id> --status=in_progress -a
   "$(flow-actor)"`. Accepted trade-off: we lose claim's atomic
   race protection; acceptable for an interactive, confirmation-driven flow.
5. **New bin helper `flow-actor`** prints the resolved actor
   (`$BD_ACTOR` → git `user.name` → `$USER`; exit non-zero / empty when none) —
   single identity implementation for skills and `flow-find-leaf`.
6. **Migration.** Existing in_progress tasks have `assignee == null`; they land
   in the Unassigned group, which is visible by default. Selecting one in
   `flow:continue` quietly assigns it to the actor, completing migration over
   time.

## Components

### 1. `plugins/flow/bin/flow-actor` (new)

Prints the actor name resolved via `$BD_ACTOR` → `git config user.name` →
`$USER`. Empty result → exit 1, print nothing.

### 2. `plugins/flow/bin/flow-find-leaf`

- `Task.owner` → `Task.assignee`, normalized: missing/JSON null → `""`
  (removes the dead `iss.get("owner", "")` default noted in the task).
- `get_git_user()` → `get_actor()` implementing the actor chain (same logic as
  `flow-actor`).
- Leaf computation unchanged (in_progress with no in_progress children).
- Selection: without `--all` keep tasks with `assignee == actor` or
  `assignee == ""`; with `--all` keep everything; `actor is None` → same as
  `--all`.
- Output: display-ready grouped list, continuous numbering across groups,
  empty output when no tasks. Line format matches the skill's current display
  format; type letters: bug→`[B]`, feature→`[F]`, task→`[T]`, epic→`[E]`,
  chore→`[C]`; label suffix `| #label` only when a label exists.

```
Мои задачи (artem.vasin):
1. [B] flow:continue per-user filter never matches… (claude-tools-g27) | P2 | #flow

Unassigned:
2. [E] StatusKit (claude-tools-5dl) | P1

ivan.petrov:
3. [F] Some task (claude-tools-xyz) | P2
```

(The third group appears only with `--all`.) Sorting inside a group: priority,
then id — as today.

### 3. `plugins/flow/skills/continue/SKILL.md`

- Arguments: `--all` — "show all users' tasks, grouped by assignee".
- Step 2: same invocation (`bd graph --all --json | flow-find-leaf [--all]`);
  drop "Parse output lines" and the pipe format contract; the script output is
  reproduced verbatim in the reply (plain text; numbering comes from the
  script).
- Step 3: 0/1/N conversational logic stays (0 → current message, 1 → confirm,
  N → select by number or id).
- New sub-step after task selection — assignee handling:
  - `assignee == actor` → no action (fast path stays mutation-free).
  - `assignee == ""` → assign quietly: `bd update <id> -a "$(flow-actor)"`,
    then `bd sync`; report "Назначил задачу на вас".
  - `assignee == other` → ask: "Задача назначена на `{assignee}`. Взять её
    себе? (yes/no)". Yes → reassign + sync; no → continue without changing
    assignee (pair work).
- Update Quick Reference, the "no mutations → no sync" rationalization row
  (sync now happens when assignee changes), and examples.

### 4. `plugins/flow/skills/start/SKILL.md`

Step 7 (Update Task Status):

- Read the task's `assignee` (from the Step 3 `bd show` output).
- `assignee` empty or equals actor →
  `bd update <id> --status=in_progress -a "$(flow-actor)"`.
- `assignee` is someone else → ask: "Задача назначена на `{assignee}`.
  Переназначить на вас? (yes/no)". Yes → same command; no → stop (suggest
  picking another task).
- The "already in_progress" edge case now still runs the update when assignee
  is empty (to backfill assignee); skip only when both status and assignee are
  already correct.

### 5. Tests (`plugins/flow/bin/tests/`)

- `test_flow_find_leaf.py`: rewrite fixtures owner→assignee. Cases: grouping
  and group order (mine/Unassigned/others alphabetical), default vs `--all`
  selection, `$BD_ACTOR` overrides git user.name, no identity → `--all`
  behavior, JSON null assignee → Unassigned, continuous numbering, label
  suffix presence, empty output for no tasks, leaf logic regression.
- `test_flow_actor.py` (new): chain order, empty result exit code.

## Out of scope

- `flow-task-tree` / `flow:start` tree output — unchanged.
- `owner` field anywhere in flow tooling — no longer read.
- Atomic claim races (documented trade-off above).
- Stale `__pycache__` leftovers under `skills/start/scripts/` and
  `skills/starting-task/` (untracked junk, separate cleanup).

## Testing

- `uv run pytest plugins/flow/bin/tests/` — unit tests above.
- Live: `bd graph --all --json | flow-find-leaf` on current data → two groups
  (g27 under "Мои задачи (artem.vasin)", 5dl under "Unassigned"); with a fake
  `BD_ACTOR=ivan.petrov` → g27 visible only with `--all`.
- Live skill pass of `/flow:continue` after merge.
