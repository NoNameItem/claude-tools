# Visual Task Tree: Emoji + Priority Formatting

**Date:** 2026-02-08
**Status:** Design approved
**Task:** claude-tools-elf.7

## Обзор и цели

**Проблема:** Список задач в `flow:start` — чёрно-белый текст. Тип и приоритет видны только при чтении, визуально ничего не выделяется. Чтобы найти баги или высокоприоритетные задачи, приходится читать каждую строку.

**Решение:** Визуальное кодирование через emoji перед буквой типа `[E]`/`[F]`/`[B]`/`[T]`/`[C]` и markdown bold для приоритета. Emoji дают цветовое различие, буква в скобках — текстовое. Задачи с минимальным приоритетом выделены жирным шрифтом.

**Пример вывода:**

```
1. **📦 [E] StatusKit (claude-tools-5dl) | P1 · in_progress | #statuskit**
   ├─ 1.1 **🚀 [F] Декларативная конфигурация модулей | P1 · open**
   ├─ 1.2 ❌ [B] statuskit --version always shows 0.1.0 | P2 · open
   ├─ 1.3 📋 [T] CLI review fixes | P2 · open
   └─ 1.4 ⚙️ [C] Update dependencies | P4 · open
```

**Почему это работает:**
- Claude Code рендерит сообщения в monospace font — выравнивание tree-символов (`├─`, `└─`) сохраняется
- Emoji отображаются корректно в любом контексте (в отличие от ANSI-кодов)
- Markdown `**bold**` работает вне code blocks, Claude Code поддерживает GitHub-flavored markdown

## Emoji Mapping

| Тип | Emoji | Обоснование |
|-----|-------|-------------|
| Epic | 📦 | Контейнер для подзадач |
| Feature | 🚀 | Запуск чего-то нового |
| Bug | ❌ | Ошибка, не работает |
| Task | 📋 | Клипборд, список дел |
| Chore | ⚙️ | Механика, техническая работа |

**Fallback:** Если тип неизвестен → `❔ [X]` (белый вопрос + первая буква типа).

## Приоритетное выделение

**Логика:** Bold применяется только к задачам с **минимальным приоритетом** среди видимых задач.

**Примеры:**
- Есть задачи P1, P2, P3 → только P1 bold
- Есть задачи P2, P3, P4 → только P2 bold
- Все задачи P1 → все bold
- Одна задача P0, десять P1 → только P0 bold

**Обоснование:** Адаптивное выделение показывает самое срочное относительно текущего списка.

## Техническая реализация

### Изменения в bd-tree.py

**1. Добавить mapping emoji:**

```python
TASK_TYPE_EMOJI = {
    "epic": "📦",
    "feature": "🚀",
    "bug": "❌",
    "task": "📋",
    "chore": "⚙️",
}

def get_type_emoji(issue_type: str) -> str:
    """Get emoji for task type, ❔ if unknown."""
    return TASK_TYPE_EMOJI.get(issue_type.lower(), "❔")
```

**2. Функция поиска минимального приоритета:**

```python
def find_min_priority(tasks: dict[str, Task]) -> int:
    """Find minimum priority among visible tasks."""
    visible_tasks = [t for t in tasks.values() if should_show(t)]
    return min(t.priority for t in visible_tasks) if visible_tasks else 0
```

**3. Функция форматирования строки:**

```python
def format_task_line(task: Task, number: str, min_priority: int) -> str:
    """Format task line with emoji and bold for highest priority tasks."""
    emoji = get_type_emoji(task.issue_type)
    labels_str = f" | {' '.join(f'#{l}' for l in task.labels)}" if task.labels else ""

    type_letter = task.issue_type[0].upper()
    line = f"{number} {emoji} [{type_letter}] {task.title} ({task.id}) | P{task.priority} · {task.status}{labels_str}"

    # Bold for tasks with minimum priority (highest urgency)
    if task.priority == min_priority:
        line = f"**{line}**"

    return line
```

**4. Интеграция в _render_tree_recursive():**

В начале функции рендеринга:
```python
min_priority = find_min_priority(all_tasks)
```

При форматировании каждой задачи:
```python
line = format_task_line(task, number, min_priority)
```

### Изменения в flow:starting-task skill

Добавить явную инструкцию после Step 1 (Build and Display Task Tree):

```markdown
**Display the tree output as plain markdown text, NOT in a code block.**
This ensures emoji and bold formatting render correctly.
```

**Обоснование:**
- Code block (`\`\`\`text ... \`\`\``) не рендерит markdown, `**bold**` показывается как звёздочки
- Plain text рендерит markdown, `**bold**` становится жирным шрифтом
- Claude Code рендерит текст в monospace, выравнивание tree-коннекторов сохраняется

## Тестирование

### Unit Tests (test_bd_tree.py)

```python
def test_get_type_emoji():
    """Test emoji mapping for known and unknown types."""
    assert get_type_emoji("epic") == "📦"
    assert get_type_emoji("feature") == "🚀"
    assert get_type_emoji("bug") == "❌"
    assert get_type_emoji("task") == "📋"
    assert get_type_emoji("chore") == "⚙️"
    assert get_type_emoji("unknown") == "❔"  # fallback


def test_format_task_line_with_min_priority():
    """Test bold formatting for minimum priority tasks."""
    task_p1 = Task(id="test-1", title="High", priority=1, issue_type="bug", status="open")
    task_p2 = Task(id="test-2", title="Medium", priority=2, issue_type="feature", status="open")

    line_p1 = format_task_line(task_p1, "1.", min_priority=1)
    line_p2 = format_task_line(task_p2, "2.", min_priority=1)

    assert line_p1.startswith("**") and line_p1.endswith("**")  # bolded
    assert not line_p2.startswith("**")  # not bolded
    assert "❌" in line_p1  # bug emoji
    assert "🚀" in line_p2  # feature emoji


def test_find_min_priority():
    """Test minimum priority calculation."""
    tasks = {
        "t1": Task(id="t1", priority=1, status="open"),
        "t2": Task(id="t2", priority=2, status="open"),
        "t3": Task(id="t3", priority=3, status="closed"),  # hidden
    }
    assert find_min_priority(tasks) == 1

    # All closed
    tasks_closed = {"t1": Task(id="t1", priority=1, status="closed")}
    assert find_min_priority(tasks_closed) == 0  # default
```

### Integration Test

```bash
bd graph --all --json | python3 bd-tree.py
```

**Проверить:**
- Emoji корректны для всех типов
- Bold применён только к задачам с минимальным приоритетом
- Выравнивание tree-коннекторов не сломано

## Edge Cases

### 1. Неизвестный тип задачи
- Используется ❔ как fallback emoji
- Пример: тип "milestone" → `❔ [M] Title`

### 2. Задачи без приоритета или с некорректным значением
- Если `task.priority` отсутствует или невалиден → считать как P4
- При расчёте `min_priority` игнорировать такие задачи

### 3. Пустое дерево (нет задач)
- `find_min_priority()` вернёт 0
- Ничего не будет bold

### 4. Все задачи одного приоритета
- Все задачи будут bold
- Это ожидаемое поведение — все одинаково важны

### 5. Выравнивание с emoji
- Emoji занимают 2 символа ширины в большинстве терминалов
- `[E]` занимает 3 символа
- Разница в 1 символ может сместить выравнивание
- **Решение:** добавить пробел после emoji для компенсации: `📦 Title` вместо `📦Title`

### 6. Markdown в code block
- Если ассистент обернёт вывод в code block — bold не отрендерится
- Тесты не поймают (тестируют только скрипт)
- Проверить вручную после внедрения

## Файлы для изменения

1. `plugins/flow/skills/starting-task/scripts/bd-tree.py` — основная логика
2. `plugins/flow/skills/starting-task/scripts/test_bd_tree.py` — тесты
3. `plugins/flow/skills/starting-task/SKILL.md` — инструкция по отображению

## Что НЕ меняется

- Логика фильтрации задач (status, blocking, deferred)
- Сортировка задач (status → priority)
- Структура дерева и нумерация (1., 1.1, 1.2)
- Tree-коннекторы (`├─`, `└─`, `│`)
- Аргументы командной строки (`-s`, `-n`, `--collapse`, `--root`)
