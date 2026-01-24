# CI Orchestrator Design

## Overview

Унификация CI workflows в единый поток с оркестратором. Заменяет разрозненные `ci.yml` и `plugins-ci.yml` на модульную архитектуру с динамическими типами проектов.

## Цели

1. **Консистентность** — изменения в tooling автоматически триггерят проверку всех проектов
2. **Упрощение поддержки** — один entry point на событие, меньше дублирования
3. **Расширяемость** — легко добавлять новые типы проектов через конфиг

## Алгоритм

```
PR/Push
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  1. DETECT                                                  │
│  - Читает [tool.ci] из pyproject.toml                       │
│  - Определяет изменённые проекты по типам                   │
│  - Определяет tooling_changed                               │
│  - Формирует матрицы для CI jobs                            │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  2. VALIDATE                                                │
│  - PR: проверяет PR title format + scope                    │
│  - Push: проверяет commit message (safety net)              │
│  - Правило: максимум 1 проект в PR/commit                   │
│  - Scope = имя проекта или пустой (repo-level)              │
│  ❌ Fail → PR заблокирован                                  │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  3. EXECUTE (blocking)                                      │
│  - Для каждого типа: запуск соответствующего reusable       │
│  - package → _reusable-python-ci.yml                        │
│  - plugin → _reusable-plugin-ci.yml                         │
│  ❌ Fail → PR заблокирован                                  │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  4. EXECUTE (non-blocking) — только если tooling_changed    │
│  - Все проекты, которые НЕ изменены                         │
│  - continue-on-error: true                                  │
│  ⚠️ Fail → показываем, но НЕ блокируем PR                   │
└─────────────────────────────────────────────────────────────┘
```

## Конфигурация

```toml
# pyproject.toml

[tool.ci]
tooling_files = [
    "pyproject.toml",
    "uv.lock",
    "sonar-project.properties",
]

[tool.ci.project-types]
package = ["packages"]
plugin = ["plugins"]
# Будущее:
# other = ["other-projects"]
```

## Структура workflow файлов

```
.github/workflows/
├── pr.yml                    # entry point: pull_request to master
├── push.yml                  # entry point: push to master
├── _reusable-detect.yml      # detect changes (shared)
├── _reusable-python-ci.yml   # package CI (lint, test, sonar)
├── _reusable-plugin-ci.yml   # plugin CI (structure, lint)
└── ...
```

## Workflow: pr.yml

```yaml
name: PR

on:
  pull_request:
    branches: [master]

jobs:
  detect:
    uses: ./.github/workflows/_reusable-detect.yml
    with:
      ref: origin/${{ github.base_ref }}..HEAD

  validate-pr:
    needs: [detect]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Validate PR
        env:
          PR_TITLE: ${{ github.event.pull_request.title }}
          DETECT_RESULT: ${{ needs.detect.outputs.result }}
        run: python .github/scripts/validate.py --pr

  package-ci:
    needs: [detect, validate-pr]
    if: fromJson(needs.detect.outputs.result).by_type.package.has_changed == true
    uses: ./.github/workflows/_reusable-python-ci.yml
    with:
      matrix: ${{ toJson(fromJson(needs.detect.outputs.result).by_type.package.matrix) }}
      changed-files: ${{ toJson(fromJson(needs.detect.outputs.result).changed_files) }}
      tooling-changed: ${{ fromJson(needs.detect.outputs.result).tooling_changed }}
    secrets: inherit

  plugin-ci:
    needs: [detect, validate-pr]
    if: fromJson(needs.detect.outputs.result).by_type.plugin.has_changed == true
    uses: ./.github/workflows/_reusable-plugin-ci.yml
    with:
      plugins: ${{ toJson(fromJson(needs.detect.outputs.result).by_type.plugin.changed) }}
      changed-files: ${{ toJson(fromJson(needs.detect.outputs.result).changed_files) }}
      tooling-changed: ${{ fromJson(needs.detect.outputs.result).tooling_changed }}

  package-ci-info:
    needs: [detect, validate-pr]
    if: |
      fromJson(needs.detect.outputs.result).tooling_changed == true &&
      fromJson(needs.detect.outputs.result).by_type.package.has_unchanged == true
    uses: ./.github/workflows/_reusable-python-ci.yml
    with:
      matrix: ${{ toJson(fromJson(needs.detect.outputs.result).by_type.package.unchanged_matrix) }}
      tooling-changed: true
    secrets: inherit
    continue-on-error: true

  plugin-ci-info:
    needs: [detect, validate-pr]
    if: |
      fromJson(needs.detect.outputs.result).tooling_changed == true &&
      fromJson(needs.detect.outputs.result).by_type.plugin.has_unchanged == true
    uses: ./.github/workflows/_reusable-plugin-ci.yml
    with:
      plugins: ${{ toJson(fromJson(needs.detect.outputs.result).by_type.plugin.unchanged) }}
      tooling-changed: true
    continue-on-error: true
```

## Workflow: push.yml

```yaml
name: Push

on:
  push:
    branches: [master]

jobs:
  detect:
    uses: ./.github/workflows/_reusable-detect.yml
    with:
      ref: HEAD~1..HEAD

  validate-commits:
    needs: [detect]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 2
      - name: Validate commits
        env:
          DETECT_RESULT: ${{ needs.detect.outputs.result }}
        run: python .github/scripts/validate.py --commits HEAD~1 HEAD

  # Остальные jobs аналогичны pr.yml, только needs: [detect, validate-commits]
  package-ci:
    # ...
  plugin-ci:
    # ...
  package-ci-info:
    # ...
  plugin-ci-info:
    # ...
```

## Workflow: _reusable-detect.yml

**Inputs:**
- `ref` — Git ref range (e.g., `origin/master..HEAD`)

**Outputs:**
- `result` — JSON со всеми данными

**Job: detect**
1. Checkout (fetch-depth: 0)
2. `python .github/scripts/detect_changes.py --ref <ref>`
3. Output result JSON

## Workflow: _reusable-python-ci.yml

**Inputs:**
- `matrix` — JSON matrix с пакетами
- `changed-files` — карта project → файлы (опционально)
- `tooling-changed` — влияет на scope ruff

**Job: lint**
1. Checkout
2. Setup uv (min Python version)
3. Install dependencies
4. Determine files to lint:
   - `tooling-changed=true` → все .py файлы пакета
   - `tooling-changed=false` → только changed .py файлы
5. `ruff format --check`
6. `ruff check`
7. `ty check` (весь пакет)

**Job: test**
1. Checkout
2. Setup uv (matrix по Python versions)
3. Install dependencies
4. `pytest --cov --cov-report=xml`
5. Upload coverage artifact

**Job: sonarcloud**
- needs: [lint, test]
1. Checkout (fetch-depth: 0)
2. Download coverage artifact
3. SonarCloud analysis

## Workflow: _reusable-plugin-ci.yml

**Inputs:**
- `plugins` — JSON array плагинов
- `changed-files` — карта project → файлы (опционально)
- `tooling-changed` — влияет на scope ruff

**Job: validate-structure**
1. Checkout
2. `python .github/scripts/validate_plugin.py plugins/<name>`

**Job: lint**
- if: есть .py файлы
1. Checkout
2. Setup uv + ruff
3. Determine files:
   - `tooling-changed=true` → все .py файлы плагина
   - `tooling-changed=false` → только changed .py файлы
4. `ruff format --check`
5. `ruff check`

## detect_changes.py output

```python
{
    "by_type": {
        "package": {
            "changed": ["statuskit"],
            "unchanged": ["other-pkg"],
            "count": 1,
            "has_changed": true,
            "has_unchanged": true,
            "matrix": {"include": [...]},
            "unchanged_matrix": {"include": [...]}
        },
        "plugin": {
            "changed": ["flow"],
            "unchanged": [],
            "count": 1,
            "has_changed": true,
            "has_unchanged": false,
            "matrix": {"include": [...]},
            "unchanged_matrix": {"include": [...]}
        }
    },

    # Для validate:
    "total_changed_count": 1,
    "single_project": "statuskit",
    "single_project_type": "package",

    # Общие:
    "has_repo_level": true,
    "tooling_changed": true,
    "changed_files": {"statuskit": ["src/foo.py"]},
    "project_types": ["package", "plugin"]
}
```

## discover_projects (projects.py)

Динамическое обнаружение проектов из конфига:

```python
def discover_projects(repo_root: Path) -> dict[str, ProjectInfo]:
    config = get_ci_config(repo_root)
    projects = {}

    # config.project_types = {"package": ["packages"], "plugin": ["plugins"]}
    for kind, dirs in config.project_types.items():
        for dir_name in dirs:
            dir_path = repo_root / dir_name
            if not dir_path.exists():
                continue
            for project_dir in dir_path.iterdir():
                if not project_dir.is_dir():
                    continue
                name = project_dir.name
                projects[name] = ProjectInfo(
                    name=name,
                    path=f"{dir_name}/{name}",
                    kind=kind,
                    python_versions=_get_python_versions(project_dir, kind),
                )

    return projects
```

## validate.py

Проверяет PR title / commit messages:

```python
def validate_pr(title: str, detect_result: dict) -> list[str]:
    errors = []

    msg_type, scope, desc = parse_message(title)
    if msg_type is None:
        errors.append(f"Invalid PR title format: {title}")
        return errors

    total_count = detect_result["total_changed_count"]

    # Максимум один проект
    if total_count > 1:
        all_changed = []
        for kind, data in detect_result["by_type"].items():
            all_changed.extend(data["changed"])
        errors.append(f"PR changes multiple projects: {all_changed}")
        return errors

    # Scope match
    expected_scope = detect_result["single_project"]

    if expected_scope:
        if scope != expected_scope:
            errors.append(f"Scope mismatch: expected '{expected_scope}', got '{scope}'")
    else:
        if scope:
            errors.append(f"Unexpected scope '{scope}' for repo-level changes")

    return errors
```

## Добавление нового типа проектов

1. Добавить в `pyproject.toml`:
   ```toml
   [tool.ci.project-types]
   other = ["other-projects"]
   ```

2. Создать `_reusable-other-ci.yml`

3. Добавить jobs в `pr.yml` / `push.yml`:
   ```yaml
   other-ci:
     if: fromJson(needs.detect.outputs.result).by_type.other.has_changed == true
     uses: ./.github/workflows/_reusable-other-ci.yml
   ```

## Открытые вопросы

1. **Python version для plugins** — сейчас `python_versions=[]`, но ruff запускаем. Хардкодим 3.11 или брать откуда-то?

2. **REPO_LEVEL_PATTERNS** в projects.py — сейчас хардкод. Нужно конфигурировать?

3. **Branch protection** — какие jobs добавить в required checks?

4. **Concurrency** — отменять in-progress runs при новом push в PR?

5. **validate.py --commits** — нужен ли вообще на push to main, если PR уже провалидирован?

6. **Тесты** — обновить tests для detect_changes.py, validate.py, projects.py?

7. **Обработка ошибок** — что если pyproject.toml битый или нет `[tool.ci]`?

8. **Отображение результатов** — badges, summary table (отдельная задача)
