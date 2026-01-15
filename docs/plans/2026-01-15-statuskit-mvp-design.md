# StatusKit MVP Design

## Overview

Минимальная рабочая версия statuskit — модульный statusline для Claude Code. MVP включает core-инфраструктуру и один модуль `model`.

## JSON Input от Claude Code

Claude Code передаёт на stdin:

```json
{
  "hook_event_name": "Status",
  "session_id": "abc123...",
  "transcript_path": "/path/to/transcript.json",
  "cwd": "/current/working/directory",
  "model": {
    "id": "claude-opus-4-1",
    "display_name": "Opus"
  },
  "workspace": {
    "current_dir": "/current/working/directory",
    "project_dir": "/original/project/directory"
  },
  "version": "1.0.80",
  "output_style": {
    "name": "default"
  },
  "cost": {
    "total_cost_usd": 0.01234,
    "total_duration_ms": 45000,
    "total_api_duration_ms": 2300,
    "total_lines_added": 156,
    "total_lines_removed": 23
  },
  "context_window": {
    "total_input_tokens": 15234,
    "total_output_tokens": 4521,
    "context_window_size": 200000,
    "current_usage": {
      "input_tokens": 8500,
      "output_tokens": 1200,
      "cache_creation_input_tokens": 5000,
      "cache_read_input_tokens": 2000
    }
  }
}
```

## Структура пакета

```
statuskit/
├── __init__.py           # main()
├── core/
│   ├── __init__.py
│   ├── types.py          # StatusInput, RenderContext, etc.
│   ├── config.py         # Config, load_config()
│   └── loader.py         # load_modules()
└── modules/
    ├── __init__.py       # re-export BaseModule, RenderContext
    ├── base.py           # BaseModule
    └── model.py          # ModelModule
```

## Зависимости

```toml
[project]
dependencies = ["termcolor"]
```

Для форматирования вывода используем `termcolor`. Разработчики сторонних модулей могут использовать любую библиотеку, но рекомендуем `termcolor` для консистентности.

## Компоненты

### core/types.py — Типы данных

```python
from dataclasses import dataclass

@dataclass
class Model:
    id: str
    display_name: str

@dataclass
class Workspace:
    current_dir: str
    project_dir: str

@dataclass
class Cost:
    total_cost_usd: float
    total_duration_ms: int
    total_api_duration_ms: int
    total_lines_added: int
    total_lines_removed: int

@dataclass
class CurrentUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int

@dataclass
class ContextWindow:
    context_window_size: int
    total_input_tokens: int
    total_output_tokens: int
    current_usage: CurrentUsage | None

@dataclass
class StatusInput:
    session_id: str
    cwd: str
    model: Model
    workspace: Workspace
    cost: Cost
    context_window: ContextWindow

    @classmethod
    def from_dict(cls, data: dict) -> "StatusInput":
        """Парсинг JSON в dataclass с дефолтами для отсутствующих полей."""
        ...

@dataclass
class RenderContext:
    debug: bool
    data: StatusInput
```

### core/config.py — Конфигурация

```python
from dataclasses import dataclass, field
from pathlib import Path
import tomllib

CONFIG_PATH = Path.home() / ".claude" / "statuskit.toml"

@dataclass
class Config:
    debug: bool = False
    modules: list[str] = field(default_factory=lambda: ["model", "git", "beads", "quota"])
    module_configs: dict[str, dict] = field(default_factory=dict)

    def get_module_config(self, name: str) -> dict:
        return self.module_configs.get(name, {})

def load_config() -> Config:
    if not CONFIG_PATH.exists():
        return Config()

    with open(CONFIG_PATH, "rb") as f:
        data = tomllib.load(f)

    module_configs = {
        k: v for k, v in data.items()
        if isinstance(v, dict) and k not in ("debug", "modules")
    }

    return Config(
        debug=data.get("debug", False),
        modules=data.get("modules", Config.modules),
        module_configs=module_configs,
    )
```

### modules/base.py — Базовый класс модуля

```python
from abc import ABC, abstractmethod
from statuskit.core.types import RenderContext

class BaseModule(ABC):
    name: str
    description: str

    def __init__(self, ctx: RenderContext, config: dict):
        self.debug = ctx.debug
        self.data = ctx.data
        self.config = config

    @abstractmethod
    def render(self) -> str | None:
        """Вернуть строку или None если нечего показывать."""
        ...
```

При переопределении `__init__` вызывайте `super().__init__(ctx, config)`.

### modules/__init__.py — Экспорты

```python
from statuskit.core.types import RenderContext
from statuskit.modules.base import BaseModule

__all__ = ["BaseModule", "RenderContext"]
```

### core/loader.py — Загрузчик модулей

```python
from statuskit.core.types import RenderContext
from statuskit.core.config import Config
from statuskit.modules.base import BaseModule
from statuskit.modules import model

BUILTIN_MODULES: dict[str, type[BaseModule]] = {
    "model": model.ModelModule,
    # "git": ...,    # v0.2
    # "beads": ...,  # v0.3
    # "quota": ...,  # v0.4
}

def load_modules(config: Config, ctx: RenderContext) -> list[BaseModule]:
    modules = []
    for name in config.modules:
        if name in BUILTIN_MODULES:
            module_config = config.get_module_config(name)
            modules.append(BUILTIN_MODULES[name](ctx, module_config))
        elif ctx.debug:
            print(f"[!] Unknown module: {name}")
    return modules
```

### modules/model.py — Модуль модели

```python
from termcolor import colored
from statuskit.modules.base import BaseModule
from statuskit.core.types import StatusInput, ContextWindow

class ModelModule(BaseModule):
    name = "model"
    description = "Model name, session duration, context window usage"

    def __init__(self, ctx, config: dict):
        super().__init__(ctx, config)
        self.show_duration = config.get("show_duration", True)
        self.show_context = config.get("show_context", True)

    def render(self) -> str | None:
        parts = []

        # [Model name]
        parts.append(f"[{self.data.model.display_name}]")

        # Duration: 2h 15m
        if self.show_duration and self.data.cost.total_duration_ms:
            duration = self._format_duration(self.data.cost.total_duration_ms)
            parts.append(duration)

        # Context: 150,000 free (75.0%)
        if self.show_context:
            ctx_str = self._format_context(self.data.context_window)
            if ctx_str:
                parts.append(f"Context: {ctx_str}")

        return " | ".join(parts) if parts else None

    def _format_duration(self, ms: int) -> str:
        total_sec = ms // 1000
        hours, remainder = divmod(total_sec, 3600)
        minutes = remainder // 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def _format_context(self, ctx: ContextWindow) -> str | None:
        if not ctx.current_usage or not ctx.context_window_size:
            return None

        usage = ctx.current_usage
        used = usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens
        free = ctx.context_window_size - used
        pct = (free / ctx.context_window_size) * 100

        if pct > 50:
            color = "green"
        elif pct > 25:
            color = "yellow"
        else:
            color = "red"

        free_fmt = f"{free:,}"
        return colored(f"{free_fmt} free ({pct:.1f}%)", color)
```

Вывод: `[Opus] | 2h 15m | Context: 150,000 free (75.0%)`

### __init__.py — Entry point

```python
import sys
import json
from termcolor import colored

from .core.config import load_config
from .core.loader import load_modules
from .core.types import StatusInput, RenderContext

def main():
    # 1. Загрузить конфиг
    config = load_config()

    # 2. Прочитать данные от Claude Code
    try:
        raw_data = json.load(sys.stdin)
        data = StatusInput.from_dict(raw_data)
    except Exception as e:
        if config.debug:
            print(colored(f"[!] Failed to parse input: {e}", "red"))
        return

    # 3. Создать контекст
    ctx = RenderContext(debug=config.debug, data=data)

    # 4. Загрузить модули
    modules = load_modules(config, ctx)

    # 5. Рендерить модули
    for mod in modules:
        try:
            output = mod.render()
            if output:
                print(output)
        except Exception as e:
            if config.debug:
                print(colored(f"[!] {mod.name}: {e}", "red"))

if __name__ == "__main__":
    main()
```

## Конфигурация

Файл: `~/.claude/statuskit.toml`

```toml
debug = false

modules = ["model", "git", "beads", "quota"]

[model]
show_duration = true
show_context = true
```

Дефолт если файл отсутствует:
- `debug = false`
- `modules = ["model", "git", "beads", "quota"]`

## Обработка ошибок

| Ситуация | Обычный режим | Debug режим |
|----------|---------------|-------------|
| Ошибка парсинга stdin | Молча завершить | Показать ошибку |
| Неизвестный модуль | Пропустить | Показать `[!] Unknown module: X` |
| Ошибка в render() | Пропустить | Показать `[!] module_name: error` |

## Расчёт контекста

Формула использованных токенов (из документации Claude Code):

```
used = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
```

`output_tokens` не учитываются.

## Дистрибуция

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
uv sync && uv run statuskit
```

## Тестирование

```bash
echo '{"model":{"display_name":"Test"},"workspace":{"current_dir":"/tmp","project_dir":"/tmp"},"cost":{"total_duration_ms":3600000},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":1000,"output_tokens":500,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}' | uv run statuskit
```

## Связь с другими документами

Этот документ детализирует MVP из `2026-01-15-statuskit-design.md`. Roadmap остаётся в силе:

- **v0.1 (MVP)** — core + model module ← этот документ
- **v0.2** — git module
- **v0.3** — beads module
- **v0.4** — quota module
- **v0.5** — external modules
- **v0.6** — testing helpers, documentation
