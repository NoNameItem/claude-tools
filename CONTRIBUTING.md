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

Каждый PR — и каждый коммит — должен затрагивать **не более одного проекта**. Repo-level
файлы (всё, что лежит вне `packages/*` и `plugins/*`) в этот счёт не входят и могут ехать
вместе с проектом в одном PR.

```
✅ только packages/statuskit/
✅ только plugins/flow/
✅ только .github/ и docs/                  — repo-level, scope не нужен
✅ plugins/flow/ + .github/ + docs/         — один проект и repo-level файлы
❌ packages/statuskit/ + plugins/flow/      — два проекта
```

**Scope следует из проекта, а не из того, каких файлов больше.** Есть файлы проекта — scope
равен его имени (`feat(flow): …`), даже если в том же PR правятся repo-level файлы. Файлов
проекта нет вовсе — scope опускается (`ci: …`, `docs: …`).

**Почему:** независимое версионирование пакетов. Release-please группирует изменения по scope
и создаёт отдельные релизы для каждого пакета. Repo-level файлы не относятся ни к одному
релизу, поэтому их соседство с проектом ничего не ломает — ломает только второй проект.

Правило проверяется автоматически, `.github/scripts/validate.py`: pre-commit хук на каждом
коммите и job в `pr.yml` на заголовке PR. Если этот текст расходится с поведением CI — баг
в тексте.

### PR Title

PR title должен следовать формату conventional commit — он станет сообщением squash-коммита в main.

```
feat(statuskit): add git module
```

### Labels

PR должен иметь label соответствующий scope в заголовке:

| Scope | Label | Описание |
|-------|-------|----------|
| `statuskit` | `statuskit` | Python statusline package |
| `beadboard` | `beadboard` | Python TUI for beads |
| `flow` | `flow` | Beads workflow plugin |
| без scope | `repo` | Repository-level changes |

```
PR title: feat(statuskit): add git module
Label: statuskit

PR title: ci: add release workflow
Label: repo
```

### PR Description

PR description должен объяснять **как работает** изменение, а не просто перечислять файлы.

**Шаблон:**

```markdown
## Summary
<зачем это нужно — 1-2 предложения>

## How it works

### Overview
<общая картина — что делает, какую проблему решает>

### Architecture
<как устроено — компоненты, их связи, поток данных>
<диаграммы в ASCII если помогают понять>

### Key components

**`path/to/file.py`** — <роль файла>
- `ClassName` — <что делает класс>
- `function_name()` — <что делает функция>

### Design decisions
<почему выбран такой подход, какие альтернативы рассматривались>

### Edge cases
<какие граничные случаи обработаны>

## Test plan
<как проверить — команды, сценарии>

## Related issues
<ссылки на beads/github issues или "None">
```

**Опциональные секции** (добавлять когда актуально):
- `## Breaking changes` — что сломается, как мигрировать
- `## Screenshots` — для UI изменений
- `## Performance` — если влияет на скорость

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
│   ├── statuskit/      # scope: statuskit
│   └── beadboard/      # scope: beadboard
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
- Все изменённые файлы относятся не более чем к одному проекту; repo-level файлы
  (вне `packages/*` и `plugins/*`) в счёт не идут и допускаются в любом количестве
- Если в staged files есть файлы из **двух** проектов → коммит блокируется

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
uv run ty check
# без пути — иначе тесты и соседние пакеты молча пропускаются
```

## Adding a New Python Package

When adding a new Python package to `packages/`, you need to configure SonarCloud.

### 1. Create Package Structure

```
packages/
└── new-package/
    ├── pyproject.toml      # With Python classifiers
    ├── CHANGELOG.md
    ├── src/new_package/
    │   └── __init__.py
    └── tests/
```

**pyproject.toml must include classifiers:**
```toml
[project]
name = "claude-new-package"
version = "0.1.0"
classifiers = [
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
]
```

### 2. Create SonarCloud Project

**Without this step, CI will fail with "Project not found".**

1. Go to [SonarCloud](https://sonarcloud.io) → nonameitem org
2. Click ✚ → "Analyze new project" → "Setup a monorepo"
3. Select `NoNameItem/claude-tools`
4. Set project key: `NoNameItem_<package-name>` (e.g., `NoNameItem_statuskit`)
5. Administration → New Code: Previous Version
6. Administration → Quality Gate: **NoNameItem way** (the organisation default `Sonar way no coverage` is not used by any project here)
7. Administration → Analysis Method: **verify Automatic Analysis is off** — the *Setup a
   monorepo* flow in step 2 already sets `sonar.autoscan.enabled = false` (non-inherited) for you,
   so this is a check, not an action. A project created through an ordinary (non-monorepo)
   "Analyze new project" import does **not** get this for free and must have it turned off here
   manually (Administration → Analysis Method), or it collides with the CI analysis.
8. Administration → General → Main branch: master

### 3. Wire the package into the repository

1. Root `pyproject.toml`: `[tool.uv.sources] <name> = { workspace = true }` **and** `<name>` in
   the `dev` dependency group — without both, `uv sync` does not install the package and its
   tests cannot import it. Run `uv sync`.
2. `release-please-config.json`: an entry under `packages` (`release-type: python`,
   `bump-minor-pre-major`, `prerelease`, `extra-label: "ci:full,<name>"`).
3. `.release-please-manifest.json`: `"packages/<name>": "0.0.0"` — release-please treats the
   value as the version *already released*, so `0.0.0` makes the first `feat:` release `0.1.0`.
   Do not seed `CHANGELOG.md`; release-please writes it.
4. `packages/<name>/sonar-project.properties`: rule mutes only, each with a written reason.
5. GitHub: create the PR label `<name>` (`gh label create <name> --color <hex>`).
6. `.coderabbit.yaml`: a `path_instructions` entry for `packages/<name>/**`.
7. `CLAUDE.md` and this file: the commit-scope and label tables, plus the project trees.
8. PyPI: register a pending publisher (owner `NoNameItem`, repository `claude-tools`, workflow
   `publish.yml`, environment `pypi`) — it reserves the name before the first release.

Nothing else needs touching: the CI matrices, the lint/test/Sonar jobs, `sonar.projectKey`, `ty`,
pytest `testpaths` and commit-scope validation are all derived from `[tool.repo]` and from paths.
The master ruleset requires the aggregate `Python CI Gate` context, so new per-project jobs need
no ruleset change.

### 4. Verify CI

1. Create a PR with changes in your package
2. Check that all jobs pass:
   - ✅ lint
   - ✅ test (all Python versions)
   - ✅ sonarcloud
3. Check PR for SonarCloud status check and summary comment
4. Merge the PR and confirm the `sonarcloud` job ran on that `master` push and the analysis is visible in SonarCloud — **before the first release is cut.**

**Why this matters:** the release notification (`sonar_pr_status.py --mode release`, run from `publish.yml`) polls `project_analyses/search` for the release commit's analysis, but an *empty* response — indistinguishable from "project has no analyses yet" — ends the wait immediately instead of retrying. If `master` has never had an analysis for this project, the first release notification permanently ships with no Sonar blocks at all, even if the analysis lands seconds later.

## Authoring Flow Skills

### Never use `AskUserQuestion` in flow skills

flow skills must ask every interactive question with a **plain-text numbered prompt** that ends
the turn and waits for the user's reply. Do **not** call the `AskUserQuestion` tool.

Why: the Claude Code `AskUserQuestion` dialog **auto-submits its pre-selected (first) option**
after the AFK idle timeout (`CLAUDE_AFK_TIMEOUT_MS`, default 60s; harness v2.1.198+). For a flow
prompt that gates an irreversible action — creating a branch/worktree, changing task
status/assignee, or `git push` — that means the action happens **without the user's consent** when
they are simply busy in another parallel session. Plain-text prose questions and permission prompts
are never auto-resolved, so they are structurally safe.

- Template: `plugins/flow/skills/continue/SKILL.md` Step 7b (numbered options, then wait).
- A no-response is **not** consent — never create branches/worktrees, mutate task/repo state, or
  push until the user actually answers.
- CI guard: `_reusable-claude-code-plugin-ci.yml` fails if any `plugins/flow/skills/**/SKILL.md`
  contains the token `AskUserQuestion`.
- To disable the harness auto-continue on your machine: `/config` or `CLAUDE_AFK_TIMEOUT_MS`.

See `claude-tools-6q4` and `docs/superpowers/specs/2026-07-04-flow-remove-askuserquestion-design.md`.
