# CI/CD Pipeline Design

## Overview

GitHub Actions CI/CD для monorepo с независимыми Python пакетами и Claude Code плагинами.

## Этапы реализации

| # | Задача | Зависит от | Deliverables |
|---|--------|------------|--------------|
| 1 | Скрипты валидации | — | `validate_commits.py`, `detect_changes.py`, unit tests |
| 2 | CI для Python пакетов | 1 | `_reusable-python-ci.yml`, `ci.yml`, `_detect-changes.yml` |
| 3 | CI для плагинов | 1 | `plugins-ci.yml` |
| 4 | Release-please setup | 2 | Конфиг, workflow, CHANGELOG.md |
| 5 | Publish workflow | 4 | `_reusable-python-publish.yml` + smoke test |
| 6 | SonarCloud интеграция | 2 | `sonar-project.properties`, интеграция в CI |
| 7 | Branch protection | 5 | Настройки на GitHub |

```
[1] Скрипты валидации
 ↓
[2] CI Python ←──────┐
 ↓                   │
[3] CI плагинов      │
 ↓                   │
[4] Release-please ──┘
 ↓
[5] Publish
 ↓
[6] SonarCloud (параллельно с 4-5)
 ↓
[7] Branch protection
```

## Ключевые решения

| Аспект              | Решение                                            |
|---------------------|----------------------------------------------------|
| Релизы              | release-please (manifest mode)                     |
| Версионирование     | Независимое для каждого пакета                     |
| Структура workflows | Reusable workflows                                 |
| Детекция изменений  | Динамическая (скрипт определяет изменённые пакеты) |
| CI проверки         | lint + format + typecheck + tests + coverage       |
| Lint scope          | Только изменённые файлы в PR                       |
| Python версии       | Из classifiers в pyproject.toml                    |
| Coverage/анализ     | SonarCloud + импорт Ruff report                    |
| Quality gate        | SonarCloud (блокирует PR)                          |
| Release protection  | Branch protection + CI gate + Smoke test           |
| Commit validation   | Scope = path, один пакет на коммит                 |
| Публикация          | PyPI Trusted Publisher (OIDC)                      |
| Кэширование         | uv cache                                           |
| Code review         | Claude Code (существующий workflow)                |

## Архитектура workflow файлов

```
.github/
├── workflows/
│   ├── _reusable-python-ci.yml      # Reusable: lint, format, typecheck, tests, coverage
│   ├── _reusable-python-publish.yml # Reusable: build + publish to PyPI
│   ├── _detect-changes.yml          # Reusable: определение изменённых пакетов/файлов
│   ├── ci.yml                       # Caller: запускает CI для изменённых Python пакетов
│   ├── plugins-ci.yml               # CI для Claude Code плагинов
│   ├── release-please.yml           # Создаёт release PR, триггерит публикацию
│   ├── claude.yml                   # (существует) Claude Code для комментариев
│   └── claude-code-review.yml       # (существует) Claude Code review на PR
├── scripts/
│   ├── detect_changes.py            # Скрипт детекции изменений
│   ├── validate_commits.py          # Валидация коммитов (scope, single-package)
│   └── tests/                       # Unit tests для скриптов
│       ├── conftest.py
│       ├── test_detect_changes.py
│       └── test_validate_commits.py
├── release-please-config.json       # Конфигурация release-please
├── .release-please-manifest.json    # Версии пакетов
├── .actrc                           # Настройки act (локальный runner)
└── .env.act                         # Переменные для локального тестирования
```

## Reusable Python CI workflow

**Файл:** `_reusable-python-ci.yml`

**Входные параметры:**

```yaml
inputs:
  package:           # Имя пакета (например "statuskit")
  package-path:      # Путь к пакету (например "packages/statuskit")
  python-versions:   # JSON массив версий ["3.11", "3.14"]
  changed-files:     # JSON массив изменённых файлов (для точечного lint)
```

**Jobs:**

1. **lint-format-typecheck** (быстрый, без матрицы)
    - `ruff check` и `ruff format --check` только на `changed-files`
    - `ty check` на весь пакет (нужен полный контекст)
    - Генерирует Ruff report для SonarCloud (`ruff check --output-format=json`)
    - Python версия: минимальная из матрицы

2. **test** (матрица Python версий)
    - `uv sync` с кэшированием
    - `pytest --cov` с coverage в формате XML
    - Артефакт: coverage report

3. **sonarcloud** (после test)
    - Загружает coverage артефакты
    - Импортирует Ruff report
    - Запускает SonarCloud анализ
    - Quality gate решает судьбу PR

**Кэширование:**

- Ключ: `uv-{package}-{python-version}-{hash(pyproject.toml)}`
- Путь: `~/.cache/uv`

## Детекция изменений

**Файл:** `_detect-changes.yml`

**Выходные данные:**

```yaml
outputs:
  packages:       # JSON: [{"name": "statuskit", "path": "packages/statuskit", "python-versions": ["3.11", "3.14"], "changed-files": ["src/foo.py"]}]
  plugins:        # JSON: [{"name": "flow", "path": "plugins/flow", "changed-files": ["skills/start.md"]}]
  has-packages:   # Boolean
  has-plugins:    # Boolean
```

**Логика (в `.github/scripts/detect-changes.py`):**

1. Получить изменённые файлы:
    - PR: `git diff origin/main...HEAD --name-only`
    - Push в main: `git diff HEAD~1 --name-only`

2. Для `packages/*/`:
    - Определить пакет по пути
    - Парсить Python версии из classifiers в pyproject.toml
    - Сгруппировать файлы по пакетам

3. Для `plugins/*/`:
    - Определить плагин по пути
    - Сгруппировать файлы по плагинам

4. Сформировать JSON outputs

## Версионирование и Changelog

### Где хранится версия

| Тип компонента | Файл с версией | Как получить в коде |
|----------------|----------------|---------------------|
| Python пакет | `pyproject.toml` | `importlib.metadata.version("package-name")` |
| Claude Code плагин | `.claude-plugin/plugin.json` | — |

**Принцип:** Single Source of Truth. Версия в одном месте, код читает динамически.

**Пример для Python:**
```python
# packages/statuskit/src/statuskit/__init__.py
from importlib.metadata import version
__version__ = version("claude-statuskit")
```

### Где хранится Changelog

Changelog хранится рядом с компонентом:

```
packages/statuskit/CHANGELOG.md
plugins/flow/CHANGELOG.md
```

Release-please автоматически обновляет эти файлы при релизе.

## Release-please и публикация

**Конфигурация (manifest mode):**

`release-please-config.json`:

```json
{
  "packages": {
    "packages/statuskit": {
      "package-name": "claude-statuskit",
      "changelog-path": "CHANGELOG.md",
      "release-type": "python",
      "extra-files": [
        {
          "type": "toml",
          "path": "pyproject.toml",
          "jsonpath": "$.project.version"
        }
      ]
    },
    "plugins/flow": {
      "package-name": "flow",
      "changelog-path": "CHANGELOG.md",
      "release-type": "simple",
      "extra-files": [
        {
          "type": "json",
          "path": ".claude-plugin/plugin.json",
          "jsonpath": "$.version"
        }
      ]
    }
  },
  "separate-pull-requests": true
}
```

`.release-please-manifest.json`:

```json
{
  "packages/statuskit": "0.1.0",
  "plugins/flow": "1.3.2"
}
```

**Ключевые настройки:**

| Настройка | Значение | Зачем |
|-----------|----------|-------|
| `separate-pull-requests` | `true` | Отдельный release PR для каждого пакета |
| `release-type: python` | для пакетов | Понимает pyproject.toml |
| `release-type: simple` | для плагинов | Только version bump, без специфики |
| `jsonpath` | путь к версии | Точечное обновление в JSON/TOML |

**Workflow логика:**

1. Push в main → release-please создаёт/обновляет release PR (отдельный для каждого пакета)
2. Мерж release PR → GitHub Release + тег `statuskit-v0.2.0` или `flow-v1.4.0` → триггер публикации

**Файл:** `_reusable-python-publish.yml`

Шаги:

1. Checkout
2. `uv build`
3. `pypa/gh-action-pypi-publish` (Trusted Publisher, без токенов)

## Защита релизов

Три слоя защиты гарантируют, что в релиз не попадёт непротестированный или сломанный код.

### Слой 1: Branch Protection (GitHub Settings)

Настройки для ветки `main` (Settings → Branches → Add rule → `main`):

**Protect matching branches:**

| Настройка | Значение | Зачем |
|-----------|----------|-------|
| Require a pull request before merging | ✅ | Нет прямых пушей в main |
| Require approvals | По желанию | Code review (опционально для solo-проекта) |
| Require status checks to pass | ✅ | CI должен быть зелёным |
| Required checks | `validate`, `test` | Конкретные jobs из CI workflow |
| Require branches to be up to date | ✅ | PR должен быть актуален с main |
| Do not allow bypassing | ✅ | Даже админ не может обойти |
| Require linear history | ✅ | Запрещает merge commits |

**Rules applied to everyone including administrators:**

| Настройка | Значение | Зачем |
|-----------|----------|-------|
| Allow force pushes | ❌ | Защита истории |
| Allow deletions | ❌ | Нельзя удалить main |

**Merge button settings** (Settings → General → Pull Requests):

| Настройка | Значение | Зачем |
|-----------|----------|-------|
| Allow merge commits | ❌ | Запрещаем |
| Allow squash merging | ✅ | Единственный разрешённый способ |
| Allow rebase merging | ❌ | Запрещаем для консистентности |
| Default commit message | PR title | PR title становится commit message |

**Что происходит при нарушении:**

| Сценарий | Результат |
|----------|-----------|
| Push напрямую в main | Rejected: "protected branch" |
| PR с failed checks | Merge button disabled |
| PR с невалидным title | validate job fails → merge blocked |
| Admin пытается bypass | Rejected (Do not allow bypassing) |
| Force push в main | Rejected: "force push not allowed" |

**Как коммиты попадают в main:**

```
1. Developer creates PR
2. PR title: "feat(statuskit): add feature"
3. CI runs:
   - validate.py --pr (checks title format + one-package rule)
   - tests, lint, etc.
4. All checks pass → Merge button enabled
5. Click "Squash and merge"
6. GitHub creates single commit in main:
   - Message = PR title: "feat(statuskit): add feature"
   - All PR commits squashed into one
7. validate.py --commits runs on push to main (safety net)
```

**Настройка через GitHub CLI:**

```bash
# Branch protection
gh api repos/{owner}/{repo}/branches/main/protection -X PUT -f \
  required_status_checks='{"strict":true,"contexts":["validate","test"]}' \
  enforce_admins=true \
  required_pull_request_reviews=null \
  restrictions=null \
  required_linear_history=true \
  allow_force_pushes=false \
  allow_deletions=false
```

### Слой 2: CI Gate перед публикацией

Release PR проходит полный CI перед мержем (как обычный PR). Дополнительно, в `release-please.yml` добавляется явная проверка:

```yaml
jobs:
  release:
    runs-on: ubuntu-latest
    outputs:
      releases_created: ${{ steps.release.outputs.releases_created }}
      paths_released: ${{ steps.release.outputs.paths_released }}
    steps:
      - uses: googleapis/release-please-action@v4
        id: release

  verify:
    needs: release
    if: needs.release.outputs.releases_created == 'true'
    strategy:
      matrix:
        path: ${{ fromJson(needs.release.outputs.paths_released) }}
    uses: ./.github/workflows/_reusable-python-ci.yml
    with:
      package-path: ${{ matrix.path }}
      # ... остальные параметры

  publish:
    needs: [release, verify]
    if: needs.release.outputs.releases_created == 'true'
    # Публикация только после успешной верификации
```

### Слой 3: Smoke Test артефакта

В `_reusable-python-publish.yml` перед публикацией:

```yaml
jobs:
  build-and-verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup uv
        uses: astral-sh/setup-uv@v4

      - name: Build package
        run: uv build
        working-directory: ${{ inputs.package-path }}

      - name: Smoke test - install and import
        run: |
          # Создаём чистый venv
          uv venv .venv-smoke
          source .venv-smoke/bin/activate

          # Устанавливаем собранный wheel
          pip install dist/*.whl

          # Проверяем импорт и версию
          python -c "
          import ${{ inputs.package-name }}
          print(f'Package: ${{ inputs.package-name }}')
          print(f'Version: {${{ inputs.package-name }}.__version__}')
          assert '${{ inputs.expected-version }}' in ${{ inputs.package-name }}.__version__
          "

          # Проверяем CLI если есть
          if command -v ${{ inputs.cli-command }} &> /dev/null; then
            ${{ inputs.cli-command }} --help
          fi
        working-directory: ${{ inputs.package-path }}

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          packages-dir: ${{ inputs.package-path }}/dist/
```

### Что защищает каждый слой

| Угроза | Слой 1 | Слой 2 | Слой 3 |
|--------|--------|--------|--------|
| Прямой push сломанного кода | ✅ | - | - |
| Мерж PR без CI | ✅ | - | - |
| Admin bypass | ✅ | - | - |
| Regression между мержем и релизом | - | ✅ | - |
| Изменение зависимостей | - | ✅ | - |
| Сломанный packaging (wheel) | - | - | ✅ |
| Неправильная версия | - | - | ✅ |
| Битый import | - | - | ✅ |

## Валидация коммитов

Строгая валидация коммитов гарантирует независимость релизов пакетов и качество changelog.

### Правила

1. **Conventional commits обязательны:** `type(scope): description`
2. **Один коммит = один пакет:** коммит не может менять файлы в разных пакетах
3. **Scope соответствует пути:** `feat(statuskit):` должен менять только `packages/statuskit/`
4. **Scope из whitelist:** только известные scopes разрешены

### Маппинг scope → пути

| Scope | Разрешённые пути | Описание |
|-------|------------------|----------|
| `statuskit` | `packages/statuskit/` | Python пакет statuskit |
| `flow` | `plugins/flow/` | Claude Code плагин flow |
| `deps` | `pyproject.toml`, `uv.lock` | Зависимости монорепо |
| `ci` | `.github/` | CI/CD конфигурация |
| `docs` | `docs/`, `*.md` | Документация |

### Пути без обязательного scope

Файлы вне пакетов не требуют scope:
- `.github/**`
- `docs/**`
- `*.md` (в корне)
- `.gitignore`, `.editorconfig`

### Скрипт валидации

**Файл:** `.github/scripts/validate-commits.py`

```python
#!/usr/bin/env python3
"""Валидация коммитов: conventional commits, single-package, scope matching."""

import re
import subprocess
import sys
from pathlib import Path

# Маппинг scope → разрешённые пути
SCOPE_TO_PATHS: dict[str, list[str]] = {
    "statuskit": ["packages/statuskit/"],
    "flow": ["plugins/flow/"],
    "deps": ["pyproject.toml", "uv.lock"],
    "ci": [".github/"],
    "docs": ["docs/", "README.md"],
}

# Паттерны путей, не требующих scope
NO_SCOPE_PATTERNS: list[str] = [
    r"^\.github/",
    r"^docs/",
    r"^[^/]+\.md$",  # *.md в корне
    r"^\.[^/]+$",    # dotfiles в корне
]

COMMIT_RE = re.compile(
    r"^(?P<type>feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(?:\((?P<scope>[a-z][a-z0-9-]*)\))?"
    r"(?P<breaking>!)?"
    r":\s*(?P<desc>.+)$",
    re.IGNORECASE,
)


def get_commit_info(sha: str) -> tuple[str, list[str]]:
    """Возвращает (message первой строки, [files])."""
    msg = subprocess.check_output(
        ["git", "log", "-1", "--format=%s", sha], text=True
    ).strip()
    files_output = subprocess.check_output(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha], text=True
    ).strip()
    files = [f for f in files_output.split("\n") if f]
    return msg, files


def get_package_from_path(path: str) -> str | None:
    """Извлекает имя пакета/плагина из пути."""
    if path.startswith("packages/"):
        parts = path.split("/")
        return parts[1] if len(parts) > 1 else None
    if path.startswith("plugins/"):
        parts = path.split("/")
        return parts[1] if len(parts) > 1 else None
    return None


def path_requires_scope(path: str) -> bool:
    """Проверяет, требует ли путь указания scope."""
    for pattern in NO_SCOPE_PATTERNS:
        if re.match(pattern, path):
            return False
    return get_package_from_path(path) is not None


def validate_commit(sha: str) -> list[str]:
    """Валидирует один коммит. Возвращает список ошибок."""
    msg, files = get_commit_info(sha)
    errors: list[str] = []

    # Проверка формата
    match = COMMIT_RE.match(msg)
    if not match:
        errors.append(
            f"Неверный формат conventional commit\n"
            f"  Ожидается: type(scope): description\n"
            f"  Получено: {msg}"
        )
        return errors

    scope = match.group("scope")
    commit_type = match.group("type").lower()

    # Собираем пакеты из изменённых файлов
    packages: set[str] = set()
    scope_required_files: list[str] = []

    for f in files:
        pkg = get_package_from_path(f)
        if pkg:
            packages.add(pkg)
        if path_requires_scope(f):
            scope_required_files.append(f)

    # Проверка 1: Один коммит — один пакет
    if len(packages) > 1:
        errors.append(
            f"Коммит затрагивает несколько пакетов: {sorted(packages)}\n"
            f"  Разбей на отдельные коммиты для каждого пакета"
        )
        return errors  # Остальные проверки бессмысленны

    # Проверка 2: Если есть файлы пакета — scope обязателен
    if packages and not scope:
        pkg = list(packages)[0]
        errors.append(
            f"Отсутствует scope для изменений в пакете '{pkg}'\n"
            f"  Используй: {commit_type}({pkg}): ..."
        )
        return errors

    # Проверка 3: Scope соответствует изменённым файлам
    if scope and packages:
        pkg = list(packages)[0]
        if scope != pkg:
            errors.append(
                f"Scope '{scope}' не соответствует изменённым файлам\n"
                f"  Изменён пакет: {pkg}\n"
                f"  Указан scope: {scope}\n"
                f"  Исправь на: {commit_type}({pkg}): ..."
            )

    # Проверка 4: Scope существует в whitelist
    if scope and scope not in SCOPE_TO_PATHS:
        errors.append(
            f"Неизвестный scope: '{scope}'\n"
            f"  Допустимые: {', '.join(sorted(SCOPE_TO_PATHS.keys()))}"
        )

    return errors


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: validate-commits.py <base-sha> <head-sha>")
        return 1

    base_sha = sys.argv[1]
    head_sha = sys.argv[2]

    # Получаем список коммитов
    result = subprocess.run(
        ["git", "rev-list", f"{base_sha}..{head_sha}"],
        capture_output=True,
        text=True,
    )
    commits = [c for c in result.stdout.strip().split("\n") if c]

    if not commits:
        print("✅ Нет коммитов для проверки")
        return 0

    all_errors: list[str] = []
    for sha in commits:
        errors = validate_commit(sha)
        if errors:
            msg, _ = get_commit_info(sha)
            all_errors.append(f"\n❌ {sha[:8]}: {msg}")
            for e in errors:
                all_errors.append(f"   {e}")

    if all_errors:
        print("Ошибки валидации коммитов:")
        print("\n".join(all_errors))
        return 1

    print(f"✅ Все {len(commits)} коммит(ов) валидны")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### GitHub Actions job

Добавляется в `ci.yml` как первый job:

```yaml
jobs:
  validate-commits:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Validate commits
        run: |
          python .github/scripts/validate-commits.py \
            ${{ github.event.pull_request.base.sha }} \
            ${{ github.sha }}
```

### Pre-commit hook (опционально)

Для быстрого фидбека локально:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: validate-commit-msg
        name: Validate commit message
        entry: python .github/scripts/validate-commits.py HEAD~1 HEAD
        language: system
        stages: [commit-msg]
```

### Примеры

```
✅ feat(statuskit): add git module
   → меняет packages/statuskit/src/git.py
   → scope=statuskit, пакет=statuskit — ОК

✅ chore(deps): update dependencies
   → меняет pyproject.toml, uv.lock
   → scope=deps разрешает эти пути — ОК

✅ docs: update README
   → меняет README.md
   → корневые .md не требуют scope — ОК

❌ feat(statuskit): add feature
   → меняет packages/statuskit/... И packages/another/...
   → ОШИБКА: несколько пакетов в одном коммите

❌ feat(flow): update config
   → меняет packages/statuskit/src/config.py
   → ОШИБКА: scope=flow, но изменён statuskit

❌ feat: add feature
   → меняет packages/statuskit/src/foo.py
   → ОШИБКА: отсутствует обязательный scope
```

### Что это даёт

| Проверка | Защищает от |
|----------|-------------|
| Conventional commit format | Нечитаемые коммиты, сломанный changelog |
| Один пакет на коммит | Смешанные релизы, неправильный version bump |
| Scope обязателен для пакетов | Потерянные изменения в changelog |
| Scope = путь | Ошибочная атрибуция изменений |
| Scope whitelist | Опечатки, несуществующие пакеты |

## CI для Claude Code плагинов

**Файл:** `plugins-ci.yml`

**Триггер:** изменения в `plugins/**`

**Jobs:**

1. **validate-structure**
    - `plugin.json` существует и валидный
    - Skills из plugin.json существуют как файлы
    - Обязательные поля: name, version, description

2. **lint-scripts**
    - `ruff check` и `ruff format --check` для `.py` файлов
    - `ty check` если есть Python файлы
    - Python 3.11 (одна версия, только линтинг)

## SonarCloud конфигурация

**Файл:** `sonar-project.properties`

```properties
sonar.organization=nonameitem
sonar.projectKey=NoNameItem_claude-tools
sonar.modules=statuskit
statuskit.sonar.projectBaseDir=packages/statuskit
statuskit.sonar.sources=src
statuskit.sonar.tests=tests
statuskit.sonar.python.coverage.reportPaths=coverage.xml
statuskit.sonar.python.ruff.reportPaths=ruff-report.json
```

**Quality Gate:** Sonar way (или кастомный)

## Caller workflow

**Файл:** `ci.yml`

```yaml
name: CI

on:
  pull_request:
    paths: [ 'packages/**', 'pyproject.toml' ]
  push:
    branches: [ main ]
    paths: [ 'packages/**' ]

jobs:
  # Валидация коммитов — первый job, блокирует всё остальное
  validate-commits:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Validate commits
        run: |
          python .github/scripts/validate-commits.py \
            ${{ github.event.pull_request.base.sha }} \
            ${{ github.sha }}

  detect:
    needs: validate-commits
    if: always() && (needs.validate-commits.result == 'success' || needs.validate-commits.result == 'skipped')
    uses: ./.github/workflows/_detect-changes.yml

  ci:
    needs: [validate-commits, detect]
    if: always() && needs.detect.result == 'success' && needs.detect.outputs.has-packages == 'true'
    strategy:
      fail-fast: false
      matrix:
        package: ${{ fromJson(needs.detect.outputs.packages) }}
    uses: ./.github/workflows/_reusable-python-ci.yml
    with:
      package: ${{ matrix.package.name }}
      package-path: ${{ matrix.package.path }}
      python-versions: ${{ toJson(matrix.package.python-versions) }}
      changed-files: ${{ toJson(matrix.package.changed-files) }}
    secrets: inherit
```

## Добавление нового пакета

1. Создать `packages/<name>/pyproject.toml` с classifiers
2. Создать `packages/<name>/CHANGELOG.md` (пустой или с начальной версией)
3. Добавить scope в `SCOPE_TO_PATHS` в `.github/scripts/validate-commits.py`
4. Добавить в `release-please-config.json`
5. Добавить в `.release-please-manifest.json`
6. Добавить модуль в `sonar-project.properties`
7. Настроить Trusted Publisher на PyPI для нового пакета

## Добавление нового плагина

1. Создать `plugins/<name>/.claude-plugin/plugin.json`
2. Создать `plugins/<name>/CHANGELOG.md`
3. Добавить scope в `SCOPE_TO_PATHS` в `.github/scripts/validate-commits.py`
4. Добавить в `release-please-config.json`
5. Добавить в `.release-please-manifest.json`
6. CI автоматически подхватит (path filter `plugins/**`)

## Тестирование CI/CD

### Стратегия

1. **Локально с act** — основное тестирование workflows
2. **Unit tests** — для Python скриптов
3. **GitHub** — финальная проверка и release flow

### act (локальный GitHub Actions runner)

**Установка:**
```bash
brew install act
```

**Запуск:**
```bash
# Симуляция pull_request event
act pull_request

# Конкретный workflow
act -W .github/workflows/ci.yml

# С переменными окружения
act pull_request --env-file .env.act

# Verbose для отладки
act pull_request -v
```

**Файл `.actrc`** (настройки по умолчанию):
```
-P ubuntu-latest=ghcr.io/catthehacker/ubuntu:act-latest
--env-file .env.act
```

**Файл `.env.act`** (переменные для тестирования):
```bash
GITHUB_TOKEN=fake-token-for-local-testing
```

### Что тестируем в act

| Workflow | Как тестировать |
|----------|-----------------|
| `ci.yml` | `act pull_request -W .github/workflows/ci.yml` |
| `validate-commits` | `act pull_request` с тестовыми коммитами |
| `_reusable-python-ci` | Через вызов из ci.yml |
| `plugins-ci.yml` | `act pull_request -W .github/workflows/plugins-ci.yml` |

### Что тестируем только на GitHub

| Workflow | Почему |
|----------|--------|
| `release-please.yml` | Требует GitHub API для создания PR/Release |
| `_reusable-python-publish.yml` | Требует PyPI OIDC |
| SonarCloud analysis | Требует токен и интеграцию |
| Branch protection | Настройки репозитория |

### Unit tests для скриптов

```
.github/scripts/
├── validate_commits.py
├── detect_changes.py
└── tests/
    ├── conftest.py
    ├── test_validate_commits.py
    └── test_detect_changes.py
```

**Запуск:**
```bash
pytest .github/scripts/tests/
```

### Порядок тестирования

1. **Скрипты локально:**
   ```bash
   pytest .github/scripts/tests/
   ```

2. **Workflows в act:**
   ```bash
   act pull_request -v
   ```

3. **Финальная проверка на GitHub:**
   - Создать PR с изменениями
   - Убедиться что CI проходит
   - Проверить что валидация коммитов работает

4. **Release flow (после мержа в main):**
   - Сделать тестовый коммит `feat(statuskit): test release`
   - Проверить что release-please создал PR
   - Смержить release PR
   - Проверить что пакет опубликован на PyPI
