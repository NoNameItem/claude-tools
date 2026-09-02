# StatusKit Design

## Overview

Модульный statusline kit для Claude Code. Набор встроенных модулей с включением/выключением через конфиг + возможность подгружать внешние модули из произвольных .py файлов.

## Roadmap

### MVP (v0.1)
1. `core/types.py` — парсинг JSON от Claude Code в dataclass
2. `core/config.py` — загрузка TOML конфига
3. `core/loader.py` — загрузка встроенных модулей по конфигу
4. `modules/base.py` — BaseModule абстракция
5. `modules/model.py` — модель + контекст + duration
6. `__init__.py` — main() связывает всё вместе

### Модуль git (v0.2)
7. `modules/git.py` — директория + ветка + статус + изменения

### Модуль beads (v0.3)
8. `modules/beads.py` — дерево задач из .beads/

### Модуль quota (v0.4)
9. `modules/quota.py` — квота API (session/weekly), кэширование
10. Добавить `cache_dir` в RenderContext

### Внешние модули (v0.5)
11. Загрузка .py файлов как модулей
12. Алиасы и дубликаты имён

### Полировка (v0.6)
13. `testing.py` — хелперы для тестирования модулей
14. Документация для создания своих модулей

## Интерфейс модуля

```python
# statuskit/modules/base.py
from abc import ABC, abstractmethod
from statuskit.core.types import RenderContext

class BaseModule(ABC):
    """Базовый класс для всех модулей statuskit"""

    name: str
    description: str

    def __init__(self, ctx: RenderContext, config: dict):
        self.debug = ctx.debug
        self.data = ctx.data
        self.config = config

    @abstractmethod
    def render(self) -> str | None:
        """
        Вернуть строку для отображения или None если нечего показывать.
        Строка может быть многострочной.
        """
        ...
```

### RenderContext

```python
# statuskit/core/types.py
from dataclasses import dataclass
from pathlib import Path

@dataclass
class RenderContext:
    debug: bool
    data: StatusInput
    cache_dir: Path | None = None  # Добавится в v0.4
```

### Пример модуля

```python
from termcolor import colored
from statuskit.modules import BaseModule

class WeatherModule(BaseModule):
    name = "weather"
    description = "Shows current weather"

    def __init__(self, ctx, config: dict):
        super().__init__(ctx, config)
        self.city = config.get("city", "Moscow")

    def render(self) -> str | None:
        temp = self._get_temperature(self.city)
        return colored(f"☀ {temp}°C", "yellow")

    def _get_temperature(self, city: str) -> int:
        # Implementation...
        return 20
```

## Формат конфига (TOML)

```toml
# ~/.claude/statuskit.toml

debug = false

# Порядок модулей = порядок отображения
# Встроенные — по имени, внешние — по пути или с алиасом
modules = [
    "model",
    "git",
    "~/.claude/modules/simple.py",
    { path = "~/.claude/modules/weather.py", alias = "weather" },
    "beads",
    "quota",
]

# Настройки модулей (по имени или алиасу)
[model]
show_duration = true
show_context = true
context_format = "free"
context_compact = false
context_threshold_green = 50
context_threshold_yellow = 25

[git]
show_commit_age = true

[beads]
max_depth = 3

[quota]
show_weekly = true
warning_threshold = 80

[weather]
city = "Moscow"
```

### Логика именования модулей

- Строка без пути (`"git"`) — встроенный модуль, имя = строка
- Строка с путём (`"~/.claude/foo.py"`) — внешний модуль, имя берётся из атрибута `name` класса
- Объект с alias (`{ path = "...", alias = "..." }`) — внешний модуль, имя = alias

### Дубликаты имён

Если два модуля имеют одинаковое итоговое имя:
- Оба загружаются и работают (получают один конфиг)
- Первой строкой statuskit выводится предупреждение:
  ```
  [!] Modules ~/.claude/a.py, ~/.claude/b.py have same name: "weather". Consider using aliases.
  ```

## Обработка ошибок

| Ситуация | Поведение |
|----------|-----------|
| stdin is tty | Показать usage и выйти |
| Ошибка парсинга конфига | **Всегда** показать ошибку, использовать дефолт |
| Ошибка парсинга stdin | Молча завершить (debug: показать ошибку) |
| Ошибка загрузки модуля | Пропустить (debug: показать ошибку) |
| Ошибка в render() | Пропустить (debug: показать ошибку) |
| Дубликаты имён | Предупреждение |
| Отсутствующие поля JSON | None в dataclass, модуль проверяет |

## Структура пакета

```
statuskit/
├── __init__.py          # main() entry point
├── core/
│   ├── __init__.py
│   ├── config.py        # загрузка TOML конфига
│   ├── loader.py        # загрузка модулей (встроенных и внешних)
│   └── types.py         # StatusInput, RenderContext
├── modules/
│   ├── __init__.py      # re-export BaseModule для удобства импорта
│   ├── base.py          # BaseModule
│   ├── model.py         # [Model] duration | Context: ...
│   ├── git.py           # dir | branch status [changes]
│   ├── beads.py         # Task tree
│   └── quota.py         # Quota session/weekly
└── testing.py           # хелперы для тестирования модулей
```

## Зависимости

```toml
[project]
dependencies = ["termcolor"]
```

Для форматирования вывода используем `termcolor`. Разработчики сторонних модулей могут использовать любую библиотеку.

## Дистрибуция

pip-пакет с CLI entry point (часть claude-tools monorepo):

```toml
# packages/statuskit/pyproject.toml
[project]
name = "statuskit"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["termcolor"]

[project.scripts]
statuskit = "statuskit:main"
```

Установка:
```bash
pip install statuskit
# или из monorepo:
uv sync && uv run statuskit
```

## Testing helpers

```python
# testing.py
from pathlib import Path
from statuskit.core.types import RenderContext, StatusInput

def make_test_context(
    debug: bool = True,
    cache_dir: Path | None = None,
    **data_overrides,
) -> RenderContext:
    """Создать контекст для тестов с разумными дефолтами"""
    data = make_test_data(**data_overrides)
    return RenderContext(debug=debug, data=data, cache_dir=cache_dir)

def make_test_data(**overrides) -> StatusInput:
    """Создать тестовые данные от Claude Code"""
    defaults = {
        "session_id": "test-123",
        "cwd": "/tmp",
        "model": {"id": "test-model", "display_name": "Test"},
        "workspace": {"current_dir": "/tmp", "project_dir": "/tmp"},
        "cost": {"total_duration_ms": 60000},
        "context_window": {
            "context_window_size": 200000,
            "current_usage": {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
    }
    defaults.update(overrides)
    return StatusInput.from_dict(defaults)
```

## Главный цикл

```python
# statuskit/__init__.py
import sys
import json
from termcolor import colored

from .core.config import load_config
from .core.loader import load_modules
from .core.types import StatusInput, RenderContext

def main():
    # 1. Проверка stdin
    if sys.stdin.isatty():
        print("statuskit: reads JSON from stdin")
        print("Usage: echo '{...}' | statuskit")
        return

    # 2. Загрузить конфиг
    config = load_config()

    # 3. Загрузить модули
    modules, warnings = load_modules(config)

    # 4. Прочитать данные от Claude Code
    try:
        raw_data = json.load(sys.stdin)
        data = StatusInput.from_dict(raw_data)
    except Exception as e:
        if config.debug:
            print(colored(f"[!] Failed to parse input: {e}", "red"))
        return

    # 5. Создать контекст
    ctx = RenderContext(debug=config.debug, data=data, cache_dir=config.cache_dir)

    # 6. Вывести предупреждения о дубликатах
    for warning in warnings:
        print(colored(f"[!] {warning}", "yellow"))

    # 7. Рендерить модули
    for mod in modules:
        try:
            mod_instance = mod.cls(ctx, config.get_module_config(mod.name))
            output = mod_instance.render()
            if output:
                print(output)
        except Exception as e:
            if config.debug:
                path_hint = f" ({mod.path})" if mod.path else ""
                print(colored(f"[!] {mod.name}{path_hint}: {e}", "red"))

if __name__ == "__main__":
    main()
```

## Дефолтный конфиг

Если `~/.claude/statuskit.toml` не существует:

```toml
debug = false
modules = ["model", "git", "beads", "quota"]
```

Несуществующие модули в списке молча пропускаются.

## Связь с другими документами

Этот документ заменяет:
- `2026-01-14-statusline-rewrite.md` — исходные требования
- `2026-01-15-statusline-architecture.md` — архитектура плагинов

Детализация:
- `2026-01-15-statuskit-mvp-design.md` — детальный дизайн MVP (v0.1)
