# Плагин `flow` — Дизайн

## Назначение
Автоматизация работы с задачами beads через slash-команды Claude Code. Устраняет необходимость писать повторяющиеся промпты.

---

## Команды

### `/flow:start [task]`
**Когда:** Начало сессии (после `/clear` или запуска CC)

**Что делает:**
1. Без аргумента — показывает in_progress leaves + ready детей, даёт выбрать
2. С аргументом — ищет задачу по id или тексту
3. Ставит статус in_progress
4. Спрашивает про ветку:
   - Generic ветка (main/master/develop) → рекомендует создать новую
   - Feature ветка → нейтрально спрашивает
5. Показывает description задачи (дизайн/план если есть)

---

### `/flow:after-design`
**Когда:** После `superpowers:brainstorming`

**Что делает:**
1. Находит in_progress leaf-задачу
2. Находит свежий дизайн в `docs/plans/`
3. Сохраняет путь в description: `Design: docs/plans/...`
4. Эвристически ищет подзадачи в дизайне
5. Если найдены — показывает превью с зависимостями, просит подтверждение
6. Если есть существующие подзадачи — умный мерж:
   - Новые → создать
   - Существующие → пропустить
   - Похожие → спросить
7. Если не найдены — просит указать секцию или подтвердить отсутствие

---

### `/flow:after-plan`
**Когда:** После `superpowers:writing-plans`

**Что делает:**
1. Находит in_progress leaf-задачу
2. Находит свежий план в `docs/plans/`
3. Сохраняет путь в description: `Plan: docs/plans/...`

---

### `/flow:done`
**Когда:** После верификации (ручное тестирование завершено)

**Что делает:**
1. Проверяет текущую ветку — если feature-ветка, останавливается и предлагает `/superpowers:finishing-a-development-branch`
2. Находит in_progress leaf-задачу
3. Закрывает её
4. Рекурсивно проверяет родителей — если нет открытых детей, предлагает закрыть
5. Выполняет `bd sync`

---

## Типичный workflow

```
[Сессия 1]
/flow:start                    → выбрать задачу, создать ветку
/superpowers:brainstorming     → дизайн
/flow:after-design             → сохранить, создать подзадачи
/clear

[Сессия 2]
/flow:start                    → продолжить подзадачу
/superpowers:brainstorming     → уточнить дизайн
/flow:after-design             → обновить
/clear

[Сессия 3]
/flow:start                    → продолжить
/superpowers:writing-plans     → план имплементации
/flow:after-plan               → сохранить
/clear

[Сессия 4]
/flow:start                    → продолжить
/superpowers:executing-plans   → имплементация
... ручная верификация ...
/superpowers:finishing-a-development-branch  → мерж
/flow:done                     → закрыть задачу + родителей
```

---

## Структура плагина

```
plugins/flow/
├── plugin.json
└── skills/
    ├── start.md
    ├── after-design.md
    ├── after-plan.md
    └── done.md
```
