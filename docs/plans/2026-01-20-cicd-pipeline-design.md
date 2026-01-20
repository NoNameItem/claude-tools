# CI/CD Pipeline Design

## Overview

GitHub Actions CI/CD для monorepo с независимыми Python пакетами и Claude Code плагинами.

## Ключевые решения

| Аспект | Решение |
|--------|---------|
| Релизы | release-please (manifest mode) |
| Версионирование | Независимое для каждого пакета |
| Структура workflows | Reusable workflows |
| Детекция изменений | Динамическая (скрипт определяет изменённые пакеты) |
| CI проверки | lint + format + typecheck + tests + coverage |
| Lint scope | Только изменённые файлы в PR |
| Python версии | Из classifiers в pyproject.toml |
| Coverage/анализ | SonarCloud + импорт Ruff report |
| Quality gate | SonarCloud (блокирует PR) |
| Публикация | PyPI Trusted Publisher (OIDC) |
| Кэширование | uv cache |
| Code review | Claude Code (существующий workflow) |

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
│   └── detect-changes.py            # Скрипт детекции изменений
├── release-please-config.json       # Конфигурация release-please
└── .release-please-manifest.json    # Версии пакетов
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
      "extra-files": ["pyproject.toml"]
    }
  }
}
```

`.release-please-manifest.json`:
```json
{
  "packages/statuskit": "0.1.0"
}
```

**Workflow логика:**

1. Push в main → release-please создаёт/обновляет release PR
2. Мерж release PR → GitHub Release + тег `statuskit-v0.2.0` → триггер публикации

**Файл:** `_reusable-python-publish.yml`

Шаги:
1. Checkout
2. `uv build`
3. `pypa/gh-action-pypi-publish` (Trusted Publisher, без токенов)

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
    paths: ['packages/**', 'pyproject.toml']
  push:
    branches: [main]
    paths: ['packages/**']

jobs:
  detect:
    uses: ./.github/workflows/_detect-changes.yml

  ci:
    needs: detect
    if: needs.detect.outputs.has-packages == 'true'
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
2. Добавить в `release-please-config.json`
3. Добавить в `.release-please-manifest.json`
4. Добавить модуль в `sonar-project.properties`
5. Настроить Trusted Publisher на PyPI для нового пакета

## Добавление нового плагина

1. Создать `plugins/<name>/.claude-plugin/plugin.json`
2. CI автоматически подхватит (path filter `plugins/**`)
