# Design: Audit flow skills & drop legacy command wrappers

**Task:** claude-tools-slg
**Date:** 2026-06-03

## Problem

Flow ships two parallel discovery surfaces:

- `plugins/flow/commands/*.md` — 8 thin slash-command wrappers
- `plugins/flow/skills/*/SKILL.md` — 9 skill directories (one, `init-worktree`, is an internal helper with no command)

Each command file is a pure forwarder (frontmatter `description` + "Invoke the `flow:X` skill"). Because Claude Code already surfaces plugin skills in the slash menu as `/flow:<skill-name>`, both surfaces appear today — e.g. `/flow:start` (command) **and** `/flow:starting-task` (skill). This 1:1 duplication is the same legacy pattern superpowers removed in 5.1.0, retained from when skill triggering was unreliable.

## Goal

Collapse to a single discovery surface (skills only), invoked by short names (`/flow:start`, `/flow:done`, …), with audited frontmatter. Users keep typing the same short commands; they now resolve to the skill instead of a wrapper.

This is a structural cleanup + frontmatter polish task. **No behavior changes** to what the skills do.

## Decisions

- **Naming:** rename skill directories to the short imperative forms (the current command names). `/flow:start`, `/flow:done`, etc. keep working because they resolve to the renamed skill.
- **`init-worktree`:** kept as-is — internal helper, no command, already imperative.
- **`docs/plans/*`:** left untouched — dated historical design records; a separate task (`claude-tools-0fu`) migrates them.
- **Oversized-skill splitting:** deferred to a follow-up beads task under the Flow epic (`claude-tools-elf`).
- **Frontmatter depth:** rewrite descriptions + add `allowed-tools` per skill + ~~`disable-model-invocation` on `init-worktree`~~ *(superseded — see Correction)*. No `!command` injection.

## Verified facts (Claude Code skills spec)

- Required frontmatter: `name`, `description`.
- `disable-model-invocation: true` — blocks model auto-invocation, keeps explicit user `/` invocation.
- `allowed-tools` — **space-separated string**; supports scoped Bash patterns like `Bash(git:*)`, `Bash(bd:*)`.
- Plugin skills auto-surface as `/flow:<skill-name>` without a `commands/` file.
- User-typed arguments reach the skill via the `$ARGUMENTS` placeholder.

## Part A — Remove `commands/`, rename skills

Delete `plugins/flow/commands/` (all 8 wrappers). Rename the 8 user-facing skill directories **and** their `name:` frontmatter:

| Old skill dir / name | New dir / name | `/` invocation (unchanged for users) |
|----------------------|----------------|--------------------------------------|
| `starting-task`      | `start`        | `/flow:start`          |
| `completing-task`    | `done`         | `/flow:done`           |
| `continue-issue`     | `continue`     | `/flow:continue`       |
| `decomposing-task`   | `decompose`    | `/flow:decompose`      |
| `linking-design`     | `after-design` | `/flow:after-design`   |
| `linking-plan`       | `after-plan`   | `/flow:after-plan`     |
| `reviewing-comments` | `review-comments` | `/flow:review-comments` |
| `syncing-sonarcloud` | `sonar-sync`   | `/flow:sonar-sync`     |
| `init-worktree`      | *(unchanged)*  | — (internal helper)    |

### Cross-reference fixes

The only path that breaks on rename:

- **`continue` borrows scripts from `start`.** It references `bd-card.py` / `bd-continue.py` via the hard-coded path `<skill-base-dir>/../starting-task/scripts/…` (3 occurrences). Update to `<skill-base-dir>/../start/scripts/…`.
- **`start`'s own scripts** use `<skill-base-dir>/scripts/…` (placeholder-relative) — survive the rename untouched.
- **`init-worktree` references** (4× in `start`, 2× in `continue`) — unchanged, since the name is kept.
- **Body skill-name references:** any `flow:<gerund>` mention in skill bodies updated to the new name. `flow:init-worktree` references stay.
- **Scripts stay in `start/scripts/`** — no move.
- **Optional cosmetic:** test fixture string `"…flow:starting-task"` in `start/scripts/test_bd_card.py:341` updated to `flow:start` for accuracy (test input data only; no logic impact).

### Net effect for users

`/flow:start`, `/flow:done`, etc. keep working — now backed by the skill. The gerund forms (`/flow:starting-task`, …) disappear. Breaking only for anyone who scripted the gerund skill names; documented in the changelog.

## Part B — Frontmatter audit (per skill)

1. **Descriptions** — rewrite each to a "short *what* + explicit *Use when [triggers]*" pattern, so one description serves both the `/` menu display and model auto-discovery.
2. **`allowed-tools`** — add per skill, derived from each skill's actual tool usage:
   - Baseline for bd/git skills: `Bash(bd:*) Bash(git:*) Bash(python3:*)` plus the structured tools each uses (`Skill`, `AskUserQuestion`, `Read`, `TodoWrite`).
   - `review-comments`: add `Bash(gh:*)`.
   - `sonar-sync`: add `Bash(gh:*)` and the SonarQube MCP tools it calls.
   - `after-design` / `after-plan`: minimal — `Bash(bd:*)` (and `Read` if used).
   - Exact per-skill lists are determined during implementation by reading each skill's commands.
3. ~~**`disable-model-invocation: true`** — on `init-worktree` **only** (pure sub-step that should never auto-fire)~~ *(superseded — see Correction: `init-worktree` does NOT get this flag; it would block the Skill-tool sub-invocation `start`/`continue` rely on)*. All user-facing skills keep model-invocation on.
4. **Not doing — `!command` injection.** It would conflict with the STOP-AND-READ command sequencing every flow skill relies on (skills explicitly order *when* to run `bd`/`git`). Rationale recorded here so it isn't re-proposed.

## Part C — Argument handling (port real logic before deleting wrappers)

Four wrappers carry argument-passing notes — the only non-forwarding content in `commands/`. Port them into the skills using the `$ARGUMENTS` placeholder so behavior is preserved:

| Skill            | `$ARGUMENTS` maps to            |
|------------------|---------------------------------|
| `start`          | `--root <task-id>`              |
| `continue`       | `<task-id>` / `--all`           |
| `review-comments`| PR number                       |
| `sonar-sync`     | project key / `--pr <id>`       |

The "do NOT run commands before invoking" guards need no porting — the skill body **is** the entry point now, so it is read first by definition.

`after-design`, `after-plan`, `decompose`, `done` take no arguments.

## Part D — Docs

- **Root `CLAUDE.md`** — update the `/flow:*` command list, the intro sentence (lines ~12–13), and the `skills/ # /flow:* commands` structure comment (line ~60). Describe them as skills.
- **`plugins/flow/README.md`** — short forms stay valid; light terminology pass ("command" → "skill" where it misleads). No structural rewrite.
- **`docs/plans/*`** — left untouched (historical records; separate migration task `claude-tools-0fu`).
- **`CHANGELOG.md`** — not hand-edited; release tooling generates it from conventional commits. The rename rides in via commit messages.

## Out of scope → follow-up task

Split the 4 oversized skills into `references/` sibling files (current line counts: `done` 778, `review-comments` 708, `start` 650, `sonar-sync` 638; guideline ≈500). File a **new beads task under the Flow epic (`claude-tools-elf`)**. Independently valuable, higher regression risk, gets its own focused review.

## Verification

- `ruff format` / `ruff check` on any touched `.py` (only the test fixture string, if updated).
- Grep proves zero live references to old gerund skill names (excluding `docs/plans/`).
- Smoke test: the `/` menu shows the 8 short flow entries; `init-worktree` is hidden from model auto-invocation but still invocable as a sub-step; each entry's skill loads and runs end-to-end.

## Done when

- `plugins/flow/commands/` removed; the arg-passing logic from its 4 wrappers ported into the matching skills.
- 8 skill directories + `name:` frontmatter renamed to short forms; `init-worktree` unchanged.
- Cross-references and script paths fixed; no broken `flow:*` references.
- Every skill's frontmatter passes the audit (description pattern, `allowed-tools`, `disable-model-invocation` on `init-worktree`).
- Root `CLAUDE.md` and `plugins/flow/README.md` accurately describe flow as skills.
- Follow-up task filed for splitting oversized skills.
- Smoke test passes.

## Correction (during planning, 2026-06-03)

Verifying the Claude Code skills spec while writing the implementation plan surfaced corrections to the decisions above. These supersede the conflicting points (notably Part B item 3 and the `disable-model-invocation` references in "Verification" / "Done when"):

- **`init-worktree` does NOT get `disable-model-invocation: true`.** That field blocks Skill-tool invocation from *other* skills (not just autonomous auto-fire), which would break the calls `start`/`continue` make to `init-worktree` and silently disable worktree initialization. Instead, `init-worktree`'s description is reworded to mark it an internal sub-step ("not for direct use; called by flow:start/continue") — this discourages auto-fire without breaking sub-invocation. Confirmed with the user.
- **`allowed-tools` is pre-authorization, not restriction.** Listing a subset never blocks a skill; it only avoids permission prompts. The subagent-dispatch tool is named `Agent` (formerly `Task`).
- **Part C (port arg logic) was a no-op.** All four arg-taking skills (`start`, `continue`, `review-comments`, `sonar-sync`) already handle their arguments in-body, so deleting `commands/` lost no behavior — Part C reduced to verification.
- **Oversized-skill split follow-up filed as `claude-tools-elf.13`.**
