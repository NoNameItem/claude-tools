# Pre-commit Issues: Validation Scripts Implementation

Session: 2026-01-21
Task: claude-tools-5dl.2.1 (CI: Скрипты валидации)

## Summary

При реализации validation scripts (~45 тестов, 5 модулей) столкнулись с множеством проблем pre-commit hooks. Основное время ушло на:
- Борьбу с ruff auto-fix который ломал код
- Правильное размещение noqa комментариев
- Проблемы с workspace при stash

## Ruff Issues

### 1. TC003: Path import в TYPE_CHECKING блок

```python
# ❌ Ruff требует:
from pathlib import Path  # TC003 error

# ✅ Нужно:
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pathlib import Path
```

**Проблема:** Каждый файл с Path требует этот boilerplate.

### 2. S603/S607: subprocess security warnings

```python
# ❌ Noqa на неправильной строке:
subprocess.run(  # noqa: S603, S607
    ["git", "init"], cwd=repo, check=True
)

# ✅ Noqa нужен на строке с массивом:
subprocess.run(  # noqa: S603
    ["git", "init"],  # noqa: S607
    cwd=repo,
    check=True,
)
```

**Проблема:** S603 на `subprocess.run(`, S607 на `["git", ...]` — разные строки!

### 3. EM102: f-string в exception

```python
# ❌ Ruff не разрешает:
raise ValueError(f"Error: {details}")

# ✅ Нужно:
msg = f"Error: {details}"
raise ValueError(msg)
```

### 4. RET503: Ruff auto-fix ломает generators

```python
# Исходный код (правильный):
@pytest.fixture
def temp_repo(tmp_path: Path) -> Generator[Path, None, None]:
    repo = tmp_path / "repo"
    # ... setup ...
    yield repo  # Generator должен yield

# После ruff --fix (СЛОМАНО):
def temp_repo(tmp_path: Path) -> Generator[Path, None, None]:
    # ...
    return repo  # ❌ Ruff заменил yield на return!
```

**Критическая проблема:** Ruff auto-fix меняет `yield` на `return`, ломая generators. Приходится менять return type на `Path` вместо `Generator[Path, None, None]`.

### 5. PLC0415: Late imports

```python
# ❌ Ruff требует top-level imports:
def validate_pr(...):
    from .packages import discover_packages  # PLC0415

# Но это нужно для:
# - Избежания circular imports
# - Package structure в .github/scripts/
```

**Решение:** Добавили в pyproject.toml:
```toml
[tool.ruff.lint.per-file-ignores]
".github/scripts/*.py" = ["PLC0415", "S603"]
```

### 6. RUF100: Unused noqa после других fixes

После исправления одних ошибок, ruff удаляет "лишние" noqa комментарии, которые потом снова нужны.

## Pre-commit Stash Issues

### Workspace Reference Breaking

```
× Failed to build `claude-tools`
├─▶ Failed to parse entry in group `dev`: `claude-statuskit`
╰─▶ `claude-statuskit` references a workspace in `tool.uv.sources`,
    but is not a workspace member
```

**Причина:** Pre-commit делает `git stash` unstaged changes перед проверкой. Если `packages/statuskit/pyproject.toml` имеет unstaged изменения (name: statuskit → claude-statuskit), stash возвращает старую версию, и workspace reference ломается.

**Решение:** Stage все связанные файлы вместе.

## ty Issues

### Unresolved relative imports

```
error[unresolved-import]: Cannot resolve imported module `..packages`
  --> .github/scripts/tests/test_packages.py:9:8
```

**Причина:** ty не понимает `.github/scripts` как Python package.

**Решение:** Добавили в pyproject.toml:
```toml
[tool.ty.src]
exclude = [".github/scripts/tests"]
```

## Финальная конфигурация

```toml
# pyproject.toml
[tool.ruff.lint.per-file-ignores]
"**/tests/**/*.py" = ["S101", "PLR2004"]
".github/scripts/*.py" = ["PLC0415", "S603"]

[tool.ty.src]
exclude = [".github/scripts/tests"]
```

## Recommendations

1. **Не использовать `yield` в fixtures** если не нужен cleanup — ruff сломает
2. **noqa комментарии** — проверять на какой именно строке ошибка
3. **Stage связанные файлы вместе** — workspace references
4. **Добавить ignore rules заранее** для нестандартных locations (.github/scripts)
5. **Использовать haiku subagents** для verbose pre-commit output — экономит контекст

## Time Spent

~60% времени на борьбу с pre-commit hooks вместо написания кода.
