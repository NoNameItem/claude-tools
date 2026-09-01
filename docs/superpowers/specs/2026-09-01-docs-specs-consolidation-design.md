# Design: Consolidate specs into docs/superpowers/specs

**Task:** claude-tools-5vg.28
**Date:** 2026-09-01

## Problem

Design specs live in two directories at once: `docs/superpowers/specs/` (48 files, the superpowers
5.x layout) and the legacy `docs/plans/` (41 files). Looking for a spec means checking both, and
`flow-find-doc` resolves "the newest design" across both — so which directory answers depends on
mtime, not on intent.

Implementation plans are the opposite kind of document: scaffolding for one execution run, stale
the moment the branch merges. That policy already holds for the current layout —
`.gitignore` excludes `docs/superpowers/plans/` — but `docs/plans/` predates it and holds plans and
specs mixed together, all committed.

The same split reaches into beads: 37 issues (mostly closed) carry `Design:` and `Plan:` links
under `docs/plans/`. Moving the files without rewriting those links would break the record of what
was designed for past work — the reason to keep specs in git in the first place.

## Classification of the 41 legacy files

Read by document header, not by filename:

- **37 specs** — 35 named `*-design.md`, plus `2026-01-14-statusline-rewrite.md` and
  `2026-01-15-statusline-architecture.md`, whose headers read `… Design` although the filename
  lacks the suffix.
- **4 implementation plans** — `2026-01-27-compact-age-format-plan.md`,
  `2026-01-27-text-coloring-fix.md`, `2026-01-28-telegram-notifications-impl.md`,
  `2026-08-31-review-comments-card-emission-plan.md`. Each opens with `# … Implementation Plan` and
  a `REQUIRED SUB-SKILL: superpowers:executing-plans` directive.

No filename collides with an existing file in `docs/superpowers/specs/`.

## Decisions

**D1. Filenames move unchanged.** The two specs without a `-design` suffix are *not* renamed, even
though every file in the target directory has one. Nothing links to them by name, so a rename buys
cosmetic consistency at the cost of rewriting a path in git history.

**D2. Plans are deleted, not moved.** `git rm`, no replacement under `docs/superpowers/plans/`.
Their content stays recoverable from git history; keeping them tracked contradicts the policy
`.gitignore` already states for the current layout.

**D3. Beads: spec links are rewritten, dead plan links are removed.** For the 37 affected issues:
the 29 paths pointing at specs that move get `docs/plans/` → `docs/superpowers/specs/`; lines of
the form `Plan: docs/plans/<file>` are deleted for the 18 files that do not exist (16 already
deleted before this task, 2 deleted by it). A dangling link is noise in a record whose whole
purpose is to be readable later.

Prose mentions of the `docs/plans/` directory (in `claude-tools-0fu` and `claude-tools-elf.11`) are
edited by hand — dropping a whole line there would break the sentence around it.

**D4. CodeRabbit stops reviewing all of `docs/`.** `.coderabbit.yaml` had
`path_filters: - "!docs/plans/**"`, excluding legacy specs only. It becomes `!docs/**` rather than
`!docs/superpowers/specs/**`: everything under `docs/` is process documentation, and the broader
filter needs no follow-up when the layout shifts again.

**D5. The flow plugin's legacy support is out of scope.** `flow-find-doc`, `after-design`,
`after-plan`, `done`, the plugin README and `test_flow_find_doc.py` deliberately read `docs/plans/`
as well, for third-party pre-v5 projects consuming the plugin. That behaviour is unrelated to this
repository's own layout and is left alone — so `grep -rn "docs/plans"` is expected to keep hitting
`plugins/flow/` after this change.

## Change set

| Target | Change |
|---|---|
| `docs/plans/*-design.md` + 2 unsuffixed specs (37) | `git mv` → `docs/superpowers/specs/` |
| 4 implementation plans | `git rm` |
| `CLAUDE.md` (Project Structure tree) | `docs/plans/` → `docs/superpowers/specs/` |
| `CONTRIBUTING.md` | path to `2026-07-04-flow-remove-askuserquestion-design.md` |
| `.coderabbit.yaml` | `!docs/plans/**` → `!docs/**` |
| 37 beads issues | per D3, then `bd dolt push` |

Beads state is not tracked in git (`.gitignore` excludes `.beads/dolt/`), so the issue edits are a
separate operation from the commit, not part of it.

## Verification

Tests are skipped for this change by explicit decision: no Python is touched, and the one test that
reads a real path under `docs/` (`test_flow_skill_contracts.py:228`) points at a file already in
`docs/superpowers/specs/`.

- `git status` shows 37 renames, 4 deletions, 3 modifications, 1 addition.
- `grep -rn "docs/plans"` hits only `plugins/flow/` (D5) and this document.
- Re-running the beads scan reports 0 issues with `docs/plans/` paths.
- `docs/plans/` is gone; `docs/` keeps `superpowers/` alongside its pre-existing root files.
