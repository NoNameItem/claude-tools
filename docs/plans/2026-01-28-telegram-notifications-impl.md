# Telegram Notifications Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Telegram notifications for CI/CD workflow status (started/finished) to PR, Push, and Publish workflows.

**Architecture:** Single composite action `.github/actions/telegram-notify/action.yml` called from workflows. Each workflow adds two jobs: `notify-start` (runs first) and `notify-finish` (runs last, after all other jobs).

**Tech Stack:** GitHub Actions composite action, bash, curl, jq, Telegram Bot API

**Design doc:** `docs/plans/2026-01-28-telegram-notifications-design.md`

---

## Task 1: Create composite action

**Files:**
- Create: `.github/actions/telegram-notify/action.yml`

**Step 1: Create action directory**

```bash
mkdir -p .github/actions/telegram-notify
```

**Step 2: Create action.yml**

Create `.github/actions/telegram-notify/action.yml`:

```yaml
name: 'Telegram Notify'
description: 'Send CI/CD status notifications to Telegram'

inputs:
  status:
    description: 'started | success | failure | cancelled'
    required: true
  event-type:
    description: 'pr | push | release'
    required: true
  title:
    description: 'Message title (e.g., PR #42: Add feature)'
    required: true
  event-url:
    description: 'URL to PR/commit/release'
    required: true
  message:
    description: 'Additional message text'
    required: false
    default: ''
  collect-failed-jobs:
    description: 'Fetch failed jobs list via GitHub API'
    required: false
    default: 'false'
  token:
    description: 'Telegram bot token'
    required: true
  chat-id:
    description: 'Telegram chat ID'
    required: true

runs:
  using: 'composite'
  steps:
    - name: Send Telegram notification
      shell: bash
      env:
        STATUS: ${{ inputs.status }}
        EVENT_TYPE: ${{ inputs.event-type }}
        TITLE: ${{ inputs.title }}
        EVENT_URL: ${{ inputs.event-url }}
        MESSAGE: ${{ inputs.message }}
        COLLECT_FAILED_JOBS: ${{ inputs.collect-failed-jobs }}
        TELEGRAM_TOKEN: ${{ inputs.token }}
        TELEGRAM_CHAT_ID: ${{ inputs.chat-id }}
      run: |
        set -euo pipefail

        # 1. Icon by status
        case "$STATUS" in
          started)   ICON="🚀" ;;
          success)   ICON="✅" ;;
          failure)   ICON="❌" ;;
          cancelled) ICON="⛔" ;;
          *)         ICON="❓" ;;
        esac

        # 2. Header
        HEADER="${ICON} ${GITHUB_REPOSITORY} | ${TITLE}"

        # 3. Links
        RUN_URL="https://github.com/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
        case "$EVENT_TYPE" in
          pr)      LINK_TEXT="View PR" ;;
          push)    LINK_TEXT="View commit" ;;
          release) LINK_TEXT="View release" ;;
          *)       LINK_TEXT="View" ;;
        esac
        LINKS="[${LINK_TEXT}](${EVENT_URL}) | [View run](${RUN_URL})"

        # 4. Failed jobs summary (if enabled)
        FAILED_SUMMARY=""
        if [ "$COLLECT_FAILED_JOBS" = "true" ]; then
          FAILED_SUMMARY=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
            "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}/jobs" \
            | jq -r '.jobs[] | select(.conclusion == "failure") | "  • \(.name)"' \
            | head -20) || true
        fi

        # 5. Build message
        TEXT="${HEADER}"
        [ -n "$MESSAGE" ] && TEXT="${TEXT}
        ${MESSAGE}"
        [ -n "$FAILED_SUMMARY" ] && TEXT="${TEXT}
        ${FAILED_SUMMARY}"
        TEXT="${TEXT}
        ${LINKS}"

        # 6. Send to Telegram
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
          -d chat_id="$TELEGRAM_CHAT_ID" \
          -d text="$TEXT" \
          -d parse_mode="Markdown" \
          -d disable_web_page_preview="true"
```

**Step 3: Commit**

```bash
git add .github/actions/telegram-notify/action.yml
git commit -m "ci: add telegram-notify composite action"
```

---

## Task 2: Add notifications to PR workflow

**Files:**
- Modify: `.github/workflows/pr.yml`

**Step 1: Add `actions: read` permission**

In `permissions` section, add `actions: read` for GitHub API access to fetch failed jobs:

```yaml
permissions:
  contents: read
  checks: write
  pull-requests: write
  actions: read  # For fetching failed jobs in notifications
```

**Step 2: Add notify-start job**

Add as first job (before `detect`):

```yaml
jobs:
  notify-start:
    name: Notify Start
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/telegram-notify
        with:
          status: started
          event-type: pr
          title: "PR #${{ github.event.pull_request.number }}: ${{ github.event.pull_request.title }}"
          event-url: ${{ github.event.pull_request.html_url }}
          message: "Checks started"
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}

  detect:
    # ... existing ...
```

**Step 3: Add notify-finish job**

Add at the end of the file, after `claude-code-plugin-ci-result`:

```yaml
  notify-finish:
    name: Notify Finish
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
          message: ${{ contains(needs.*.result, 'failure') && 'Finished with errors:' || 'All checks passed' }}
          collect-failed-jobs: ${{ contains(needs.*.result, 'failure') }}
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

**Step 4: Commit**

```bash
git add .github/workflows/pr.yml
git commit -m "ci: add telegram notifications to PR workflow"
```

---

## Task 3: Add notifications to Push workflow

**Files:**
- Modify: `.github/workflows/push.yml`

**Step 1: Add `actions: read` permission**

```yaml
permissions:
  contents: read
  checks: write
  pull-requests: write
  actions: read  # For fetching failed jobs in notifications
```

**Step 2: Add notify-start job**

Add as first job (before `detect`):

```yaml
jobs:
  notify-start:
    name: Notify Start
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - id: commit-info
        run: |
          MSG=$(git log -1 --pretty=%s)
          SHORT_SHA="${GITHUB_SHA:0:7}"
          echo "message=${MSG:0:50}" >> "$GITHUB_OUTPUT"
          echo "short-sha=$SHORT_SHA" >> "$GITHUB_OUTPUT"
      - uses: ./.github/actions/telegram-notify
        with:
          status: started
          event-type: push
          title: "Push ${{ steps.commit-info.outputs.short-sha }}: ${{ steps.commit-info.outputs.message }}"
          event-url: ${{ github.event.head_commit.url }}
          message: "Checks started"
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}

  detect:
    # ... existing ...
```

**Step 3: Add notify-finish job**

Add at the end of the file:

```yaml
  notify-finish:
    name: Notify Finish
    needs: [validate-commits, python-ci, claude-code-plugin-ci]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - id: commit-info
        run: |
          MSG=$(git log -1 --pretty=%s)
          SHORT_SHA="${GITHUB_SHA:0:7}"
          echo "message=${MSG:0:50}" >> "$GITHUB_OUTPUT"
          echo "short-sha=$SHORT_SHA" >> "$GITHUB_OUTPUT"
      - uses: ./.github/actions/telegram-notify
        with:
          status: ${{ (contains(needs.*.result, 'failure') && 'failure') || (contains(needs.*.result, 'cancelled') && 'cancelled') || 'success' }}
          event-type: push
          title: "Push ${{ steps.commit-info.outputs.short-sha }}: ${{ steps.commit-info.outputs.message }}"
          event-url: ${{ github.event.head_commit.url }}
          message: ${{ contains(needs.*.result, 'failure') && 'Finished with errors:' || 'All checks passed' }}
          collect-failed-jobs: ${{ contains(needs.*.result, 'failure') }}
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

**Step 4: Commit**

```bash
git add .github/workflows/push.yml
git commit -m "ci: add telegram notifications to Push workflow"
```

---

## Task 4: Add notifications to Publish workflow

**Files:**
- Modify: `.github/workflows/publish.yml`

**Step 1: Add `actions: read` permission**

```yaml
permissions:
  contents: read
  id-token: write  # For PyPI Trusted Publisher
  actions: read    # For fetching failed jobs in notifications
```

**Step 2: Add notify-start job**

Add as first job (before `resolve`):

```yaml
jobs:
  notify-start:
    name: Notify Start
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
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}

  resolve:
    # ... existing ...
```

**Step 3: Add notify-finish job**

Add at the end of the file (after `summary` job):

```yaml
  notify-finish:
    name: Notify Finish
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
          message: ${{ needs.publish-pypi.result == 'success' && needs.publish-pypi.outputs.summary-message || 'Publish failed' }}
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}
```

**Step 4: Commit**

```bash
git add .github/workflows/publish.yml
git commit -m "ci: add telegram notifications to Publish workflow"
```

---

## Task 5: Test on real PR

**Step 1: Push branch and create PR**

```bash
git push -u origin feature/telegram-notify
gh pr create --title "ci: add Telegram notifications for CI/CD workflows" --body "..."
```

**Step 2: Verify notifications**

- Check Telegram for "started" message when PR opens
- Wait for CI to complete
- Check Telegram for "finished" message with status

**Step 3: Fix any issues**

If notifications don't work:
- Check Actions logs for errors
- Verify secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set
- Check bot has permission to send messages to chat
