# Python CI Workflows Design

Дизайн для задачи `claude-tools-5dl.2.2`: GitHub Actions workflows для CI Python пакетов.

## Overview

Создание CI pipeline для Python пакетов в monorepo. Включает валидацию коммитов, детекцию изменений, линтинг и тестирование.

## Deliverables

| Файл | Действие | Описание |
|------|----------|----------|
| `.github/workflows/ci.yml` | создать | Caller workflow |
| `.github/workflows/_reusable-python-ci.yml` | создать | Reusable: lint + test |
| `.github/scripts/detect_changes.py` | изменить | Добавить `changed_files` map |

## ci.yml

### Триггеры

```yaml
on:
  pull_request:
    paths:
      - 'packages/**'
      - 'pyproject.toml'
      - 'uv.lock'
  push:
    branches: [master]
    paths:
      - 'packages/**'
      - 'pyproject.toml'
      - 'uv.lock'
```

Параноидальный подход: запускаем CI при изменении tooling файлов (pyproject.toml, uv.lock) для проверки совместимости всех пакетов.

### Jobs

#### 1. validate-pr

```yaml
validate-pr:
  if: github.event_name == 'pull_request'
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0
    - name: Validate PR title
      env:
        PR_TITLE: ${{ github.event.pull_request.title }}
        BASE_REF: ${{ github.event.pull_request.base.ref }}
      run: python .github/scripts/validate.py --pr
```

Валидирует PR title на соответствие conventional commits и single-package rule.

#### 2. validate-push

```yaml
validate-push:
  if: github.event_name == 'push'
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0
    - name: Validate commits
      run: |
        python .github/scripts/validate.py --commits \
          ${{ github.event.before }} \
          ${{ github.sha }}
```

Валидирует каждый коммит в push на соответствие conventional commits.

#### 3. detect

```yaml
detect:
  needs: [validate-pr, validate-push]
  if: |
    always() &&
    (needs.validate-pr.result == 'success' || needs.validate-pr.result == 'skipped') &&
    (needs.validate-push.result == 'success' || needs.validate-push.result == 'skipped')
  runs-on: ubuntu-latest
  outputs:
    matrix: ${{ steps.detect.outputs.matrix }}
    all-packages-matrix: ${{ steps.detect.outputs.all_packages_matrix }}
    has-packages: ${{ steps.detect.outputs.has_packages }}
    tooling-changed: ${{ steps.detect.outputs.tooling_changed }}
    changed-files: ${{ steps.detect.outputs.changed_files }}
  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0
    - name: Detect changes
      id: detect
      run: |
        OUTPUT=$(python .github/scripts/detect_changes.py --ref origin/master..HEAD)
        echo "matrix=$(echo $OUTPUT | jq -c '.matrix')" >> $GITHUB_OUTPUT
        echo "all_packages_matrix=$(echo $OUTPUT | jq -c '.all_packages_matrix')" >> $GITHUB_OUTPUT
        echo "has_packages=$(echo $OUTPUT | jq -r '.has_packages')" >> $GITHUB_OUTPUT
        echo "tooling_changed=$(echo $OUTPUT | jq -r '.tooling_changed')" >> $GITHUB_OUTPUT
        echo "changed_files=$(echo $OUTPUT | jq -c '.changed_files')" >> $GITHUB_OUTPUT
```

#### 4. ci

```yaml
ci:
  needs: detect
  if: needs.detect.outputs.has-packages == 'true' || needs.detect.outputs.tooling-changed == 'true'
  strategy:
    fail-fast: false
    matrix: ${{ needs.detect.outputs.tooling-changed == 'true' && fromJson(needs.detect.outputs.all-packages-matrix) || fromJson(needs.detect.outputs.matrix) }}
  uses: ./.github/workflows/_reusable-python-ci.yml
  with:
    package: ${{ matrix.package }}
    package-path: ${{ matrix.path }}
    python-versions: # см. ниже
    changed-files: ${{ toJson(fromJson(needs.detect.outputs.changed-files)[matrix.package] || '[]') }}
```

**Логика выбора матрицы:**
- Если `tooling_changed == true` → используем `all-packages-matrix` (CI для всех пакетов)
- Иначе → используем `matrix` (только изменённые пакеты)

**Python versions:**
Передаются из матрицы. Матрица строится в `detect_changes.py` на основе classifiers из pyproject.toml каждого пакета.

## _reusable-python-ci.yml

### Inputs

```yaml
on:
  workflow_call:
    inputs:
      package:
        description: 'Package name (e.g., statuskit)'
        required: true
        type: string
      package-path:
        description: 'Path to package (e.g., packages/statuskit)'
        required: true
        type: string
      python-versions:
        description: 'JSON array of Python versions'
        required: true
        type: string
      changed-files:
        description: 'JSON array of changed files for targeted linting'
        required: false
        type: string
        default: '[]'
```

### Jobs

#### 1. lint

Запускается на минимальной версии Python (первая в списке). Без матрицы.

```yaml
lint:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4

    - name: Get minimum Python version
      id: py-version
      run: |
        MIN_PY=$(echo '${{ inputs.python-versions }}' | jq -r '.[0]')
        echo "version=$MIN_PY" >> $GITHUB_OUTPUT

    - uses: astral-sh/setup-uv@v7
      with:
        enable-cache: true
        python-version: ${{ steps.py-version.outputs.version }}

    - name: Install dependencies
      run: uv sync
      working-directory: ${{ inputs.package-path }}

    - name: Filter Python files
      id: filter
      run: |
        FILES='${{ inputs.changed-files }}'
        if [ "$FILES" == "[]" ] || [ -z "$FILES" ]; then
          echo "py_files=${{ inputs.package-path }}" >> $GITHUB_OUTPUT
        else
          PY_FILES=$(echo "$FILES" | jq -r '.[] | select(endswith(".py"))' | tr '\n' ' ')
          if [ -z "$PY_FILES" ]; then
            echo "py_files=" >> $GITHUB_OUTPUT
          else
            echo "py_files=$PY_FILES" >> $GITHUB_OUTPUT
          fi
        fi

    - name: Ruff format check
      id: format
      if: steps.filter.outputs.py_files != ''
      continue-on-error: true
      run: uv run ruff format --check ${{ steps.filter.outputs.py_files }}

    - name: Ruff lint
      id: lint
      if: steps.filter.outputs.py_files != ''
      continue-on-error: true
      run: uv run ruff check ${{ steps.filter.outputs.py_files }}

    - name: Type check
      id: typecheck
      continue-on-error: true
      run: uv run ty check
      working-directory: ${{ inputs.package-path }}

    - name: Check results
      run: |
        failed=false
        if [ "${{ steps.format.outcome }}" == "failure" ]; then
          echo "::error::Ruff format check failed"
          failed=true
        fi
        if [ "${{ steps.lint.outcome }}" == "failure" ]; then
          echo "::error::Ruff lint failed"
          failed=true
        fi
        if [ "${{ steps.typecheck.outcome }}" == "failure" ]; then
          echo "::error::Type check failed"
          failed=true
        fi
        if [ "$failed" == "true" ]; then
          exit 1
        fi
```

**Особенности:**
- `continue-on-error: true` на каждом шаге линтинга — видим все ошибки сразу
- Summary step в конце — fail если любой шаг упал
- Если `changed-files` пуст → lint весь `package-path`
- Фильтрация `.py` файлов через jq

#### 2. test

Запускается в матрице Python версий. `fail-fast: false`.

```yaml
test:
  runs-on: ubuntu-latest
  strategy:
    fail-fast: false
    matrix:
      python: ${{ fromJson(inputs.python-versions) }}
  steps:
    - uses: actions/checkout@v4

    - uses: astral-sh/setup-uv@v7
      with:
        enable-cache: true
        python-version: ${{ matrix.python }}

    - name: Install dependencies
      run: uv sync
      working-directory: ${{ inputs.package-path }}

    - name: Run tests
      run: uv run pytest --cov --cov-report=xml
      working-directory: ${{ inputs.package-path }}

    - name: Get minimum Python version
      id: min-py
      run: |
        MIN_PY=$(echo '${{ inputs.python-versions }}' | jq -r '.[0]')
        echo "version=$MIN_PY" >> $GITHUB_OUTPUT

    - name: Upload coverage
      if: matrix.python == steps.min-py.outputs.version
      uses: actions/upload-artifact@v4
      with:
        name: coverage-${{ inputs.package }}
        path: ${{ inputs.package-path }}/coverage.xml
```

**Особенности:**
- Coverage генерируется для всех версий Python, но артефакт загружается только от минимальной версии
- `fail-fast: false` — запускаем все jobs матрицы даже при ошибке

## detect_changes.py — изменения

### Новое поле в DetectionResult

```python
@dataclass
class DetectionResult:
    projects: list[str] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)
    has_packages: bool = False
    has_plugins: bool = False
    has_repo_level: bool = False
    tooling_changed: bool = False
    matrix: dict = field(default_factory=lambda: {"include": []})
    all_packages_matrix: dict = field(default_factory=lambda: {"include": []})
    changed_files: dict[str, list[str]] = field(default_factory=dict)  # NEW

    def to_json(self) -> str:
        return json.dumps({
            "projects": self.projects,
            "packages": self.packages,
            "plugins": self.plugins,
            "has_packages": self.has_packages,
            "has_plugins": self.has_plugins,
            "has_repo_level": self.has_repo_level,
            "tooling_changed": self.tooling_changed,
            "matrix": self.matrix,
            "all_packages_matrix": self.all_packages_matrix,
            "changed_files": self.changed_files,  # NEW
        })
```

### Новая функция

```python
def build_changed_files_map(
    changed_files: list[str],
) -> dict[str, list[str]]:
    """
    Группирует изменённые файлы по проектам.

    Возвращает ВСЕ файлы без фильтрации по расширению.
    Фильтрация (.py и т.д.) происходит на стороне consumer'а (workflow).

    Args:
        changed_files: список путей изменённых файлов (относительно корня репо)

    Returns:
        Словарь: имя проекта → список файлов.
        Repo-level файлы под ключом "repo".

    Examples:
        >>> build_changed_files_map(["packages/statuskit/src/foo.py"])
        {"statuskit": ["packages/statuskit/src/foo.py"]}

        >>> build_changed_files_map(["pyproject.toml", ".github/scripts/validate.py"])
        {"repo": ["pyproject.toml", ".github/scripts/validate.py"]}

        >>> build_changed_files_map([
        ...     "packages/statuskit/src/foo.py",
        ...     "packages/statuskit/README.md",
        ...     "pyproject.toml"
        ... ])
        {
            "statuskit": ["packages/statuskit/src/foo.py", "packages/statuskit/README.md"],
            "repo": ["pyproject.toml"]
        }
    """
    from .projects import get_project_from_path

    result: dict[str, list[str]] = {}

    for file_path in changed_files:
        project_name = get_project_from_path(file_path)
        key = project_name if project_name else "repo"

        if key not in result:
            result[key] = []
        result[key].append(file_path)

    return result
```

### Интеграция в detect_changes()

```python
def detect_changes(
    changed_files: list[str],
    repo_root: Path,
) -> DetectionResult:
    # ... существующая логика ...

    # Добавляем в конце, перед return
    result.changed_files = build_changed_files_map(changed_files)

    return result
```

## Решения

| Аспект | Решение | Обоснование |
|--------|---------|-------------|
| SonarCloud | Отложен до 5dl.2.6 | Требует отдельной настройки |
| Lint scope | changed-files с фильтрацией .py | Экономия времени на больших пакетах |
| Lint errors | continue-on-error + summary | Видим все ошибки сразу |
| Python versions | Все из classifiers | Python 3.14 уже стабилен |
| Coverage | Только XML, от min Python | Для SonarCloud, без дублирования |
| Caching | setup-uv с enable-cache | Общий кэш эффективнее per-package |
| Python install | setup-uv (uv managed) | Проще, один action |
| Validate jobs | Два отдельных | Явное разделение PR vs push |
| detect job | Внутри ci.yml | Небольшой, не нужен отдельный файл |
| CI workflow | Reusable | Будет использоваться release-please |
| Tooling changes | CI для всех пакетов | Параноидальный подход |

## Тестирование

### Локально

```bash
# Unit tests для изменений в detect_changes.py
pytest .github/scripts/tests/test_detect_changes.py -v

# Lint workflows
actionlint .github/workflows/ci.yml
actionlint .github/workflows/_reusable-python-ci.yml
```

### act (локальный GitHub Actions runner)

```bash
# Симуляция pull_request
act pull_request -W .github/workflows/ci.yml

# С verbose output
act pull_request -W .github/workflows/ci.yml -v
```

### На GitHub

1. Создать PR с изменениями в `packages/statuskit/`
2. Проверить что CI запускается и проходит
3. Проверить что при изменении только `pyproject.toml` запускается CI для всех пакетов

## Связанные задачи

- **claude-tools-5dl.2.1** (closed): Скрипты валидации — `validate.py`, `detect_changes.py`
- **claude-tools-5dl.2.4** (blocked by this): Release-please setup — будет использовать `_reusable-python-ci.yml`
- **claude-tools-5dl.2.6** (blocked by this): SonarCloud интеграция — добавит job в reusable workflow
