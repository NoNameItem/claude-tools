# Align flow plugin with superpowers 5.x paths & command names

**Date:** 2026-06-05
**Task:** claude-tools-elf.11
**Status:** Design approved

## Problem

Superpowers 5.x changed where design and plan documents live. The flow plugin
still assumes the old `docs/plans/` location throughout its skills, README, and
test fixtures. The original task framed this as four concerns; an audit of the
plugin against the installed superpowers 5.1.0 shows only two are real.

## Audit findings

| Concern (from task) | Reality in flow plugin |
|---|---|
| 1. Spec/plan paths moved | **Real & large.** ~43 references to `docs/plans/` across README, 5 skills, and `test_bd_card.py`. New layout confirmed: designs → `docs/superpowers/specs/`, plans → `docs/superpowers/plans/`. |
| 2. Review Loops removed | **No-op.** Flow never references spec/plan review loops. |
| 3. Subagent-driven mandatory | **No-op, and premise is stale.** Flow never documents an execution-mode choice. superpowers 5.1.0 `writing-plans` still offers "Two execution options," so the "now mandatory" claim does not hold for the installed version. |
| 4. Legacy slash commands | **Real, but mis-described.** Flow does not use `/brainstorm` etc. Its README uses `/superpowers:brainstorm`, `/superpowers:write-plan`, `/superpowers:execute-plan` — old short names that should be the current skill names. |

Supporting context confirmed during the audit:

- This repo runs **both layouts at once**: `docs/plans/` holds 40 historical
  design + plan files (committed); `docs/superpowers/specs/` is the new home;
  `.gitignore` already ignores `docs/superpowers/plans/` (plans stay local).
- `decompose` runs `git add docs/plans/...` to commit a design doc with the
  decomposition appended — that file is a spec, so it moves to
  `docs/superpowers/specs/`.

## Decisions

1. **Scope:** concern #1 (paths) + reframed #4 (README command names). Drop #2
   and #3 as no-ops; record the reasoning in the task's closing comment.
2. **Backwards compatibility:** `after-design` / `after-plan` search **both**
   new and old paths and let the newest file (by mtime) win. New work always
   lands in the new path and wins; a stray old file is still found.
3. **Labels unchanged:** task-description links stay `Design:` and `Plan:`.
   Files are still named `*-design.md`; existing linked tasks keep working; the
   card script and `decompose` parsing stay untouched. Only paths change.

## Path mapping

| Artifact | Old | New |
|---|---|---|
| Design / spec docs | `docs/plans/` | `docs/superpowers/specs/` (committed) |
| Implementation plans | `docs/plans/` | `docs/superpowers/plans/` (gitignored, local-only) |

## Per-skill changes

### after-design (`plugins/flow/skills/after-design/SKILL.md`)
- Search newest design across **both** `docs/superpowers/specs/*.md` and
  `docs/plans/*.md` (e.g. `ls -t docs/superpowers/specs/*.md docs/plans/*.md
  2>/dev/null | head -1`).
- Save the `Design:` link pointing at whatever path the chosen file lives in.
- Update the box mockup and every example path.
- Occurrences to revise: lines 24, 39, 64, 67, 88, 95, 185, 205, 225, 227, 234,
  237, 238.

### after-plan (`plugins/flow/skills/after-plan/SKILL.md`)
- Same dual-glob over `docs/superpowers/plans/*.md` + `docs/plans/*.md`.
- Save the `Plan:` link to the chosen file's path.
- Update mockup and examples.
- Occurrences to revise: lines 22, 37, 62, 65, 86, 93, 207, 239, 267, 269, 275,
  284, 287, 288.

### done (`plugins/flow/skills/done/SKILL.md`)
- Local-plan cleanup targets **only** `docs/superpowers/plans/` (gitignored,
  local-only). It must **not** touch `docs/plans/` — those files are committed
  history and must never be deleted.
- Keep the dual detection: plan linked in the description **OR** an untracked
  local plan file.
- Impl note for the plan phase: the `git ls-files` listing must surface
  gitignored files in `docs/superpowers/plans/` (the default `--others` excludes
  ignored paths unless told otherwise) — verify the exact invocation when
  implementing.
- Occurrences to revise: lines 109, 113, 288, 351, 424, 428, 437, 470, 473, 493,
  677, 680, 689.

### decompose (`plugins/flow/skills/decompose/SKILL.md`)
- `git add docs/plans/...` → `git add docs/superpowers/specs/...` (the
  decomposition is appended to the committed design/spec doc).
- Update the `Design: docs/plans/...` parse example (line 43) and the `git add`
  example (line 190).

### test_bd_card.py (`plugins/flow/skills/start/scripts/test_bd_card.py`)
- Update the 3 fixture example paths (lines 160, 231, 351) to the new layout.
  Cosmetic — the card script extracts any `Design:`/`Plan:` line regardless of
  path, so tests stay green; this just keeps examples current.

## README.md (`plugins/flow/README.md`)
- Path examples (lines 38–39, 145, 165) → `docs/superpowers/specs/` (design) and
  `docs/superpowers/plans/` (plan).
- Command names (lines 52, 55, 77, 86, 94, 147, 167):
  - `/superpowers:brainstorm` → `superpowers:brainstorming`
  - `/superpowers:write-plan` → `superpowers:writing-plans`
  - `/superpowers:execute-plan` → `superpowers:executing-plans`
  - Drop the leading slash; use current skill names, matching how
    `after-plan`'s frontmatter and the superpowers skills cross-reference each
    other.

## Out of scope

Concerns #2 (review loops) and #3 (subagent-driven choice) have zero references
in the flow plugin and require no changes. Record this on the task at close so
the reasoning is preserved.

## Verification

No runtime logic changes (only skill content + test fixtures), so TDD does not
apply. Verify by:

- `uv run pytest` on the flow scripts stays green after fixture edits.
- `grep -rn "docs/plans/" plugins/flow/` → only the intentional
  backwards-compat globs remain.
- `grep -rn "/superpowers:" plugins/flow/README.md` → empty.
- Read-through of each edited skill for residual `docs/plans/` assumptions.
