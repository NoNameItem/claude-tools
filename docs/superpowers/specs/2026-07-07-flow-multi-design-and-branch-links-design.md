# Flow: multiple designs and branches per task

- **Date:** 2026-07-07
- **Task:** claude-tools-elf.18 — Поддержка нескольких дизайнов и планов в задаче
- **Status:** Design approved

## Problem

A beads task stores exactly one `Design:` link and one `Plan:` link in its
description. `flow-link-doc <task> Design|Plan <path>` replaces the existing line
(or appends if absent), and `flow:after-design` / `flow:after-plan` overwrite it
with the newest document.

When a feature needs rework after review or testing, the follow-up work can be
large enough to warrant its own design. The single-link model then loses history:
a new design silently overwrites the original. A task can also spawn more than one
git branch — when it spans several projects that each need a separate PR (as the
AGENTS.md work did) — and the single `Git:` line cannot hold them.

## Goal

Let one task carry a **history of designs** and a **set of branches**, without
losing the original entries, while keeping plans as the ephemeral single artifact
they already are. Preserve full backward compatibility with existing tasks.

## Non-goals

- Plan history. Plans are ephemeral: linked only to survive a `/clear` between
  writing and executing them, and removed by `flow:done`. There is only ever one
  live plan, so plans stay single-valued.
- Explicit "active/current" markers or migration of existing tasks.
- A structured/serialized links block. Links stay hand-editable plain-text lines.

## Model

Three link kinds, two behaviors:

| Kind       | Multiplicity                     | How a reader resolves "the one to use"          |
|------------|----------------------------------|--------------------------------------------------|
| **Design** | history list (sequential rework) | latest = active (`decompose` uses the newest)    |
| **Git**    | parallel set (one per project/PR)| user picks (`continue` asks when >1)             |
| **Plan**   | single                           | the one plan (unchanged)                         |

Design and Git are both stored as repeating lines; they differ only in how
consumers interpret the list. Design entries are a chronological rework history,
so the newest is the one that matters. Git entries are parallel, independent
workstreams (different projects, different PRs), so there is no "latest" — the
user chooses which branch a session works on.

## Storage format

Links remain plain lines appended to the task `description`. A key may repeat and
may carry an optional parenthesized label:

```
<task body>

Design: docs/superpowers/specs/2026-07-06-design.md
Design (rework): docs/superpowers/specs/2026-07-20-rework-design.md
Design (fixes after review): docs/superpowers/specs/2026-07-25-fixes.md
Git (statuskit): feature/claude-tools-elf.18-statuskit
Git (flow): feature/claude-tools-elf.18-flow
Plan: docs/superpowers/plans/2026-07-20-plan.md
```

One canonical parse rule, shared by every reader and writer:

```
^\s*(Git|Design|Plan)(?:\s*\(([^)]*)\))?:\s*(.+?)\s*$
        key              optional label       value
```

- **Order is chronological** — appends go to the end. "Latest design" is the last
  `Design:` line.
- **Label** is optional free text with no `)` inside; it describes the entry
  (`rework`, `fix review issues`, a project name for a branch).
- **Backward compatible** — an existing bare `Git:` / `Design:` / `Plan:` line is a
  one-element list with no label. No migration needed.

## `flow-link-doc` (writer)

Gains an optional label and a mode. The **default behavior is unchanged**, so
existing callers keep working.

```
flow-link-doc <task-id> <Git|Design|Plan> <value> [--label TEXT] [--append | --replace-latest]
flow-link-doc <task-id> <Git|Design|Plan> ""      # remove all lines of that key
```

| Mode              | Meaning                                                              | Used by                              |
|-------------------|---------------------------------------------------------------------|--------------------------------------|
| *(default)*       | replace the **first** matching line, else append (single-value)     | `after-plan` (Plan)                  |
| `--append`        | append a new line; **no-op if that exact value already exists**      | `after-design` "new", `start` (Git)  |
| `--replace-latest`| replace the **last** matching line (append if none)                 | `after-design` "amend"               |
| value `""`        | remove all lines of that key                                        | `flow:done` (Plan)                   |

Notes:

- Matching for replace/remove ignores the label (matches `Key:` and `Key (…):`).
- With `--label TEXT`, the written line is `Key (TEXT): value`; without it, `Key: value`.
- `--append` dedupes by **value** only. Re-recording an already-present value is a no-op.
- `--append` and `--replace-latest` are mutually exclusive; passing both is an error.

## Skill behavior

| Skill              | Change                                                                                                                                                                                                                             |
|--------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`after-design`** | If Design lines exist and the new path is not already recorded → prompt **"new design (append)"** vs **"amend the latest (replace)"**. Also **propose 2–3 label suggestions inferred from session context** (e.g. `rework`, `fix review issues`); user picks one, types their own, or uses none. Identical path → no-op. Calls `--append` / `--replace-latest` with `--label`. |
| **`flow:start`**   | Records the branch with `--append` (append-if-new; re-recording the current branch is a no-op). May prompt for an optional label when adding a *second* branch to a task.                                                          |
| **`after-plan`**   | Essentially unchanged — Plan stays single (default replace). Parser updated to tolerate an optional label.                                                                                                                        |
| **`flow:continue`**| Parse **all** `Git:` lines. 0 → exit (as today); 1 → auto-checkout (as today); **>1 → list them with labels and ask which to resume**.                                                                                            |
| **`flow:decompose`**| Parse `Design:` lines and use the **latest**; if several exist, mention them.                                                                                                                                                    |
| **`flow:done`**    | Plan handling unchanged (reads/removes `Plan:`). Design and Git history is **preserved** on close — it is the durable record. Parser updated to tolerate an optional label.                                                        |

## `flow-task-card` rendering

- `extract_links` updated to match the optional label and to collect **all**
  `Design:` and `Plan:` lines.
- Multiple designs render numbered, with labels, in the `LINKS` section:

  ```
  LINKS
  Design #1: docs/superpowers/specs/2026-07-06-design.md
  Design #2 (rework): docs/superpowers/specs/2026-07-20-rework-design.md
  Plan: docs/superpowers/plans/2026-07-20-plan.md
  ```

- **Git stays hidden on the card** (unchanged) — branch names are reading-noise on
  the task card. Branches surface only through `flow:continue`.

## Consumers summary

Every reader of link lines moves to the shared parse rule (optional label aware):

- `flow-task-card.extract_links` — collect all Design/Plan, hide Git.
- `flow:continue` — collect all Git, resolve by asking when >1.
- `flow:decompose` — collect all Design, use latest.
- `flow:done` — read/remove Plan (single).

## Testing strategy

- **Scripts (TDD):**
  - `test_flow_link_doc.py` — new modes (`--append` dedupe, `--replace-latest`),
    labels, and backward-compat single-line behavior.
  - `test_flow_task_card.py` — multiple designs, labels, Git still hidden.
- **Skills:** edits follow `superpowers:writing-skills` RED→GREEN per behavioral
  change (after-design prompt + label suggestions, continue multi-branch pick,
  start append-if-new). Mechanical parser-wording edits verify by grep.

## Rollout and backward compatibility

- No data migration. Existing tasks with single bare link lines render and resolve
  identically (list of one, no label).
- `flow-link-doc` default mode is unchanged; only `flow:start` switches its Git
  call to `--append`.
- Bump `plugins/flow/.claude-plugin/plugin.json` version (feature: 3.0.0 → 3.1.0).

## Files touched

- `plugins/flow/bin/flow-link-doc` (+ `tests/test_flow_link_doc.py`)
- `plugins/flow/bin/flow-task-card` (+ `tests/test_flow_task_card.py`)
- `plugins/flow/skills/after-design/SKILL.md`
- `plugins/flow/skills/after-plan/SKILL.md`
- `plugins/flow/skills/start/SKILL.md`
- `plugins/flow/skills/continue/SKILL.md`
- `plugins/flow/skills/decompose/SKILL.md`
- `plugins/flow/skills/done/SKILL.md`
- `plugins/flow/.claude-plugin/plugin.json` (version bump)
- README / format documentation note

## Open questions

None — resolved during design:

- Plan history: not wanted (plans are ephemeral).
- Git list semantics: parallel per-project branches; `continue` asks when >1.
- Design conflict UX: prompt new-vs-amend; Git only appends new branches.
- Storage: bare repeating lines with optional `(label)`; card hides Git.
