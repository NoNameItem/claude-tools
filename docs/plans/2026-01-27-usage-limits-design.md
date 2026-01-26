# Usage Limits Module Design

## Overview

Модуль отображения лимитов использования API для statuskit. Показывает текущее потребление квоты (5-hour session, 7-day weekly, Sonnet-only) с умной раскраской на основе времени до сброса.

## Источник данных

### API Endpoint

```
GET https://api.anthropic.com/api/oauth/usage
Headers:
  Authorization: Bearer {token}
  anthropic-beta: oauth-2025-04-20
Timeout: 3 sec
```

### Ответ API

```json
{
  "five_hour": {"utilization": 45.0, "resets_at": "2026-01-27T18:00:00+00:00"},
  "seven_day": {"utilization": 32.0, "resets_at": "2026-01-30T17:00:00+00:00"},
  "seven_day_sonnet": {"utilization": 15.0, "resets_at": "2026-01-30T17:00:00+00:00"}
}
```

### Получение токена (приоритет)

1. macOS Keychain: `security find-generic-password -s "Claude Code-credentials" -w`
2. Fallback: `~/.claude/.credentials.json` → `claudeAiOauth.accessToken`

## Конфигурация

```toml
[usage_limits]
# Что показывать
show_session = true
show_weekly = true
show_sonnet = false
show_reset_time = true

# Формат вывода
multiline = true
show_progress_bar = false
bar_width = 10

# Формат времени
session_time_format = "remaining"   # "remaining" | "reset_at"
weekly_time_format = "reset_at"     # "remaining" | "reset_at"
sonnet_time_format = "reset_at"     # "remaining" | "reset_at"

# Кэширование
cache_ttl = 60
cache_dir = "~/.cache/statuskit"
```

## Логика раскрашивания

Цвет определяется соотношением потребления к прошедшему времени:

```python
time_percent = (1 - remaining_hours / window_hours) * 100
margin = 10  # фиксированный коридор

if utilization > time_percent:
    color = "red"      # перерасход
elif utilization > time_percent - margin:
    color = "yellow"   # близко к лимиту
else:
    color = "green"    # всё ок
```

### Примеры (5h окно)

| Прошло | time% | usage | Цвет |
|--------|-------|-------|------|
| 2.5h | 50% | 60% | красный |
| 2.5h | 50% | 45% | жёлтый |
| 2.5h | 50% | 35% | зелёный |
| 4h | 80% | 75% | жёлтый |
| 4h | 80% | 65% | зелёный |

## Форматы вывода

### Multiline без баров (default)

```
Usage:
├ Session: 45% (2h 30m)
├ Weekly:  32% (Thu 17:00)
└ Sonnet:  15% (Thu 17:00)
```

### Multiline с барами

```
Usage:
├ Session: [████░░░░░░] 45% (2h 30m)
├ Weekly:  [███░░░░░░░] 32% (Thu 17:00)
└ Sonnet:  [█░░░░░░░░░] 15% (Thu 17:00)
```

### Однострочный без баров

```
Usage: 5h 45% (2h 30m) | 7d 32% (Thu 17:00) | Sonnet 15%
```

### Однострочный с барами

```
Usage: 5h [████░░] 45% | 7d [███░░░] 32% | Sonnet [█░░░░░] 15%
```

## Форматирование времени

### Формат "remaining"

- `< 1h`: `45m`
- `1-24h`: `2h 30m`
- `> 24h`: `5d 3h`

### Формат "reset_at"

- Локальное время: `Thu 17:00`

## Работа с таймзонами

- API возвращает UTC timestamps
- Все вычисления (раскрашивание) в UTC
- Отображение "reset_at" конвертируется в локальную таймзону

```python
reset_at_utc = datetime.fromisoformat(reset_time)
reset_at_local = reset_at_utc.astimezone()  # системная TZ
```

## Кэширование

- Файл: `{cache_dir}/usage_limits.json`
- TTL: `cache_ttl` секунд (default: 60)
- Rate limit: не чаще 1 запроса в 30 сек
- Lock file: `{cache_dir}/usage_limits.lock`

### Структура кэша

```json
{
  "data": {
    "five_hour": {"utilization": 45.0, "resets_at": "..."},
    "seven_day": {"utilization": 32.0, "resets_at": "..."},
    "seven_day_sonnet": {"utilization": 15.0, "resets_at": "..."}
  },
  "fetched_at": "2026-01-27T15:30:00+00:00"
}
```

## Обработка ошибок

| Ситуация | Обычный режим | Debug режим |
|----------|---------------|-------------|
| Нет токена | `None` (не отображается) | `Usage: [error: token not found]` |
| API timeout | Кэш или `None` | Кэш или `Usage: [error: API timeout]` |
| API ошибка | Кэш или `None` | Кэш или `Usage: [error: API {status_code}]` |
| Нет кэша и API недоступен | `None` | `Usage: [error: no data]` |
| `seven_day_sonnet` отсутствует | Не показываем Sonnet | Не показываем Sonnet |

## Архитектура

### Файлы

```
packages/statuskit/src/statuskit/modules/usage_limits.py  # Модуль
packages/statuskit/tests/test_usage_limits.py             # Тесты
packages/statuskit/src/statuskit/modules/__init__.py      # Регистрация
```

### Dataclasses

```python
@dataclass
class UsageLimit:
    utilization: float        # 0-100
    resets_at: datetime

@dataclass
class UsageData:
    session: UsageLimit | None     # five_hour
    weekly: UsageLimit | None      # seven_day
    sonnet: UsageLimit | None      # seven_day_sonnet
    fetched_at: datetime
```

### Класс модуля

```python
class UsageLimitsModule(BaseModule):
    name = "usage_limits"
    description = "API usage limits (5h session, 7d weekly, Sonnet-only)"

    def render(self) -> str | None
    def _get_usage_data(self) -> UsageData | None
    def _get_token(self) -> str | None
    def _fetch_api(self, token: str) -> dict | None
    def _load_cache(self) -> dict | None
    def _save_cache(self, data: dict) -> None
    def _calculate_color(self, utilization: float, reset_time: datetime, window_hours: float) -> str
    def _format_bar(self, utilization: float) -> str
    def _format_reset_time(self, reset_time: datetime, format: str) -> str
```

## Тесты

- Парсинг ответа API
- Логика раскрашивания (red/yellow/green) с разными комбинациями utilization/time
- Форматирование времени (remaining/reset_at)
- Форматирование прогресс-бара
- Кэширование (TTL, rate limit)
- Обработка ошибок (нет токена, API недоступен)
- Таймзоны (UTC → local)
