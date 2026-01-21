# Contributing Guide

## Commit Messages

Все коммиты должны следовать формату [Conventional Commits](https://www.conventionalcommits.org/).

### Формат

```
type(scope): description

[optional body]

[optional footer]
```

### Types

| Type | Когда использовать |
|------|-------------------|
| `feat` | Новая функциональность |
| `fix` | Исправление бага |
| `docs` | Изменения в документации |
| `style` | Форматирование, пробелы, точки с запятой |
| `refactor` | Рефакторинг без изменения поведения |
| `test` | Добавление или исправление тестов |
| `chore` | Обслуживание, обновление зависимостей |
| `ci` | Изменения в CI/CD |
| `build` | Изменения в системе сборки |
| `perf` | Улучшение производительности |
| `revert` | Откат предыдущего коммита |

### Scope

**Для изменений в пакетах/плагинах** — scope обязателен, равен имени пакета:

```
feat(statuskit): add git module
fix(flow): correct skill loading
```

**Для repo-level файлов** — scope не указывается:

```
ci: add release workflow
docs: update contributing guide
chore: update dependencies
```

### Примеры

```bash
# Добавление фичи в пакет
feat(statuskit): add quota tracking module

# Исправление бага в плагине
fix(flow): handle missing task gracefully

# Изменение CI
ci: add SonarCloud integration

# Обновление документации
docs: add API reference

# Обновление зависимостей
chore: update pytest to 8.0

# Breaking change (с восклицательным знаком)
feat(statuskit)!: change config format

# Или с footer
feat(statuskit): change config format

BREAKING CHANGE: config.toml format changed, see migration guide
```

## Pull Requests

### Одно изменение — один PR

Каждый PR должен затрагивать **только один пакет** (или только repo-level файлы).

```
✅ PR меняет только packages/statuskit/
✅ PR меняет только plugins/flow/
✅ PR меняет только .github/ и docs/
❌ PR меняет и packages/statuskit/ и plugins/flow/
```

**Почему:** независимое версионирование пакетов. Release-please группирует изменения по scope и создаёт отдельные релизы для каждого пакета.

### PR Title

PR title должен следовать формату conventional commit — он станет сообщением squash-коммита в main.

```
feat(statuskit): add git module
```

### Merge Strategy

Используется **squash merge**. Все коммиты PR объединяются в один коммит с сообщением = PR title.

Это значит:
- В PR можно делать WIP коммиты, fixup, и т.д.
- Главное — правильный PR title
- История в main остаётся чистой

## Частые ошибки и как исправить

### Неверный формат коммита

```
❌ add new feature
❌ Added new feature
❌ feat - add new feature
```

**Как исправить:**
```bash
git commit --amend -m "feat(statuskit): add new feature"
```

### Забыл scope для пакета

```
❌ feat: add git module
   (меняет packages/statuskit/src/git.py)
```

**Как исправить:**
```bash
git commit --amend -m "feat(statuskit): add git module"
```

### Указал scope для repo-level файлов

```
❌ ci(github): add workflow
   (меняет только .github/workflows/)
```

**Как исправить:**
```bash
git commit --amend -m "ci: add workflow"
```

### Несколько пакетов в одном PR

```
❌ PR меняет packages/statuskit/ и packages/another/
```

**Как исправить:**

Разбей на отдельные PR:
```bash
# Создай ветку для первого пакета
git checkout -b feature/statuskit-change
git cherry-pick <commits for statuskit>
git push -u origin feature/statuskit-change

# Создай ветку для второго пакета
git checkout main
git checkout -b feature/another-change
git cherry-pick <commits for another>
git push -u origin feature/another-change
```

### CI упал на валидации после push

Если уже запушил коммиты с неправильным форматом:

```bash
# Исправить последний коммит
git commit --amend -m "feat(statuskit): correct message"
git push --force-with-lease

# Исправить несколько коммитов
git rebase -i origin/main
# В редакторе: измени 'pick' на 'reword' для нужных коммитов
git push --force-with-lease
```

## Структура проекта

```
claude-tools/
├── packages/           # Python пакеты (PyPI)
│   └── statuskit/      # scope: statuskit
├── plugins/            # Claude Code плагины
│   └── flow/           # scope: flow
├── .github/            # CI/CD (без scope)
├── docs/               # Документация (без scope)
└── pyproject.toml      # Workspace config (без scope)
```

## Локальная разработка

### Установка зависимостей

```bash
uv sync
```

### Pre-commit hooks

В проекте настроен pre-commit hook, который проверяет, что коммит не затрагивает несколько пакетов одновременно.

**Установка:**
```bash
uv run pre-commit install
```

**Что проверяется:**
- Все изменённые файлы относятся к одному пакету (или все repo-level)
- Если в staged files есть файлы из разных пакетов → коммит блокируется

**Пример ошибки:**
```
❌ Multiple packages in one commit

   Staged files from multiple packages:
   - statuskit: packages/statuskit/src/module.py
   - flow: plugins/flow/skills/start.md

   Create separate commits for each package:
   1. git reset HEAD plugins/flow/
   2. git commit -m "feat(statuskit): ..."
   3. git add plugins/flow/
   4. git commit -m "feat(flow): ..."
```

**Обход (если действительно нужно):**
```bash
git commit --no-verify -m "..."
```
Но такой коммит не пройдёт CI.

### Запуск тестов

```bash
# Все тесты
uv run pytest

# Тесты конкретного пакета
uv run pytest packages/statuskit/tests
```

### Линтинг

```bash
# Проверка
uv run ruff check .

# Автоисправление
uv run ruff check . --fix

# Форматирование
uv run ruff format .
```

### Type checking

```bash
uv run ty check packages/statuskit
```
