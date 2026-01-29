# Branch and Worktree Cleanup on Task Close

## Context

When closing a task via `/flow:done`, associated git branches and worktrees persist indefinitely. The typical workflow:

1. `flow:start` — creates branch and worktree
2. Multiple sessions of design, planning, implementation
3. PR created and merged via GitHub UI
4. `flow:done` — closes the task but leaves branch and worktree behind

## Decision

Add cleanup as **Step 7** in the completing-task skill, after `bd sync` (Step 6). Cleanup is non-blocking: if it fails, the task is already closed and synced.

## Design

### Step 7. Cleanup Branch and Worktree

#### 7.1. Validate current branch matches the task

```bash
CURRENT_BRANCH=$(git branch --show-current)
```

Check if `$CURRENT_BRANCH` contains the closed task's ID. If not — skip cleanup silently. The user ran `flow:done` from an unrelated branch (e.g. master).

#### 7.2. Detect what exists

Gather cleanup targets:

- **Worktree:** `pwd | grep -q "\.worktrees/"` — are we in a worktree?
- **Remote branch:** `git branch -r | grep "$CURRENT_BRANCH"` — does remote branch exist?
- Local branch is always present (we're on it).

#### 7.3. Show branch name and ask once

Display the current branch explicitly and list what will be deleted:

```
You are on branch `feature/claude-tools-elf.6-delete-branches-worktrees`.

Delete branch and associated resources?
  - Worktree: .worktrees/feature-claude-tools-elf.6-delete-branches-worktrees
  - Local branch: feature/claude-tools-elf.6-delete-branches-worktrees
  - Remote branch: origin/feature/claude-tools-elf.6-delete-branches-worktrees

(yes/no)
```

Show only items that exist. If no worktree, omit the worktree line. If no remote branch, omit the remote line.

#### 7.4. If yes — execute in order

1. **If in worktree:** `cd` to the main repo root (parent of `.worktrees/`)
2. **Remove worktree:** `git worktree remove <path>` (if in worktree)
3. **Detect default branch:**
   ```bash
   DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD | sed 's|refs/remotes/origin/||')
   ```
   Fallback: try `master`, then `main`.
4. **Switch to default branch:** `git checkout $DEFAULT_BRANCH`
5. **Pull merged changes:** `git pull`
6. **Delete local branch:** `git branch -d <branch>` (safe delete; use `-D` if needed when PR is confirmed merged)
7. **Delete remote branch:** `git push origin --delete <branch>` (if remote exists)

#### 7.5. If no — skip, done

No cleanup performed. User can clean up manually later.

### Edge Cases

**Current branch doesn't match task ID:**
Skip cleanup silently. User is on master or another branch.

**Worktree remove fails (uncommitted changes):**
Show error, suggest `git worktree remove --force` or manual cleanup. Don't block.

**Remote branch already deleted (GitHub auto-delete):**
`git push origin --delete` will fail — catch the error and continue. Not a problem.

**Branch delete fails (unmerged changes):**
`git branch -d` will refuse. Show warning. Offer `git branch -D` only if PR state is MERGED.

## Scope

### This step DOES:
- Check if current branch matches closed task
- Show what will be deleted and ask confirmation
- Remove worktree, local branch, remote branch
- Switch to default branch and pull

### This step does NOT:
- Search for branches beyond the current one
- Clean up branches for parent tasks (cascade closures)
- Force-delete without confirmation
- Block task closure if cleanup fails

## Decomposition

1. Add Step 7 to completing-task/SKILL.md with the cleanup algorithm
2. Update Quick Reference table to include Step 7
3. Update Scope Boundaries section
4. Add edge case examples
5. Add Red Flags for cleanup-related rationalizations
