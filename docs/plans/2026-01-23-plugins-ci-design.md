# Plugins CI Design

Task: claude-tools-5dl.2.3

## Overview

GitHub Actions CI workflow для Claude Code плагинов с валидацией структуры и линтингом Python скриптов.

## Scope

1. **Рефакторинг терминологии** — переименование "packages" → "projects" в скриптах валидации, добавление раздельных `packages`/`plugins` в output
2. **Скрипт `validate_plugin.py`** — валидация структуры Claude Code плагинов
3. **Workflow `plugins-ci.yml`** — GitHub Actions CI для плагинов

## Deliverables

```
.github/
├── scripts/
│   ├── projects.py          # переименован из packages.py
│   ├── detect_changes.py    # обновлён output
│   ├── validate.py          # обновлены импорты
│   ├── validate_plugin.py   # новый
│   └── tests/
│       ├── test_projects.py # переименован
│       └── test_validate_plugin.py # новый
└── workflows/
    └── plugins-ci.yml       # новый
```

**Вне scope:**
- Изменения в ci.yml для Python пакетов
- Release-please для плагинов
- SonarCloud для плагинов

## Рефакторинг терминологии

### Переименования

| Было | Стало |
|------|-------|
| `packages.py` | `projects.py` |
| `PackageInfo` | `ProjectInfo` |
| `discover_packages()` | `discover_projects()` |
| `get_package_from_path()` | `get_project_from_path()` |
| `test_packages.py` | `test_projects.py` |

### Изменения в detect_changes.py output

```json
{
  "projects": ["statuskit", "flow"],
  "packages": ["statuskit"],
  "plugins": ["flow"],
  "has_projects": true,
  "has_packages": true,
  "has_plugins": true,
  "has_repo_level": false,
  "tooling_changed": false,
  "matrix": { ... },
  "all_packages_matrix": { ... }
}
```

**Логика разделения:**
- `projects` — все (packages + plugins), для one-project rule
- `packages` — только `kind="package"`, для Python CI
- `plugins` — только `kind="plugin"`, для plugins CI

### Обновление импортов в validate.py

```python
# Было
from .packages import get_package_from_path, discover_packages

# Стало
from .projects import get_project_from_path, discover_projects
```

Функция `_get_packages_from_files` переименовать в `_get_projects_from_files`.

## validate_plugin.py

### Интерфейс

```bash
python -m scripts.validate_plugin <plugin-path>

# Пример
python -m scripts.validate_plugin plugins/flow
```

### Exit codes

| Code | Значение |
|------|----------|
| 0 | Успех |
| 1 | plugin.json не найден или невалидный JSON |
| 2 | Отсутствует обязательное поле |
| 3 | Невалидный формат (name, version, paths) |
| 4 | Структура компонентов некорректна |
| 5 | Дубликаты имён между компонентами |
| 6 | Плагин не зарегистрирован в маркетплейсе |
| 10 | Ошибка скрипта |

### Структура модуля

```python
@dataclass
class PluginValidationResult:
    success: bool
    errors: list[str]
    warnings: list[str]

def validate_plugin_json(plugin_path: Path) -> PluginValidationResult
def validate_components(plugin_path: Path, plugin_json: dict) -> PluginValidationResult
def validate_name_uniqueness(plugin_path: Path, plugin_json: dict) -> PluginValidationResult
def validate_marketplace_registration(plugin_path: Path, plugin_json: dict, repo_root: Path) -> PluginValidationResult

def validate_plugin(plugin_path: Path, repo_root: Path) -> PluginValidationResult
```

### Проверки

#### 1. Валидация plugin.json

| Проверка | Ошибка |
|----------|--------|
| `.claude-plugin/plugin.json` существует | "plugin.json not found" |
| Валидный JSON | "Invalid JSON: {parse_error}" |
| Поле `name` присутствует | "Missing required field: name" |
| `name` в kebab-case | "Invalid name format: must be kebab-case" |
| `version` если есть — semver | "Invalid version format: must be semver" |
| Пути начинаются с `./` | "Invalid path '{path}': must start with ./" |

**Regex для валидации:**

```python
KEBAB_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$")
PATH_FIELDS = ["commands", "agents", "skills", "hooks", "mcpServers", "outputStyles", "lspServers"]
```

#### 2. Валидация компонентов

| Компонент | Проверка |
|-----------|----------|
| skills | Каждая папка содержит `SKILL.md` |
| commands | Файлы имеют расширение `.md` |
| agents | Файлы имеют расширение `.md` |

Проверяем как default директории (`skills/`, `commands/`, `agents/`), так и custom paths из plugin.json.

#### 3. Уникальность имён

Собираем имена из всех компонентов:

| Компонент | Как извлекается имя |
|-----------|---------------------|
| skills | имя папки: `skills/pdf-processor/` → `pdf-processor` |
| commands | имя файла без `.md`: `commands/status.md` → `status` |
| agents | имя файла без `.md`: `agents/reviewer.md` → `reviewer` |

```python
def collect_component_names(plugin_path: Path, plugin_json: dict) -> dict[str, list[str]]:
    """Returns {"skill": ["name1"], "command": ["name2"], "agent": ["name3"]}"""
```

Ошибка если одно имя встречается в разных компонентах:

```
Name collision: 'review' exists in both skills and commands
```

#### 4. Регистрация в маркетплейсе

| Проверка | Ошибка |
|----------|--------|
| Плагин есть в `.claude-plugin/marketplace.json` → `plugins[]` | "Plugin not registered in marketplace" |
| `source` указывает на правильный путь | "Marketplace source mismatch" |
| `name` совпадает | "Name mismatch: plugin.json has '{a}', marketplace has '{b}'" |

## plugins-ci.yml

### Триггеры

```yaml
on:
  pull_request:
    paths: ['plugins/**']
  push:
    branches: [main]
    paths: ['plugins/**']
```

### Структура jobs

```
┌─────────────────────┐
│  detect-changes     │
│  (определяет плагин)│
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐     ┌─────────────────────┐
│  validate-structure │     │    lint-scripts     │
│  (validate_plugin)  │     │  (ruff check/format)│
└─────────────────────┘     └─────────────────────┘
```

### Job: detect-changes

```yaml
detect-changes:
  runs-on: ubuntu-latest
  outputs:
    plugin: ${{ steps.detect.outputs.plugin }}
    plugin_path: ${{ steps.detect.outputs.plugin_path }}
    has_plugins: ${{ steps.detect.outputs.has_plugins }}
    has_python: ${{ steps.check-python.outputs.has_python }}
  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0

    - name: Detect changes
      id: detect
      run: |
        OUTPUT=$(python -m scripts.detect_changes --ref origin/${{ github.base_ref }}..HEAD)
        echo "plugin=$(echo $OUTPUT | jq -r '.plugins[0] // empty')" >> $GITHUB_OUTPUT
        echo "plugin_path=plugins/$(echo $OUTPUT | jq -r '.plugins[0] // empty')" >> $GITHUB_OUTPUT
        echo "has_plugins=$(echo $OUTPUT | jq -r '.has_plugins')" >> $GITHUB_OUTPUT
      working-directory: .github

    - name: Check for Python files
      id: check-python
      if: steps.detect.outputs.has_plugins == 'true'
      run: |
        if find ${{ steps.detect.outputs.plugin_path }} -name "*.py" | grep -q .; then
          echo "has_python=true" >> $GITHUB_OUTPUT
        else
          echo "has_python=false" >> $GITHUB_OUTPUT
        fi
```

### Job: validate-structure

```yaml
validate-structure:
  needs: detect-changes
  if: needs.detect-changes.outputs.has_plugins == 'true'
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4

    - name: Validate plugin structure
      run: |
        python -m scripts.validate_plugin ${{ needs.detect-changes.outputs.plugin_path }}
      working-directory: .github
```

### Job: lint-scripts

```yaml
lint-scripts:
  needs: detect-changes
  if: needs.detect-changes.outputs.has_plugins == 'true' && needs.detect-changes.outputs.has_python == 'true'
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4

    - name: Setup Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'

    - name: Setup uv
      uses: astral-sh/setup-uv@v4

    - name: Install ruff
      run: uv tool install ruff

    - name: Ruff check
      run: ruff check --config pyproject.toml ${{ needs.detect-changes.outputs.plugin_path }}

    - name: Ruff format check
      run: ruff format --config pyproject.toml --check ${{ needs.detect-changes.outputs.plugin_path }}
```

**Примечания:**
- Python 3.11 — одна версия, только для линтинга
- `uv tool install ruff` — быстрая установка без создания venv
- Не используем ty (type check) — скрипты в плагинах standalone
- `--config pyproject.toml` — используем конфигурацию ruff из корня репо

## Тестирование

### Структура тестов

```
.github/scripts/tests/
├── test_projects.py          # переименован из test_packages.py
├── test_detect_changes.py    # обновлён для новых полей
└── test_validate_plugin.py   # новый
```

### test_validate_plugin.py — основные кейсы

| Тест | Описание |
|------|----------|
| `test_valid_plugin` | Минимальный валидный плагин |
| `test_missing_plugin_json` | Нет plugin.json |
| `test_invalid_json` | Невалидный JSON |
| `test_missing_name` | Нет обязательного поля name |
| `test_invalid_name_format` | name не в kebab-case |
| `test_invalid_version` | version не semver |
| `test_invalid_path_format` | Путь не начинается с `./` |
| `test_skill_missing_skill_md` | Папка skill без SKILL.md |
| `test_name_collision` | Одинаковые имена в skills и commands |
| `test_not_in_marketplace` | Плагин не зарегистрирован |
| `test_marketplace_name_mismatch` | Имена не совпадают |

### Фикстуры

```python
@pytest.fixture
def temp_plugin(tmp_path) -> Path:
    """Создаёт минимальный валидный плагин."""
    plugin = tmp_path / "plugins" / "test-plugin"
    plugin.mkdir(parents=True)
    (plugin / ".claude-plugin").mkdir()
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "test-plugin", "version": "1.0.0"}'
    )
    return plugin
```

## Порядок реализации

1. **Рефакторинг терминологии**
   - Переименовать `packages.py` → `projects.py`
   - Обновить классы и функции
   - Обновить импорты в `validate.py`, `detect_changes.py`
   - Переименовать `test_packages.py` → `test_projects.py`
   - Запустить тесты

2. **Обновить detect_changes.py**
   - Добавить `packages`, `plugins`, `has_packages`, `has_plugins` в output
   - Обновить тесты

3. **Создать validate_plugin.py**
   - Реализовать все проверки
   - Написать тесты

4. **Создать plugins-ci.yml**
   - detect-changes job
   - validate-structure job
   - lint-scripts job

### Тестирование

```bash
# Unit tests
uv run pytest .github/scripts/tests/ -v

# Локально workflow (act)
act pull_request -W .github/workflows/plugins-ci.yml
```
