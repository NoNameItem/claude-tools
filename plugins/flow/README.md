[![CI](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/NoNameItem/claude-tools/badges-data/flow.json)](https://github.com/NoNameItem/claude-tools/actions/workflows/push.yml)
![Version](https://img.shields.io/badge/version-1.5.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Claude%20Code-orange)

# Flow Plugin

Automated workflow skills for [Claude Code](https://code.claude.com) that guide you through a task lifecycle: from picking a task and creating a branch, through design, planning, and implementation, to PR review and task closure. Built on top of [beads](https://github.com/steveyegge/beads) for task management.

## Prerequisites

- [Claude Code](https://code.claude.com) — flow runs as a Claude Code plugin
- [beads](https://github.com/steveyegge/beads) — required. Flow skills use `bd` to select, update, and close tasks. See [bd requirements and migration](#bd-requirements-and-migration) for supported versions and the bd 1.0.x status.
- [superpowers](https://github.com/obra/superpowers) — recommended. Flow was designed to pair with superpowers for brainstorming, planning, and implementation. You can substitute your own approach, but the workflow descriptions below assume superpowers.
- Python — the `bin/` helpers run under whatever `python3` is first on your `PATH`. **3.11+ recommended** (matches the workspace's `requires-python`); they stay compatible down to **3.9** as a fallback for the stock macOS system `python3`.

## bd requirements and migration

Flow currently targets **bd 0.47.x**, which provides the commands flow relies on (`bd graph --all --json`, `bd sync`, and the auto-syncing daemon). Older builds can break flow in confusing ways — for example a stale Homebrew `bd 0.44.0` lacked `graph --all`, so flow failed with cryptic errors when that binary shadowed the working one on `PATH`.

**Pinning the bd binary.** Flow resolves `bd` via the `BD_BIN` environment variable, falling back to the first `bd` on your `PATH`. If you have more than one `bd` installed, check which one is active with `which -a bd`, and pin a specific binary with `BD_BIN=/full/path/to/bd` to avoid PATH-shadowing.

### bd 1.0.x support (in progress)

bd 1.0.x is a major release and **flow does not fully support it yet** — keep your working bd on 0.47.x for flow until this lands. Status:

- ✅ Flow renders the new first-class `decision` issue type, and its `--json` parsers are verified against real bd 1.0.5 output (the built-in types are `bug | feature | task | epic | chore | decision`).
- ⚠️ bd 1.0.x **removed `bd sync` and the `bd daemon` command** in favour of a Dolt-native model (`bd export` for JSONL interchange, `bd vc` / `bd federation` for sync, with Dolt auto-push). Flow's state-persistence steps assume `bd sync`, so they need redesigning before flow runs on 1.0.x.
- A version-guard helper (`bin/flow-require-bd`) is in place to require a supported bd once 1.0.x support is complete; it is not yet enforced in the skills.

The remaining bd 1.0.x migration — sync/persistence redesign, version-guard enforcement, and the environment cutover — is tracked as a separate follow-up.

## Installation

From GitHub:

```bash
/plugin marketplace add NoNameItem/claude-tools
/plugin install flow@nonameitem-toolkit
```

Local development:

```bash
/plugin marketplace add /path/to/claude-tools
/plugin install flow@nonameitem-toolkit
```

## How Flow Stores State

Flow saves task state as special lines in the beads task description:

```text
Git: feature/claude-tools-abc-login-error
Design: docs/superpowers/specs/2026-02-10-login-error-design.md
Plan: docs/superpowers/plans/2026-02-10-login-error-impl-plan.md
```

Paths above use the superpowers 5.x layout — `docs/superpowers/specs/` for designs, `docs/superpowers/plans/` for plans. Pre-v5 projects may still use `docs/plans/` for both; flow reads either.

Each line is written by one skill and read by others:

| Line       | Written by           | Read by                            |
|------------|----------------------|------------------------------------|
| `Git:`     | `/flow:start`        | `/flow:continue` (find branch)     |
| `Design:`  | `/flow:after-design`  | `/flow:decompose` (read design)    |
| `Plan:`    | `/flow:after-plan`    | `/flow:done` (cleanup plan file)   |

With superpowers, the typical chain looks like this:

1. `/superpowers:brainstorming` writes a **design document** — problem analysis, proposed approaches, architecture decisions
2. `/flow:after-design` finds it and saves `Design:` to the task
3. `/flow:decompose` reads `Design:`, opens the doc, creates subtasks
4. `/superpowers:writing-plans` writes an **implementation plan** — step-by-step commits, files to change, tests to add
5. `/flow:after-plan` finds it and saves `Plan:` to the task
6. `/flow:done` reads `Plan:`, offers to delete or archive the file

If you edit task descriptions manually, keep these lines intact.

## Why Multiple Sessions?

Claude Code has a finite context window. As a session grows, the available context shrinks — older messages get compressed, and the model loses track of earlier decisions. Long sessions lead to degraded quality.

Splitting work into focused sessions — design, planning, implementation, review — keeps each session short and the context fresh. `/clear` or restarting Claude Code resets the context, and `/flow:continue` reconnects you to the task in seconds.

Flow skills preserve continuity across sessions by saving state in beads tasks: branch name, linked documents, subtask structure. The context resets, but the task context doesn't.

## Typical Workflow

A task lifecycle typically spans multiple Claude Code sessions. Here's how flow skills chain together across sessions.

### Session 1: Pick a task and design

```bash
/flow:start                       # choose task, create branch
/superpowers:brainstorming        # explore the problem, write design doc
/flow:after-design                # link design to task
/flow:decompose                   # break into subtasks (if needed)
```

### Session 2: Plan implementation

```bash
/flow:continue                    # resume active task
/superpowers:writing-plans        # create implementation plan
/flow:after-plan                  # link plan to task
```

### Session 3: Implement

```bash
/flow:continue                    # resume active task
/superpowers:executing-plans      # implement the plan
# create PR when ready
```

### Session 4: Address review feedback

```bash
/flow:continue                    # resume active task
/flow:review-comments             # process PR comments, fix, push
/flow:sonar-sync                  # import SonarCloud issues as subtasks
```

### Session 5: Close

```bash
/flow:continue                    # resume active task
/flow:done                        # close task, clean up branch
```

Not every task needs all phases. A small bug fix might go straight from `/flow:start` to implementation to `/flow:done` in a single session. The skills are independent — use what fits.

## Commands

### Starting Work

#### `/flow:start`

Begins a work session. Shows a hierarchical task tree, lets you pick a task by number or ID, displays full task details, then handles branch creation or checkout. Offers worktree as an option for parallel work.

When to use: at the start of a new work session, or when switching to a different task.

```bash
/flow:start           # show all tasks
/flow:start 5dl       # show subtree rooted at task 5dl
```

#### `/flow:continue`

Fast return to an active task after `/clear` or Claude Code restart. Finds your in_progress leaf tasks, switches to the saved branch or worktree, and displays the task card. If multiple tasks are in progress, lets you pick which one to resume.

When to use: after `/clear`, new session, or Claude Code restart.

```bash
/flow:continue          # find and resume active task(s)
/flow:continue elf.3    # resume specific task directly
```

### Design & Planning

#### `/flow:after-design`

Links a design document to the current task. Finds the most recent design file in `docs/superpowers/specs/` or `docs/plans/`, saves a `Design:` reference in the task description. Run this after completing the brainstorming phase.

When to use: after `/superpowers:brainstorming` (or your own design process) produces a design document.

```bash
/flow:after-design
```

#### `/flow:decompose`

Breaks a task into subtasks based on its design document. Proposes 2-3 decomposition approaches (by component, stage, layer), lets you choose, then builds a subtask list with full preview. Creates subtasks only after explicit confirmation.

When to use: after design is linked, when the task is too large to implement in one go.

```bash
/flow:decompose
```

#### `/flow:after-plan`

Links an implementation plan to the current task. Finds the most recent plan file in `docs/superpowers/plans/` or `docs/plans/`, saves a `Plan:` reference in the task description. Run this after the planning phase.

When to use: after `/superpowers:writing-plans` (or your own planning process) produces an implementation plan.

```bash
/flow:after-plan
```

### Code Review & Quality

#### `/flow:review-comments`

Processes unresolved GitHub PR review comments. Collects comments, categorizes them by source (human vs bot), analyzes each one, then applies accepted fixes and replies on GitHub. Applies higher skepticism to nitpicks and style suggestions.

When to use: after pushing a PR and receiving review comments.

```bash
/flow:review-comments
```

#### `/flow:sonar-sync`

Syncs SonarQube/SonarCloud issues with beads tasks. Two modes: on main branch — bulk import of tech debt issues; on PR branch — fix now or defer as subtasks. Shows a preview table and lets you select which issues to import.

When to use: during tech debt review or after SonarCloud analysis flags new issues.

```bash
/flow:sonar-sync
```

### Completing Work

#### `/flow:done`

Completes the current task. Checks git branch and PR status, closes the task, offers to clean up plan files (delete/archive/keep), recursively checks if parent tasks can be closed too, runs bd sync, and offers to delete the feature branch and worktree. If you're on a feature branch without a PR, stops and suggests creating one first.

When to use: when implementation is complete, PR is merged, and you're ready to close the task.

```bash
/flow:done
```

## Command Reference

| Command                 | Description                                       |
|-------------------------|---------------------------------------------------|
| `/flow:start`           | Pick a task, create branch, begin work             |
| `/flow:continue`        | Resume active task after /clear or restart          |
| `/flow:after-design`    | Link design document to current task               |
| `/flow:decompose`       | Break task into subtasks from design               |
| `/flow:after-plan`      | Link implementation plan to current task           |
| `/flow:review-comments` | Process GitHub PR review comments                  |
| `/flow:sonar-sync`      | Sync SonarCloud issues with beads tasks            |
| `/flow:done`            | Close task, clean up branch and plan files         |

## bin/ helpers

`plugins/flow/bin/` holds small executables that the skills call **by bare name**
(the plugin loader adds this directory to `PATH`). Each is an extension-less
Python file with a `#!/usr/bin/env python3` shebang and a co-located test in
`bin/tests/`.

| Helper | Purpose |
|--------|---------|
| `flow-task-card` | Render a beads task card from `bd show --json` |
| `flow-task-tree` | Render the task tree from `bd graph --json` |
| `flow-find-leaf` | Leaf in-progress tasks as a grouped list (mine → Unassigned → others) |
| `flow-actor` | Resolve actor name: `$BD_ACTOR` → git `user.name` → `$USER` |
| `flow-branch-for <id>` | Compute the branch name for a task |
| `flow-link-doc <id> <Git\|Design\|Plan> <value>` | Set/remove a link line (empty value removes) |
| `flow-find-doc <design\|plan>` | Newest doc across `docs/superpowers/{specs,plans}/` + `docs/plans/` |
| `flow-current-task [id]` | Extract the task id from the branch, or match the branch against `id` |
| `flow-in-worktree` | Exit 0 if CWD is inside `.worktrees/` |
| `flow-worktree-dir <branch>` | Map a branch to its `.worktrees/` directory |
| `flow-find-branches <id>` | Branches matching a task id (local/remote/worktree) |

Run the tests: `uv run pytest plugins/flow/bin/tests/`. CI runs them too — the
plugin-CI `test` job executes any plugin's `bin/tests/` on every PR.

**Adding a helper:** create the executable (`chmod +x`, no `.py`), ensure it's
covered by `pyproject.toml`'s `[tool.ruff] extend-include` glob (`plugins/flow/bin/flow-*`),
write a `bin/tests/test_flow_<name>.py`, and call it by bare name from the skill.

**PATH fallback:** if a skill's Bash context can't resolve a bare helper name
(`which flow-task-card` is empty), call it via `<skill-base-dir>/../../bin/<helper>`.
