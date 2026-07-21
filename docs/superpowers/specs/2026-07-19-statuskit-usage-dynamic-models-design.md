# StatusKit usage_limits: динамический список моделей

**Дата:** 2026-07-19
**Задача:** claude-tools-6fy
**Модуль:** `packages/statuskit/src/statuskit/modules/usage_limits.py`

## Проблема

Anthropic отдаёт per-model недельные лимиты (Sonnet, недавно — Fable), и список моделей
будет расти. Текущий модуль `usage_limits` жёстко зашивает каждый такой лимит отдельным полем
`UsageData.sonnet`, отдельной веткой в парсинге, сериализации кэша и в display-параметрах
(`show_sonnet`, `sonnet_time_format`). Каждая новая модель от Anthropic требует правок в 4-5
местах. Нужно, чтобы новые per-model лимиты подхватывались без доработки кода.

## Ключевая находка: формат API изменился

Живой ответ `GET https://api.anthropic.com/api/oauth/usage` показывает, что per-model лимиты
**больше не приходят** через top-level ключи вида `seven_day_<model>` (они `null`), а живут в
новом самоописывающемся массиве `limits`:

```json
"limits": [
  { "kind": "session",       "group": "session", "percent": 11, "resets_at": "…",  "scope": null,
    "severity": "normal", "is_active": true },
  { "kind": "weekly_all",    "group": "weekly",  "percent": 2,  "resets_at": "…",  "scope": null,
    "severity": "normal", "is_active": false },
  { "kind": "weekly_scoped", "group": "weekly",  "percent": 0,  "resets_at": null,
    "scope": { "model": { "id": null, "display_name": "Fable" }, "surface": null },
    "severity": "normal", "is_active": false }
]
```

Каждый элемент несёт всё нужное: `group` (session/weekly → окно и группировка), `percent`,
`resets_at`, `scope.model.display_name` (готовый ярлык модели). Новая модель просто появляется
новым элементом `weekly_scoped` — код менять не нужно.

Наивный «парсить любой `seven_day_*`» подход отпадает: в top-level сейчас лежат мусорные
кодовые имена (`seven_day_cowork`, `seven_day_omelette`, `tangelo`, `iguana_necktie`, …), все
`null`, и они не модели.

## Решение: перейти на массив `limits`, легаси — как fallback

### Источник данных

1. Если в ответе есть непустой `limits` → парсим его.
2. Если `limits` отсутствует/пустой (старый API) → fallback на легаси top-level ключи
   (`five_hour` → Session, `seven_day` → Weekly, `seven_day_sonnet` → scoped-модель "Sonnet").
   Мусорные кодовые ключи игнорируем.

Оба пути наполняют одну и ту же внутреннюю модель.

### Внутренняя модель — группировка по `group`

Поле `group` из API — естественный группировочный ключ. scoped-модели семантически являются
подлимитами недельного окна (`group: weekly`), поэтому моделируем это иерархически:

```python
@dataclass
class UsageLimit:
    label: str                  # "Session" / "Weekly" / "Fable" / "Fable·cli"
    utilization: float          # из percent (int) или legacy utilization (float)
    resets_at: datetime | None
    model: str | None = None    # scope.model.display_name
    surface: str | None = None  # scope.surface

@dataclass
class UsageGroup:
    key: str                    # "session" | "weekly"
    window_hours: float         # 5.0 или 168.0 — выводится из group
    overall: UsageLimit | None  # scope == null: kind session / weekly_all
    models: list[UsageLimit]    # scope.model: weekly_scoped, label = display_name

@dataclass
class UsageData:
    groups: list[UsageGroup]    # заменяет session/weekly/sonnet
    fetched_at: datetime
    last_attempt_at: datetime | None = None
```

**Парсинг массива `limits`:**

- Раскладываем элементы по `group`. Порядок групп: `session`, затем `weekly`.
- `scope == null` → `overall` группы. Ярлык: `session` → `"Session"`, `weekly_all` → `"Weekly"`.
- `scope` — объект → строка идентифицируется **парой `(model, surface)`**, а не одной моделью:
  API умеет сузить лимит по модели, по поверхности или по обеим сразу, и две строки,
  различающиеся только `surface`, — разные квоты, которые нельзя схлопывать. Ярлык собирается
  из пары: `"Fable"` / `"cli"` / `"Fable·cli"`. Если ни `model`, ни `surface` не дают непустой
  строки — элемент пропускаем. Повтор той же пары в ответе — аномалия API, берём первую строку.
  `surface` показывается **как есть**, без интерпретации: поле не задокументировано и в живых
  ответах всегда `null`, так что любое наше сопоставление было бы гаданием. Смысл — не дать
  узкой квоте выдать себя за общемодельную.
- `percent` → `utilization`; `resets_at` парсим как раньше (ISO, при ошибке → `None`).
- Окно: `session` → `FIVE_HOUR_WINDOW` (5.0), `weekly` → `SEVEN_DAY_WINDOW` (168.0).
- Неизвестные значения `group` (гипотетические новые окна) игнорируем — окно для них
  неизвестно, поэтому цветовую эвристику посчитать нельзя. Отмечено как возможное будущее
  расширение.

**Цвет:** оставляем текущую эвристику «utilization vs elapsed time» (burn-rate), окно берём из
`group.window_hours`. Поле `severity` из API пока игнорируем — эвристика информативнее и уже
проверена; переход на `severity` — возможное будущее улучшение.

## Настройки

Схема-система statuskit (`core/schema.py`) поддерживает только примитивы и `list[X]`/`tuple[X]`
над примитивом — **dict не поддерживается**. Поэтому точечные переопределения делаем списками
имён, а не map.

```python
@schema
class UsageLimitsParams:
    show_session: bool = param(True, "Show 5-hour session limit")
    show_weekly: bool = param(True, "Show 7-day weekly limit")
    # Per-model (scoped) отображение
    models_always_show: list[str] = param([], "Model display names to always show, even at 0%")
    models_never_show: list[str] = param([], "Model display names to never show")
    model_time_format: str = param("reset_at", "Per-model time display", choices=_TIME_FORMAT_CHOICES)
    # Без изменений
    show_reset_time: bool = param(True, "Show time until / when reset occurs")
    multiline: bool = param(True, "Multi-line output (one limit per line)")
    show_progress_bar: bool = param(False, "Show ASCII progress bar")
    bar_width: int = param(10, "Progress bar character width")
    session_time_format: str = param("remaining", "Session time display", choices=_TIME_FORMAT_CHOICES)
    weekly_time_format: str = param("reset_at", "Weekly time display", choices=_TIME_FORMAT_CHOICES)
    cache_ttl: int = param(60, "Minimum seconds between usage-API refetches")
```

Удаляются: `show_sonnet`, `sonnet_time_format`.

### Логика показа

- **Session overall** — показывается, если `show_session` и `overall` присутствует.
- **Weekly overall** — показывается, если `show_weekly` и `overall` присутствует.
- **Модель (scoped)** — по умолчанию показывается, если `utilization > 0` **или** задан
  `resets_at` («живой» лимит). Переопределения (сопоставление `display_name`
  регистронезависимо):
  - имя в `models_never_show` → не показывать никогда;
  - имя в `models_always_show` → показывать всегда, даже при 0%;
  - приоритет: `never_show` > `always_show` > дефолт (`utilization > 0 or resets_at`).

Пример конфига:

```toml
[usage_limits]
show_session = true
show_weekly = true
models_always_show = ["Fable"]
models_never_show  = ["Opus"]
model_time_format  = "reset_at"
```

### Обратная совместимость конфига

Старые ключи `show_sonnet` / `sonnet_time_format` удаляются. Существующие
`statuskit.toml` с ними не ломаются: `parse_params` пометит их как `unknown key` (warning),
дефолты применятся. Миграции нет — Sonnet сейчас и так `null`; когда/если появится в `limits`,
подхватится дефолтной логикой или через `models_always_show = ["Sonnet"]`.

## Отображение

### Multiline — вложенный вид

Модели рендерятся с отступом под `overall` своей группы, отражая семантику «модель = срез
недельного окна»:

```
Usage:
├ Session: 11% (2h 30m)
└ Weekly:  2% (Thu 17:00)
  ├ Fable:  34% (Fri 03:59)
  └ Opus:   88% (Fri 03:59)
```

Правила рендера:

- Верхний уровень — видимые группы (session, затем weekly). Коннекторы `├`/`└`, последняя
  группа — `└`.
- Если у группы виден `overall` — это строка-заголовок группы; видимые модели идут под ней с
  отступом (2 пробела) и собственными коннекторами `├`/`└`.
- Если `overall` группы не виден (`show_weekly=false` или `overall is None`), но модели есть —
  модели рендерятся на верхнем уровне этой группы (без строки-заголовка).
- Группа целиком опускается, если у неё нет ни видимого `overall`, ни видимых моделей.
- Ярлык scoped-модели = `display_name` как есть; ширина колонки лейблов считается динамически
  по самому длинному видимому ярлыку (чтобы длинные имена не ломали выравнивание).

### Single-line — плоский вид

Иерархия схлопывается в плоскую последовательность сегментов через ` | `:

```
Usage: 5h 11% (2h 30m) | 7d 2% (Thu 17:00) | Fable 34% (Fri 03:59) | Opus 88% (Fri 03:59)
```

Короткие ярлыки: session overall → `5h`, weekly overall → `7d`, модель → `display_name`.

### Форматы времени

- `session_time_format` → session overall
- `weekly_time_format` → weekly overall
- `model_time_format` → все scoped-модели

## Кэш

Формат кэша меняется на группированный (сериализуем `groups`). Старые кэш-файлы формата
`{"data": {"session": …, "weekly": …, "sonnet": …}}` читаются толерантно, без миграции:
`load()` пытается прочитать новый формат; если структуры `groups` нет — возвращает `None`
(кэш-промах → рефетч). Требование «старые кэш-файлы читаются без падения» соблюдено; кэш
одноразовый.

## Тесты (`packages/statuskit/tests/test_usage_limits.py`)

- **Парсинг `limits`:** session + weekly_all + один/несколько weekly_scoped; корректные
  ярлыки, окна, utilization/resets_at; пропуск scoped без `display_name`.
- **Fallback на легаси:** ответ без `limits` → session/weekly/Sonnet из top-level; мусорные
  кодовые ключи игнорируются.
- **Логика показа:** модель при 0% скрыта; при `utilization>0` показана; `models_always_show`
  форсит показ при 0%; `models_never_show` прячет; приоритет never > always;
  регистронезависимое сопоставление.
- **Рендер multiline (вложенный):** отступы и коннекторы для session+weekly+модели; случай
  скрытого weekly overall с видимыми моделями; динамическая ширина лейблов.
- **Рендер single-line (плоский):** короткие ярлыки, порядок сегментов.
- **Кэш:** roundtrip нового формата (save → load); старый формат `{session,weekly,sonnet}` →
  пустой `groups` без исключения, но с сохранёнными `fetched_at`/`last_attempt_at` — метки
  времени единственное, что троттлит API, и их потеря заставляла падающий API дёргаться на
  каждом рендере. `None` только когда не распарсилась ни одна из двух меток.
- **Back-compat конфига:** `statuskit.toml` с `show_sonnet`/`sonnet_time_format` не падает
  (unknown-key warning), дефолты применяются.

## Acceptance

- Новый per-model лимит от API (напр. Fable, а в будущем — любой другой) отображается без
  изменений кода.
- `models_always_show` / `models_never_show` управляют показом моделей.
- Вложенный multiline и плоский single-line соответствуют мокапам выше.
- Старые кэш-файлы и старые конфиги не вызывают падений.
- `uv run ruff check` и `uv run ty check` — зелёные.

## Вне scope

- Переход цветовой индикации на API-поле `severity`.
- Поддержка гипотетических новых значений `group` (кроме session/weekly).
- Отображение `is_active`, денежных полей (`*_dollars`, `spend`, `extra_usage`).
- **Интерпретация** `surface` (сопоставление значений с человекочитаемыми названиями поверхностей,
  отдельная ось группировки, своя конфигурация показа). Само поле теперь входит в ключ строки и
  попадает в ярлык сырым — см. «Парсинг массива `limits`».
