# Git Worktree Integration for flow:starting-task

## Overview

Add git worktree support to `flow:starting-task` skill for parallel Claude Code sessions.

**Problem:** When working with beads tasks, `execute-plan` can run for a long time. User wants to start brainstorming next task or run multiple `execute-plan` in parallel without waiting.

**Solution:** Extend `flow:starting-task` to optionally create worktrees instead of regular checkout, enabling multiple Claude Code sessions working on different tasks simultaneously.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Worktree location | `.worktrees/` in project | Simple, visible, one-time .gitignore setup |
| Naming convention | Branch name with `/` → `-` | `.worktrees/feature-claude-tools-5dl-statuskit/` |
| Integration approach | Extend existing skill | Single entry point, reuse existing logic |
| Worktree creation | Delegate to `superpowers:using-git-worktrees` | No code duplication, handles setup/tests |
| agent-deck support | Optional, detect at runtime | Graceful degradation, no hard dependency |

## Architecture

### Responsibility Split

| Component | Responsibility |
|-----------|----------------|
| `flow:starting-task` | Task selection, branch choice, "worktree?" question, beads status update |
| `superpowers:using-git-worktrees` | Worktree creation, .gitignore check, project setup, test verification |
| `agent-deck` (optional) | Session creation with worktree in one command |

### Environment Detection

At skill start, detect available tools:

```bash
command -v agent-deck >/dev/null 2>&1 && echo "HAS_AGENT_DECK=true"
```

## Workflow Changes

### New Step 6.5: Ask About Worktree

Inserted between current steps 6 (Ask About Branch) and 7 (Update Task Status).

**With agent-deck installed:**

```
Как открыть ветку `feature/claude-tools-c7b-git-module`?

1. Здесь (обычный checkout)
2. В новой сессии agent-deck с worktree
```

**Without agent-deck:**

```
Как открыть ветку `feature/claude-tools-c7b-git-module`?

1. Здесь (обычный checkout)
2. В worktree (для параллельной работы)
```

### Execution Paths

**Option 1 (checkout here):**
- Proceed to step 7 (update beads)
- Execute step 8 (git checkout)

**Option 2 with agent-deck:**
```bash
agent-deck add "$(pwd)" -t "{task-title}" --worktree {branch-name}
```
- Proceed to step 7 (update beads)
- Skip step 8 (branch created by agent-deck)

**Option 2 without agent-deck:**
- Invoke `superpowers:using-git-worktrees` with branch name
- Proceed to step 7 (update beads)
- Skip step 8 (branch created by worktree skill)

## Edge Cases

### Worktree already exists

```bash
git worktree list | grep "{branch-name}"
```

**With agent-deck:**
- Check for existing session: `agent-deck session list | grep "{branch-name}"`
- Session exists → "Сессия уже существует, переключитесь в agent-deck TUI"
- No session → "Worktree есть, создать сессию?" → `agent-deck add` without `--worktree`

**Without agent-deck:**
- "Worktree уже существует: `{path}`. Откройте в новом терминале."

### agent-deck command fails

Fallback to git approach:
```
agent-deck недоступен или вернул ошибку.
Создаю worktree через git...
```
Then invoke `superpowers:using-git-worktrees`.

### User already in worktree

Detect by path:
```bash
pwd | grep -q "\.worktrees/" && echo "IN_WORKTREE=true"
```

If true — don't offer to create another worktree:
```
Вы уже в worktree. Продолжить работу здесь или переключиться на другую ветку?
```

## Example Workflows

### Scenario A: With agent-deck

```
User: /flow:start

Agent: Доступные задачи:

       1. [E] StatusKit (claude-tools-5dl) | P1 · in_progress
          └─ 1.1 [F] Git module (claude-tools-c7b) | P2 · open

User: 1.1

Agent: ┌─ [F] Git module ──────────────────────────────────────────┐
       │ ID: claude-tools-c7b                                      │
       │ Priority: P2  Status: open  Type: feature                 │
       ├───────────────────────────────────────────────────────────┤
       │ DESCRIPTION                                               │
       │ Create module that displays git info...                   │
       └───────────────────────────────────────────────────────────┘

       Вы на `master`. Рекомендую создать feature branch.
       Создать ветку `feature/claude-tools-c7b-git-module`?

User: да

Agent: Как открыть ветку?

       1. Здесь (обычный checkout)
       2. В новой сессии agent-deck с worktree

User: 2

Agent: Создана сессия `git-module` с worktree.
       Статус задачи обновлён на in_progress.

       Переключитесь на неё в agent-deck TUI (Ctrl+j/k).
```

### Scenario B: Without agent-deck

```
User: /flow:start
...
User: 2

Agent: [invokes superpowers:using-git-worktrees]

       Worktree готов: .worktrees/feature-claude-tools-c7b-git-module
       Tests passing (12 tests)
       Статус задачи обновлён на in_progress.

       Откройте эту директорию в новом терминале:
       cd .worktrees/feature-claude-tools-c7b-git-module && claude
```

## Implementation Checklist

- [ ] Add environment detection (step 0) to SKILL.md
- [ ] Add step 6.5 (worktree question) to SKILL.md
- [ ] Update step 8 to be conditional (skip if worktree)
- [ ] Add edge case handling (existing worktree, in worktree, agent-deck error)
- [ ] Update Quick Reference table
- [ ] Add examples to SKILL.md
- [ ] Test with agent-deck installed
- [ ] Test without agent-deck (fallback to superpowers skill)
- [ ] Update CLAUDE.md with `.worktrees/` convention

## Out of Scope

- Worktree cleanup (handled by `git worktree remove` or `superpowers:finishing-a-development-branch`)
- agent-deck plugin installation/setup
- Modifying `superpowers:using-git-worktrees` skill
