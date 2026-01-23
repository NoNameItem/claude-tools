# SonarCloud Integration Design

## Overview

Интеграция SonarCloud в CI pipeline для статического анализа кода и контроля качества Python пакетов в monorepo.

## Цель

Добавить SonarCloud как дополнительный слой проверки качества кода, который:
- Находит баги через data flow analysis (что Ruff не умеет)
- Детектирует security vulnerabilities через taint analysis
- Отслеживает code coverage и дупликацию
- Блокирует PR через Quality Gate при нарушении стандартов

## Scope

- **Включено:** Python пакеты в `packages/`
- **Исключено:** Claude Code плагины в `plugins/` (markdown skills, нет coverage)
- **Исключено:** CI скрипты в `.github/scripts/` (инфраструктура, не продукт)

## Связь с существующими инструментами

| Инструмент | Роль | Когда блокирует PR |
|------------|------|-------------------|
| Ruff | Style, formatting, простые баги | lint job (быстро) |
| ty | Type checking | lint job |
| pytest | Тесты + coverage generation | test job |
| **SonarCloud** | Deep analysis + coverage gate | sonarcloud job |

Ruff и SonarCloud работают параллельно без импорта — избегаем дублирования issues.

## Ключевые решения

| Аспект | Решение | Обоснование |
|--------|---------|-------------|
| Quality Gate | Sonar way | Стандартные пороги, проверено временем |
| Ruff импорт | Нет | Избегаем дублей, разделение ответственности |
| New Code (PR) | vs target branch | Автоматически в SonarCloud |
| New Code (master) | Previous version | С последнего релиза |
| Тесты в анализе | Да, исключены из coverage | Находим баги в тестах |
| Python версии | Динамически из матрицы CI | Из classifiers в pyproject.toml |
| Монорепо | Отдельные проекты в SonarCloud | Независимые dashboards и Quality Gates |
| Главная ветка | master | Консистентность с ci.yml |

### Что анализирует SonarCloud (уникальное)

- **Taint analysis:** SQL/command/XSS injection через отслеживание untrusted data
- **Data flow:** None access, division by zero, unreachable code
- **Async patterns:** 12 правил для async/await anti-patterns
- **ML frameworks:** PyTorch, NumPy, Scikit-learn специфичные баги
- **Regex analysis:** ReDoS, invalid patterns, contradictory assertions
- **Coverage & duplication:** Quality Gate пороги

### Что остаётся за Ruff

- Style и formatting (E, W, I)
- Modernization (UP, PTH)
- Pytest best practices (PT)
- Comprehension style (C4)
- Fast feedback в pre-commit и lint job

## Архитектура workflow

SonarCloud job добавляется в `_reusable-python-ci.yml` после lint и test:

```
PR / push to master
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                 validate-pr / validate-push                 │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                          detect                             │
│              (один пакет на PR — валидация)                 │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│              _reusable-python-ci.yml                        │
│                                                             │
│  ┌───────────┐    ┌───────────────────────────────────┐    │
│  │   lint    │    │              test                 │    │
│  │ ruff, ty  │    │  py3.11 → py3.14 (матрица)        │    │
│  └───────────┘    │  coverage upload (min version)    │    │
│        │          └───────────────────────────────────┘    │
│        │                         │                          │
│        └────────────┬────────────┘                          │
│                     ▼                                       │
│           ┌─────────────────┐                               │
│           │   sonarcloud    │                               │
│           │  static analysis│                               │
│           │  coverage import│                               │
│           │  quality gate   │                               │
│           └─────────────────┘                               │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
    PR Status Checks
    (Ruff + tests + SonarCloud)
```

### Jobs summary

| Job | Количество | Зависит от |
|-----|------------|------------|
| validate | 1 | — |
| detect | 1 | validate |
| lint | 1 | detect |
| test | 4 (матрица Python) | detect |
| sonarcloud | 1 | lint, test |
| **Итого** | **8** | |

## Конфигурация workflow

### Job в _reusable-python-ci.yml

```yaml
sonarcloud:
  name: SonarCloud
  needs: [lint, test]
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0  # full history для blame

    - uses: actions/download-artifact@v4
      with:
        name: coverage-${{ inputs.package }}
        path: ${{ inputs.package-path }}

    - uses: SonarSource/sonarcloud-github-action@master
      env:
        SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
      with:
        projectBaseDir: ${{ inputs.package-path }}
        args: >
          -Dsonar.projectKey=NoNameItem_${{ inputs.package }}
          -Dsonar.organization=nonameitem
          -Dsonar.python.version=${{ join(fromJson(inputs.python-versions), ',') }}
          -Dsonar.sources=src
          -Dsonar.tests=tests
          -Dsonar.python.coverage.reportPaths=coverage.xml
          -Dsonar.coverage.exclusions=**/tests/**,**/conftest.py
```

### Secrets

| Secret | Описание | Где получить |
|--------|----------|--------------|
| `SONAR_TOKEN` | API token для SonarCloud | SonarCloud → My Account → Security |

Token добавляется в GitHub: Settings → Secrets → Actions → `SONAR_TOKEN`

## Настройка проекта в SonarCloud

### Создание проекта (monorepo mode)

1. [SonarCloud](https://sonarcloud.io) → nonameitem org
2. ✚ → "Analyze new project" → "Setup a monorepo"
3. Выбрать репозиторий `NoNameItem/claude-tools`
4. Добавить проект:
   - **Project key:** `NoNameItem_<package-name>` (например `NoNameItem_statuskit`)
   - **Display name:** `<package-name>`

### Настройки проекта (Administration)

| Раздел | Настройка | Значение |
|--------|-----------|----------|
| New Code | Definition | Previous Version |
| Quality Gate | Gate | Sonar way |
| General | Main branch | master |

### Sonar way Quality Gate (стандартные пороги)

| Метрика | Порог | На новый код |
|---------|-------|--------------|
| Coverage | ≥ 80% | ✓ |
| Duplications | ≤ 3% | ✓ |
| Reliability Rating | A (0 bugs) | ✓ |
| Security Rating | A (0 vulnerabilities) | ✓ |
| Maintainability Rating | A | ✓ |
| Security Hotspots Reviewed | 100% | ✓ |

### PR Decoration

Автоматически включено при подключении GitHub. SonarCloud будет:
- Добавлять статус check в PR
- Оставлять summary comment с метриками
- Добавлять inline comments на проблемные строки

## Добавление нового Python пакета

### Чеклист

- [ ] Структура пакета создана
- [ ] `pyproject.toml` с Python classifiers
- [ ] Проект создан в SonarCloud (monorepo mode)
- [ ] Добавлен в release-please (если нужен PyPI)

### 1. Структура пакета

```
packages/
└── new-package/
    ├── pyproject.toml      # Обязательно с classifiers
    ├── CHANGELOG.md
    ├── src/new_package/
    │   └── __init__.py
    └── tests/
```

**pyproject.toml:**
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

> CI автоматически обнаружит пакет по структуре директорий.
> Scope для conventional commits определяется по имени директории.

### 2. SonarCloud проект

**Без этого шага CI упадёт с ошибкой "Project not found".**

1. SonarCloud → nonameitem → ✚ → "Analyze new project" → "Setup a monorepo"
2. Выбрать `NoNameItem/claude-tools`
3. Project key: `NoNameItem_new-package`
4. Administration → New Code: Previous Version
5. Administration → Quality Gate: Sonar way

### 3. Release-please (опционально)

Если пакет публикуется на PyPI, добавить в `release-please-config.json` и `.release-please-manifest.json`.

## Тестирование

### Перед началом

1. Создать проект `NoNameItem_statuskit` в SonarCloud
2. Добавить `SONAR_TOKEN` в GitHub Secrets

### Локальное тестирование

SonarCloud требует токен и облачную инфраструктуру — локально не тестируется.

Можно проверить:
```bash
# Coverage генерируется корректно
cd packages/statuskit
uv run pytest --cov --cov-report=xml
ls coverage.xml  # должен существовать
```

### Тестирование на GitHub

1. Создать PR с изменениями в `packages/statuskit/`
2. Проверить что jobs выполняются:
   - ✅ lint
   - ✅ test (4 версии Python)
   - ✅ sonarcloud
3. Проверить PR:
   - SonarCloud status check появился
   - Summary comment с метриками
   - Quality Gate passed/failed

### Возможные ошибки

| Ошибка | Причина | Решение |
|--------|---------|---------|
| "Project not found" | Проект не создан в SonarCloud | Создать через UI (monorepo mode) |
| "Invalid token" | SONAR_TOKEN неверный/отсутствует | Проверить GitHub Secrets |
| "No coverage data" | coverage.xml не найден | Проверить путь в artifact upload |
| Quality Gate failed | Не прошли пороги | Исправить код или review issues |

## Этапы реализации

### Шаг 1: Настройка SonarCloud (вручную)

1. Создать проект `NoNameItem_statuskit` в SonarCloud UI
2. Настроить New Code Definition: Previous Version
3. Настроить Quality Gate: Sonar way
4. Добавить `SONAR_TOKEN` в GitHub Secrets

### Шаг 2: Обновить _reusable-python-ci.yml

Добавить job `sonarcloud` после `lint` и `test`.

### Шаг 3: Тестирование

1. Создать PR с изменениями в statuskit
2. Убедиться что SonarCloud job проходит
3. Проверить Quality Gate статус в PR

### Шаг 4: Документация

Добавить секцию "Добавление нового пакета" в CONTRIBUTING.md.

## Зависимости

- **Блокируется:** claude-tools-2a4 (CI orchestrator generalization)
- **Требует:** SONAR_TOKEN в GitHub Secrets
- **Требует:** Проект создан в SonarCloud UI
