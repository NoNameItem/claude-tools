# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.1] - 2026-01-25

### Fixed

- Task closure now allowed on feature branches when PR already exists

## [1.4.0] - 2026-01-25

### Changed

- Replaced agent-deck integration with native git worktrees
- Simplified worktree workflow without external dependencies

### Added

- Auto `bd sync` at skill start to fetch tasks from all branches
- Auto `cd` into worktree directory after creation

## [1.3.0] - 2026-01-23

### Added

- Initial agent-deck integration for worktree management

## [1.2.0] - 2026-01-22

### Added

- Hierarchical task display in `flow:start` skill with tree formatting
- `bd-tree.py` script for task tree building
- Branch naming with type prefixes (`fix/`, `feature/`, `chore/`)
- Search for existing branches before creating new ones
- Worktree integration for parallel work sessions
- CRITICAL section with validation checkpoints

### Fixed

- Premature command execution in flow commands
- STOP-AND-READ section to enforce skill reading before action
- Skill renaming to resolve name conflict with commands
- Script path resolution using `<skill-base-dir>` placeholder
- Removed `disable-model-invocation` flag from commands

## [1.1.0] - 2026-01-17

### Added

- Complete skill suite for beads workflow automation:
  - `flow:start` — task selection, branch management, context display
  - `flow:after-design` — links design docs, parses subtasks
  - `flow:after-plan` — links implementation plans to tasks
  - `flow:done` — task completion with parent task handling
- Command files for slash command invocation (`/flow:start`, etc.)

### Fixed

- Plugin.json schema corrected to match Claude Code requirements
- Removed references to non-existent skills

## [1.0.0] - 2026-01-16

### Added

- Initial plugin structure
- Basic flow:start skill implementation
