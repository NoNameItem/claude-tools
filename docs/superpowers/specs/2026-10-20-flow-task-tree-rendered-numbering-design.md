# flow-task-tree — number only what is printed

**Task:** claude-tools-elf.65
**Date:** 2026-10-20
**Status:** design

Mockups: none — the output is terminal text from `plugins/flow/bin/flow-task-tree`; the line
format does not change.

## Problem

`/flow:start` prints the task tree and asks the user to pick a task by its hierarchical number.
The script assigns those numbers before it decides what to print, so a task that is not printed
still consumes a number, a tree connector, a `-n` slot or a `[+N]` count. The numbers still map
to the right tasks, but gaps look like lost tasks: in nuxt-ui-ds three blocked root bugs made the
tree go 1..5, then 9, and the user asked where 6-8 went.

### Reproduction (master `b9d4a30`)

Synthetic graph, all tasks `open`, priority P2 unless noted, input order as listed:

| Task | Parent | Notes |
|---|---|---|
| `r1` | — | |
| `r2-blocked` | — | blocked by `blocker` |
| `r3` | — | |
| `blocker` | — | P3 |
| `r5-last-blocked` | — | P3, blocked by `blocker` |
| `p` (epic) | — | |
| `p-c1` | `p` | |
| `p-c2-blocked` | `p` | blocked by `blocker` |
| `p-c2-gc` | `p-c2-blocked` | |
| `p-c3` | `p` | |

`flow-task-tree` today (`¶` marks the end of an empty last line):

```
**1\. 📋 [T] r1 (r1) | P2 · open**

**3\. 📋 [T] r3 (r3) | P2 · open**

**4\. 📦 [E] p (p) | P2 · open**
├─ **4.1 📋 [T] p-c1 (p-c1) | P2 · open**
└─ **4.3 📋 [T] p-c3 (p-c3) | P2 · open**

5\. 📋 [T] blocker (blocker) | P3 · open
¶
```

Other modes on the same graph:

- `-n 2` prints only `1\. r1`, followed by an empty line.
- `-s r3` prints `3\. r3`.
- `--root p` prints children `1.1` and `1.3`.
- `-s p-c1 --collapse` prints `4\. p … [+3]`, while `-s p-c1` expanded shows one child.

### Symptoms

1. **Root gaps.** `build_tree()` numbers roots with `enumerate(roots)`; `print_tree()` then
   returns `[]` for a root it does not print, and its number is already spent. Mid-list gaps come
   from blocked roots and from roots outside the search set. A closed root never leaves a gap:
   `sort_tasks()` gives any status missing from `STATUS_ORDER` the key `99`, so closed tasks
   always sort after their printed siblings. They only cause symptoms 3, 5 and 6.
2. **`-n N` prints fewer than N roots.** `roots[:limit]` is applied before anything is filtered,
   so hidden roots take slots.
3. **Trailing empty line.** The separator is appended when `not is_last and root_lines`; if the
   last root(s) are hidden, the last printed root still gets a separator after it.
4. **Child gaps.** `print_tree()` keeps a child when `should_show(c) or has_visible_descendants(c)`,
   but the child's own `print_tree()` call prints it only when `should_show(c)` or it is
   `deferred` with visible descendants. A blocked child that is not `deferred` and has open
   descendants passes the first check and fails the second: `4.1, 4.3`. A closed child with open
   descendants fails the same way but sorts last (see symptom 1), so it never leaves a gap, only
   symptoms 5 and 6. The task description says "children are fine"; this case was found during
   design, and the user chose to fix it in the same change (2026-10-20).
5. **Wrong connector.** `is_child_last` is computed over the same list, so `└─` can land on the
   unprinted child and the last printed child gets `├─`. In the reproduction the hidden child is
   in the middle, so the connector happens to look right. With the hidden child last (`p` with
   open `c1`, `c2` and a blocked `c3` that has an open child), `--root p` prints:

   ```
   **1\. 📋 [T] p (p) | P2 · open**
   ├─ **1.1 📋 [T] c1 (c1) | P2 · open**
   ├─ **1.2 📋 [T] c2 (c2) | P2 · open**
   ```
6. **Wrong `[+N]`.** In `--collapse` the count includes the unprinted child, and it is taken
   before the search filter is applied to children.

All six have one cause: the list used for numbers, connectors, separators, `-n` and `[+N]` is not
the list of tasks that get printed.

## Decision

One predicate decides whether a task is printed, and every number, connector, separator, limit
and counter is computed over the list that predicate produces.

`renders(task, search_ids)` is `print_tree()`'s current self-check (lines 244-250), extracted
unchanged:

- a search is active (`search_ids` truthy) and `task.id` is not in it → not printed;
- `should_show(task)` → printed;
- `task.status == "deferred"` and `has_visible_descendants(task)` → printed;
- otherwise → not printed.

`VISIBLE_STATUSES` contains `deferred`, so `should_show()` already accepts every unblocked
deferred task. The third branch is reached only by a **blocked** deferred task.

Because the predicate is the existing check, **the set of printed tasks stays exactly the same**;
only numbering, connectors, separators, `-n` and `[+N]` change.

Expected output on the reproduction graph after the change:

```
**1\. 📋 [T] r1 (r1) | P2 · open**

**2\. 📋 [T] r3 (r3) | P2 · open**

**3\. 📦 [E] p (p) | P2 · open**
├─ **3.1 📋 [T] p-c1 (p-c1) | P2 · open**
└─ **3.2 📋 [T] p-c3 (p-c3) | P2 · open**

4\. 📋 [T] blocker (blocker) | P3 · open
```

No empty line after the last root. Other modes:

- `-n 2` prints `1\. r1` and `2\. r3`, with one empty line between them and none after.
- `-s r3` prints `1\. r3`.
- `--root p` prints children `1.1` (`p-c1`) and `1.2` (`p-c3`).
- `-s p-c1 --collapse` prints `1\. p … [+1]`.

## Non-goals

- **Which tasks are visible.** Today's rules stay exactly as they are (verified on master
  `b9d4a30`):
  - a blocked task that is not `deferred` is hidden together with its subtree;
  - a closed task is hidden together with its subtree;
  - an unblocked `deferred` task is always printed, with or without children;
  - a blocked `deferred` task is printed when it has a `should_show` descendant at any depth, and
    its printable children are printed under it.
- **Two visibility quirks, kept as they are.** Both come from the blocked-deferred branch.
  Changing either changes visibility, so neither is done here. They can be filed as a separate
  task.
  - A blocked `deferred` task with open children is printed with them, although a blocked task is
    otherwise hidden with its subtree.
  - `has_visible_descendants()` looks through unprinted intermediate tasks. So a blocked
    `deferred` task whose only open descendants sit under a blocked or closed child is printed
    with no children under it.
- **Bold.** `find_min_priority()` still runs over every `should_show` task in the input,
  including ones under hidden parents or outside the search set.
- `--root` resolution, search matching (`collect_matching_ids()`), sort order, the line format,
  the "Search … found no tasks" / "Task … not found" / "No tasks match" messages.
- **Skill and docs text.** `flow:start` SKILL.md already says "`-n 10` — limit to first N root
  tasks", which is accurate after the change. No SKILL.md, README or AGENTS.md edits, so the
  skill contract tests are unaffected.

## Design

### 1. `plugins/flow/bin/flow-task-tree`

- **Add `renders(task, search_ids)`** next to `should_show()` / `has_visible_descendants()`.
  Keep the truthiness test on `search_ids` (`if search_ids and …`), as today. An empty set never
  reaches it anyway: `build_tree()` replaces an empty match set with `None` and falls back to the
  full tree.
- **`build_tree()`**: sort the roots, keep only those for which `renders()` is true, then apply
  `-n`, then enumerate for numbers and `is_last`. The separator logic stays
  `not is_last and root_lines`, now over the filtered list.
- **`print_tree()` children**: build the child list once, before the `--collapse` branch, as the
  sorted children for which `renders(c, search_ids)` is true. Use that one list for `[+N]`, for
  `child_number` and for `is_child_last`. The separate post-sort search filter goes away, because
  `renders()` already includes it.
- **`print_tree()` self-check**: replace with `renders(task, search_ids)`. It must stay, because
  the `--root` path calls `print_tree()` on the found task directly, and a hidden `--root`
  target must still produce `[]` (then `main()` prints the existing "No tasks match" message).

### 2. Tests — `plugins/flow/bin/tests/test_flow_task_tree.py`

New test class (e.g. `TestRenderedNumbering`) built from the existing `issue()` / `dep()` /
`make_graph()` helpers plus a `blocks(blocked_id, blocker_id)` helper for `"blocks"` dependencies.
Test first: tests 1-10 must fail on master before the fix. Test 11 pins current behaviour, so
it passes on master by design and must keep passing after the fix.

1. Blocked root between two printed roots → roots numbered `1..k` with no gap.
2. Closed root in the input (it sorts last) → output does not end with an empty line.
3. Search → the first matching root is numbered `1`.
4. `-n N` with a hidden root among the first N → exactly N roots printed (graph has ≥ N
   printable roots).
5. Blocked last root → output does not end with an empty line; exactly one empty line between
   consecutive roots.
6. Blocked child with an open grandchild, between two open children → children `x.1`, `x.2`.
7. Closed child with an open child, next to two open children (it sorts last) → the last printed
   child gets `└─`, and `--collapse` shows `[+2]`.
8. Blocked child with an open grandchild, sorted **last** among siblings → the last printed
   child gets `└─`, the others `├─`.
9. `--collapse` → `[+N]` equals the number of children that would print; under `-s` it equals
   the expanded child count.
10. `--root` → the subtree's children are numbered without gaps.
11. Visibility unchanged → the set of task IDs in the output equals the set master prints today,
    on the reproduction graph and on a graph with:
    - an unblocked `deferred` leaf (printed);
    - a blocked `deferred` task with an open child (both printed);
    - a blocked `deferred` → blocked `open` → `open` chain (only the top task printed);
    - a blocked `open` task with an open child (neither printed).

    The expected sets come from running master, not from the prose above.

Existing tests stay green without edits.

### 3. Release

Commit type `fix(flow)`; release-please bumps the flow patch version. No manual edits to
`plugin.json` versions or the CHANGELOG.

## Acceptance

- On the reproduction graph, the output of each mode matches the "after" blocks in **Decision**
  exactly.
- Run from the worktree, `bd graph --all --json | plugins/flow/bin/flow-task-tree` on this repo
  prints contiguous root and child numbers and no trailing empty line.
- `uv run pytest` from the repo root (all suites) passes; `uv run ruff format` and
  `uv run ruff check` on changed files are clean; `uv run ty check` (pathless) is clean.
- The change cannot be seen through `/flow:start` until the flow plugin is released: skills run
  from the installed plugin cache, not from the worktree. Acceptance is the direct script run
  above.

## Designer's calls

The user decided only the scope: fix children together with roots (2026-10-20). These were
settled during design without asking:

- `renders()` is today's self-check, extracted verbatim, so visibility cannot drift, including
  the two blocked-deferred quirks.
- `print_tree()` keeps the self-check as a guard for the `--root` path.
- Under `-s`, `[+N]` counts the children that would print with the same filter, not all
  unblocked children.
- Closed tasks are tested for what they actually break (trailing empty line, connector, `[+N]`),
  not for gaps they cannot cause. Test 11 is exempt from test-first.

## Left to the builder

- The predicate's exact name and where it sits in the file.
- The fixtures used in each test, beyond the cases listed in **Design §2**.
