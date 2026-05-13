# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.6.0](https://github.com/NoNameItem/claude-tools/compare/flow-1.5.0...flow-1.6.0) (2026-02-12)


### Features

* **flow:** add /flow:continue command for fast task return ([#54](https://github.com/NoNameItem/claude-tools/issues/54)) ([a5c09f5](https://github.com/NoNameItem/claude-tools/commit/a5c09f5c6e79792420501c2f3edbdc821c9abd8d))
* **flow:** add AskUserQuestion to branch selection in starting-task ([#61](https://github.com/NoNameItem/claude-tools/issues/61)) ([c48cba5](https://github.com/NoNameItem/claude-tools/commit/c48cba544e8f9fcbdb1c65e9f89924e2e694904d))
* **flow:** add bd sync after task mutations in all flow skills ([#51](https://github.com/NoNameItem/claude-tools/issues/51)) ([5e04ef0](https://github.com/NoNameItem/claude-tools/commit/5e04ef0642252434d82a12e0c71290a2469fe0b8))
* **flow:** add bd-card.py script for task card rendering ([#62](https://github.com/NoNameItem/claude-tools/issues/62)) ([3f7255b](https://github.com/NoNameItem/claude-tools/commit/3f7255b8e976321d54a574193ea33033cdeb9208))
* **flow:** add branch/worktree cleanup to completing-task skill ([#52](https://github.com/NoNameItem/claude-tools/issues/52)) ([2c9a215](https://github.com/NoNameItem/claude-tools/commit/2c9a2151a5529d8f7da00402143fc93452ee44dd))
* **flow:** add decompose skill ([#60](https://github.com/NoNameItem/claude-tools/issues/60)) ([4195a99](https://github.com/NoNameItem/claude-tools/commit/4195a99528935ae7708af5553c3f0ffeda0401e6))
* **flow:** add emoji and bold formatting to task tree ([#59](https://github.com/NoNameItem/claude-tools/issues/59)) ([b720851](https://github.com/NoNameItem/claude-tools/commit/b7208518b41c0055e30bb403740807f442c15972))
* **flow:** add plan cleanup step to completing-task skill ([#56](https://github.com/NoNameItem/claude-tools/issues/56)) ([2a9cb5f](https://github.com/NoNameItem/claude-tools/commit/2a9cb5f920396a868f7081cb718a29dc3d5be2a1))
* **flow:** add project initialization after worktree creation ([#53](https://github.com/NoNameItem/claude-tools/issues/53)) ([5947e4a](https://github.com/NoNameItem/claude-tools/commit/5947e4a87d7da4e359e967778d35221c91aa915e))
* **flow:** add review-comments skill ([#58](https://github.com/NoNameItem/claude-tools/issues/58)) ([3d9cf95](https://github.com/NoNameItem/claude-tools/commit/3d9cf9530da56d10604949678534efa791623886))
* **flow:** add sonar-sync skill ([#57](https://github.com/NoNameItem/claude-tools/issues/57)) ([92f724e](https://github.com/NoNameItem/claude-tools/commit/92f724ebc77ca42e65088b14f8ee9b5a4943ab1f))


### Bug Fixes

* **flow:** add subtask selection to flow:start ([#49](https://github.com/NoNameItem/claude-tools/issues/49)) ([7488f1d](https://github.com/NoNameItem/claude-tools/commit/7488f1d9f93eb29c04e6936c44af55a28175caed))


### Documentation

* **flow:** add user-facing plugin documentation ([#63](https://github.com/NoNameItem/claude-tools/issues/63)) ([3bf4442](https://github.com/NoNameItem/claude-tools/commit/3bf4442f14ba66123f894242c6f833b3687ac3a4))

## [1.5.0](https://github.com/NoNameItem/claude-tools/compare/flow-1.4.1...flow-1.5.0) (2026-01-29)


### Features

* **flow:** add bd-tree.py script for task tree building ([21df417](https://github.com/NoNameItem/claude-tools/commit/21df417bde9f78857941642edefc47bdae9fbae8))
* **flow:** add command files for slash commands ([4c3aca6](https://github.com/NoNameItem/claude-tools/commit/4c3aca6694ff26e62f5ad3138181bad5276113b8))
* **flow:** add worktree integration to starting-task skill ([7e44708](https://github.com/NoNameItem/claude-tools/commit/7e447086272794c61a31f1d5776013276cec74dd))
* **flow:** enhance branch naming with type prefixes and existing branch search ([75beee2](https://github.com/NoNameItem/claude-tools/commit/75beee20dea6ab78227af3bfe4165a787005a9fc))
* **flow:** update flow:start skill for hierarchical task display ([c681ed6](https://github.com/NoNameItem/claude-tools/commit/c681ed6256610635ae98b3b5d89d1396c31c48b1))
* implement flow:after-design skill for beads workflow ([1d8722d](https://github.com/NoNameItem/claude-tools/commit/1d8722d77424f09851871986a3c845023fe78b19))
* implement flow:after-plan skill for beads workflow ([70e5e2c](https://github.com/NoNameItem/claude-tools/commit/70e5e2cdd2a095a359db92a8fb7af1d3f6a54c13))
* implement flow:done skill - complete flow plugin suite ([45a30af](https://github.com/NoNameItem/claude-tools/commit/45a30af3da3af1cacd3ce3aef6bf8363733f741b))
* implement flow:start skill for beads workflow ([5cc92ec](https://github.com/NoNameItem/claude-tools/commit/5cc92ec1ad8f9b0531752639a5f6005d13771734))


### Bug Fixes

* correct plugin.json schema to match Claude Code requirements ([8324cd0](https://github.com/NoNameItem/claude-tools/commit/8324cd0042d44e84d7f9275848de8d6d9589100b))
* **flow:** add STOP-AND-READ section to prevent premature command execution ([f3ace1f](https://github.com/NoNameItem/claude-tools/commit/f3ace1f2b770b17ca598d8bf141346d18141cc47))
* **flow:** allow task closure on feature branches with existing PR ([#15](https://github.com/NoNameItem/claude-tools/issues/15)) ([9b7e883](https://github.com/NoNameItem/claude-tools/commit/9b7e883872c7e8b362015817a257485481038de9))
* **flow:** fix bd-tree.py tree formatting and null handling ([9ae62b3](https://github.com/NoNameItem/claude-tools/commit/9ae62b332cf6183c157676be0d3c53555fc03791))
* **flow:** prevent premature command execution in flow commands ([10bf992](https://github.com/NoNameItem/claude-tools/commit/10bf992a56b0e39fbece89cf466b3b9e19875461))
* **flow:** remove disable-model-invocation flag from commands ([870e409](https://github.com/NoNameItem/claude-tools/commit/870e4096a52fff4b2d28155227db2f32157fe205))
* **flow:** renamed skills to resolve name conflict with commands ([3cf595c](https://github.com/NoNameItem/claude-tools/commit/3cf595c38247bc3305f8d1f95811b78fef1e3bfe))
* **flow:** restore simple skill invocation in command files ([460379f](https://github.com/NoNameItem/claude-tools/commit/460379ff8fcde4d6eab82ea7fc0a9a8f49d489e0))
* **flow:** skills autocomplete ([5efd89d](https://github.com/NoNameItem/claude-tools/commit/5efd89d82a20c62d200df948f36b26cd0e42dddc))
* **flow:** strengthen flow:start skill with CRITICAL section and validation ([5f0bb44](https://github.com/NoNameItem/claude-tools/commit/5f0bb4420c8c095396723c3b16de1bb3d40e88f9))
* **flow:** use &lt;skill-base-dir&gt; for script path in starting-task skill ([3c0ee13](https://github.com/NoNameItem/claude-tools/commit/3c0ee13eb743277ff34a1ab752726bb8599fbbf4))
* remove non-existent skills from plugin.json ([348873d](https://github.com/NoNameItem/claude-tools/commit/348873d0b379cf8ead446910e00b38153f4b1914))

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
