# Release-please Setup Design

## Overview

Настройка release-please для автоматического создания релизов в monorepo с независимыми пакетами.

## Ключевые решения

| Аспект | Решение |
|--------|---------|
| Версионирование | Независимое для каждого пакета |
| Формат тегов | `{name}-{semver}` (без `v`) |
| Release PRs | Отдельный для каждого пакета |
| statuskit | `release-type: python`, pre-release mode |
| flow | `release-type: simple`, явный `extra-files` |
| После мержа | GitHub Release + тег |
| Публикация | Отдельный workflow (задача 5dl.2.5) |

## Конфигурация

### release-please-config.json

Размещение: корень репозитория.

```json
{
  "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
  "separate-pull-requests": true,
  "include-v-in-tag": false,
  "tag-separator": "-",
  "pull-request-title-pattern": "chore(${component}): release ${version}",
  "changelog-sections": [
    {"type": "feat", "section": "Features"},
    {"type": "fix", "section": "Bug Fixes"},
    {"type": "perf", "section": "Performance"},
    {"type": "revert", "section": "Reverts"},
    {"type": "docs", "section": "Documentation"},
    {"type": "chore", "hidden": true},
    {"type": "refactor", "hidden": true},
    {"type": "test", "hidden": true}
  ],
  "packages": {
    "packages/statuskit": {
      "package-name": "statuskit",
      "release-type": "python",
      "changelog-path": "CHANGELOG.md",
      "bump-minor-pre-major": true,
      "prerelease": true
    },
    "plugins/flow": {
      "package-name": "flow",
      "release-type": "simple",
      "changelog-path": "CHANGELOG.md",
      "extra-files": [
        {
          "type": "json",
          "path": ".claude-plugin/plugin.json",
          "jsonpath": "$.version"
        }
      ]
    }
  }
}
```

**Настройки:**

| Параметр | Значение | Зачем |
|----------|----------|-------|
| `separate-pull-requests` | `true` | Отдельный Release PR для каждого пакета |
| `include-v-in-tag` | `false` | Теги без `v`: `statuskit-0.2.0` |
| `tag-separator` | `-` | Разделитель между именем и версией |
| `pull-request-title-pattern` | `chore(${component}): release ${version}` | Совместимость с валидацией коммитов |
| `changelog-sections` | см. выше | docs видимы, chore/refactor/test скрыты |

**Настройки statuskit:**

| Параметр | Значение | Зачем |
|----------|----------|-------|
| `release-type` | `python` | Понимает pyproject.toml, PEP 440 версии |
| `bump-minor-pre-major` | `true` | Breaking changes → minor пока версия < 1.0.0 |
| `prerelease` | `true` | GitHub Release помечается как pre-release |

**Настройки flow:**

| Параметр | Значение | Зачем |
|----------|----------|-------|
| `release-type` | `simple` | Минимальный, без языковой специфики |
| `extra-files` | plugin.json | Явное указание файла версии |

### .release-please-manifest.json

Размещение: корень репозитория.

```json
{
  "packages/statuskit": "0.1.0",
  "plugins/flow": "1.4.1"
}
```

Хранит текущие версии пакетов. Обновляется автоматически при мерже Release PR.

### .github/workflows/release-please.yml

```yaml
name: Release Please

on:
  push:
    branches:
      - main

permissions:
  contents: write
  pull-requests: write

jobs:
  release-please:
    runs-on: ubuntu-latest
    steps:
      - uses: googleapis/release-please-action@v4
        with:
          config-file: release-please-config.json
          manifest-file: .release-please-manifest.json
```

## CHANGELOG файлы

Формат: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Размещение:
- `packages/statuskit/CHANGELOG.md`
- `plugins/flow/CHANGELOG.md`

Release-please автоматически обновляет CHANGELOG при создании Release PR.

### Начальный CHANGELOG для statuskit

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-01-19

### Added

- Modular statusline architecture with plugin system
- Built-in module `model` displaying:
  - Current Claude model name
  - Session duration (e.g., `2h 15m`)
  - Context window usage with color coding (green/yellow/red)
  - Multiple display formats: `free`, `used`, `ratio`, `bar`
  - Compact number formatting option (e.g., `150k` instead of `150,000`)
- CLI interface with `--version` and `--help`
- Setup command for hook installation:
  - `statuskit setup` — interactive installation
  - `statuskit setup --check` — verify installation
  - `statuskit setup --remove` — uninstall hook
- Hierarchical config loading (global → project → local)
- Automatic detection of higher-scope installations
- Backup creation before modifying settings
- Gitignore handling for local scope configs

### Fixed

- Type checker warnings resolved
```

### Начальный CHANGELOG для flow

```markdown
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
- `bd-tree.py` script for task tree building (`├─`, `└─` connectors)
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
```

## Добавление нового проекта

При добавлении нового пакета или плагина:

1. Создать директорию проекта
2. Добавить в `release-please-config.json`:
   ```json
   "packages/new-package": {
     "package-name": "new-package",
     "release-type": "python",  // или "simple" для плагинов
     "changelog-path": "CHANGELOG.md"
   }
   ```
3. Добавить в `.release-please-manifest.json`:
   ```json
   "packages/new-package": "0.1.0"
   ```
4. Создать `packages/new-package/CHANGELOG.md` с начальной версией

## Процесс релиза

```
1. Push в main с conventional commits
   ↓
2. release-please создаёт/обновляет Release PR
   - Заголовок: "chore(statuskit): release 0.2.0"
   - Обновляет CHANGELOG.md
   - Обновляет версию в pyproject.toml / plugin.json
   ↓
3. Review и мерж Release PR
   ↓
4. release-please создаёт GitHub Release + тег
   - Тег: statuskit-0.2.0
   - Release помечен как pre-release (для statuskit)
   ↓
5. Publish workflow (задача 5dl.2.5) триггерится на release
```

## Deliverables

- [ ] `release-please-config.json`
- [ ] `.release-please-manifest.json`
- [ ] `.github/workflows/release-please.yml`
- [ ] `packages/statuskit/CHANGELOG.md`
- [ ] `plugins/flow/CHANGELOG.md`
