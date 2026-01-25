# CI Validation Scripts Design

Task: claude-tools-5dl.2.1

## Overview

Python скрипты для валидации PR и детекции изменений в monorepo. Обеспечивают корректное версионирование пакетов через release-please.

**Цели:**
- PR содержит изменения только одного пакета (для независимого версионирования)
- PR title соответствует conventional commits
- Автоматическое определение затронутых пакетов для CI matrix

## Deliverables

```
.github/scripts/
├── validate.py
├── detect_changes.py
└── tests/
    ├── conftest.py
    ├── test_validate.py
    └── test_detect_changes.py

.pre-commit-config.yaml  # Добавить hook single-package-commit
```

## validate.py

### Режимы работы

**Режим hook** — pre-commit проверка staged files:
```bash
python validate.py --hook
```

Проверяет:
- Все staged файлы относятся к одному пакету (или все repo-level)
- Не проверяет формат сообщения (его ещё нет)

Получает файлы через `git diff --cached --name-only`.

**Режим PR** — валидация pull request:
```bash
python validate.py --pr
```

Переменные окружения:
- `PR_TITLE` — заголовок PR (из `${{ github.event.pull_request.title }}`)
- `BASE_REF` — целевая ветка (из `${{ github.base_ref }}`)

Проверяет:
1. PR title — conventional commit формат
2. One-package rule — все файлы PR относятся к одному пакету

**Режим commits** — валидация коммитов в main:
```bash
python validate.py --commits <before> <after>
```

Проверяет каждый коммит в диапазоне:
1. Сообщение — conventional commit формат
2. Scope — соответствует изменённым файлам

### Conventional Commit Format

```
type(scope): description

[optional body]

[optional footer]
```

**Types:** feat, fix, docs, style, refactor, test, chore, ci, revert, build, perf

**Scope:**
- Имя пакета/плагина — если изменены файлы в `packages/*/` или `plugins/*/`
- Пустой — если изменены только repo-level файлы
- Breaking changes: `type(scope)!:` или `BREAKING CHANGE:` footer — принимаем как есть

**Примеры:**
```
feat(statuskit): add git module          ✓ пакет
fix(flow): correct skill loading         ✓ плагин
ci: add release workflow                 ✓ repo-level, без scope
docs: update contributing guide          ✓ repo-level, без scope
feat: add feature                        ✗ куда? нужен scope
chore(statuskit): update ci              ✗ .github/* не в statuskit
```

### Определение пакетов

Автоопределение при запуске:
1. Сканируем `packages/*/` — имена директорий = имена пакетов
2. Сканируем `plugins/*/` — имена директорий = имена плагинов
3. Проверяем на коллизии — если имя есть и там, и там → ошибка

**Коллизия scope:**
```
✗ Scope collision detected

  Name 'flow' exists in both:
    - packages/flow/
    - plugins/flow/

  Rename one to ensure unique scope names.
```

### Правила валидации

**One-package rule (режим --pr):**
- Определяем пакеты по изменённым файлам
- Если изменён 1 пакет → scope в title должен совпадать
- Если изменено 0 пакетов (только repo-level) → scope должен быть пустым
- Если изменено >1 пакета → ошибка

**Repo-level файлы** — всё что не в `packages/*/` и не в `plugins/*/`:
- `.github/**`
- `docs/**`
- `*.md` в корне
- `pyproject.toml`, `uv.lock` в корне
- `.gitignore`, `.editorconfig`, etc.

При смешанных изменениях (пакет + repo-level) — repo-level файлы игнорируются:
```
feat(statuskit): add httpx client        ✓
  - packages/statuskit/src/client.py     → пакет
  - pyproject.toml                       → игнорируется
  - uv.lock                              → игнорируется
```

**Запрещённые коммиты:**

Merge commits:
```
✗ Merge commits not allowed

  Found: Merge branch 'feature/x' into main

  Use squash merge for pull requests.
  Configure repository: Settings → General → Pull Requests → Allow squash merging only
```

Revert в неправильном формате:
```
✗ Invalid revert format

  Got: Revert "feat(statuskit): add feature"
  Expected: revert(statuskit): add feature

  Use conventional commit format for reverts.
```

### Exit Codes

| Code | Значение |
|------|----------|
| 0 | Успех |
| 1 | Неверный формат conventional commit |
| 2 | Scope не соответствует файлам |
| 3 | Изменено больше одного пакета |
| 4 | Коллизия scope (packages/ и plugins/) |
| 10 | Ошибка скрипта (git, env vars, etc.) |

### Формат сообщений

**Успех:**
```
✓ PR title valid: feat(statuskit): add git module
✓ Changed packages: statuskit
✓ Scope matches changed files
```

**Ошибки:**

Неверный формат:
```
✗ Invalid conventional commit format

  Expected: type(scope): description
  Got:      add new feature

  Valid types: feat, fix, docs, style, refactor, test, chore, ci, revert, build, perf
  Scope: package name (statuskit, flow) or empty for repo-level changes
```

Scope mismatch:
```
✗ Scope mismatch

  PR title scope: statuskit
  Changed packages: flow

  The scope in PR title must match the changed package.
```

Multiple packages:
```
✗ Multiple packages changed

  Changed packages: statuskit, flow

  Each PR should modify only one package.
  Split into separate PRs for independent versioning.
```

## detect_changes.py

### Интерфейс

```bash
# Из stdin
git diff --name-only origin/main..HEAD | python detect_changes.py

# Из git ref
python detect_changes.py --ref origin/main..HEAD
```

### Output Format

```json
{
  "packages": ["statuskit"],
  "has_packages": true,
  "has_repo_level": true,
  "tooling_changed": false,
  "matrix": {
    "include": [
      {"package": "statuskit", "path": "packages/statuskit", "python": "3.10"},
      {"package": "statuskit", "path": "packages/statuskit", "python": "3.11"},
      {"package": "statuskit", "path": "packages/statuskit", "python": "3.12"}
    ]
  },
  "all_packages_matrix": {
    "include": [
      {"package": "statuskit", "path": "packages/statuskit", "python": "3.10"},
      {"package": "statuskit", "path": "packages/statuskit", "python": "3.11"},
      {"package": "statuskit", "path": "packages/statuskit", "python": "3.12"}
    ]
  }
}
```

**Поля:**
- `packages` — список затронутых пакетов
- `has_packages` — есть ли изменения в пакетах
- `has_repo_level` — есть ли изменения в repo-level файлах
- `tooling_changed` — изменился root pyproject.toml или uv.lock (без пакетов)
- `matrix` — для CI matrix (только изменённые пакеты)
- `all_packages_matrix` — для tooling check (все пакеты)

### Python Versions

Парсим из classifiers в `pyproject.toml` каждого пакета:

```toml
[project]
classifiers = [
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
```

**Если classifiers отсутствуют — ошибка:**
```
✗ Missing Python version classifiers

  Package: statuskit
  File: packages/statuskit/pyproject.toml

  Add classifiers like:
    classifiers = [
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ]
```

### Tooling Changes

**Триггеры:**
- Root `pyproject.toml` изменился
- `uv.lock` изменился без изменений в пакетах

**Результат:**
- `tooling_changed: true`
- `all_packages_matrix` заполнен всеми пакетами
- CI запускает проверку всех пакетов в warning mode

## CI Integration

### PR Workflow

```yaml
name: PR Validation

on:
  pull_request:
    branches: [main]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Validate PR
        env:
          PR_TITLE: ${{ github.event.pull_request.title }}
          BASE_REF: ${{ github.base_ref }}
        run: python .github/scripts/validate.py --pr

  detect:
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.detect.outputs.matrix }}
      has_packages: ${{ steps.detect.outputs.has_packages }}
      tooling_changed: ${{ steps.detect.outputs.tooling_changed }}
      all_packages_matrix: ${{ steps.detect.outputs.all_packages_matrix }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Detect changes
        id: detect
        run: |
          OUTPUT=$(python .github/scripts/detect_changes.py --ref origin/${{ github.base_ref }}..HEAD)
          echo "matrix=$(echo $OUTPUT | jq -c .matrix)" >> $GITHUB_OUTPUT
          echo "has_packages=$(echo $OUTPUT | jq -r .has_packages)" >> $GITHUB_OUTPUT
          echo "tooling_changed=$(echo $OUTPUT | jq -r .tooling_changed)" >> $GITHUB_OUTPUT
          echo "all_packages_matrix=$(echo $OUTPUT | jq -c .all_packages_matrix)" >> $GITHUB_OUTPUT

  test:
    needs: detect
    if: needs.detect.outputs.has_packages == 'true'
    runs-on: ubuntu-latest
    strategy:
      matrix: ${{ fromJson(needs.detect.outputs.matrix) }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}

      - name: Install dependencies
        run: uv sync --all-packages

      - name: Lint
        run: ruff check ${{ matrix.path }}

      - name: Type check
        run: ty check ${{ matrix.path }}

      - name: Test
        run: pytest ${{ matrix.path }}/tests

  tooling-check:
    needs: detect
    if: needs.detect.outputs.tooling_changed == 'true'
    runs-on: ubuntu-latest
    strategy:
      matrix: ${{ fromJson(needs.detect.outputs.all_packages_matrix) }}
    continue-on-error: true  # Warning, not blocking
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}

      - name: Install dependencies
        run: uv sync --all-packages

      - name: Lint (tooling check)
        run: ruff check ${{ matrix.path }}

      - name: Type check (tooling check)
        run: ty check ${{ matrix.path }}

      - name: Test (tooling check)
        run: pytest ${{ matrix.path }}/tests
```

### Main Branch Workflow

```yaml
name: Main Branch Validation

on:
  push:
    branches: [main]

jobs:
  validate-commits:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Validate commits
        run: |
          python .github/scripts/validate.py --commits ${{ github.event.before }} ${{ github.event.after }}
```

## Pre-commit Hook

### Конфигурация

Добавить в существующий `.pre-commit-config.yaml`:
```yaml
  - repo: local
    hooks:
      # ... existing hooks ...

      - id: single-package-commit
        name: Check single package per commit
        entry: uv run python .github/scripts/validate.py --hook
        language: system
        always_run: true
        pass_filenames: false
```

### Установка

```bash
uv run pre-commit install
```

### Поведение

**Что проверяется:**
- Staged файлы (из `git diff --cached --name-only`)
- Все файлы должны относиться к одному пакету или все быть repo-level

**Успех:**
```
✓ Single package: statuskit
```
или
```
✓ Repo-level changes only
```

**Ошибка:**
```
✗ Multiple packages in one commit

  Staged files from multiple packages:
  - statuskit: packages/statuskit/src/module.py
  - flow: plugins/flow/skills/start.md

  Create separate commits for each package:
  1. git reset HEAD plugins/flow/
  2. git commit -m "feat(statuskit): ..."
  3. git add plugins/flow/
  4. git commit -m "feat(flow): ..."
```

Exit code: 3 (multi-package)

### Обход

```bash
git commit --no-verify -m "..."
```

Коммит будет создан, но не пройдёт CI.

## Testing

### Test Structure

```
.github/scripts/tests/
├── conftest.py           # Shared fixtures
├── test_validate.py      # validate.py tests
└── test_detect_changes.py # detect_changes.py tests
```

### Test Cases

**validate.py:**
- Парсинг conventional commits (valid/invalid formats)
- Scope matching (package, plugin, repo-level, mixed)
- One-package rule violations
- Merge commit detection
- Revert format validation
- Scope collision detection
- Edge cases: breaking changes, empty scope, special characters
- Hook mode: staged files from one package, multiple packages, repo-level only

**detect_changes.py:**
- Package detection from file paths
- Python version parsing from classifiers
- Missing classifiers error
- Tooling change detection (root pyproject.toml, uv.lock)
- Matrix generation
- Mixed changes (packages + repo-level)

### Fixtures

```python
# conftest.py
import pytest
from pathlib import Path
import tempfile
import subprocess

@pytest.fixture
def temp_repo():
    """Create a temporary git repo with packages structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)

        # Init git
        subprocess.run(["git", "init"], cwd=repo)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo)

        # Create structure
        (repo / "packages/statuskit/src").mkdir(parents=True)
        (repo / "packages/statuskit/pyproject.toml").write_text('''
[project]
name = "statuskit"
classifiers = [
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
''')
        (repo / "plugins/flow").mkdir(parents=True)

        yield repo
```

## Summary

**Ключевые решения:**
1. Один скрипт validate.py с тремя режимами (--hook, --pr, --commits)
2. Pre-commit hook для раннего фидбека (one-package check)
3. Автоопределение пакетов из packages/ и plugins/ с проверкой коллизий
4. Scope обязателен для пакетов, запрещён для repo-level
5. One-package rule на уровне PR и коммита
6. Squash-only merge (merge commits запрещены)
7. Python версии из classifiers (обязательны)
8. Tooling changes (root pyproject.toml, uv.lock) — warning mode для всех пакетов
