# Telegram Notifications Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Telegram notifications for CI/CD workflow status (started/finished) to PR, Push, and Publish workflows.

**Architecture:** Composite GitHub Action sends notifications via Telegram Bot API. Each workflow gets notify-start and notify-finish jobs. Failed jobs are collected via GitHub API for detailed error reporting.

**Tech Stack:** GitHub Actions (composite action), Bash, curl, jq, Telegram Bot API

---

## Task 1: Create Composite Action

**Files:**
- Create: `.github/actions/telegram-notify/action.yml`

**Step 1: Create action directory**

```bash
mkdir -p .github/actions/telegram-notify
```

**Step 2: Create action.yml**

```yaml
# .github/actions/telegram-notify/action.yml
name: 'Telegram CI Notify'
description: 'Send CI/CD notifications to Telegram'

inputs:
  status:
    description: 'started | success | failure | cancelled'
    required: true
  event-type:
    description: 'pr | push | release'
    required: true
  title:
    description: 'Event title (e.g., PR #42: Add feature)'
    required: true
  event-url:
    description: 'URL to PR / commit / release'
    required: true
  message:
    description: 'Additional message text (optional)'
    required: false
    default: ''
  collect-failed-jobs:
    description: 'Fetch failed jobs via GitHub API'
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
        TG_TOKEN: ${{ inputs.token }}
        TG_CHAT_ID: ${{ inputs.chat-id }}
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

        # 4. Collect failed jobs if requested
        FAILED_SUMMARY=""
        if [ "$COLLECT_FAILED_JOBS" = "true" ]; then
          FAILED_SUMMARY=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
            "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}/jobs" \
            | jq -r '.jobs[] | select(.conclusion == "failure") | "  • [\(.name)](\(.html_url))"' \
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
        curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
          -d chat_id="$TG_CHAT_ID" \
          -d text="$TEXT" \
          -d parse_mode="Markdown" \
          -d disable_web_page_preview="true" \
          > /dev/null
```

**Step 3: Commit**

```bash
git add .github/actions/telegram-notify/action.yml
git commit -m "ci: add telegram-notify composite action"
```

---

## Task 2: Add Notifications to PR Workflow

**Files:**
- Modify: `.github/workflows/pr.yml`

**Step 1: Add notify-start job after line 20 (before jobs:)**

Insert at line 21 (inside `jobs:` block, as first job):

```yaml
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
          message: "Started"
          collect-failed-jobs: false
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}
```

**Step 2: Add notify-finish job at end of file**

Append after line 116:

```yaml

  notify-finish:
    name: Notify Finish
    needs: [detect, validate-pr, python-ci-result, claude-code-plugin-ci-result]
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

**Step 3: Commit**

```bash
git add .github/workflows/pr.yml
git commit -m "ci: add telegram notifications to PR workflow"
```

---

## Task 3: Add Notifications to Push Workflow

**Files:**
- Modify: `.github/workflows/push.yml`

**Step 1: Add notify-start job at beginning of jobs block**

Insert at line 18 (inside `jobs:` block, as first job):

```yaml
  notify-start:
    name: Notify Start
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - id: commit-msg
        run: |
          MSG=$(git log -1 --pretty=%s)
          echo "msg=${MSG:0:50}" >> "$GITHUB_OUTPUT"
      - uses: ./.github/actions/telegram-notify
        with:
          status: started
          event-type: push
          title: "Push ${{ github.sha }}: ${{ steps.commit-msg.outputs.msg }}"
          event-url: ${{ github.event.head_commit.url }}
          message: "Started"
          collect-failed-jobs: false
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}
```

**Step 2: Add notify-finish job at end of file**

Append after line 87:

```yaml

  notify-finish:
    name: Notify Finish
    needs: [detect, validate-commits, python-ci, claude-code-plugin-ci]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - id: commit-msg
        run: |
          MSG=$(git log -1 --pretty=%s)
          echo "msg=${MSG:0:50}" >> "$GITHUB_OUTPUT"
      - uses: ./.github/actions/telegram-notify
        with:
          status: ${{ (contains(needs.*.result, 'failure') && 'failure') || (contains(needs.*.result, 'cancelled') && 'cancelled') || 'success' }}
          event-type: push
          title: "Push ${{ github.sha }}: ${{ steps.commit-msg.outputs.msg }}"
          event-url: ${{ github.event.head_commit.url }}
          message: ${{ contains(needs.*.result, 'failure') && 'Finished with errors:' || 'Finished: All checks passed' }}
          collect-failed-jobs: ${{ contains(needs.*.result, 'failure') }}
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}
```

**Step 3: Commit**

```bash
git add .github/workflows/push.yml
git commit -m "ci: add telegram notifications to Push workflow"
```

---

## Task 4: Add Notifications to Publish Workflow

**Files:**
- Modify: `.github/workflows/publish.yml`

**Step 1: Add notify-start job at beginning of jobs block**

Insert at line 12 (inside `jobs:` block, as first job):

```yaml
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
          collect-failed-jobs: false
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}
```

**Step 2: Replace summary job with notify-finish**

Replace lines 176-193 (the `summary` job) with:

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
          message: ${{ needs.publish-pypi.outputs.summary-message || 'Publish failed' }}
          collect-failed-jobs: false
          token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}
```

**Step 3: Commit**

```bash
git add .github/workflows/publish.yml
git commit -m "ci: add telegram notifications to Publish workflow"
```

---

## Task 5: Test with Real PR

**Step 1: Push branch**

```bash
git push -u origin feature/telegram-notify
```

**Step 2: Create PR**

```bash
gh pr create --title "ci: add Telegram notifications for CI/CD workflows" --label "repo" --body "$(cat <<'EOF'
## Summary

Add Telegram notifications for CI/CD workflow status:
- Notify on workflow start and finish
- Show failed jobs with links on failure
- Support PR, Push, and Publish workflows

## How it works

1. Composite action `.github/actions/telegram-notify/` sends messages via Telegram Bot API
2. Each workflow has `notify-start` and `notify-finish` jobs
3. On failure, GitHub API is called to get list of failed jobs with links

## Secrets required

- `TELEGRAM_BOT_TOKEN` - from @BotFather
- `TELEGRAM_CHAT_ID` - your chat/channel ID

## Test plan

- [ ] Create Telegram bot via @BotFather
- [ ] Add secrets to repository
- [ ] Verify PR workflow sends start notification
- [ ] Verify PR workflow sends finish notification
- [ ] Force a failure and verify failed jobs are listed

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

**Step 3: Verify notifications arrive in Telegram**

Manual verification:
1. Check Telegram for "Started" message when PR is created
2. Check Telegram for "Finished" message when workflow completes
3. If tests fail, verify failed jobs are listed with links

---

## Pre-requisites (Manual Steps)

Before testing, complete these manual steps:

1. **Create Telegram bot:**
   - Message @BotFather on Telegram
   - Send `/newbot`
   - Follow prompts, save the token

2. **Get chat ID:**
   - Send any message to your bot
   - Open `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Find `chat.id` in the response

3. **Add secrets to repository:**
   - Go to repository Settings → Secrets → Actions
   - Add `TELEGRAM_BOT_TOKEN`
   - Add `TELEGRAM_CHAT_ID`
