# Flow bin/ Helpers — Design

**Task:** claude-tools-uaj — Extract repeated bash snippets from flow skills into `bin/` helpers
**Date:** 2026-05-13 (revised 2026-06-05 after merging master)
**Status:** Approved

> **Revision note (2026-06-05).** Two sibling tasks landed in master after this
> design was approved and are now merged into the work branch:
> - **claude-tools-slg** renamed every flow skill to its short form
>   (`starting-task` → `start`, `linking-design` → `after-design`,
>   `completing-task` → `done`, etc.) and moved the scripts to
>   `skills/start/scripts/`. All skill names and paths below reflect the new layout.
> - **claude-tools-elf.11** made both design/plan doc locations
>   (`docs/superpowers/specs|plans/` and pre-v5 `docs/plans/`) first-class, but
>   implemented the "newest doc across both locations" search as inline bash
>   duplicated in `after-design` and `after-plan`. That fresh duplication is now
>   captured by a new helper (`flow-find-doc`).
>
> Net change from the original spec: the helper set grows from 8 to 10
> (`flow-find-doc`, `flow-worktree-dir` added), and the migration plan uses the
> current skill names.

## Problem

Flow skills (`/flow:start`, `/flow:continue`, `/flow:done`, `/flow:after-design`, `/flow:after-plan`, `/flow:decompose`, plus `init-worktree`, `review-comments`, `sonar-sync`) duplicate bash snippets for common operations:

- Rendering task cards. A Python script `bd-card.py` already exists but lives inside one skill's `scripts/` directory, which misrepresents its scope — it is already called from a sibling skill (`continue`) via an ugly `<skill-base-dir>/../start/scripts/bd-card.py` relative jump.
- Building hierarchical task trees (`bd-tree.py`, same misplacement).
- Finding leaf in-progress tasks (`bd-continue.py`, same misplacement, also called cross-skill from `continue`).
- Computing branch names from task IDs (inline bash in `start`, repeated logic in `continue`).
- Updating description "link lines" (`Git:`, `Design:`, `Plan:`) — currently done inline with HEREDOCs. `start`, `after-design`, and `after-plan` each have a slightly different implementation.
- Finding the newest design/plan doc across **both** the v5+ (`docs/superpowers/specs|plans/`) and pre-v5 (`docs/plans/`) locations — duplicated inline in `after-design` and `after-plan`.
- Detecting "am I in a worktree?" (`pwd | grep "\.worktrees/"`) in `start` and `continue`.
- Computing the worktree directory from a branch name (`.worktrees/$(echo "$branch" | tr '/' '-')`) in `start` and `continue`.
- Extracting the task ID from the current branch name in multiple skills.
- Searching for existing branches matching a task ID across local, remote, and worktrees, with deduplication.

This drifts as skills evolve independently.

## Goals

1. Single source of truth for each helper, accessible to every flow skill by bare name (no relative paths).
2. Tested independently of skill markdown so behavior is verified in isolation.
3. Skill markdown becomes thin orchestration — no significant bash logic inline.
4. Behavior unchanged. Pure refactor — skill UX byte-identical before and after.

## Non-Goals

- Behavior changes of any kind. No new flags, no rephrased prompts, no different option text.
- Replacing trivial commands. `bd sync`, `git branch --show-current`, `bd list --status=in_progress` stay as-is in skill markdown.
- **PR detection** (`gh pr view --json … || NO_PR`, used by `done`, `sonar-sync`, `review-comments`) — considered and excluded. The three callers request different `--json` field sets, so a shared wrapper would only pass the fields through, adding indirection without removing meaningful logic.
- Refactoring the internals of `bd-card.py`, `bd-tree.py`, `bd-continue.py` — only rename and move.
- Migrating to shell scripts. Python is the established convention and stays uniform across all helpers.
- Refactoring `sonar-sync` or `review-comments` beyond the helpers listed below.

## Approach

### Directory Layout

```
plugins/flow/
├── bin/                              # auto-added to PATH per Claude Code plugin convention
│   ├── flow-task-card                # moved + renamed from skills/start/scripts/bd-card.py
│   ├── flow-task-tree                # moved + renamed from skills/start/scripts/bd-tree.py
│   ├── flow-find-leaf                # moved + renamed from skills/start/scripts/bd-continue.py
│   ├── flow-branch-for               # new
│   ├── flow-link-doc                 # new
│   ├── flow-find-doc                 # new
│   ├── flow-current-task             # new
│   ├── flow-in-worktree              # new
│   ├── flow-worktree-dir             # new
│   ├── flow-find-branches            # new
│   └── tests/
│       ├── test_flow_task_card.py
│       ├── test_flow_task_tree.py
│       ├── test_flow_find_leaf.py
│       ├── test_flow_branch_for.py
│       ├── test_flow_link_doc.py
│       ├── test_flow_find_doc.py
│       ├── test_flow_current_task.py
│       ├── test_flow_in_worktree.py
│       ├── test_flow_worktree_dir.py
│       └── test_flow_find_branches.py
└── skills/
    └── */SKILL.md                    # call helpers by bare name (PATH-resolved)
```

### Path Resolution

Per the Claude Code plugin specification, `plugins/<name>/bin/` is automatically added to the Bash tool's `PATH` while the plugin is enabled. Skill markdown therefore calls helpers by bare name:

```bash
bd show <id> --json | flow-task-card
bd graph --all --json | flow-task-tree --root <id>
flow-branch-for <id>
flow-find-doc design
```

No `<skill-base-dir>/...` paths, no `python3` prefixes. Helpers are executable Python files with shebang `#!/usr/bin/env python3`. No `.py` extension on the executable.

### Naming Convention

`flow-<noun>[-<modifier>]`. All helpers carry the `flow-` prefix even when they wrap `bd` operations — they are flow-plugin helpers, not generic beads tooling. This includes the renamed scripts:

| Old name | New name |
|----------|----------|
| `bd-card.py` | `flow-task-card` |
| `bd-tree.py` | `flow-task-tree` |
| `bd-continue.py` | `flow-find-leaf` |

### Helper Specifications

#### flow-task-card

**Input:** stdin = `bd show <id> --json` output (handles both single-object and one-element-array forms).
**Output:** ASCII task box on stdout (the existing `bd-card.py` rendering).
**Exit codes:** 0 on success, 1 on malformed JSON.
**Implementation:** Renamed from `bd-card.py`. No behavior changes.
**Callers:** `start`, `continue`.

#### flow-task-tree

**Input:** stdin = `bd graph --all --json` output.
**Args:**
- `--root <id>` — subtree rooted at task (suffix match allowed)
- `--collapse` — show roots only with `[+N]` child count
- `-n N` — limit to first N root tasks
- `-s TERM` — filter by search term

**Output:** Hierarchical tree on stdout (the existing `bd-tree.py` rendering).
**Implementation:** Renamed from `bd-tree.py`. No behavior changes.
**Callers:** `start`.

#### flow-find-leaf

**Args:** `--status <status>` (defaults to `in_progress`), other args as in current `bd-continue.py`.
**Output:** JSON array of leaf tasks (no open children) at the given status.
**Implementation:** Renamed from `bd-continue.py`. No behavior changes.
**Callers:** `continue`.

#### flow-branch-for

**Input:** task ID as positional arg.
**Algorithm:**
1. Call `bd show <id> --json`, extract `type` and `title`.
2. Map type to prefix:
   - `bug` → `fix/`
   - `chore` → `chore/`
   - `task`, `feature`, `epic` → `feature/`
   - unknown → `feature/` with warning to stderr
3. Compute brief name: lowercase title, replace non-alphanumeric with `-`, collapse repeated `-`, strip leading/trailing `-`, truncate to ~5 words.
4. Print `{prefix}{task-id}-{brief-name}` on stdout.

**Exit codes:** 0 on success, 1 if task not found, 2 if `bd` errored.
**Callers:** `start`.

#### flow-link-doc

**Synopsis:** `flow-link-doc <task-id> <key> <value>`
**Keys (allowlist):** `Git`, `Design`, `Plan`.
**Algorithm:**
1. Call `bd show <id> --json`, extract description.
2. Regex find `^{key}:.*$` (multiline). If present, replace; if absent, append after a blank line.
3. Call `bd update <id> --description "..."`.

**Exit codes:** 0 on success, 1 if key not in allowlist, 2 if task not found.
**Callers:** `start` (Git), `after-design` (Design), `after-plan` (Plan).

**Why centralize:** today three skills implement this with subtly different HEREDOCs. One helper, one regex, one tested behavior.

**Open question for the plan phase:** `done` currently strips the `Plan:` link from the description when cleaning up a completed task. Confirm during planning whether that is a true description rewrite (in which case `flow-link-doc` gains a `remove`/empty-value mode) or whether `done` only deletes the local plan file and leaves the link. Pick one and make it explicit in the plan; do not expand `flow-link-doc`'s contract speculatively.

#### flow-find-doc

**Synopsis:** `flow-find-doc design|plan`
**Algorithm:** glob the relevant location pair and print the single newest `.md` by mtime:
- `design` → newest of `docs/superpowers/specs/*.md` + `docs/plans/*.md`
- `plan` → newest of `docs/superpowers/plans/*.md` + `docs/plans/*.md`

**Output:** the path of the newest matching file on stdout, or nothing if none exist.
**Exit codes:** 0 always (empty output = no doc found), 1 if the kind arg is not `design`/`plan`.
**Callers:** `after-design` (design), `after-plan` (plan). Pairs with `flow-link-doc`: find the path, then write the `Design:`/`Plan:` link.

**Why centralize:** `claude-tools-elf.11` established that both doc locations are first-class but left the dual-location search copy-pasted in two skills. This helper makes the location list a single source of truth — a future doc location is added once, not in every path-aware skill.

**Boundary:** purely mtime-based glob; it makes **no** assumption about the host repo's `.gitignore`. `done`'s plan-cleanup keeps its own `git ls-files --others --modified -- docs/plans/ docs/superpowers/plans/` detection and does **not** use this helper — that path needs git's untracked/modified semantics, which are a different concern.

#### flow-current-task

**Input:** none. Reads `git branch --show-current` internally.
**Algorithm:** match against `^(fix|chore|feature|docs)/([a-z0-9-]+-[a-z0-9]+(?:\.[0-9]+)*)(-.*)?$`. Print the captured task ID. Print nothing if no match.
**Exit codes:** 0 always (empty output = "not on a task branch"). Exit 1 only on git error.
**Callers:** skills that derive a task ID from the branch — to be enumerated exactly in the implementation plan (candidates: `done`, `continue`, `review-comments`, `sonar-sync`, and `start`'s auto-resolve check).

#### flow-in-worktree

**Input:** none.
**Algorithm:** check if `pwd` contains `/.worktrees/`.
**Exit codes:** 0 if in worktree, 1 if not. No stdout/stderr.
**Callers:** `start`, `continue`.

#### flow-worktree-dir

**Synopsis:** `flow-worktree-dir <branch-name>`
**Algorithm:** print `.worktrees/<branch-name with '/' replaced by '-'>`.
**Exit codes:** 0 on success, 1 if no branch arg given.
**Callers:** `start`, `continue`. Mirrors the existing inline `WORKTREE_DIR=".worktrees/$(echo '<branch>' | tr '/' '-')"`.

#### flow-find-branches

**Synopsis:** `flow-find-branches <task-id>`
**Algorithm:**
1. Run `git branch -a` and filter lines containing the task ID with a prefix-aware regex (`(fix|chore|feature|docs)/<task-id>`).
2. Run `git worktree list --porcelain` and find branches whose worktree path or branch ref matches the same pattern.
3. Deduplicate: same branch in local + remote → emit once with `location=local`. Worktree presence is an additional fact.
4. Output one branch per line: `<branch-name>\t<location>` where location ∈ {`local`, `remote`, `worktree`}.

**Exit codes:** 0 always (empty output = no matches). Exit 1 only on git error.
**Callers:** `start`.

### Testing Strategy

- Test framework: pytest, run via `uv run pytest plugins/flow/bin/tests/`.
- Per-helper test file: `tests/test_flow_<name>.py`.
- **stdin/stdout helpers** (`flow-task-card`, `flow-task-tree`, `flow-find-leaf`): feed fixed JSON, capture stdout/stderr, assert on output. Reuse existing test fixtures from `test_bd_card.py`, `test_bd_tree.py`, `test_bd_continue.py` — these tests come along with the rename.
- **git-aware helpers** (`flow-current-task`, `flow-in-worktree`, `flow-find-branches`): use `tmp_path` + `subprocess.run(..., cwd=tmp_path)`. Initialize a temp git repo and create the conditions under test.
- **filesystem helper** (`flow-find-doc`): use `tmp_path` with the two location dirs populated, set distinct mtimes, assert the newest path wins and that an empty tree prints nothing. No git needed.
- **pure-string helper** (`flow-worktree-dir`): assert the slash→hyphen mapping directly; no fixtures.
- **bd-dependent helpers** (`flow-branch-for`, `flow-link-doc`): use a `BD_BIN` env var pointing to a fake `bd` shell script in `tests/fixtures/`. The fake `bd` reads expected args, prints the canned JSON response.

### Migration Plan

Each commit migrates one logical unit and runs the full pre-commit checks (`uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, `uv run pytest plugins/flow/bin/tests/`).

The exact per-skill call sites and line numbers are enumerated in the implementation plan (writing-plans phase), not here — the skill renames shifted every line number, so binding them in the design would invite drift. The steps below give the unit-of-work boundaries.

1. **Setup:** Create `plugins/flow/bin/` with the three renamed scripts (`flow-task-card`, `flow-task-tree`, `flow-find-leaf`) + their renamed tests in `bin/tests/`. Update callers in `start/SKILL.md` and `continue/SKILL.md` (this removes the cross-skill `../start/scripts/...` jump) to call by bare name. Delete `skills/start/scripts/`.
2. **flow-branch-for:** New helper + tests. Migrate `start`.
3. **flow-link-doc:** New helper + tests. Migrate `start` (Git line), `after-design` (Design line), `after-plan` (Plan line). Resolve the `done` Plan-removal question noted in the helper spec.
4. **flow-find-doc:** New helper + tests. Migrate `after-design` and `after-plan` (replace the inline dual-location `ls -t … | head -1`).
5. **flow-current-task:** New helper + tests. Migrate the confirmed callers.
6. **flow-in-worktree:** New helper + tests. Migrate `start`, `continue`.
7. **flow-worktree-dir:** New helper + tests. Migrate `start`, `continue`.
8. **flow-find-branches:** New helper + tests. Migrate `start`.
9. **Docs:** Update `plugins/flow/README.md` to describe the `bin/` directory and how to add new helpers.

**Acceptance per migration commit:** the skill markdown contains zero significant bash logic for that pattern (only the helper invocation). Manual smoke test of the affected `/flow:*` command shows identical UX.

### Risk and Mitigations

| Risk | Mitigation |
|------|------------|
| Skill markdown becomes harder to read | Bare-name calls are shorter than the current `<skill-base-dir>/scripts/...` references. Reading improves. |
| Helper signature drift breaks all dependent skills | Tests are co-located. Pre-commit runs them. CI runs them. |
| Plugin loader fails to add `bin/` to PATH | Validated in the setup commit by running `which flow-task-card` from a skill context before relying on bare names. If it fails, fall back to `<skill-base-dir>/../../bin/flow-task-card` in skill markdown (documented in `plugins/flow/README.md`). |
| Existing tests fail after rename | Tests are renamed alongside scripts in the same commit; pytest is run as part of the commit checklist. |
| `flow-find-doc` and `done`'s plan cleanup diverge on location handling | They are intentionally separate: `flow-find-doc` is mtime-based for the "newest existing doc" case; `done` uses git untracked/modified detection for the "safe to delete" case. The design records this boundary so neither is "fixed" to match the other. |

## Done When

- All ten helpers exist in `plugins/flow/bin/` with passing tests.
- `plugins/flow/skills/start/scripts/` deleted.
- All flow skills that previously had duplicated bash now delegate to a helper. No skill contains an inline branch-name computation, link-line update, dual-location doc search, worktree check, worktree-dir computation, or current-task extraction.
- `uv run pytest plugins/flow/bin/tests/` passes.
- Manual smoke test of `/flow:start`, `/flow:continue`, `/flow:done`, `/flow:after-design`, `/flow:after-plan`, `/flow:decompose` shows no UX regression.
- `plugins/flow/README.md` documents the `bin/` directory.
