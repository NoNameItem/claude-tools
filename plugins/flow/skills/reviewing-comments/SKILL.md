---
name: reviewing-comments
description: Use when processing GitHub PR review comments. Collects all unresolved comments, categorizes by source, analyzes each with subagents, applies accepted fixes, argues against invalid ones, and replies on GitHub. Invoked via /flow:review-comments.
---

# Flow: Review Comments

## Overview

**Core principle:** Analyze before acting. Skepticism for nitpicks.

This skill processes all unresolved PR review comments in one pass — applies fixes, argues against invalid comments, and replies on GitHub. Code is written by Claude Code, reviewed by the user and CodeRabbit.

**Command:** `/flow:review-comments [PR-number]`

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 1. PR Detection | Detect PR, sync branch | Argument or autodetect |
| 2. Collect | Subagent: fetch + parse threads | Haiku subagent for heavy lifting |
| 3. Categorize | Show table, user confirms | Humans first, bots second |
| 4. Analyze | Parallel subagents per comment | Verdicts: agree/disagree/outdated |
| 5. Implement | Batch confirm → apply → reply → commit | Group by file, push with confirmation |

## Workflow

Follow these steps **in order**. Do not skip steps.

### Phase 1: PR Detection & Branch Sync

#### 1.1. Get owner/repo

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

Store as `{owner}/{repo}` for all subsequent `gh api` calls.

#### 1.2. Detect PR

**Without argument:**

```bash
gh pr view --json number,title,headRefName,url
```

- PR found: show number, title, URL — continue
- No PR: report "No PR for current branch" — stop

**With argument (PR number provided):**

```bash
gh pr view <number> --json number,title,headRefName,url
```

Get `headRefName` (PR branch). Compare with current branch:

```bash
git branch --show-current
```

- Match: continue
- Mismatch: `git checkout <headRefName>`

#### 1.3. Sync with remote

In both cases after PR detection:

```bash
git pull origin <headRefName>
```

### Phase 2: Collect Comments (Single Haiku Subagent)

Use a **single haiku subagent** to fetch all comments and return structured data. This keeps raw API responses out of the main context.

**Subagent:** `subagent_type="Bash"`, `model="haiku"`

**Subagent prompt:**

```
Run these steps and return results in the EXACT format specified at the end.

1. Fetch inline review comments:
   gh api repos/{owner}/{repo}/pulls/{number}/comments --paginate

2. Fetch reviews (for CodeRabbit summary):
   gh api repos/{owner}/{repo}/pulls/{number}/reviews

3. Parse inline comments:
   - Keep only root comments (in_reply_to_id is null or absent)
   - For each root comment, collect thread replies (other comments with in_reply_to_id == root.id)
   - Detect outdated: comment has "original_line" but "line" is null
   - Detect source: user.login contains "[bot]" or equals "coderabbitai" → bot; else → human
   - Display format for lines: single line → "file.py:42"; range → "file.py:42-58" (use start_line and line)
   - Check if the latest reply in each thread is from the authenticated user (gh api user -q .login) — if so, mark as "already_replied"

4. Check CodeRabbit summary:
   - Find review where user.login is "coderabbitai" or contains "[bot]"
   - Read review body
   - Check if summary contains actionable items not covered by inline comments
   - If found, add as separate items with path="(summary)" and line="—"

5. Return in this EXACT format with these two sections separated by a blank line:

TABLE:
## @{username} ({count} comments)
| #  | File          | Lines  | Comment (brief)               | Outdated |
|----|---------------|--------|-------------------------------|----------|
| U1 | workflow.yml  | 22     | Add contents: read            |          |
| U2 | projects.py   | 32-45  | Legacy code, needed?          | ⚠️       |

## CodeRabbit ({count} comments)
| #  | File          | Lines  | Comment (brief)               | Outdated |
|----|---------------|--------|-------------------------------|----------|
| C1 | workflow.yml  | 15-20  | Missing error handling        |          |
| C2 | (summary)     | —      | Consider adding retry logic   |          |

METADATA:
[
  {"id": 12345, "ref": "U1", "user": "username", "is_bot": false, "path": "workflow.yml", "start_line": null, "line": 22, "body": "Add contents: read for...", "outdated": false, "already_replied": false, "thread": [{"user": "author", "body": "reply text"}]},
  ...
]

Rules for TABLE:
- Humans first (U1, U2...), bots second (C1, C2...)
- "Comment (brief)" column: truncate to ~40 chars
- Outdated column: "⚠️" if outdated, empty otherwise
- Summary items: show "(summary)" as file, "—" as lines

Rules for METADATA JSON:
- "body": truncate to ~200 chars
- "thread": array of {user, body} for all replies in the thread
- "already_replied": true if the latest thread reply is from the authenticated user
- Include ALL root comments, even if already_replied is true (table will mark them)
- One JSON array, valid JSON, on a single line after "METADATA:"

If there are NO unresolved comments, return:
TABLE:
No unresolved review comments found.

METADATA:
[]
```

**After subagent returns:**

1. Parse output: split by `TABLE:` and `METADATA:` markers
2. Store the JSON metadata array for Phase 4
3. Display the TABLE section to the user
4. Filter out comments where `already_replied` is true — mention count: "({N} already replied, skipping)"
5. If no actionable comments remain after filtering, report and stop

### Phase 3: Categorization & Confirmation

Display the table from Phase 2 (already formatted by subagent).

Then ask user:

```
Process all {N} comments? (yes / select / no)
```

- **yes**: process all comments
- **select**: user provides comma-separated refs (e.g., "U1, U3, C2") to process
- **no**: stop

### Phase 4: Analyze Comments (Parallel Haiku Subagents)

For each selected comment (or group of comments in the same file with overlapping line ranges), launch a **haiku subagent**.

**Grouping rule:** Comments in the same file where line ranges overlap or are within 10 lines of each other → single subagent. This avoids reading the same file section multiple times.

**Subagent:** `subagent_type="Bash"`, `model="haiku"`

**Subagent prompt (per comment/group):**

```
Analyze this PR review comment and return a verdict.

Comment ref: {ref} (by {user})
File: {path}
Lines: {start_line}-{line} (or just {line} if no start_line)
Comment: {full_body}
Thread replies:
{formatted thread replies}

Outdated: {yes/no}

Steps:
1. Read the file at the relevant lines (with context ±20 lines):
   Read tool or: sed -n '{start-20},{end+20}p' {path}

2. If outdated: check if the problem described in the comment is already fixed
   in the current code. If fixed → return "outdated_fixed".

3. Analyze whether the comment is valid:
   - Is it a real bug, security issue, or correctness problem? → likely agree
   - Is it a style nitpick, naming preference, or optional suggestion? → higher skepticism
   - Does the current code already handle what the comment asks for? → disagree
   - Is the suggestion actually worse than current code? → disagree

4. For nitpick/style comments: does the change genuinely improve readability,
   correctness, or maintainability? If not → disagree with reasoning.

5. Return EXACTLY one of these verdicts on the FIRST line, followed by a brief explanation:

   VERDICT: agree_obvious | <one-line description of fix>
   VERDICT: agree_unclear | <2-3 option descriptions, separated by " OR ">
   VERDICT: disagree | <2-3 sentence reasoning>
   VERDICT: outdated_fixed | <one-line explanation of what changed>

Return ONLY the verdict line. No other output.
```

**Launch all subagents in parallel** (independent comments have no dependencies).

**After all subagents return:**

Collect verdicts and group by type:

```
Analysis complete:

Obvious fixes (auto-apply):
  U1: remove unused import in utils.py
  C1: add error handling in workflow.yml:15-20

Needs clarification:
  U2: rename variable — Option A: camelCase OR Option B: snake_case OR Option C: keep as is

Disagree:
  C3: naming preference — current naming follows project conventions, change adds churn

Already fixed (outdated):
  U3: import order — fixed in subsequent commits
```

### Phase 5: Implementation & Completion

#### 5.1. Batch Confirmation

Present grouped verdicts for user approval:

**Obvious fixes:**

```
Obvious fixes (batch apply after confirmation):
- U1: remove unused import in utils.py
- C1: add error handling in workflow.yml:15-20

Apply all? (yes / select / no)
```

**Needs clarification** — ask one by one:

For each `agree_unclear` comment, use AskUserQuestion:

```
U2: {comment brief}
File: {path}:{lines}

Options:
1. {Option A description}
2. {Option B description}
3. Skip this comment
```

**Disagree** — ask one by one:

For each `disagree` comment, use AskUserQuestion:

```
C3: {comment brief}
File: {path}:{lines}

Agent's reasoning: {2-3 sentence argument}

Options:
1. Accept anyway — {describe what will be done}
2. Reject (post reasoning as reply)
3. Discuss further
```

If user chooses "Discuss further", engage in conversation until user decides accept or reject.

**Already fixed (outdated):**

```
Already fixed in current code:
- U3: import order

Will reply "Fixed in subsequent commits" to all. OK? (yes / no)
```

#### 5.2. Apply Changes

Group accepted fixes by file. For each file (or group of related files), launch a **haiku subagent**:

**Subagent:** `subagent_type="Bash"`, `model="haiku"`

**Subagent prompt:**

```
Apply these fixes to {path}:

{list of fixes with line numbers and descriptions}

After applying:
1. Run: uv run ruff format {path}  (if Python file)
2. Run: uv run ruff check --fix {path}  (if Python file)

Return: "OK" if all applied successfully, or describe what failed.
```

After all file subagents complete, run a final verification in the main context:

```bash
uv run ruff check {changed_files}  # if Python files changed
```

#### 5.3. Reply on GitHub

For each processed comment, post a reply. Execute **sequentially** (avoid rate limiting):

```bash
gh api repos/{owner}/{repo}/pulls/{number}/comments/{comment_id}/replies \
  -f body="<reply text>"
```

**Reply format by decision:**

| Decision | Reply |
|----------|-------|
| Accepted (fixed) | `"Fixed: {brief description of what was changed}"` |
| Rejected | `"Won't fix: {reasoning}"` |
| Outdated, already fixed | `"Fixed in subsequent commits"` |

**Do NOT reply to comments where `already_replied` is true.**

#### 5.4. Commit

Stage only changed files:

```bash
git add {specific files that were modified}
```

Commit message follows CLAUDE.md scope rules:

- Changes in `plugins/flow/` → `fix(flow): address PR review feedback`
- Changes in `packages/statuskit/` → `fix(statuskit): address PR review feedback`
- Changes across scopes → separate commits per scope (single-package-commit hook enforces this)

#### 5.5. Push

**MANDATORY: Use AskUserQuestion to confirm before pushing** (per CLAUDE.md global instructions).

```
Push to origin/{branch}?

Changes: {N} files modified, {M} comments addressed
Commits: fix(scope): address PR review feedback

Options:
1. Push
2. Skip
```

#### 5.6. Summary Report

```
Processed: {total} comments
  Fixed: {count} ({list of refs})
  Rejected: {count} ({list of refs with brief reason})
  Already fixed: {count} ({list of refs})
  Skipped: {count} ({list of refs user chose to skip})
```

## Scope Boundaries

### This Skill DOES:
- Detect PR from current branch or argument
- Sync branch with remote
- Collect all unresolved inline comments and review summaries
- Categorize by source (human vs bot)
- Analyze each comment with subagents (parallel)
- Apply higher skepticism to nitpick/style comments
- Present grouped verdicts for batch confirmation
- Apply accepted fixes grouped by file
- Reply on GitHub with appropriate messages
- Commit with proper scope
- Push with user confirmation
- Show summary report

### This Skill Does NOT:
- Resolve/dismiss comment threads on GitHub (only replies)
- Create beads tasks from comments
- Modify files outside the scope of comments
- Handle PR approval or merge
- Process comments from closed/merged PRs
- Auto-push without confirmation
- Auto-apply without showing verdicts first
- Reply to comments that already have a reply from the authenticated user

## Red Flags - STOP

If you're thinking any of these, STOP and follow the workflow:

- "I'll apply all fixes without showing verdicts"
- "This nitpick is valid, just apply it"
- "Skip the subagent, I'll read the file inline"
- "I'll reply on GitHub before applying fixes"
- "Push without asking, user wants it done"
- "Skip outdated comments entirely"
- "Reply to already-replied comments anyway"
- "Process comments without user confirmation"
- "I know this fix is right, skip clarification"
- "Commit all changes in one go regardless of scope"
- "User already said 'yes' in Phase 3, skip Phase 5 confirmation"

**All of these mean: Follow the workflow. Analyze before acting. User decides.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Nitpick is obviously correct" | Nitpicks deserve skepticism. Evaluate if change genuinely improves code. |
| "Skip subagents for small PRs" | Subagents keep context clean. Always use them for file reads and analysis. |
| "Apply fixes then show results" | Show verdicts FIRST. User approves before any changes. |
| "One commit is cleaner" | Single-package-commit hook enforces scope. Respect it. |
| "Push is implied" | Push requires explicit confirmation per CLAUDE.md. Always ask. |
| "Already replied = skip entirely" | Skip replying, but still analyze if comment was selected by user. |
| "Outdated = irrelevant" | Outdated might not be fixed. Check current code before dismissing. |
| "Group all comments together" | Group by file for applying, but present individually for unclear/disagree. |
| "CodeRabbit summary is noise" | Summary may contain valid points not in inline comments. Check it. |
| "I'll auto-reject bot nitpicks" | Bots catch real issues too. Analyze each comment on merit. |
| "User approved in Phase 3, skip Phase 5 confirm" | Phase 3 = approve processing. Phase 5 = approve specific fixes. Different decisions. |

## Examples

### BAD: Auto-apply without showing verdicts

```
User: "/flow:review-comments"
Agent: [Fetches 5 comments]
       [Reads files, applies all fixes]
       [Replies on GitHub]
       [Commits and pushes]
       Done! Fixed 5 comments.
```

**Problems:**
- No verdicts shown to user
- No confirmation before applying
- No push confirmation
- No distinction between agree/disagree

### GOOD: Full workflow

```
User: "/flow:review-comments"
Agent: [Detects PR #42 from current branch]
       [Syncs branch with remote]
       [Dispatches haiku subagent to collect comments]

       ## @reviewer (3 comments)
       | #  | File          | Lines  | Comment (brief)          | Outdated |
       |----|---------------|--------|--------------------------|----------|
       | U1 | config.py     | 15     | Missing type annotation   |          |
       | U2 | parser.py     | 42-58  | Simplify this logic       |          |
       | U3 | utils.py      | 10     | Unused import             | ⚠️       |

       ## CodeRabbit (2 comments)
       | #  | File          | Lines  | Comment (brief)          | Outdated |
       |----|---------------|--------|--------------------------|----------|
       | C1 | config.py     | 22     | Possible None access      |          |
       | C2 | (summary)     | —      | Consider retry logic      |          |

       Process all 5 comments? (yes / select / no)

User: yes

Agent: [Dispatches 4 parallel haiku subagents]
       [Groups U1+C1 for config.py, others separate]

       Analysis complete:

       Obvious fixes (auto-apply):
         U1: add type annotation to config_path parameter
         C1: add None check before accessing .name

       Disagree:
         U2: current logic is already clear; extracting helper adds
             indirection without improving readability

       Already fixed (outdated):
         U3: import removed in previous commit

       Low value (nitpick):
         C2: retry logic is out of scope for this PR

       ---

       Obvious fixes — apply all? (yes / select / no)

User: yes

Agent: U2: Simplify this logic
       File: parser.py:42-58

       Agent's reasoning: The current implementation uses a single
       loop with clear variable names. Extracting into a helper
       method would add a level of indirection without improving
       readability or testability.

       1. Accept anyway — extract loop into _parse_tokens() method
       2. Reject (post reasoning as reply)
       3. Discuss further

User: 2

Agent: C2: Consider retry logic
       File: (summary)

       Agent's reasoning: Retry logic is an architectural decision
       beyond the scope of this PR. The current error handling
       raises exceptions appropriately.

       1. Accept anyway — add retry wrapper
       2. Reject (post reasoning as reply)
       3. Discuss further

User: 2

Agent: Already fixed in current code:
         U3: unused import

       Will reply "Fixed in subsequent commits". OK? (yes / no)

User: yes

Agent: [Applies fixes to config.py via subagent]
       [Runs ruff format + check]
       [Replies on GitHub sequentially:
         U1: "Fixed: added type annotation for config_path"
         U2: "Won't fix: current logic is clear, helper adds indirection"
         U3: "Fixed in subsequent commits"
         C1: "Fixed: added None check before accessing .name"
         C2: "Won't fix: retry logic is out of scope for this PR"]
       [Commits: fix(statuskit): address PR review feedback]

       Push to origin/feature/add-config?

       Changes: 1 file modified, 5 comments addressed
       Commits: fix(statuskit): address PR review feedback

       1. Push
       2. Skip

User: Push

Agent: [Pushes to remote]

       Processed: 5 comments
         Fixed: 2 (U1, C1)
         Rejected: 2 (U2 — helper adds indirection, C2 — out of scope)
         Already fixed: 1 (U3)
```

**Correct because:**
- Detected PR and synced
- Used subagent for collection
- Showed categorized table
- Asked before processing
- Used parallel subagents for analysis
- Showed grouped verdicts
- Asked for each unclear/disagree item
- Applied skepticism to nitpick (C2)
- Grouped file changes
- Replied on GitHub after applying
- Committed with proper scope
- Asked before push
- Showed summary

### BAD: Blindly accept nitpick

```
Agent: C2: "Consider using snake_case for variable 'configPath'"
       [Immediately applies rename without analysis]
```

**Problem:** Didn't evaluate whether rename improves code. If project convention is camelCase, this is wrong.

### GOOD: Scrutinize nitpick

```
Agent: C2: "Consider using snake_case for variable 'configPath'"
       VERDICT: disagree | Project uses camelCase consistently in this
       module. Renaming one variable breaks consistency.
```

**Correct because:** Analyzed against project conventions before deciding.

## Edge Cases

### No PR for Current Branch

```
No PR found for current branch `feature/work-in-progress`.

Create a PR first, then run /flow:review-comments.
```

Stop. Do not proceed.

### No Unresolved Comments

```
No unresolved review comments found on PR #42.

Nothing to process.
```

Stop. Do not proceed.

### All Comments Already Replied

```
Found 4 review comments, but all already have replies from you.

Nothing to process.
```

Stop. Do not proceed.

### All Comments Outdated

```
All 3 unresolved comments are outdated and already fixed in current code.

Will reply "Fixed in subsequent commits" to all. OK? (yes / no)
```

Skip Phase 4 analysis for these. Go directly to reply confirmation.

### GitHub API Error

```
GitHub API error: {error message}

Check that:
- gh is authenticated (gh auth status)
- You have access to this repository
- The PR number is correct
```

Stop. Do not retry automatically.

### Mixed Scopes (Multiple Packages Changed)

If accepted fixes span multiple scopes (e.g., both `plugins/flow/` and `packages/statuskit/`):

1. Apply all fixes
2. Create **separate commits** per scope:
   - `fix(statuskit): address PR review feedback`
   - `fix(flow): address PR review feedback`
3. Push once after all commits

### PR Number Provided But Branch Mismatch

```
PR #42 is on branch `feature/add-auth` but you're on `master`.

Switching to feature/add-auth...
[git checkout feature/add-auth]
[git pull origin feature/add-auth]

Continuing with PR #42.
```

### Comment References Deleted File

If a comment's `path` points to a file that no longer exists:

- Treat as outdated
- Verdict: `outdated_fixed` with note "file was removed"
- Reply: "Fixed in subsequent commits (file removed)"

### Very Large Number of Comments (>30)

For PRs with many comments, process in batches:

1. Show full table
2. Ask user: "30+ comments found. Process all, or select specific ones?"
3. If user selects subset, process only those
4. Offer to continue with remaining after first batch

## The Bottom Line

**Analyze before acting. Skepticism for nitpicks.**

Always collect with subagent. Always show verdicts before applying. Always ask before pushing.

Nitpicks deserve extra scrutiny — if it doesn't improve readability, correctness, or maintainability, argue against it.

Never auto-apply. Never skip confirmation. Never push without asking.
