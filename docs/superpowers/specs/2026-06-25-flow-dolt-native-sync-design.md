# Design: редизайн синхронизации flow под Dolt-native bd 1.0.x

- **Задача:** claude-tools-akt
- **Дата:** 2026-06-25
- **Зависит от:** claude-tools-elf.20 (задел: `flow-require-bd`, фикстуры 1.0.5, тесты схемы, тип `decision`) — лежит на неслитой ветке `origin/feature/claude-tools-elf.20-bd-1-0-0-1`
- **Связанный инцидент:** claude-tools-elf.19 (PATH-shadowing старым bd)
- **Предыдущий дизайн:** `docs/superpowers/specs/2026-06-24-flow-bd-1-0-migration-design.md` (на ветке elf.20; этот документ его продолжает и закрывает отложенный раздел про sync)

## Контекст и проблема

flow обращается к beads (`bd`) только через CLI и парсит `--json`. Текущая модель персистентности:

- скиллы вызывают `bd sync`, который экспортирует `.beads/issues.jsonl`, коммитит и пушит его через выделенную ветку `beads-sync`;
- демон bd авто-синкает в фоне;
- `.beads/issues.jsonl` трекается в git и считается каноном.

**В bd 1.0.x этой модели не существует.** Команда `bd sync` и подкоманда `bd daemon` удалены. Синхронизация стала Dolt-native:

- источник истины — встроенная (embedded) БД Dolt в `.beads/embeddeddolt/`;
- `.beads/issues.jsonl` — теперь **пассивный экспорт** (для ревью/интеропа/миграции), не транспорт и не бэкап;
- удалённая синхронизация — через `bd dolt push` / `bd dolt pull` в git-ref `refs/dolt/data` на том же git-remote;
- **авто-pull отсутствует**: чужие изменения подтягиваются только вручную (`bd dolt pull`) либо через `post-merge` git-хук на `git pull`;
- демона нет — embedded-движок работает в самом процессе `bd`, координация через файловый лок.

Запуск flow на 1.0.x в текущем виде ломается: `bd sync` не существует. Нужно переопределить, как flow персистит и подтягивает состояние задач.

## Модель синхронизации bd 1.0.x (опорные факты)

Источник: официальные доки bd (DOLT.md, SYNC_SETUP.md, CONFIG.md, cli-reference) на 2026-06-25.

**Dolt** — «Git для данных»: SQL-БД с версионированием (commits, branches, cell-level diff/merge, push/pull к remote). Cell-level merge: правки в разные ячейки одной строки сливаются автоматически; конфликт только при правке одной и той же ячейки.

**Конфиг-ключи (значения/дефолты выверить на живом 1.0.5 — дефолты плавают между под-версиями):**

| Ключ | Значения | Дефолт | Роль |
|------|----------|--------|------|
| `dolt.auto-commit` | on/off | on (по CONFIG.md) | каждая запись → коммит в Dolt |
| `dolt.auto-push` | true/false | false | фоновый push в `refs/dolt/data` (интервал 5m) |
| `export.auto` | true/false | false | переэкспорт JSONL после записи |
| `sync.remote` | URL | — | адрес dolt-remote (пишется `bd dolt remote add`) |

- Запрос конфига: `bd config get <key>` / `bd config list --json`.
- `bd dolt push` / `bd dolt pull` **требуют настроенного remote** — без него падают с ошибкой.
- Детект remote: `bd dolt remote list` (непустой вывод) либо ключ `sync.remote` в `.beads/config.yaml`.
- «bd без синхронизации» = **отсутствие remote** (отдельного no-sync режима/флага в актуальных доках нет; `--sandbox` из карточки akt подтвердить не удалось — на него не закладываемся).
- Хуки ставит `bd hooks install` (`post-merge` → pull на `git pull`, `pre-push` → push на `git push`). **flow их не ставит и не проверяет** — это забота разработчика при настройке bd.

## Ключевые решения

| # | Решение | Обоснование |
|---|---------|-------------|
| 1 | **Dolt-native модель.** Источник истины — embedded Dolt; транспорт — `refs/dolt/data` на git origin. | Это и есть нативная модель bd 1.0.x; даёт настоящий cell-level merge для команд. |
| 2 | **`.beads/issues.jsonl` уходит из git** (gitignore + `git rm`). | В 1.0.x JSONL — пассивный экспорт, не транспорт. Убирает трение демон↔git и ветку `beads-sync`. |
| 3 | **Ревьюабельность JSONL в git не нужна.** | Явный выбор пользователя — доверяем мерджу bd, а не текстовому diff. |
| 4 | **flow ставит страховочные `bd dolt pull`/`push`** на место `bd sync` (pull на входе, push после изменений). | Авторы bd сами рекомендуют «push before leaving, pull before starting» на multi-machine; не полагаемся на throttled auto-push. |
| 5 | **Хуки — не забота flow.** | Разделение ответственности: окружение настраивает разработчик. |
| 6 | **Graceful degradation по конфигу.** Нет remote / sync не настроен → flow не запускает pull/push, печатает заметку, продолжает (non-blocking). | flow не должен падать или блокировать работу из-за конфигурации синхры. |
| 7 | **Version-guard `bd >= 1.0.0`** первой командой во всех bd-скиллах. | Парсеры ориентированы на схему 1.0.x; на старом bd flow падал непонятно (elf.19). |
| 8 | **Backward-compat с 0.47 не тащим.** | Двойная совместимость схем усложняет код; guard падает быстро до парсинга. |

## Компоненты

### 1. `bin/flow-sync` (новый хелпер)

Standalone Python-хелпер в стиле остальных `bin/`-скриптов (`#!/usr/bin/env python3`, `from __future__ import annotations`, `subprocess.run(..., check=False)`, `main() -> int`, override через `BD_BIN`).

**Интерфейс:** `flow-sync pull` и `flow-sync push`.

**Поведение:**
1. Резолвит бинарь bd через `BD_BIN` (дефолт `bd`) — как `flow-require-bd`/`flow-branch-for`.
2. Детектит наличие dolt-remote (`bd dolt remote list`; точную проверку выверить на 1.0.5).
3. **remote есть** → запускает `bd dolt pull` или `bd dolt push`:
   - успех → тихо, exit 0;
   - ошибка (offline/auth/прочее) → warning в stderr («синхра не удалась: <причина>; синхронизируйте вручную / см. README»), **exit 0** (non-blocking).
4. **remote нет** → короткая заметка в stderr («dolt-remote не настроен — синхронизация на вас; см. README#bd-requirements») + exit 0.
5. **flow-sync никогда не возвращает ненулевой код** — он информирует, но не блокирует скилл.

**Зачем хелпер, а не инлайн в SKILL.md:** централизует логику детекта/деградации в одном месте, тестируется юнит-тестами, держит SKILL.md чистыми (одна строка `flow-sync pull`).

**Предположения:** version-guard (`flow-require-bd`, Шаг 0) уже отработал — flow-sync не проверяет версию. `push` рассчитывает на `dolt.auto-commit=on` (часть ожидаемого конфига, выставляется при катовере); проверка auto-commit внутри flow-sync — возможное уточнение, но не в базовом scope.

### 2. Замена `bd sync` в скиллах

Правило: **sync-перед-чтением → `flow-sync pull`; sync-после-записи → `flow-sync push`.** Точки берём из текущей карты вызовов `bd sync`.

| Скилл | Текущий `bd sync` (шаг) | Станет |
|-------|--------------------------|--------|
| `start` | Step 0 (вход, до показа дерева) | `flow-sync pull` |
| `start` | Step 7.1 (после `bd update --status`) | `flow-sync push` |
| `start` | Step 8.1 (после сохранения ветки) | `flow-sync push` (или объединить с 7.1 в один push в конце) |
| `continue` | Step 1 (вход) | `flow-sync pull` |
| `after-design` | Step 4 (после `flow-link-doc`) | `flow-sync push` |
| `after-plan` | Step 4 (после `flow-link-doc`) | `flow-sync push` |
| `decompose` | Step 8 (после `bd create` цикла) | `flow-sync push` |
| `done` | Step 7 (mandatory, конец) | `flow-sync push` |
| `sonar-sync` | (sync отсутствует) | без изменений по sync; добавить только guard (Шаг 0) |

**Важно:** правка касается **только команд**, не прозы/примеров. Предыдущая попытка blanket find-replace ломала текст и была откатана. Каждую правку делаем точечно: меняем конкретный bash-блок `bd sync`, проверяем, что окружающие пояснения остаются корректными (упоминания «daemon auto-syncs» убрать/переписать, т.к. демона нет).

### 3. Version-guard (`flow-require-bd`, Шаг 0)

Подбираем готовый `flow-require-bd` из elf.20 (guard `bd >= 1.0.0`, `BD_BIN`-override, exit 0/1/2/3, сообщения на stderr с резолвнутым путём — против PATH-shadowing). Добавляем «Шаг 0: require bd» первой командой во **все** bd-скиллы: `start`, `continue`, `decompose`, `done`, `after-design`, `after-plan`, `review-comments`, `sonar-sync`. При exit ≠ 0 скилл останавливается, ни одного вызова `bd` не делает.

### 4. Подбор задела elf.20 (cherry-pick)

Задел существует, но **только на `origin/feature/claude-tools-elf.20-bd-1-0-0-1`** (на master его нет). Cherry-pick'аем 4 коммита на ветку akt, чтобы не переписывать:

- `e1863c4` — `flow-require-bd` + тесты;
- `5ee585f` — фикстуры реального bd 1.0.5 + тесты совместимости схемы;
- `24395ae` — правки по ревью (anchor semver, тест карточки);
- тип `decision` в `flow-task-tree`/`flow-find-leaf`/`flow-task-card` (если не в перечисленных — взять соответствующий коммит).

Прошлый design-doc (`16e7dcf`) — справочный, не переносим как есть (этот документ его замещает по части sync). Конфликты при cherry-pick разрешаем вручную; после — прогон тестов.

### 5. `.beads/issues.jsonl` → gitignore + untrack

**Что уже игнорит bd:** `.beads/.gitignore` (его ведёт сам bd) уже игнорит `*.db*`, runtime демона (`bd.sock`, `*.log.gz`, `daemon.*`), `.local_version`, `redirect`, merge-артефакты, sync-state. JSONL (`issues.jsonl`, `interactions.jsonl`) и config (`config.yaml`, `metadata.json`) — **трекаются по умолчанию**; в файле явная заметка против negation-паттернов (fork-protection через `.git/info/exclude`).

**План:**
- **JSONL-игнор кладём в КОРНЕВОЙ `.gitignore`, не в `.beads/.gitignore`** — bd при init перезаписывает свой `.beads/.gitignore`, корневой он не трогает. Добавляем: `.beads/issues.jsonl`, `.beads/interactions.jsonl`.
- `.beads/embeddeddolt/` / `.beads/dolt/` (стор Dolt) — bd 1.0.5 добавит в свой `.gitignore` при init; продублировать в корневом для надёжности.
- `git rm --cached .beads/issues.jsonl .beads/interactions.jsonl` + коммит.
- **`config.yaml` оставляем трекаемым** (repo-level identity: prefix и т.п.); `metadata.json` — выверить на 1.0.5 (в миграции llms-full его `rm -f` как stale server-метаданные → вероятно runtime, кандидат на untrack).
- Снять трекинг ветки `beads-sync` как механизма синхры (оставить как историю или удалить — операционно).

### 6. Worktree-поддержка (Dolt-native)

**Хорошая новость: под Dolt-native worktree-история чище, чем в 0.47.** Подтверждено доками bd (GIT_INTEGRATION.md, worktree.md) и эмпирически (`bd where` из этого worktree → main `.beads`).

- **Все worktree'ы делят ОДИН embedded Dolt-стор** в main-репо (`.beads/embeddeddolt/`), резолвинг — автоматически через **git common directory** («no redirect file needed»). Из любого worktree `bd` работает с тем же стором и теми же 122 задачами.
- **Gitignore `embeddeddolt/` безопасен для worktree'ов**: свежий worktree без локального стора всё равно находит main через common dir. **Не нужен** ни per-worktree `bd init`, ни `bd bootstrap` (bootstrap — только для свежего clone на новой машине, где стора нет вообще).
- **Трение демон↔worktree из 0.47 исчезает by construction**: предупреждение «daemon may commit to wrong branch» — это про демона, а в 1.0.x демона нет. Снимается главная worktree-боль (см. reference_beads_daemon_git_friction).
- **`flow-sync push/pull` из любого worktree** работает с общим стором → один `refs/dolt/data` на origin. Консистентно независимо от git-ветки worktree.
- **Dolt-ветка не привязана к git-ветке** worktree: beads-задачи — глобальный граф проекта, видны из всех worktree'ов/веток (как и текущее `--all`-поведение flow).
- **Caveat — single-writer:** embedded Dolt одно-писательный (файловый лок). Две одновременные flow-сессии в разных worktree'ах, пишущие в один момент, сериализуются на локе (одна ждёт/получает ошибку). Для интерактивного flow (одна сессия за раз) — приемлемо; multi-writer = server mode, вне scope.
- **Диагностика:** `bd where` — авторитетная проверка «какой `.beads`/стор активен» (полезно в troubleshooting README и при отладке).

**Влияние на flow:** flow продолжает создавать worktree'ы своим механизмом (`git worktree add` через `flow-worktree-dir`); `bd worktree create` (который сам gitignore'ит путь и шарит БД) — не обязателен, шаринг и так автоматический. Убедиться, что каталог flow-worktree'ов (`.worktrees/`) в gitignore. `flow:init-worktree` для bd ничего доп. делать не должен — стор уже общий.

## Катовер окружения (двухфазный)

Необратимую часть выполняем **последней**, уже убедившись, что flow работает на 1.0.5.

**Инвентаризация (фактическая, 2026-06-25):**

| Путь | Версия | Что |
|------|--------|-----|
| `~/.local/bin/bd` | 0.47.1 | standalone-бинарь (не Homebrew), активный, 1-й в PATH — **якорь отката** |
| `/opt/homebrew/bin/bd` → `Cellar/bd/0.44.0` | 0.44.0 | формула `bd` тапа `gastownhall/beads` — источник тени elf.19 |
| `/opt/homebrew/Cellar/beads/1.0.5/bin/bd` | 1.0.5 | core-формула `beads`, установлена, не слинкована |

### Фаза 1 — изолированная проверка (обратимая)

Все `flow-*` хелперы уважают `BD_BIN`. Тестируем flow на 1.0.5, не трогая систему:

```bash
export BD_BIN=/opt/homebrew/Cellar/beads/1.0.5/bin/bd
# поднять временную тестовую БД (bd init во временном каталоге / из копии JSONL)
# прогнать скиллы flow + тесты на 1.0.5; живой 0.47-сетап и daemon не трогаем
```

Если что-то не так — сбрасываем `BD_BIN`, правим, повторяем.

### Фаза 2 — реальная миграция + relink (необратимое, только после зелёной Фазы 1)

```bash
# 1. Свежий экспорт старым 0.47 + бэкап
bd list --json -n 0 --all > .beads/issues.jsonl
cp -a .beads .beads.backup-0.47

# 2. Убрать тень 0.47.1, сохранив бинарь для отката
mv ~/.local/bin/bd ~/.local/bin/bd-0.47.1

# 3. Слинковать 1.0.5 как системный bd; опц. убить источник тени elf.19
brew unlink bd && brew link beads
brew uninstall bd && brew untap gastownhall/beads   # опционально
bd version   # должно быть 1.0.5

# 4. Снести старое хранилище/метаданные и инициализировать embedded Dolt из JSONL
rm -f .beads/metadata.json .beads/config.json
rm -rf .beads/dolt .beads/embeddeddolt
bd init claude-tools --from-jsonl .beads/issues.jsonl --quiet   # точный синтаксис выверить по `bd init --help`

# 5. Dolt-native конфиг + remote + хуки (хуки — разово, рукам разработчика)
bd config set dolt.auto-commit on
bd dolt remote add origin git+ssh://git@github.com/NoNameItem/claude-tools.git   # или авто-детект origin при bd init
bd hooks install

# 6. Верификация
bd stats                      # ожидаем 122 задачи
bd show claude-tools-akt
bd migrate                    # проверка версии схемы
```

**Откат:** `mv ~/.local/bin/bd-0.47.1 ~/.local/bin/bd` (вернуть в начало PATH) + восстановить `.beads.backup-0.47`. Три независимых пути отката: standalone-бинарь 0.47.1, бэкап `.beads`, git-история JSONL.

## Миграция данных (для пользователя плагина)

Канонический путь bd 1.0.x — **JSONL-bridge** (Path A), документируется в README для любого, кто обновляется 0.47→1.0.x:

- **Авто-миграции нет**; bd 1.0.5 не читает старый layout.
- Мост — `.beads/issues.jsonl`; импорт через **`bd init <prefix> --from-jsonl <file>`** (команда `bd import` **удалена** — не использовать).
- `--from-jsonl` сохраняет ID, префикс, зависимости, статусы, лейблы, комментарии.
- Fallback Path B (сырой `dolt dump` + ремонт схемы) — для очень старых SQLite-источников; нам не нужен.

flow в `.beads/*` не лезет — миграцию исполняет bd; flow только **документирует** путь и **разово** исполняет его на машине (Фаза 2 выше).

## README

`plugins/flow/README.md`:
- Переписать раздел **«How Flow Stores State»** под Dolt-native: источник истины — embedded Dolt; синхра — `bd dolt push/pull` через `refs/dolt/data`; роль `flow-sync`; что хуки/remote настраивает пользователь; `Git:`/`Design:`/`Plan:`-линии в описании задачи остаются (они независимы от транспорта).
- Новый раздел **«Требования к bd и миграция»**: минимально `bd >= 1.0.0` (реком. 1.0.5); путь 0.47→1.0.5 через `bd init --from-jsonl`; настройка remote + `bd hooks install` + `dolt.auto-commit on`; caveat про PATH-shadowing (elf.19) и `BD_BIN`/`which -a bd`. На этот раздел ссылается сообщение version-guard.

## Тестирование

- `tests/test_flow_sync.py`: фейковый `bd` (через `BD_BIN`) — кейсы: remote есть + успех; remote есть + ошибка push/pull; remote нет; bd недоступен. Проверяем: всегда exit 0, корректные сообщения на stderr, правильная вызванная подкоманда (`dolt pull`/`dolt push`).
- Тесты из elf.20 (`test_flow_require_bd.py`, тесты схемы на фикстурах 1.0.5, рендер `decision`) — приходят с cherry-pick, прогнать.
- Ручной прогон скиллов на живом 1.0.5 (Фаза 1) — `start`/`continue`/`after-*`/`decompose`/`done`.

## Definition of Done

- flow проверен и работает на bd 1.0.5 (Фаза 1 зелёная).
- `bd sync` нигде не вызывается; вместо него `flow-sync pull`/`push` в нужных точках.
- `flow-sync` корректно деградирует при отсутствии remote / ошибке (non-blocking, exit 0).
- Version-guard (`flow-require-bd`) — Шаг 0 во всех bd-скиллах.
- `.beads/issues.jsonl` (и производные) убраны из git и в `.gitignore`.
- Задел elf.20 (guard, фикстуры, тесты схемы, тип `decision`) интегрирован.
- Окружение мигрировано на 1.0.5 (122 задачи на месте, `bd stats` сходится), 0.47.1 сохранён для отката.
- README: «How Flow Stores State» переписан + добавлен раздел требований/миграции.
- Все тесты зелёные; ruff/ty чисто.

## Вне scope

- Использование новых возможностей bd 1.0 (`bd batch`, `bd ready --json`, `bd close --claim-next` и т.п.) — отдельная задача (ранее намечалась как elf.21).
- Server-mode Dolt (`bd init --server`) — не используем, embedded по умолчанию.
- Проверка/выставление хуков из flow — сознательно на пользователе.

## Открытые вопросы / риски

- **Точные дефолты конфига 1.0.5** (`dolt.auto-commit`, `export.auto`) и **синтаксис `bd init --from-jsonl`** (позиционный префикс vs `--prefix=`, нужен ли `--role`) — выверить против живого `bd ... --help` на Фазе 1.
- **Способ детекта remote** в `flow-sync` (`bd dolt remote list` парсинг vs `bd config get sync.remote`) — выбрать по реальному выводу 1.0.5.
- **Поведение `bd dolt push` при `auto-commit=off`** (есть ли что пушить) — решить, нужен ли `bd dolt commit` перед push внутри `flow-sync push`.
- **Судьба `.beads/metadata.json`** при untrack — выверить на 1.0.5 (вероятно runtime → untrack; `config.yaml` оставляем). `interactions.jsonl` — в untrack по умолчанию.
- **Worktree-резолвинг БД — РЕШЕНО:** все worktree'ы делят main-стор через git common dir; gitignore стора безопасен; per-worktree init/bootstrap не нужен; демон-трение исчезает (демона нет). Остаётся проверить на 1.0.5 точное имя каталога стора (`embeddeddolt/` vs `dolt/`).
- Миграция данных на машине необратима в части relink — снимается двухфазностью и тройным откатом.
