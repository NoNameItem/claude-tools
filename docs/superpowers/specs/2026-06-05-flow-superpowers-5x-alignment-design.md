# Align flow plugin with superpowers 5.x paths & command names

**Date:** 2026-06-05
**Task:** claude-tools-elf.11
**Status:** Design approved

## Problem

Superpowers 5.x added a new home for design and plan documents
(`docs/superpowers/specs/` and `docs/superpowers/plans/`). The flow plugin still
assumes the pre-v5 `docs/plans/` location throughout its skills, README, and test
fixtures. The original task framed this as four concerns; an audit of the plugin
against the installed superpowers 5.1.0 shows only two are real.

## Audit findings

| Concern (from task) | Reality in flow plugin |
|---|---|
| 1. Spec/plan paths moved | **Real & large.** ~43 references to `docs/plans/` across README, 5 skills, and `test_bd_card.py`. New layout confirmed: designs → `docs/superpowers/specs/`, plans → `docs/superpowers/plans/`. |
| 2. Review Loops removed | **No-op.** Flow never references spec/plan review loops. |
| 3. Subagent-driven mandatory | **No-op, and premise is stale.** Flow never documents an execution-mode choice. superpowers 5.1.0 `writing-plans` still offers "Two execution options," so the "now mandatory" claim does not hold for the installed version. |
| 4. Legacy slash commands | **Real, but mis-described.** Flow does not use `/brainstorm` etc. Its README uses `/superpowers:brainstorm`, `/superpowers:write-plan`, `/superpowers:execute-plan` — old short names that should be the current skill names (slash kept). |

## Core principle: both locations are first-class

`docs/plans/` is **not** legacy to be phased out. Projects that adopted
superpowers before v5 may continue saving designs and plans there; projects on
v5+ use `docs/superpowers/specs/` and `docs/superpowers/plans/`. Every
path-aware flow skill must support **both** locations as first-class, both for
finding existing files and going forward.

**The flow plugin is distributed to arbitrary repos.** It must not assume the
host project's `.gitignore` — e.g. it cannot assume `docs/superpowers/plans/` is
ignored or that `docs/plans/` is committed. Where a skill needs to know whether
a file is "local, not yet committed" (the `done` cleanup), it relies on git's
own untracked/modified detection, never on a hardcoded directory convention.

*(This repo happens to ignore `docs/superpowers/plans/` and commit specs to
`docs/superpowers/specs/`, but that is one project's convention and the skills
must not depend on it.)*

## Decisions

1. **Scope:** concern #1 (paths) + reframed #4 (README command names, slash
   kept). Drop #2 and #3 as no-ops; record the reasoning in the task's closing
   comment.
2. **Dual-location search:** `after-design` / `after-plan` search **both** the
   new and old directories and let the newest file (by mtime) win. `done`'s
   cleanup searches **both** directories too, relying on git's untracked/modified
   filter for safety. `decompose` operates on whatever path the task's `Design:`
   link points to.
3. **Labels unchanged:** task-description links stay `Design:` and `Plan:`.
   Files are still named `*-design.md`; existing linked tasks keep working; the
   card script and `decompose` parsing stay untouched. Only the directories the
   skills look in change.

## Path mapping

| Artifact | Pre-v5 location | v5+ location |
|---|---|---|
| Design / spec docs | `docs/plans/` | `docs/superpowers/specs/` |
| Implementation plans | `docs/plans/` | `docs/superpowers/plans/` |

Both remain supported; skills search both.

## Per-skill changes

### after-design (`plugins/flow/skills/after-design/SKILL.md`)
- Find newest design across **both** locations, newest by mtime wins:
  `ls -t docs/superpowers/specs/*.md docs/plans/*.md 2>/dev/null | head -1`.
- Save the `Design:` link pointing at whatever path the chosen file lives in.
- Update the box mockup and every example path (show `docs/superpowers/specs/`
  as the v5+ example, but the instruction text must name both locations).
- Occurrences to revise: lines 24, 39, 64, 67, 88, 95, 185, 205, 225, 227, 234,
  237, 238.

### after-plan (`plugins/flow/skills/after-plan/SKILL.md`)
- Same dual search over `docs/superpowers/plans/*.md` + `docs/plans/*.md`,
  newest wins.
- Save the `Plan:` link to the chosen file's path.
- Update mockup and examples; instruction text names both locations.
- Occurrences to revise: lines 22, 37, 62, 65, 86, 93, 207, 239, 267, 269, 275,
  284, 287, 288.

### done (`plugins/flow/skills/done/SKILL.md`)
- Local-plan cleanup searches **both** `docs/plans/` and
  `docs/superpowers/plans/` for the local plan file.
- Safety comes from git's untracked/modified detection — not from any gitignore
  assumption — so committed files are never blindly deleted:
  `git ls-files --others --modified -- docs/plans/ docs/superpowers/plans/`.
  - Impl note for the plan phase: do **not** add `--exclude-standard`, or
    gitignored plan files (in repos that ignore the plans dir) won't be
    surfaced. Verify the exact invocation when implementing.
- Keep the dual detection: plan linked in the description **OR** a local plan
  file found by the search above.
- Occurrences to revise: lines 109, 113, 288, 351, 424, 428, 437, 470, 473, 493,
  677, 680, 689.

### decompose (`plugins/flow/skills/decompose/SKILL.md`)
- `git add` the design doc at the path the task's `Design:` link points to
  (which may be under `docs/plans/` or `docs/superpowers/specs/`) — do not
  hardcode a directory. Update the `git add docs/plans/...` example (line 190) to
  use the linked path; show `docs/superpowers/specs/` as the v5+ example.
- Update the `Design: docs/plans/...` parse example (line 43); parsing stays
  path-agnostic.

### test_bd_card.py (`plugins/flow/skills/start/scripts/test_bd_card.py`)
- Update the 3 fixture example paths (lines 160, 231, 351) to the v5+ layout.
  Cosmetic — the card script extracts any `Design:`/`Plan:` line regardless of
  path, so tests stay green; this just keeps examples current.

## README.md (`plugins/flow/README.md`)
- Path examples (lines 38–39, 145, 165): show the v5+ dirs, and mention that
  pre-v5 projects may still use `docs/plans/`.
- Command names (lines 52, 55, 77, 86, 94, 147, 167) — **keep the leading
  slash**, correct the names to the current skills:
  - `/superpowers:brainstorm` → `/superpowers:brainstorming`
  - `/superpowers:write-plan` → `/superpowers:writing-plans`
  - `/superpowers:execute-plan` → `/superpowers:executing-plans`

## Out of scope

Concerns #2 (review loops) and #3 (subagent-driven choice) have zero references
in the flow plugin and require no changes. Record this on the task at close so
the reasoning is preserved.

## Verification

No runtime logic changes (only skill content + test fixtures), so TDD does not
apply. Verify by:

- `uv run pytest` on the flow scripts stays green after fixture edits.
- `grep -rn "docs/plans/" plugins/flow/` → every remaining hit is part of an
  intentional dual-location search or example, never a sole/hardcoded path.
- `grep -rn "/superpowers:" plugins/flow/README.md` → only the corrected
  `brainstorming` / `writing-plans` / `executing-plans` forms (slash kept).
- Read-through of each edited skill for residual single-location assumptions.
