# Telegram Notifications for CI/CD

## Overview

Отправка уведомлений в Telegram о статусе CI/CD workflows. Три workflow получают уведомления:
- **PR** — при открытии/обновлении pull request
- **Push** — при merge в master
- **Publish** — при публикации релиза

Каждый workflow отправляет два сообщения: started и finished со статусом.

## Требования

### Формат сообщений

Сообщение состоит из четырёх частей:
1. **Заголовок** — формируется автоматически: `{icon} {repo} | {title}`
2. **Сообщение** — опционально, выводится as-is
3. **Сводка по упавшим jobs** — опционально, формируется через GitHub API
4. **Ссылки** — формируются автоматически: `[View PR](url) | [View run](url)`

### Примеры сообщений

**PR Started:**
```
🚀 claude-tools | PR #42: Add quota module
Started
View PR | View run
```

**PR Success:**
```
✅ claude-tools | PR #42: Add quota module
Finished: All checks passed
View PR | View run
```

**PR Failure:**
```
❌ claude-tools | PR #42: Add quota module
Finished with errors:
  • Lint (statuskit)
  • Test (statuskit, py3.11)
  • Test (statuskit, py3.12)
View PR | View run
```

**Push Started:**
```
🚀 claude-tools | Push abc1234: feat: add feature
Started
View commit | View run
```

**Push Success:**
```
✅ claude-tools | Push abc1234: feat: add feature
Finished: All checks passed
View commit | View run
```

**Push Failure:**
```
❌ claude-tools | Push abc1234: feat: add feature
Finished with errors:
  • Lint (statuskit)
View commit | View run
```

**Publish Started:**
```
🚀 claude-tools | statuskit-v0.3.1
Publishing...
View release | View run
```

**Publish Success:**
```
✅ claude-tools | statuskit 0.3.1
Published to PyPI
pip install claude-statuskit==0.3.1
View release | View run
```

**Publish Failure:**
```
❌ claude-tools | statuskit 0.3.1
Publish failed
View release | View run
```

## Архитектура

### Composite Action

Один composite action в `claude-tools`, переиспользуется из других репо:

```
.github/
└── actions/
    └── telegram-notify/
        └── action.yml
```

Использование из другого репо:
```yaml
- uses: NoNameItem/claude-tools/.github/actions/telegram-notify@master
```

### Inputs

```yaml
inputs:
  status:
    description: 'started | success | failure | cancelled'
    required: true
  event-type:
    description: 'pr | push | release'
    required: true
  title:
    description: 'PR #42: Add quota module / Push abc1234: feat / statuskit 0.3.1'
    required: true
  event-url:
    description: 'URL на PR / commit / release'
    required: true
  message:
    description: 'Дополнительный текст, выводится as-is'
    required: false
    default: ''
  collect-failed-jobs:
    description: 'Получить список упавших jobs через GitHub API'
    required: false
    default: 'false'
  token:
    description: 'Telegram bot token'
    required: true
  chat-id:
    description: 'Telegram chat ID'
    required: true
```

### Логика action

```bash
#!/bin/bash

# 1. Иконка по статусу
case "$STATUS" in
  started)   ICON="🚀" ;;
  success)   ICON="✅" ;;
  failure)   ICON="❌" ;;
  cancelled) ICON="⛔" ;;
esac

# 2. Заголовок
HEADER="${ICON} ${GITHUB_REPOSITORY} | ${TITLE}"

# 3. Ссылки
RUN_URL="https://github.com/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
case "$EVENT_TYPE" in
  pr)      LINK_TEXT="View PR" ;;
  push)    LINK_TEXT="View commit" ;;
  release) LINK_TEXT="View release" ;;
esac
LINKS="[${LINK_TEXT}](${EVENT_URL}) | [View run](${RUN_URL})"

# 4. Сводка по упавшим jobs (если флаг включён)
FAILED_SUMMARY=""
if [ "$COLLECT_FAILED_JOBS" = "true" ]; then
  FAILED_SUMMARY=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
    "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}/jobs" \
    | jq -r '.jobs[] | select(.conclusion == "failure") | "  • [\(.name)](\(.html_url))"' \
    | head -20)
fi

# 5. Собрать сообщение
TEXT="${HEADER}"
[ -n "$MESSAGE" ] && TEXT="${TEXT}\n${MESSAGE}"
[ -n "$FAILED_SUMMARY" ] && TEXT="${TEXT}\n${FAILED_SUMMARY}"
TEXT="${TEXT}\n${LINKS}"

# 6. Отправить в Telegram
curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d chat_id="$CHAT_ID" \
  -d text="$TEXT" \
  -d parse_mode="Markdown" \
  -d disable_web_page_preview="true"
```

## Изменения в workflows

### PR workflow (pr.yml)

```yaml
jobs:
  notify-start:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/telegram-notify
        with:
          status: started
          event-type: pr
          title: "PR #${{ github.event.pull_request.number }}: ${{ github.event.pull_request.title }}"
          event-url: ${{ github.event.pull_request.html_url }}
          message: "Started"
          collect-failed-jobs: false
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}

  # ... existing jobs ...

  notify-finish:
    needs: [validate-pr, python-ci-result, claude-code-plugin-ci-result]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/telegram-notify
        with:
          status: ${{ (contains(needs.*.result, 'failure') && 'failure') || (contains(needs.*.result, 'cancelled') && 'cancelled') || 'success' }}
          event-type: pr
          title: "PR #${{ github.event.pull_request.number }}: ${{ github.event.pull_request.title }}"
          event-url: ${{ github.event.pull_request.html_url }}
          message: ${{ contains(needs.*.result, 'failure') && 'Finished with errors:' || 'Finished: All checks passed' }}
          collect-failed-jobs: ${{ contains(needs.*.result, 'failure') }}
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}
```

### Push workflow (push.yml)

```yaml
jobs:
  notify-start:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - id: commit
        run: |
          MSG=$(git log -1 --pretty=%s)
          echo "message=${MSG:0:50}" >> "$GITHUB_OUTPUT"
      - uses: ./.github/actions/telegram-notify
        with:
          status: started
          event-type: push
          title: "Push ${{ github.sha }}: ${{ steps.commit.outputs.message }}"
          event-url: ${{ github.event.head_commit.url }}
          message: "Started"
          collect-failed-jobs: false
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}

  # ... existing jobs ...

  notify-finish:
    needs: [validate-commits, python-ci, claude-code-plugin-ci]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - id: commit
        run: |
          MSG=$(git log -1 --pretty=%s)
          echo "message=${MSG:0:50}" >> "$GITHUB_OUTPUT"
      - uses: ./.github/actions/telegram-notify
        with:
          status: ${{ (contains(needs.*.result, 'failure') && 'failure') || 'success' }}
          event-type: push
          title: "Push ${{ github.sha }}: ${{ steps.commit.outputs.message }}"
          event-url: ${{ github.event.head_commit.url }}
          message: ${{ contains(needs.*.result, 'failure') && 'Finished with errors:' || 'Finished: All checks passed' }}
          collect-failed-jobs: ${{ contains(needs.*.result, 'failure') }}
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}
```

### Publish workflow (publish.yml)

```yaml
jobs:
  notify-start:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/telegram-notify
        with:
          status: started
          event-type: release
          title: ${{ github.event.release.tag_name }}
          event-url: ${{ github.event.release.html_url }}
          message: "Publishing..."
          collect-failed-jobs: false
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}

  # ... existing jobs ...

  notify-finish:
    needs: [resolve, publish-pypi]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/telegram-notify
        with:
          status: ${{ needs.publish-pypi.result == 'success' && 'success' || 'failure' }}
          event-type: release
          title: "${{ needs.resolve.outputs.project-name }} ${{ needs.resolve.outputs.version }}"
          event-url: ${{ github.event.release.html_url }}
          message: ${{ needs.publish-pypi.outputs.summary-message }}
          collect-failed-jobs: false
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}
```

## Секреты

В каждом репозитории нужны два секрета:

| Секрет | Откуда |
|--------|--------|
| `TELEGRAM_BOT_TOKEN` | @BotFather при создании бота |
| `TELEGRAM_CHAT_ID` | Отправить боту сообщение, затем `https://api.telegram.org/bot<TOKEN>/getUpdates` |

Один бот используется для всех репозиториев.

## Порядок реализации

1. Создать Telegram бота через @BotFather
2. Получить chat_id
3. Добавить секреты в репозиторий
4. Создать composite action `.github/actions/telegram-notify/action.yml`
5. Добавить notify-start и notify-finish jobs в pr.yml
6. Добавить notify-start и notify-finish jobs в push.yml
7. Добавить notify-start и notify-finish jobs в publish.yml
8. Протестировать на реальном PR
