# StatusKit MVP Design

## Overview

Минимальная рабочая версия statuskit — модульный statusline для Claude Code. MVP включает core-инфраструктуру и один модуль `model`.

## JSON Input от Claude Code

Claude Code передаёт на stdin через pipe:

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

Поля могут отсутствовать — парсер использует None для отсутствующих значений.

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

Для форматирования вывода используем `termcolor`. Разработчики сторонних модулей могут использовать любую библиотеку.

## Компоненты

### core/types.py — Типы данных

```python
from dataclasses import dataclass

@dataclass
class Model:
    id: str | None
    display_name: str

@dataclass
class Workspace:
    current_dir: str
    project_dir: str

@dataclass
class Cost:
    total_cost_usd: float | None
    total_duration_ms: int | None
    total_api_duration_ms: int | None
    total_lines_added: int | None
    total_lines_removed: int | None

@dataclass
class CurrentUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int

@dataclass
class ContextWindow:
    context_window_size: int | None
    total_input_tokens: int | None
    total_output_tokens: int | None
    current_usage: CurrentUsage | None

@dataclass
class StatusInput:
    session_id: str | None
    cwd: str | None
    model: Model | None
    workspace: Workspace | None
    cost: Cost | None
    context_window: ContextWindow | None

    @classmethod
    def from_dict(cls, data: dict) -> "StatusInput":
        """Парсинг JSON в dataclass. Отсутствующие поля = None."""
        model_data = data.get("model")
        model = Model(
            id=model_data.get("id"),
            display_name=model_data.get("display_name", "Unknown"),
        ) if model_data else None

        workspace_data = data.get("workspace")
        workspace = Workspace(
            current_dir=workspace_data.get("current_dir", ""),
            project_dir=workspace_data.get("project_dir", ""),
        ) if workspace_data else None

        cost_data = data.get("cost")
        cost = Cost(
            total_cost_usd=cost_data.get("total_cost_usd"),
            total_duration_ms=cost_data.get("total_duration_ms"),
            total_api_duration_ms=cost_data.get("total_api_duration_ms"),
            total_lines_added=cost_data.get("total_lines_added"),
            total_lines_removed=cost_data.get("total_lines_removed"),
        ) if cost_data else None

        ctx_data = data.get("context_window")
        context_window = None
        if ctx_data:
            usage_data = ctx_data.get("current_usage")
            current_usage = CurrentUsage(
                input_tokens=usage_data.get("input_tokens", 0),
                output_tokens=usage_data.get("output_tokens", 0),
                cache_creation_input_tokens=usage_data.get("cache_creation_input_tokens", 0),
                cache_read_input_tokens=usage_data.get("cache_read_input_tokens", 0),
            ) if usage_data else None

            context_window = ContextWindow(
                context_window_size=ctx_data.get("context_window_size"),
                total_input_tokens=ctx_data.get("total_input_tokens"),
                total_output_tokens=ctx_data.get("total_output_tokens"),
                current_usage=current_usage,
            )

        return cls(
            session_id=data.get("session_id"),
            cwd=data.get("cwd"),
            model=model,
            workspace=workspace,
            cost=cost,
            context_window=context_window,
        )

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
from termcolor import colored

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

    try:
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        # Ошибки конфига всегда показываем
        print(colored(f"[!] Config error: {e}", "red"))
        return Config()

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
        """Вернуть строку (может быть многострочной) или None."""
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
from statuskit.core.types import ContextWindow

class ModelModule(BaseModule):
    name = "model"
    description = "Model name, session duration, context window usage"

    def __init__(self, ctx, config: dict):
        super().__init__(ctx, config)
        self.show_duration = config.get("show_duration", True)
        self.show_context = config.get("show_context", True)
        self.context_format = config.get("context_format", "free")
        self.context_compact = config.get("context_compact", False)
        self.threshold_green = config.get("context_threshold_green", 50)
        self.threshold_yellow = config.get("context_threshold_yellow", 25)

    def render(self) -> str | None:
        parts = []

        # [Model name]
        if self.data.model:
            parts.append(f"[{self.data.model.display_name}]")

        # Duration: 2h 15m
        if self.show_duration:
            duration = self._format_duration()
            if duration:
                parts.append(duration)

        # Context: 150,000 free (75.0%)
        if self.show_context:
            ctx_str = self._format_context()
            if ctx_str:
                parts.append(f"Context: {ctx_str}")

        return " | ".join(parts) if parts else None

    def _format_duration(self) -> str | None:
        if not self.data.cost or not self.data.cost.total_duration_ms:
            return None

        ms = self.data.cost.total_duration_ms
        if ms == 0:
            return None

        total_sec = ms // 1000
        if total_sec < 60:
            return f"{total_sec}s"

        hours, remainder = divmod(total_sec, 3600)
        minutes = remainder // 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def _format_context(self) -> str | None:
        ctx = self.data.context_window
        if not ctx or not ctx.current_usage or not ctx.context_window_size:
            return None

        usage = ctx.current_usage
        total = ctx.context_window_size
        used = usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens
        free = total - used
        pct_free = (free / total) * 100
        pct_used = (used / total) * 100

        # Determine color based on free percentage
        if pct_free > self.threshold_green:
            color = "green"
        elif pct_free > self.threshold_yellow:
            color = "yellow"
        else:
            color = "red"

        # Format numbers
        if self.context_compact:
            free_fmt = self._compact_number(free)
            used_fmt = self._compact_number(used)
            total_fmt = self._compact_number(total)
            pct_fmt = f"{pct_free:.0f}%" if self.context_format == "free" else f"{pct_used:.0f}%"
        else:
            free_fmt = f"{free:,}"
            used_fmt = f"{used:,}"
            total_fmt = f"{total:,}"
            pct_fmt = f"{pct_free:.1f}%" if self.context_format == "free" else f"{pct_used:.1f}%"

        # Format output based on style
        if self.context_format == "free":
            text = f"{free_fmt} free ({pct_fmt})"
        elif self.context_format == "used":
            text = f"{used_fmt} used ({pct_fmt})"
        elif self.context_format == "ratio":
            pct_fmt = f"{pct_used:.0f}%" if self.context_compact else f"{pct_used:.1f}%"
            text = f"{used_fmt}/{total_fmt} ({pct_fmt})"
        elif self.context_format == "bar":
            bar = self._make_bar(pct_free)
            text = f"{bar} {pct_free:.0f}%"
        else:
            text = f"{free_fmt} free ({pct_fmt})"

        return colored(text, color)

    def _compact_number(self, n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.0f}k"
        return str(n)

    def _make_bar(self, pct_free: float, width: int = 10) -> str:
        filled = int(pct_free / 100 * width)
        empty = width - filled
        return f"[{'█' * filled}{'░' * empty}]"
```

Примеры вывода:
- `[Opus] | 2h 15m | Context: 150,000 free (75.0%)`
- `[Opus] | 45s | Context: 150k free (75%)`
- `[Opus] | 2h 15m | Context: [████████░░] 75%`

### __init__.py — Entry point

```python
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

    # 3. Прочитать данные от Claude Code
    try:
        raw_data = json.load(sys.stdin)
        data = StatusInput.from_dict(raw_data)
    except Exception as e:
        if config.debug:
            print(colored(f"[!] Failed to parse input: {e}", "red"))
        return

    # 4. Создать контекст
    ctx = RenderContext(debug=config.debug, data=data)

    # 5. Загрузить модули
    modules = load_modules(config, ctx)

    # 6. Рендерить модули
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
context_format = "free"          # free | used | ratio | bar
context_compact = false          # true = "150k", false = "150,000"
context_threshold_green = 50     # >50% free = green
context_threshold_yellow = 25    # >25% free = yellow, else red
```

Дефолт если файл отсутствует:
- `debug = false`
- `modules = ["model", "git", "beads", "quota"]`

Несуществующие модули в списке молча пропускаются (показываются в debug режиме).

## Обработка ошибок

| Ситуация | Поведение |
|----------|-----------|
| stdin is tty | Показать usage и выйти |
| Ошибка парсинга конфига | **Всегда** показать ошибку, использовать дефолт |
| Ошибка парсинга stdin | Молча завершить (debug: показать ошибку) |
| Неизвестный модуль | Пропустить (debug: показать `[!] Unknown module: X`) |
| Ошибка в render() | Пропустить (debug: показать `[!] module_name: error`) |
| Отсутствующие поля JSON | None в dataclass, модуль проверяет перед использованием |

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
- **v0.4** — quota module (+ cache_dir в RenderContext)
- **v0.5** — external modules
- **v0.6** — testing helpers, documentation
