# flow-wait-ci: GitHub-ветка всегда таймаутит — дизайн фикса

**Задача:** claude-tools-r1r · тип: bug · P1 · #flow
**Дата:** 2026-07-22

## Проблема

`flow-wait-ci <pr> <sha> --platform github` никогда не возвращает `0` на реальном
GitHub-PR: висит до `WAIT_TIMEOUT` (30 мин) и выходит с кодом `2` (timeout), даже когда
весь пайплайн давно терминальный и зелёный. Из-за этого `/flow:review-loop` на GitHub
нерабочий — каждый раунд упирается в таймаут-промпт.

Воспроизведено на PR #112 (`NoNameItem/claude-tools`), head `6ff336e`: все 20 проверок
pass/skipping, rollup state `SUCCESS`, `mergeStateStatus` `BLOCKED`, сигнатура между двумя
подряд поллами идентична — и всё равно `WAIT_TIMEOUT=40 WAIT_INTERVAL=5 flow-wait-ci 112
<sha> --platform github` → exit 2.

### Причина

`plugins/flow/bin/flow-wait-ci:165-170`:

```python
active = (
    rollup.get("state") in {"EXPECTED", "PENDING"}
    or any(s in GH_ACTIVE_CHECK_STATES for s in check_counts)
    or any(s in GH_ACTIVE_STATUS_STATES for s in status_counts)
)
```

`check_counts` / `status_counts` — это словари `{state: count}`, построенные из
`checkRunCountsByState` / `statusContextCountsByState`. Итерация `for s in check_counts`
идёт по **ключам**. Реальный GitHub возвращает ВЕСЬ енум состояний, включая нулевые:

```
{"count":0,"state":"IN_PROGRESS"}, {"count":0,"state":"QUEUED"},
{"count":0,"state":"PENDING"}, {"count":0,"state":"WAITING"},
{"count":3,"state":"SKIPPED"}, {"count":15,"state":"SUCCESS"}
```

Поэтому активные ключи (`QUEUED`/`IN_PROGRESS`/`PENDING`/`WAITING`) присутствуют всегда →
`active` всегда `True` → условие `terminal` (`flow-wait-ci:215`) не выполняется никогда →
таймаут.

### Почему тесты не поймали

Фейк в `plugins/flow/bin/tests/conftest.py:157-166` (`gh_response`) считает состояния по
факту (`check_counts[st] = check_counts.get(st, 0) + 1`) и сериализует только ненулевые
записи. Реальную форму ответа GitHub (полный енум с нулями) он не воспроизводит, поэтому
баг проходит мимо тестов.

## Решение

### 1. `plugins/flow/bin/flow-wait-ci` (строки 165-170)

Сравнивать по количеству, перебирая фиксированный набор активных состояний, а не
наличие ключа:

```python
active = (
    # rollup `state` uses the same StatusState enum as per-context checks; PENDING/EXPECTED are non-terminal.
    rollup.get("state") in {"EXPECTED", "PENDING"}
    or any(check_counts.get(s, 0) > 0 for s in GH_ACTIVE_CHECK_STATES)
    or any(status_counts.get(s, 0) > 0 for s in GH_ACTIVE_STATUS_STATES)
)
```

Правка минимальная и хирургическая; явно выражает намерение «есть ли активное состояние
с ненулевым count».

**`signature` (строки 171-177) не трогаем.** Нулевые записи в `check_counts` постоянны
между поллами, поэтому на сравнение `snap.signature == prev_sig` они не влияют.

**GitLab-ветка (`_gl_poll`) чистая.** Там `status` — скалярная строка, проверяется
`snap.status not in GL_ACTIVE_STATES` (`flow-wait-ci:302`). Итерации по ключам словаря нет,
аналогичного бага нет — код не меняется.

### 2. Фикстура `plugins/flow/bin/tests/conftest.py` → `gh_response`

Заставить `*CountsByState` отдавать полный набор состояний с нулевыми `count` — реальную
форму ответа GitHub. Добавить константы с полными енумами:

```python
GH_CHECK_STATES  = ["REQUESTED", "QUEUED", "IN_PROGRESS", "COMPLETED", "WAITING", "PENDING"]  # CheckStatusState
GH_STATUS_STATES = ["EXPECTED", "PENDING", "ERROR", "FAILURE", "SUCCESS"]                     # StatusState
```

`checkRunCountsByState` / `statusContextCountsByState` строятся по всем состояниям енума:
фактический count из `nodes`, `0` для отсутствующих. `checkRunCount` / `statusContextCount`
остаются суммой реальных (ненулевых) записей — так и отдаёт GitHub. `nodes` без изменений.

> **Уточнение по реализации.** В итоге сидинг нулями сузили до *активного* подмножества
> состояний (`_GH_ZERO_CHECK_STATES` = `REQUESTED/QUEUED/IN_PROGRESS/WAITING/PENDING`,
> `_GH_ZERO_STATUS_STATES` = `EXPECTED/PENDING`), а не всего енума. Терминальные состояния
> (`COMPLETED`/`SUCCESS`/…) приходят реальными count из `nodes`, а на баг и его регресс-тест
> влияют только нулевые *активные* состояния — так что достаточно и точнее засеивать именно их.
> Тупли совпадают с продуктовыми `GH_ACTIVE_CHECK_STATES` / `GH_ACTIVE_STATUS_STATES`, поэтому
> фикстура и фикс связаны, а не совпадают случайно.

`_gh_page` (отдельный билдер для теста пагинации в `test_flow_wait_ci.py`) не трогаем — он
про другой сценарий, его `check_counts` заданы явно и не содержат активных состояний.

**Побочный эффект (желателен):** после смены фикстуры существующие зелёные терминальные
тесты (`test_github_terminal_emits_check_lines` и др.) начинают гонять реальную форму
ответа и становятся неявными регресс-тестами.

### 3. Тесты (`plugins/flow/bin/tests/test_flow_wait_ci.py`)

- **Новый** `test_github_terminal_ignores_zero_active_states`: зелёный терминальный роллап,
  где `checkRunCountsByState` содержит нулевые `QUEUED`/`IN_PROGRESS`/`PENDING`/`WAITING` →
  **exit 0**. Явный, документирующий намерение тест (RED против текущего кода, GREEN после
  фикса).
- Сценарий «непустой count в активном состоянии → продолжает ждать» уже покрыт
  `test_github_timeout_exits_2` (`IN_PROGRESS` count 1 → exit 2). Усилить комментарий,
  отдельный тест не заводить.

### 4. Мелочь для DX

Снизить дефолт `WAIT_TIMEOUT` в `fake_gh.env()` (`conftest.py`) с `30` до `5`. При повторном
заносе такого бага тесты падают за ~5с, а не висят 30с. Безопасно: все converging-тесты
сходятся за ≤4 мгновенных полла (`WAIT_INTERVAL=0`).

## Затрагиваемые файлы

- `plugins/flow/bin/flow-wait-ci` — правка выражения `active`.
- `plugins/flow/bin/tests/conftest.py` — полный енум в `gh_response`, константы, `WAIT_TIMEOUT` → 5.
- `plugins/flow/bin/tests/test_flow_wait_ci.py` — новый регресс-тест + комментарий.

## Порядок работ (TDD)

1. Правка фикстуры + новый регресс-тест → прогон, убедиться в **RED**.
2. Правка `flow-wait-ci` (выражение `active`) → прогон, **GREEN**.
3. `ruff format` + `ruff check --fix` + `ty check` (pathless, whole-project).
4. Ручная проверка на живом GitHub-PR: `flow-wait-ci <pr> <sha> --platform github` →
   `0` за ~2 интервала (acceptance).

## Acceptance

- Тест: терминальный зелёный GitHub-роллап с нулевыми записями
  `QUEUED`/`IN_PROGRESS`/`PENDING`/`WAITING` → exit 0 (сейчас падал бы в timeout).
- Тест: непустой count в активном состоянии → продолжает ждать.
- Ручная проверка на живом PR: `flow-wait-ci <pr> <sha> --platform github` возвращает 0 за ~2 интервала.
- `ruff` + `ty check` зелёные.
