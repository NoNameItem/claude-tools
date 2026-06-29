# Agent Instructions — flow

Claude Code plugin (`flow`) in the claude-tools monorepo. See the root `AGENTS.md` for
repo-wide agent and review guidance.

## Architecture & principles

`flow` automates the beads task workflow as `/flow:*` slash commands. Each command is a
**skill** (`skills/<name>/SKILL.md`, surfaced as a slash command); shared logic lives in
**extension-less Python helpers** under `bin/` (`flow-*`), called from skills via pipes.

- **Skills:** `start` (pick task, branch/worktree strategy, set in_progress), `continue`
  (fast resume of an active leaf task), `after-design` / `after-plan` (link the newest
  spec/plan doc into the task), `decompose` (discuss → create subtasks), `done` (verify PR,
  close task, walk up to parents, sync), `init-worktree` (sub-skill: init a fresh worktree),
  `review-comments` (process all PR/MR review threads — GitHub & GitLab), `sonar-sync`
  (pull Sonar issues into beads tasks).
- **Helpers (`bin/flow-*`):** `flow-actor` (resolve actor: `BD_ACTOR` → git user → `$USER`),
  `flow-find-leaf` / `flow-task-tree` (render task lists/trees from `bd graph --json`),
  `flow-task-card` (Unicode-aware card renderer), `flow-branch-for` (task → branch name),
  `flow-find-branches` / `flow-current-task` / `flow-in-worktree` / `flow-worktree-dir`
  (branch & worktree resolution), `flow-link-doc` (set `Git:`/`Design:`/`Plan:` lines),
  `flow-find-doc` (newest spec/plan), `flow-require-bd` (enforce a minimum bd version),
  `flow-sync` (sync wrapper).

**Principles:**
- **bd only via the CLI** — helpers shell out to `bd` (`bd graph`, `bd show`, `bd create`,
  `bd close`, `bd update`, `bd dolt …`); **never** touch Dolt/SQLite files directly.
- **Mode-agnostic** — must work across all bd Dolt modes (embedded, server, shared-server).
  The embedded store is single-writer Dolt (file lock), **not SQLite**.
- **Best-effort sync** — `flow-sync` runs `bd dolt commit` then push/pull, **exits 0 even on
  failure**, and reports problems on **stderr**; a sync failure must never block a workflow.
- **Analyze before acting & confirm destructive steps** — skills read full context (task
  card, branches, PR state) first, and gate destructive actions (closing tasks, taking
  someone else's task, deleting local plan files, pushing) behind explicit confirmation.
- **Reproduce the card inline** — a skill showing a task card must paste the `flow-task-card`
  output verbatim in a fenced code block; tool output alone isn't shown to the user.

## Review guidelines

These apply on top of the root `AGENTS.md` review guidelines, for changes under
`plugins/flow/`. Focus on judgment issues CI can't catch. (Root Secrets rule still applies.)

**bd via CLI, mode-agnostic (P1).** Flag any helper/skill that reads or writes bd storage
directly (Dolt/SQLite paths, config files) instead of using `bd` CLI commands, or that
assumes a specific Dolt mode. Calling the embedded store "SQLite" is wrong — it's
single-writer Dolt behind a file lock.

**flow-sync is best-effort (P1).** `flow-sync` must exit 0 and surface problems on stderr;
it must not hard-fail in a way that blocks the surrounding skill. Flag changes that make a
sync/commit/push failure fatal.

**Skill safety gates (P1).** Flag a `SKILL.md` change that drops a documented confirmation
before a destructive or outward-facing action (closing a task, reassigning another user's
task, deleting plan files, `git push`), or that reorders a mutation ahead of its gate.

**Helper conventions.** `bin/flow-*` are extension-less Python scripts invoked via pipes —
keep clear exit codes (0 = success, non-zero + stderr = failure), no silent failures, and
keep them extension-less.
