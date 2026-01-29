# Дизайн: Выбор подзадачи при указании ID в flow:start

**Задача:** claude-tools-lmr
**Дата:** 2026-01-29

## Проблема

Когда пользователь вызывает `/flow:start` с ID задачи, у которой есть открытые подзадачи, скилл должен предложить выбрать конкретную подзадачу, а не сразу начинать работу над родительской задачей.

**Текущее поведение:** сразу показывает родительскую задачу и предлагает работать над ней.

**Ожидаемое поведение:** показать поддерево начиная с указанной задачи, дать выбрать подзадачу.

## Решение

### Поведение команды

| Вызов | Поведение |
|-------|-----------|
| `/flow:start` | Полное дерево, выбор как сейчас |
| `/flow:start <id>` | Поддерево начиная с задачи `<id>` |

### Поиск по ID

- Полный ID: `claude-tools-5dl` → точное совпадение
- Суффикс: `5dl` → поиск по `-5dl` в конце ID

### Логика после нахождения задачи

1. Задача найдена, **есть открытые children** → показать поддерево, пользователь выбирает
2. Задача найдена, **нет открытых children** → сразу к branch workflow
3. Задача **не найдена** → сообщение "Задача с id не найдена, показываю всё дерево" + полное дерево

### Формат поддерева

Родительская задача становится корнем с номером `1.`:

```
1. [E] StatusKit (claude-tools-5dl) | P1 · in_progress
├─ 1.1 [F] Декларативная конфигурация (claude-tools-5dl.9) | P1 · open
├─ 1.2 [F] Git module (claude-tools-5dl.15) | P2 · open
└─ 1.3 [T] CLI review fixes (claude-tools-5dl.11) | P2 · open
   ├─ 1.3.1 [B] --version shows 0.1.0 (claude-tools-7x8) | P2 · open
   └─ 1.3.2 [T] Fix --help text (claude-tools-5dl.11.5) | P3 · open

Выберите задачу (1, 1.1, 1.2, ...):
```

Выбор работает как сейчас — по номеру или ID.

## Изменения в компонентах

### 1. Скрипт `bd-tree.py`

**Новая опция:** `--root <id>`

```bash
bd graph --all --json | python3 bd-tree.py --root 5dl
```

**Логика поиска:**

```python
def find_task_by_id(tasks: dict[str, Task], task_id: str) -> Task | None:
    # Точное совпадение
    if task_id in tasks:
        return tasks[task_id]

    # Поиск по суффиксу -<id>
    suffix = f"-{task_id}"
    for tid, task in tasks.items():
        if tid.endswith(suffix):
            return task

    return None
```

**Поведение при `--root`:**
- Найдена → показать поддерево с этой задачей как корнем `1.`
- Не найдена → вывести предупреждение, показать полное дерево

### 2. Скилл `SKILL.md`

**Изменение в Step 1:**

```bash
# Без аргумента — полное дерево
bd graph --all --json | python3 <skill-base-dir>/scripts/bd-tree.py

# С аргументом — поддерево
bd graph --all --json | python3 <skill-base-dir>/scripts/bd-tree.py --root <task-id>
```

**Добавить проверку после выбора:**

Если у выбранной задачи нет открытых children → сразу к Step 3 (Show Task Description).

### 3. Команда `start.md`

Добавить инструкцию передавать аргумент:

```markdown
**If the user provided a task ID argument** (e.g., `/flow:start 5dl`),
pass it to the skill so it can filter the task tree.
```

## Примеры использования

### Пример 1: Поддерево с children

```
User: /flow:start 5dl

Agent: 1. [E] StatusKit (claude-tools-5dl) | P1 · in_progress
       ├─ 1.1 [F] Декларативная конфигурация (claude-tools-5dl.9) | P1 · open
       ├─ 1.2 [F] Git module (claude-tools-5dl.15) | P2 · open
       └─ 1.3 [T] CLI review fixes (claude-tools-5dl.11) | P2 · open

       Выберите задачу (по номеру или ID):

User: 1.2

Agent: [показывает task box для claude-tools-5dl.15, спрашивает про branch]
```

### Пример 2: Задача без children

```
User: /flow:start 7x8

Agent: [сразу показывает task box для claude-tools-7x8, спрашивает про branch]
```

### Пример 3: Задача не найдена

```
User: /flow:start xyz123

Agent: Задача с id "xyz123" не найдена, показываю всё дерево.

       1. [E] StatusKit (claude-tools-5dl) | P1 · in_progress
       ...

       Выберите задачу (по номеру или ID):
```

## Файлы для изменения

1. `plugins/flow/skills/starting-task/scripts/bd-tree.py` — добавить `--root` опцию
2. `plugins/flow/skills/starting-task/SKILL.md` — добавить логику обработки аргумента
3. `plugins/flow/commands/start.md` — добавить инструкцию про аргумент
