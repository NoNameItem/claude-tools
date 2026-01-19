# Дизайн: Дистрибуция statuskit

## Обзор

Подготовка statuskit к публикации на PyPI для пользователей Claude Code. Включает настройку метаданных пакета, команду автоматической интеграции `setup`, и трёхуровневую конфигурацию.

## CLI интерфейс

```
statuskit                          # Основной режим (stdin JSON)
statuskit setup [--scope SCOPE]    # Настройка интеграции
statuskit setup --check            # Статус установки (все scopes)
statuskit setup --remove --scope   # Удаление интеграции
statuskit --help                   # Справка с модулями
statuskit --version                # Версия
```

**Флаги setup:**
- `--scope`, `-s` — `user` (default) | `project` | `local`
- `--check` — проверить все scopes
- `--remove` — удалить (требует --scope)
- `--force` — без подтверждений, с backup

## Команда setup: поведение

**Основной сценарий:**
1. Найти settings.json для указанного scope
2. Проверить, установлен ли statuskit на более высоком scope
3. Добавить/обновить `statusLine` в settings.json
4. Создать `statuskit.toml` с дефолтами

**Пути файлов по scope:**

| Scope | settings.json | statuskit.toml |
|-------|---------------|----------------|
| user | `~/.claude/settings.json` | `~/.claude/statuskit.toml` |
| project | `.claude/settings.json` | `.claude/statuskit.toml` |
| local | `.claude/settings.local.json` | `.claude/statuskit.local.toml` |

**Формат statusLine в settings.json:**
```json
{
  "statusLine": {
    "type": "command",
    "command": "statuskit"
  }
}
```

**Обработка конфликтов:**

| Ситуация | Поведение |
|----------|-----------|
| Хук уже есть (наш) | "Already installed", ничего не делаем |
| Хук уже есть (чужой) | Предупредить → спросить → backup → перезаписать |
| Установлен на уровне выше | Предложить: только конфиг или хук тоже |
| Установлен на уровне ниже | Предупредить, продолжить |
| Нет директории/файла | Создать автоматически |
| `--force` | Пропустить вопросы, делать backup |

**Примечание:** Создание statuskit.toml — независимая операция. Конфиг создаётся если не существует, независимо от состояния хука. Если хук уже установлен (наш), но конфига нет — конфиг будет создан.

**Детекция "нашего" хука:**

```python
import shlex
from pathlib import Path

def is_our_hook(hook: dict) -> bool:
    """Check if the hook points to statuskit."""
    cmd = hook.get("command", "")
    if not cmd:
        return False
    try:
        first_word = shlex.split(cmd)[0]
        return Path(first_word).name == "statuskit"
    except ValueError:
        return False
```

Это позволяет распознать:
- `statuskit`
- `/usr/local/bin/statuskit`
- `~/.local/bin/statuskit --debug`

**Стратегия бэкапов:**

- Бэкап создаётся как `.bak` файл рядом с оригиналом
- Пример: `settings.json` → `settings.json.bak`
- Предыдущий `.bak` перезаписывается
- Бэкап создаётся только при перезаписи чужого хука или с `--force`

## Команда setup: вывод

**Успешная установка:**
```
✓ Added statusline hook to ~/.claude/settings.json
✓ Created ~/.claude/statuskit.toml

Run `claude` to see your new statusline!
```

**Уже установлен выше:**
```
statuskit is already installed at user scope.
The hook will work for this project too.

What would you like to do?
1. Create config only at .claude/statuskit.toml (override settings)
2. Add hook to project scope as well (will duplicate)
3. Cancel
```

**Установка в user при наличии project:**
```
Note: this project has a config at project scope.
It will take priority over user-level settings.

Continue installation? [Y/n]
```

**--check:**
```
User:    ✓ Installed
Project: ✗ Not installed
Local:   ✗ Not installed
```

**--remove с чужим хуком:**
```
statusLine points to a different script: /some/other/script.sh
Remove anyway? [y/N]
```

## Конфигурация statuskit.toml

**Поиск конфига (приоритет):**
1. `.claude/statuskit.local.toml` (Local)
2. `.claude/statuskit.toml` (Project)
3. `~/.claude/statuskit.toml` (User)

**Мерж:** Полное переопределение на уровне top-level ключей. Конфиг с более высоким приоритетом полностью заменяет ключи из нижестоящего.

**Дефолтный statuskit.toml:**
```toml
# Statuskit configuration
# See: https://github.com/NoNameItem/claude-tools

# Modules to display (in order)
modules = ["model", "git", "beads", "quota"]

# Enable debug output
# debug = false
```

## pyproject.toml метаданные

```toml
[project]
name = "statuskit"
version = "0.1.0"
description = "Modular statusline for Claude Code"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Artem Vasin", email = "nonameitem@me.com" }]
keywords = ["claude", "claude-code", "statusline", "cli"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
]
dependencies = ["termcolor"]

[project.scripts]
statuskit = "statuskit:main"

[project.urls]
Homepage = "https://github.com/NoNameItem/claude-tools/tree/master/packages/statuskit"
Repository = "https://github.com/NoNameItem/claude-tools"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/statuskit"]
```

## README.md структура

```markdown
# statuskit

Modular statusline for Claude Code.

## Installation

uv tool install statuskit
# or
pipx install statuskit

## Quick Start

statuskit setup

## Configuration

Configuration file locations (in priority order):
1. `.claude/statuskit.local.toml` (local, gitignored)
2. `.claude/statuskit.toml` (project)
3. `~/.claude/statuskit.toml` (user)

Example:
modules = ["model", "git", "beads", "quota"]

## Built-in Modules

- **model** — Display current Claude model name
- **git** — Show git branch and status
- **beads** — Display active beads tasks
- **quota** — Track token usage

## License

MIT
```

## --help вывод

```
statuskit - Modular statusline for Claude Code

Usage:
  statuskit              Read JSON from stdin, render statusline
  statuskit setup        Configure Claude Code integration

Options:
  -h, --help             Show this help
  -V, --version          Show version

Setup options:
  -s, --scope <scope>    Installation scope: user, project, local (default: user)
  --check                Check installation status (all scopes)
  --remove               Remove integration (requires --scope)
  --force                Skip confirmations, backup and overwrite

Built-in modules:
  model                  Display current Claude model name
  git                    Show git branch and status
  beads                  Display active beads tasks
  quota                  Track token usage
```

## Процесс тестирования

**Локальная сборка и проверка:**
```bash
cd packages/statuskit
uv build
uv tool install dist/statuskit-0.1.0-py3-none-any.whl
statuskit --help
statuskit setup --check
```

**Test PyPI (перед первым релизом):**
```bash
uv publish --index-url https://test.pypi.org/simple/
uv tool install --index-url https://test.pypi.org/simple/ statuskit
```

**Production PyPI:**
```bash
uv publish
```

Автоматизация — в рамках задачи CI/CD (claude-tools-5dl.2).
