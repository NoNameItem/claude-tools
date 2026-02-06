---
name: init-worktree
description: Initialize project environment after worktree creation. Detects project type from config files and CLAUDE.md, proposes setup commands with confirmation. Used by flow:start and flow:continue after new worktree creation.
---

# Flow: Initialize Worktree

## Overview

**Core principle:** Detect and confirm before running.

This skill initializes a newly created worktree's project environment. It detects the project type, proposes setup commands, and runs them only after user confirmation.

**When invoked:** After a new worktree is created by `flow:start` or `flow:continue`. NOT invoked for existing worktrees or regular checkouts.

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 1. Read docs | Check CLAUDE.md / README.md | Docs take priority |
| 2. Detect | Inspect config files | Fallback if no docs |
| 3. Propose | Show commands to run | Always confirm first |
| 4. Execute | Run if user confirms | Failure is non-blocking |

## Algorithm

### 1. Read Project Documentation

Check for setup instructions in order:
1. `CLAUDE.md` — project-specific instructions (highest priority)
2. `README.md` — general project docs

Look for sections mentioning: "install", "setup", "getting started", "development", "dependencies".

If docs specify exact commands (e.g., "run `uv sync`"), use those commands.

### 2. Detect Project Type

If documentation doesn't provide clear commands, inspect config files at the current directory root:

| File | Project Type | Default Command |
|------|-------------|-----------------|
| `pyproject.toml` | Python (uv) | `uv sync` |
| `package.json` + `pnpm-lock.yaml` | Node (pnpm) | `pnpm install` |
| `package.json` + `yarn.lock` | Node (yarn) | `yarn install` |
| `package.json` + `bun.lockb` | Node (bun) | `bun install` |
| `package.json` | Node (npm) | `npm install` |
| `Cargo.toml` | Rust | `cargo build` |
| `Gemfile` | Ruby | `bundle install` |
| `go.mod` | Go | `go mod download` |
| `docker-compose.yml` | Docker | `docker compose up -d` |

**Priority:** Documentation commands > lockfile-specific detection > default commands.

### 3. Propose Commands

**If project type recognized**, show what will run and ask:

```
Обнаружен Python-проект (pyproject.toml). Предлагаю выполнить инициализацию:
  → uv sync

Выполнить? (да/нет)
```

**Multiple project types:**

```
Обнаружены конфигурации проектов:
  → uv sync (pyproject.toml)
  → npm install (package.json)

Выполнить? (да/нет)
```

**If nothing recognized** — skip silently. Do NOT ask "no project detected, skip?"

### 4. Execute

**If user confirms** — run commands one by one. Show output.

**If any command fails** — show the error and continue. Init failure is non-blocking:

```
⚠️ Инициализация завершилась с ошибкой:
  uv sync → exit code 1: <error message>

Продолжаем работу. Вы можете запустить инициализацию вручную позже.
```

**If user declines** — skip silently and continue.

## Scope Boundaries

**This skill does NOT:**
- Create worktrees (caller's responsibility)
- Decide whether to use worktree (caller's decision)
- Check if worktree is new vs existing (caller filters this)
- Run tests or lint
- Modify project files

**This skill DOES:**
- Read CLAUDE.md/README.md for setup instructions
- Detect project type from config files
- Propose initialization commands
- Run commands after user confirmation

## Red Flags

- "I'll run `uv sync` without asking" → Always confirm first
- "No need to check docs, I know the project type" → Docs take priority over guessing
- "Init failed, I should stop the workflow" → Show error, continue. Non-blocking.
- "I'll also run tests to make sure everything works" → Out of scope. Init only.
- "The project has both pyproject.toml and package.json, I'll pick one" → Show both, let user decide

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "I'll run init without asking" | Always confirm. User might not want it now. |
| "I know the project type, skip docs" | Docs take priority. `package.json` could be npm, pnpm, yarn, or bun. |
| "Init failed, abort workflow" | Show error, continue. Init failure is non-blocking. |
| "I'll also set up pre-commit hooks" | Out of scope. Only run what was proposed and confirmed. |
| "Nothing to init, I'll tell the user" | Skip silently if nothing recognized. |
