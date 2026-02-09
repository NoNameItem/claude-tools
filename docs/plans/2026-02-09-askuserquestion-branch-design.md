# Design: Unified Branch & Worktree Selection via AskUserQuestion

**Task:** claude-tools-sgf
**Date:** 2026-02-09

## Problem

Steps 6 and 6.5 of `flow:starting-task` skill use free-text input for branch and worktree decisions. Users must type responses like "Да, продолжай в этой ветке" each time. This is inconvenient.

## Solution

Merge steps 6 (branch choice) and 6.5 (worktree choice) into a single `AskUserQuestion` call. Add auto-resolve cases that skip the question entirely when the answer is obvious.

## Auto-Resolve Cases

Checked before showing the question. If matched, skip steps 6-8, go directly to step 7 (update status).

1. **Current branch matches task branch** — detected by pattern `(fix|feature|chore)/{task-id}` in current branch name. Action: update status, report "Вы уже на ветке `{branch}`, продолжаем".

2. **Worktree exists for task branch** — detected by `git worktree list | grep "{branch-name}"`. Action: `cd {worktree-path}`, update status, report "Переключился в worktree `{path}`".

These two cases are mutually exclusive (git does not allow a branch to be checked out in both main directory and a worktree simultaneously).

## Options Matrix

### IN_WORKTREE=false

**0 existing branches:**

| # | Label | Description (generic branch) | Description (feature branch) |
|---|-------|------------------------------|------------------------------|
| 1 | Создать ветку (checkout) | `{branch-name}` — checkout в текущем каталоге | `{branch-name}` — checkout в текущем каталоге |
| 2 | Создать ветку (worktree) | `{branch-name}` — в отдельном worktree для параллельной работы | `{branch-name}` — в отдельном worktree для параллельной работы |
| 3 | Остаться на {branch} | Не рекомендуется — master лучше держать чистым | Продолжить работу в текущей ветке |

**1 existing branch:**

| # | Label | Description |
|---|-------|-------------|
| 1 | Checkout здесь | `{existing-branch}` — checkout в текущем каталоге |
| 2 | Checkout в worktree | `{existing-branch}` — в отдельном worktree для параллельной работы |
| 3 | Остаться на {branch} | Description depends on generic/feature |

**2+ existing branches:**

Same structure as 1 branch, using the most probable branch (prefer local over remote). Description of options 1-2 includes a note: "Также найдены: `branch-2`, `branch-3`".

### IN_WORKTREE=true

Worktree options are removed. Always 2 options:

| # | Label | Description |
|---|-------|-------------|
| 1 | Создать ветку / Checkout | Same as above but without worktree variant |
| 2 | Остаться на {branch} | Description depends on generic/feature |

## Option Ordering

- Recommended option is always first.
- "Остаться на текущей" is always last.
- On generic branches (main/master/develop): creating/checking out a branch is recommended, staying is marked as not recommended in description.
- On feature branches: neutral tone, no explicit recommendation.

## Other (Free-Form Input)

User can type arbitrary text via the automatic "Other" option. The LLM interprets user intent, extracting:
- Branch name (if specified)
- Method: checkout here / worktree

If the method is not clear from the text, ask a follow-up `AskUserQuestion` with 2 options: "Checkout здесь" / "В worktree".

## Response Handling

**Create branch (checkout):**
```bash
git checkout -b {branch-name}
```

**Create branch (worktree):**
```bash
WORKTREE_DIR=".worktrees/$(echo '{branch-name}' | tr '/' '-')"
git worktree add "$WORKTREE_DIR" -b {branch-name}
cd "$WORKTREE_DIR"
```

**Checkout existing (here):**
```bash
git checkout {existing-branch}
```

**Checkout existing (worktree):**
```bash
WORKTREE_DIR=".worktrees/$(echo '{existing-branch}' | tr '/' '-')"
git worktree add "$WORKTREE_DIR" {existing-branch}
cd "$WORKTREE_DIR"
```

**Stay on current branch:**
No branch action, proceed to `bd update`.

All paths end with `bd update <task-id> --status=in_progress`.

## Changes to SKILL.md

**Steps 4, 5** (check branch, search existing) — unchanged, but results feed into the unified question.

**New step between 5 and 6** — auto-resolve check (current branch match, worktree exists).

**Step 6** — rewritten: single `AskUserQuestion` with options from the matrix above. Replaces three text-based scenarios (A, B, C).

**Step 6.5** — deleted as separate step. Worktree choice is embedded in step 6 options.

**Step 7** (update status) — unchanged.

**Step 8** (create/checkout branch) — expanded to handle worktree creation (previously done in step 6.5).

**Other sections to update:**
- Quick Reference table
- Red Flags / Common Rationalizations (remove step 6.5 references)
- Examples (update to show AskUserQuestion flow)
- Edge Cases ("When User Already in Worktree" simplifies)
