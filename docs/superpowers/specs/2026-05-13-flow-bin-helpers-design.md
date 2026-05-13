# Flow bin/ Helpers — Design

**Task:** claude-tools-uaj — Extract repeated bash snippets from flow skills into `bin/` helpers
**Date:** 2026-05-13
**Status:** Approved

## Problem

Flow skills (`/flow:start`, `/flow:continue`, `/flow:done`, `/flow:after-design`, `/flow:after-plan`, `/flow:decompose`, plus `init-worktree`, `reviewing-comments`, `syncing-sonarcloud`) duplicate bash snippets for common operations:

- Rendering task cards. A Python script `bd-card.py` already exists but lives inside one skill's `scripts/` directory, which misrepresents its scope — it is already called from a sibling skill via an ugly `<skill-base-dir>/../starting-task/scripts/bd-card.py` relative jump.
- Building hierarchical task trees (`bd-tree.py`, same misplacement).
- Finding leaf in-progress tasks (`bd-continue.py`, same misplacement).
- Computing branch names from task IDs (inline bash in `starting-task`, repeated logic in `continue-issue`).
- Updating description "link lines" (`Git:`, `Design:`, `Plan:`) — currently done inline with HEREDOCs. `starting-task`, `linking-design`, and `linking-plan` each have a slightly different implementation.
- Detecting "am I in a worktree?" (`pwd | grep "\.worktrees/"`) in four skills.
- Extracting task ID from current branch name in three skills.
- Searching for existing branches matching a task ID across local, remote, and worktrees, with deduplication.

This drifts as skills evolve independently.

## Goals

1. Single source of truth for each helper, accessible to every flow skill by bare name (no relative paths).
2. Tested independently of skill markdown so behavior is verified in isolation.
3. Skill markdown becomes thin orchestration — no significant bash logic inline.
4. Behavior unchanged. Pure refactor — skill UX byte-identical before and after.

## Non-Goals

- Behavior changes of any kind. No new flags, no rephrased prompts, no different option text.
- Replacing trivial commands. `bd sync` and `git branch --show-current` stay as-is in skill markdown.
- Refactoring the internals of `bd-card.py`, `bd-tree.py`, `bd-continue.py` — only rename and move.
- Migrating to shell scripts. Python is the established convention and stays uniform across all helpers.
- Refactoring `syncing-sonarcloud` or `reviewing-comments` beyond the helpers listed below.

## Approach

### Directory Layout

```
plugins/flow/
├── bin/                              # auto-added to PATH per Claude Code plugin convention
│   ├── flow-task-card                # moved + renamed from skills/starting-task/scripts/bd-card.py
│   ├── flow-task-tree                # moved + renamed from skills/starting-task/scripts/bd-tree.py
│   ├── flow-find-leaf                # moved + renamed from skills/starting-task/scripts/bd-continue.py
│   ├── flow-branch-for               # new
│   ├── flow-link-doc                 # new
│   ├── flow-current-task             # new
│   ├── flow-in-worktree              # new
│   ├── flow-find-branches            # new
│   └── tests/
│       ├── test_flow_task_card.py
│       ├── test_flow_task_tree.py
│       ├── test_flow_find_leaf.py
│       ├── test_flow_branch_for.py
│       ├── test_flow_link_doc.py
│       ├── test_flow_current_task.py
│       ├── test_flow_in_worktree.py
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

#### flow-task-tree

**Input:** stdin = `bd graph --all --json` output.
**Args:**
- `--root <id>` — subtree rooted at task (suffix match allowed)
- `--collapse` — show roots only with `[+N]` child count
- `-n N` — limit to first N root tasks
- `-s TERM` — filter by search term

**Output:** Hierarchical tree on stdout (the existing `bd-tree.py` rendering).
**Implementation:** Renamed from `bd-tree.py`. No behavior changes.

#### flow-find-leaf

**Args:** `--status <status>` (defaults to `in_progress`), other args as in current `bd-continue.py`.
**Output:** JSON array of leaf tasks (no open children) at the given status.
**Implementation:** Renamed from `bd-continue.py`. No behavior changes.

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
4. Print `{prefix}{task-id}-{brief-name}` on stdout (no trailing newline beyond `print()`'s default).

**Exit codes:** 0 on success, 1 if task not found, 2 if `bd` errored.

#### flow-link-doc

**Synopsis:** `flow-link-doc <task-id> <key> <value>`
**Keys (allowlist):** `Git`, `Design`, `Plan`.
**Algorithm:**
1. Call `bd show <id> --json`, extract description.
2. Regex find `^{key}:.*$` (multiline). If present, replace; if absent, append after a blank line.
3. Call `bd update <id> --description "..."`.

**Exit codes:** 0 on success, 1 if key not in allowlist, 2 if task not found.

**Why centralize:** today three skills implement this with subtly different HEREDOCs. One helper, one regex, one tested behavior.

#### flow-current-task

**Input:** none. Reads `git branch --show-current` internally.
**Algorithm:** match against `^(fix|chore|feature|docs)/([a-z0-9-]+-[a-z0-9]+(?:\.[0-9]+)*)(-.*)?$`. Print the captured task ID. Print nothing if no match.
**Exit codes:** 0 always (empty output = "not on a task branch"). Exit 1 only on git error.

#### flow-in-worktree

**Input:** none.
**Algorithm:** check if `pwd` contains `/.worktrees/`.
**Exit codes:** 0 if in worktree, 1 if not. No stdout/stderr.

#### flow-find-branches

**Synopsis:** `flow-find-branches <task-id>`
**Algorithm:**
1. Run `git branch -a` and filter lines containing the task ID with a prefix-aware regex (`(fix|chore|feature|docs)/<task-id>`).
2. Run `git worktree list --porcelain` and find branches whose worktree path or branch ref matches the same pattern.
3. Deduplicate: same branch in local + remote → emit once with `location=local`. Worktree presence is an additional fact.
4. Output one branch per line: `<branch-name>\t<location>` where location ∈ {`local`, `remote`, `worktree`}.

**Exit codes:** 0 always (empty output = no matches). Exit 1 only on git error.

### Testing Strategy

- Test framework: pytest, run via `uv run pytest plugins/flow/bin/tests/`.
- Per-helper test file: `tests/test_flow_<name>.py`.
- **stdin/stdout helpers** (`flow-task-card`, `flow-task-tree`, `flow-find-leaf`): feed fixed JSON, capture stdout/stderr, assert on output. Reuse existing test fixtures from `test_bd_card.py`, `test_bd_tree.py`, `test_bd_continue.py` — these tests come along with the rename.
- **git-aware helpers** (`flow-current-task`, `flow-in-worktree`, `flow-find-branches`): use `tmp_path` + `subprocess.run(..., cwd=tmp_path)`. Initialize a temp git repo and create the conditions under test.
- **bd-dependent helpers** (`flow-branch-for`, `flow-link-doc`): use `BD_BIN` env var pointing to a fake `bd` shell script in `tests/fixtures/`. The fake `bd` reads expected args, prints the canned JSON response.

### Migration Plan

Each commit migrates one logical unit and runs the full pre-commit checks (`uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, `uv run pytest plugins/flow/bin/tests/`).

1. **Setup:** Create `plugins/flow/bin/` with three renamed scripts (`flow-task-card`, `flow-task-tree`, `flow-find-leaf`) + their renamed tests in `bin/tests/`. Update callers in `starting-task/SKILL.md` and `continue-issue/SKILL.md` to call by bare name. Delete `skills/starting-task/scripts/`.
2. **flow-branch-for:** New helper + tests. Migrate `starting-task/SKILL.md` to use it (Step 5 of that skill).
3. **flow-link-doc:** New helper + tests. Migrate `starting-task/SKILL.md` (Step 8.1 Git line), `linking-design/SKILL.md`, `linking-plan/SKILL.md`.
4. **flow-current-task:** New helper + tests. Migrate `completing-task/SKILL.md`, `continue-issue/SKILL.md`, `reviewing-comments/SKILL.md`.
5. **flow-in-worktree:** New helper + tests. Migrate `starting-task/SKILL.md` (Step 0), `continue-issue/SKILL.md`, `completing-task/SKILL.md`.
6. **flow-find-branches:** New helper + tests. Migrate `starting-task/SKILL.md` (Step 5), `continue-issue/SKILL.md`, `completing-task/SKILL.md`.
7. **Docs:** Update `plugins/flow/README.md` to describe the `bin/` directory and how to add new helpers.

**Acceptance per migration commit:** the skill markdown contains zero significant bash logic for that pattern (only the helper invocation). Manual smoke test of the affected `/flow:*` command shows identical UX.

### Risk and Mitigations

| Risk | Mitigation |
|------|------------|
| Skill markdown becomes harder to read | Bare-name calls are shorter than the current `<skill-base-dir>/scripts/...` references. Reading improves. |
| Helper signature drift breaks all dependent skills | Tests are co-located. Pre-commit runs them. CI runs them. |
| Plugin loader fails to add `bin/` to PATH | Validated in setup commit by running `which flow-task-card` from a skill context before relying on bare names. If it fails, fall back to `<skill-base-dir>/../../bin/flow-task-card` in skill markdown (documented in plugins/flow/README.md). |
| Existing tests fail after rename | Tests are renamed alongside scripts in the same commit; pytest is run as part of the commit checklist. |

## Done When

- All eight helpers exist in `plugins/flow/bin/` with passing tests.
- `plugins/flow/skills/starting-task/scripts/` deleted.
- All flow skills that previously had duplicated bash now delegate to a helper. No skill contains an inline branch-name computation, link-line update, worktree check, or current-task extraction.
- `uv run pytest plugins/flow/bin/tests/` passes.
- Manual smoke test of `/flow:start`, `/flow:continue`, `/flow:done`, `/flow:after-design`, `/flow:after-plan`, `/flow:decompose` shows no UX regression.
- `plugins/flow/README.md` documents the `bin/` directory.
