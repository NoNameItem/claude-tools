# Flow Plugin Documentation — Design

## Decision Log

- **Audience:** Plugin users (not contributors)
- **Location:** `plugins/flow/README.md` (single file)
- **Detail level:** Concise — 2-3 sentences per command, when to use, one example
- **Language:** English
- **Prerequisites:** Brief with explicit links. beads required, superpowers recommended.
- **Badges:** Version (from plugin.json), License (MIT), Platform (Claude Code). CI badge deferred — see `claude-tools-wm2`.

## Structure

1. **Badges** — version, license, platform (shields.io static badges)
2. **Flow Plugin** — one-paragraph overview
3. **Prerequisites** — [Claude Code](https://claude.com/claude-code), [beads](https://github.com/steveyegge/beads) (required), [superpowers](https://github.com/obra/superpowers) (recommended)
4. **Installation** — from GitHub + local development
5. **How Flow Stores State** — Git/Design/Plan lines in task description, table of who writes/reads each, chain with superpowers
6. **Why Multiple Sessions?** — context window limits, focused sessions, state preserved in beads
7. **Typical Workflow** — 5 sessions demonstrating full lifecycle:
   - Session 1: `/flow:start` → brainstorm → `/flow:after-design` → `/flow:decompose`
   - Session 2: `/flow:continue` → write plan → `/flow:after-plan`
   - Session 3: `/flow:continue` → implement → create PR
   - Session 4: `/flow:continue` → `/flow:review-comments` → `/flow:sonar-sync`
   - Session 5: `/flow:continue` → `/flow:done`
   - Note: not every task needs all phases
8. **Commands** — grouped by lifecycle phase:
   - **Starting Work:** `/flow:start`, `/flow:continue`
   - **Design & Planning:** `/flow:after-design`, `/flow:decompose`, `/flow:after-plan`
   - **Code Review & Quality:** `/flow:review-comments`, `/flow:sonar-sync`
   - **Completing Work:** `/flow:done`
9. **Command Reference** — quick-reference table

## Command Descriptions

Each command: what it does (2-3 sentences), when to use, one example.

### `/flow:start`

Pick a task from hierarchical tree, create or checkout a branch, begin work. Offers worktree for parallel work. Accepts optional task ID to show subtree.

### `/flow:continue`

Fast return to active task after `/clear` or restart. Finds in_progress leaf tasks, switches to saved branch/worktree, shows task card. If multiple tasks in progress, lets you pick.

### `/flow:after-design`

Links most recent design document to current task. Saves `Design:` reference in task description.

### `/flow:decompose`

Breaks task into subtasks based on design document. Proposes 2-3 decomposition approaches, builds subtask list with preview, creates only after confirmation.

### `/flow:after-plan`

Links most recent implementation plan to current task. Saves `Plan:` reference in task description.

### `/flow:review-comments`

Processes unresolved GitHub PR review comments. Categorizes by source (human vs bot), analyzes each, applies accepted fixes, replies on GitHub. Higher skepticism for nitpicks.

### `/flow:sonar-sync`

Syncs SonarCloud issues with beads tasks. On main branch — bulk import. On PR branch — fix now or defer as subtasks.

### `/flow:done`

Closes task, offers plan file cleanup (delete/archive/keep), recursively checks parent tasks, runs bd sync, offers to delete feature branch and worktree. Stops on feature branch without PR.
