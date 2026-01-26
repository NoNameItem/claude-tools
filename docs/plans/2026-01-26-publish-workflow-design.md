# Publish Workflow Design

## Overview

Публикация пакетов монорепо на PyPI и другие платформы.

**Триггер:** `release: published` (release-please создаёт GitHub Release)

**Архитектура:**
```
publish.yml (роутер)
    ↓
resolve_publish.py (парсинг тега → проект → способы публикации)
    ↓
_reusable-publish-pypi.yml (или другие _reusable-publish-*.yml)
```

## Рефакторинг конфигурации

### Изменения в pyproject.toml

**Было:**
```toml
[tool.ci]
tooling_files = [...]

[tool.ci.project-types]
package = ["packages"]
plugin = ["plugins"]
```

**Станет:**
```toml
[tool.repo]
tooling_files = [
    "pyproject.toml",
    "uv.lock",
    "sonar-project.properties",
]

[tool.repo.project-types.python]
paths = ["packages"]
publish = ["pypi"]

[tool.repo.project-types.claude-code-plugin]
paths = ["plugins"]
publish = []

# Опционально: переопределения для конкретных проектов
# [tool.repo.projects.<name>]
# publish = [...]           # полная замена
# publish-add = [...]       # добавить к родительским
# publish-disable = [...]   # убрать из родительских
```

### Разрешение publish targets

1. Определить тип проекта по пути
2. Взять `publish` из `project-types.<type>`
3. Если `projects.<name>.publish` задан → заменить полностью
4. Иначе: удалить `publish-disable`, добавить `publish-add`

## Рефакторинг скриптов и workflows

### Переименования типов проектов

| Было | Станет |
|------|--------|
| `package` | `python` |
| `plugin` | `claude-code-plugin` |

### Файлы для изменения

| Файл | Изменения |
|------|-----------|
| `pyproject.toml` | `[tool.ci]` → `[tool.repo]`, новая структура |
| `.github/scripts/projects.py` | `tool.ci` → `tool.repo`, обновить `kind` значения |
| `.github/scripts/tests/conftest.py` | Обновить фикстуры |
| `.github/scripts/tests/test_projects.py` | Обновить тесты |

### Workflows — переименования job IDs и names

**pr.yml и push.yml:**

| Было | Станет |
|------|--------|
| `package-ci` (name: "Package CI") | `python-ci` (name: "Python CI") |
| `plugin-ci` (name: "Plugin CI") | `claude-code-plugin-ci` (name: "Claude Code Plugin CI") |
| `package-ci-info` (name: "Package CI (info)") | `python-ci-info` (name: "Python CI (info)") |
| `plugin-ci-info` (name: "Plugin CI (info)") | `claude-code-plugin-ci-info` (name: "Claude Code Plugin CI (info)") |
| `package-ci-result` (name: "Package CI") | `python-ci-result` (name: "Python CI") |
| `plugin-ci-result` (name: "Plugin CI") | `claude-code-plugin-ci-result` (name: "Claude Code Plugin CI") |

**References в условиях:**

| Было | Станет |
|------|--------|
| `by_type.package.has_changed` | `by_type.python.has_changed` |
| `by_type.plugin.has_changed` | `by_type["claude-code-plugin"].has_changed` |

**Reusable workflows:**

| Было | Станет |
|------|--------|
| `_reusable-plugin-ci.yml` | `_reusable-claude-code-plugin-ci.yml` |
| `name: Plugin CI (Reusable)` | `name: Claude Code Plugin CI (Reusable)` |

## Release-please конфигурация

### Добавить labels

```json
{
  "packages": {
    "packages/statuskit": {
      "labels": ["ci:full", "statuskit"]
    },
    "plugins/flow": {
      "labels": ["ci:full", "flow"]
    }
  }
}
```

### Логика ci:full в pr.yml

```yaml
jobs:
  detect:
    outputs:
      force-full-ci: ${{ contains(github.event.pull_request.labels.*.name, 'ci:full') }}

  python-ci:
    with:
      tooling-changed: ${{ needs.detect.outputs.force-full-ci == 'true' || fromJson(needs.detect.outputs.result).tooling_changed }}
```

Label `ci:full` запускает lint/test на всём пакете, а не только на изменённых файлах.

## Новые файлы

### .github/workflows/publish.yml

**Триггер:** `release: published`

**Шаги:**
1. Парсит тег (`statuskit-0.2.0`)
2. Вызывает `resolve_publish.py` → проект + способы публикации
3. Вызывает `_reusable-publish-*.yml` для каждого способа
4. Если `publish = []` — завершается успешно без действий

**Входные данные для reusable workflows:**
- `project-path` — путь к проекту (например `packages/statuskit`)
- `project-name` — имя проекта (например `statuskit`)
- `version` — версия из тега (например `0.2.0`)

### .github/workflows/_reusable-publish-pypi.yml

**Входные параметры:**
```yaml
inputs:
  project-path:
    required: true
    type: string
  project-name:
    required: true
    type: string
  version:
    required: true
    type: string
```

**Jobs:**

1. **build-and-verify**
   - Checkout
   - Setup uv
   - `uv build` в `project-path`
   - Smoke test:
     - Создать чистый venv
     - Установить собранный wheel
     - Проверить import
     - Проверить версию через `importlib.metadata`
     - Проверить CLI команды (`--help`) из `project.scripts`
   - `pypa/gh-action-pypi-publish` (Trusted Publisher, без токенов)

**Данные из pyproject.toml пакета:**
- `project.name` — имя пакета на PyPI
- `project.scripts` — CLI команды для smoke test

### .github/scripts/resolve_publish.py

**Входные данные:** тег релиза (например `statuskit-0.2.0`)

**Выходные данные (JSON):**
```json
{
  "project_name": "statuskit",
  "project_path": "packages/statuskit",
  "project_type": "python",
  "version": "0.2.0",
  "publish_targets": ["pypi"]
}
```

**Шаги:**
1. Парсить тег: `<component>-<version>`
2. Найти путь компонента в `release-please-config.json`
3. Определить тип проекта по пути из `[tool.repo]`
4. Вычислить publish targets с учётом переопределений

## Разделение ответственности

| Этап | Что проверяет | Где |
|------|---------------|-----|
| PR CI | Код работает (lint, test) | `pr.yml` → `_reusable-python-ci.yml` |
| Release PR CI | Полный CI (label `ci:full`) | `pr.yml` с `force-full-ci` |
| Publish | Артефакт собирается и работает | `_reusable-publish-pypi.yml` smoke test |

**Гарантия:** release-please создаёт тег только после успешного CI. Publish проверяет артефакт.

## PyPI Trusted Publisher

**Настройка на PyPI:**
- Repository: `NoNameItem/claude-tools`
- Workflow: `.github/workflows/_reusable-publish-pypi.yml` (или `publish.yml`)
- Environment: не используется

Без environment — публикация происходит автоматически после создания GitHub Release.

## Декомпозиция

### 1. Рефакторинг конфига и скриптов
- [ ] Обновить `pyproject.toml`: `[tool.ci]` → `[tool.repo]`, новая структура
- [ ] Обновить `.github/scripts/projects.py`
- [ ] Обновить тесты в `.github/scripts/tests/`

### 2. Рефакторинг workflows
- [ ] Переименовать `_reusable-plugin-ci.yml` → `_reusable-claude-code-plugin-ci.yml`
- [ ] Обновить `pr.yml`: job names, references, логика `ci:full`
- [ ] Обновить `push.yml`: job names, references

### 3. Release-please labels
- [ ] Добавить `labels` в `release-please-config.json`

### 4. Publish workflow
- [ ] Создать `.github/scripts/resolve_publish.py`
- [ ] Создать `.github/workflows/publish.yml`
- [ ] Создать `.github/workflows/_reusable-publish-pypi.yml`

### 5. PyPI настройка
- [ ] Создать проект `claude-statuskit` на PyPI (если не существует)
- [ ] Настроить Trusted Publisher

### 6. Тестирование
- [ ] Локально: unit tests для `resolve_publish.py`
- [ ] GitHub: создать тестовый release PR, проверить CI
- [ ] GitHub: первый реальный релиз statuskit
