# Design: Project Initialization After Worktree Creation

**Task:** claude-tools-elf.5
**Date:** 2026-01-30

## Problem

After creating a worktree via `flow:starting-task`, the user must manually run project setup commands (`uv sync`, `npm install`, `docker compose up`, etc.). This is easy to forget and breaks the flow.

## Solution

Add a new step to `flow:starting-task` skill that detects the project type and runs initialization commands after worktree creation.

## Where and When

The step triggers only when the user chose the worktree option in Step 6.5. It runs after Step 7 (status update to `in_progress`), as a new Step 7.1.

Flow:

1. Step 6.5: User picks "В worktree"
2. `git worktree add` + `cd` into worktree
3. Step 7: `bd update --status=in_progress`
4. **Step 7.1 (new): Detect project type, confirm with user, run init**

## Detection Logic

Claude Code performs these steps in order:

1. **Read project docs** — `CLAUDE.md` and/or `README.md` for installation/setup instructions
2. **Inspect config files** — look at the worktree root for typical files (`pyproject.toml`, `package.json`, `docker-compose.yml`, `Gemfile`, `Cargo.toml`, etc.)
3. **Decide on commands** — docs take priority over guessing from config files. For example, if `package.json` exists but docs say `pnpm install`, propose `pnpm install`, not `npm install`. Docker projects (`docker compose build`, `docker compose up -d`) are handled the same way — no special logic, just read the docs.
4. **If ambiguous** — use best judgment, confirmation step protects against mistakes

## User Interaction

Always ask for confirmation before running:

```
Обнаружен Python-проект (pyproject.toml). Предлагаю выполнить инициализацию:
  → uv sync

Выполнить? (да/нет)
```

Multiple project types:

```
Обнаружены конфигурации проектов:
  → uv sync (pyproject.toml)
  → npm install (package.json)

Выполнить? (да/нет)
```

If nothing recognized — skip silently, no question asked.

## Error Handling

If initialization fails — show the error and continue. The task is already claimed, branch is created. User can fix manually.

## Scope of Change

One new step (7.1) in `plugins/flow/skills/starting-task/SKILL.md`. No scripts, no config files, no new dependencies.

## Decomposition

1. Add Step 7.1 to `SKILL.md` with detection and confirmation logic
2. Update Quick Reference table
3. Update Red Flags / Common Rationalizations sections
