# Flow:Start Branch Naming Test Scenarios

## Test Scenario 1: Bug Task - No Existing Branches

**Setup:**
- Current branch: `master` (generic)
- Task: claude-tools-abc (type: bug)
- Task title: "Fix authentication timeout"
- Existing branches: none matching task-id

**Expected behavior:**
1. Search for existing branches: `git branch -a | grep -i "claude-tools-abc"`
2. No matches found
3. Generate branch name: `fix/claude-tools-abc-authentication-timeout`
4. Show recommendation (generic branch):
   > You're currently on `master` (main development branch). **I recommend creating a separate branch** for this work to keep main clean and make it easier to create PRs later.
   >
   > Would you like me to create branch `fix/claude-tools-abc-authentication-timeout`?

## Test Scenario 2: Feature Task - Existing Branches Found

**Setup:**
- Current branch: `master`
- Task: claude-tools-xyz (type: feature)
- Task title: "Add dark mode"
- Existing branches:
  - `feature/claude-tools-xyz-dark-mode` (local)
  - `feature/claude-tools-xyz-theme` (origin)

**Expected behavior:**
1. Search for existing branches: `git branch -a | grep -i "claude-tools-xyz"`
2. Found 2 matches
3. Present options:
   > Found existing branches for this task:
   > - `feature/claude-tools-xyz-dark-mode` (local)
   > - `feature/claude-tools-xyz-theme` (origin)
   >
   > Would you like to:
   > 1. Checkout existing branch: `feature/claude-tools-xyz-dark-mode`
   > 2. Create new branch: `feature/claude-tools-xyz-dark-mode`

## Test Scenario 3: Chore Task - Feature Branch

**Setup:**
- Current branch: `feature/some-work` (feature branch)
- Task: claude-tools-123 (type: chore)
- Task title: "Update dependencies"
- Existing branches: none matching

**Expected behavior:**
1. Search for existing branches: `git branch -a | grep -i "claude-tools-123"`
2. No matches found
3. Generate branch name: `chore/claude-tools-123-update-dependencies`
4. Show neutral question (feature branch):
   > You're currently on feature branch `feature/some-work`.
   >
   > Would you like to continue work on this branch, or create a new branch `chore/claude-tools-123-update-dependencies`?

## Test Scenario 4: Task (as Feature)

**Setup:**
- Task type: task
- Task title: "Setup CI/CD pipeline"

**Expected prefix:**
- `feature/` (task → feature prefix)
- Example: `feature/claude-tools-456-setup-cicd-pipeline`

## Verification Checklist

- [ ] Correct prefix for bug → `fix/`
- [ ] Correct prefix for chore → `chore/`
- [ ] Correct prefix for feature → `feature/`
- [ ] Correct prefix for task → `feature/`
- [ ] Brief name generated from 2-3 key words
- [ ] Brief name in lowercase with hyphens
- [ ] Search performed with `git branch -a | grep -i "{task-id}"`
- [ ] Existing branches presented as option #1
- [ ] Generic branch → RECOMMEND tone
- [ ] Feature branch → NEUTRAL tone
- [ ] Remote branch checkout uses correct command
