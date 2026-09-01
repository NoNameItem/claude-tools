# Statusline Architecture Design

## Overview

Расширяемая архитектура statusline с поддержкой плагинов. Набор встроенных модулей с включением/выключением через конфиг + возможность подгружать внешние модули из произвольных .py файлов.

## Интерфейс модуля

```python
# statusline/core/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

@dataclass
class RenderContext:
    style: "Style"
    cache_dir: Path
    debug: bool

class BaseModule(ABC):
    """Базовый класс для всех модулей statusline"""

    name: str
    description: str
    default_enabled: bool = True
    config_schema: dict = {}

    def __init__(self, ctx: RenderContext):
        self.style = ctx.style
        self.cache_dir = ctx.cache_dir
        self.debug = ctx.debug

    @abstractmethod
    def render(self, data: "StatusInput", config: dict) -> str | None:
        """
        Вернуть строку для отображения или None если нечего показывать.
        Строка может быть многострочной.
        """
        ...
```

### Пример модуля

```python
from statusline.modules import BaseModule

class WeatherModule(BaseModule):
    name = "weather"
    description = "Shows current weather"
    config_schema = {
        "city": {"type": "str", "default": "Moscow"},
    }

    def render(self, data, config):
        temp = self.get_temperature(config["city"])
        return f"{self.style.yellow('☀')} {temp}°C"
```

## Формат конфига (TOML)

```toml
# ~/.claude/statusline.toml

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
- Первой строкой statusline выводится предупреждение:
  ```
  [!] Modules ~/.claude/a.py, ~/.claude/b.py have same name: "weather". Consider using aliases.
  ```

## Обработка ошибок

| Ситуация | Обычный режим | Debug режим |
|----------|---------------|-------------|
| Ошибка парсинга stdin | Молча | Показать ошибку |
| Ошибка загрузки модуля | Пропустить | Показать ошибку |
| Ошибка в render() | Пропустить | Показать ошибку |
| Дубликаты имён | Предупреждение | Предупреждение |

## Структура пакета

```
statusline/
├── __init__.py          # main() entry point
├── core/
│   ├── __init__.py
│   ├── base.py          # BaseModule, RenderContext
│   ├── config.py        # загрузка TOML конфига
│   ├── loader.py        # загрузка модулей (встроенных и внешних)
│   ├── types.py         # StatusInput (данные от Claude Code)
│   └── style.py         # ANSI-стили с гарантированным RESET
├── modules/
│   ├── __init__.py      # re-export BaseModule для удобства импорта
│   ├── model.py         # [Model] duration | Context: ...
│   ├── git.py           # dir | branch status [changes]
│   ├── beads.py         # Task tree
│   └── quota.py         # Quota session/weekly
└── testing.py           # хелперы для тестирования модулей
```

## Дистрибуция

pip-пакет с CLI entry point:

```toml
# pyproject.toml
[project]
name = "claude-statusline"
version = "0.1.0"
requires-python = ">=3.11"

[project.scripts]
claude-statusline = "statusline:main"
```

Установка:
```bash
pip install -e ~/Coding/claude-tools
# или после публикации на PyPI:
pip install claude-statusline
```

## ANSI-стили

```python
# core/style.py
class Style:
    """ANSI-коды с гарантированным RESET"""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"

    @classmethod
    def _wrap(cls, code: str, text: str) -> str:
        if not text:
            return ""
        return f"{code}{text}{cls.RESET}"

    @classmethod
    def bold(cls, text: str) -> str:
        return cls._wrap(cls.BOLD, text)

    @classmethod
    def dim(cls, text: str) -> str:
        return cls._wrap(cls.DIM, text)

    @classmethod
    def red(cls, text: str) -> str:
        return cls._wrap(cls.RED, text)

    @classmethod
    def green(cls, text: str) -> str:
        return cls._wrap(cls.GREEN, text)

    @classmethod
    def yellow(cls, text: str) -> str:
        return cls._wrap(cls.YELLOW, text)
```

## Testing helpers

```python
# testing.py
from pathlib import Path
from statusline.core.base import RenderContext
from statusline.core.types import StatusInput
from statusline.core.style import Style

def make_test_context(**overrides) -> RenderContext:
    """Создать контекст для тестов с разумными дефолтами"""
    defaults = {
        "style": Style,
        "cache_dir": Path("/tmp/statusline-test"),
        "debug": True,
    }
    defaults.update(overrides)
    return RenderContext(**defaults)

def make_test_data(**overrides) -> StatusInput:
    """Создать тестовые данные от Claude Code"""
    defaults = {
        "model": "Test Model",
        "session_id": "test-123",
        "cwd": "/tmp",
        "project_dir": "/tmp",
        "context_window_size": 200000,
        "input_tokens": 1000,
    }
    defaults.update(overrides)
    return StatusInput(**defaults)
```

## Главный цикл

```python
# statusline/__init__.py
import sys
import json
from .core.config import load_config
from .core.loader import load_modules
from .core.types import StatusInput
from .core.base import RenderContext
from .core.style import Style

def main():
    # 1. Загрузить конфиг
    config = load_config()

    # 2. Создать контекст
    ctx = RenderContext(
        style=Style,
        cache_dir=config.cache_dir,
        debug=config.debug,
    )

    # 3. Загрузить модули
    modules, warnings = load_modules(config, ctx)

    # 4. Прочитать данные от Claude Code
    try:
        raw_data = json.load(sys.stdin)
        data = StatusInput.from_dict(raw_data)
    except Exception as e:
        if config.debug:
            print(Style.red(f"[!] Failed to parse input: {e}"))
        return

    # 5. Вывести предупреждения о дубликатах
    for warning in warnings:
        print(Style.yellow(f"[!] {warning}"))

    # 6. Рендерить модули
    for mod in modules:
        try:
            module_config = config.get_module_config(mod.name)
            output = mod.instance.render(data, module_config)
            if output:
                print(output)
        except Exception as e:
            if config.debug:
                path_hint = f" ({mod.path})" if mod.path else ""
                print(Style.red(f"[!] {mod.name}{path_hint}: {e}"))

if __name__ == "__main__":
    main()
```

## Дефолтный конфиг

Если `~/.claude/statusline.toml` не существует:

```toml
debug = false
modules = ["model", "git", "beads", "quota"]
```

## Связь с предыдущим дизайном

Этот документ расширяет `2026-01-14-statusline-rewrite.md`:
- Сохраняет требования к отображению (4 секции)
- Добавляет плагин-архитектуру
- Меняет формат конфига с простого на TOML
- Меняет дистрибуцию со скрипта на pip-пакет
