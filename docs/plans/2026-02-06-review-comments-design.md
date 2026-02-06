# Design: /flow:review-comments

Skill for systematic processing of GitHub PR review comments.

## Context

Code is written by Claude Code, reviewed by the user and CodeRabbit. This skill processes all unresolved comments in
one pass — applies fixes, argues against invalid comments, and replies on GitHub.

## Invocation

```
/flow:review-comments [PR-number]
```

- Without argument: detect PR from current branch
- With argument: work with specified PR, switch branch if needed

## Architecture

```
plugins/flow/
├── commands/
│   └── review-comments.md          # Entry point
└── skills/
    └── reviewing-comments/
        └── SKILL.md                 # Skill implementation
```

No Python scripts. All logic is a step-by-step workflow in SKILL.md. Data from GitHub via `gh api`.

## Phase 1: PR Detection and Branch Sync

**Without argument:**

```bash
gh pr view --json number,title,headRefName,url
```

- PR found: show number, title, URL — continue
- No PR: report "No PR for current branch" — stop

**With argument:**

```bash
gh pr view <number> --json number,title,headRefName,url
```

- Get `headRefName` (PR branch)
- Compare with current branch (`git branch --show-current`)
- Match: continue
- Mismatch: `git checkout <headRefName> && git pull origin <headRefName>`

**In both cases** after PR detection, sync with remote:

```bash
git pull origin <headRefName>
```

## Phase 2: Collecting Comments

### Inline comments (primary source)

```bash
gh api repos/{owner}/{repo}/pulls/{number}/comments
```

Fields per comment:

| Field | Purpose |
|-------|---------|
| `id` | For reply |
| `user.login` | Source (human or bot) |
| `path` | File |
| `start_line` + `line` | Line range (single line if `start_line` is null) |
| `body` | Comment text |
| `in_reply_to_id` | Thread detection |

**Display format:**

- Single line: `file.py:42`
- Range: `file.py:42-58`

**Filtering:**

- Keep only root comments (`in_reply_to_id == null`) for the table
- Collect thread replies (`in_reply_to_id == root.id`) as context for processing
- Resolved comments are automatically excluded by GitHub API
- Keep outdated comments (determined by `original_line` present but `line` absent)

**Source detection:**

- `user.login` contains `[bot]` or equals `coderabbitai` → bot
- Everything else → human

### Summary check (supplementary)

```bash
gh api repos/{owner}/{repo}/pulls/{number}/reviews
```

Find CodeRabbit review by `user.login`, read `body`. CC checks if summary contains important points not covered by
inline comments. If found, add as separate items to the table.

## Phase 3: Categorization and Table

Group by source. Humans first (higher priority), then bots.

```
## @username (4 comments)
| #  | File          | Lines  | Comment (brief)               | Outdated |
|----|---------------|--------|-------------------------------|----------|
| U1 | workflow.yml  | 22     | Add contents: read            |          |
| U2 | projects.py   | 32-45  | Legacy code, needed?          |          |
| U3 | config.py     | 10     | Inconsistent naming           | ⚠️       |
| U4 | utils.py      | 88     | Unused import                 |          |

## CodeRabbit (3 comments)
| #  | File          | Lines  | Comment (brief)               | Outdated |
|----|---------------|--------|-------------------------------|----------|
| C1 | workflow.yml  | 15-20  | Missing error handling        |          |
| C2 | parser.py     | 42     | Possible None access          | ⚠️       |
| C3 | (summary)     | —      | Consider adding retry logic   |          |
```

**Numbering:**

- `U1, U2...` — user comments
- `C1, C2...` — CodeRabbit comments

**`⚠️` mark** — outdated comments, CC will check relevance during processing.

**Summary items** shown with `(summary)` instead of file.

## Phase 4: Processing Comments

**Order:** human comments first, then bot comments.

**For each comment CC:**

1. Reads the file at the line range (and full thread if replies exist)
2. Analyzes the problem
3. Chooses strategy based on assessment:

### CC agrees, obvious fix (nitpick, simple fix)

Add to batch. After analyzing all comments, show batch list:

```
Obvious fixes (will be applied automatically):
- U4: remove unused import in utils.py
- C1: add error handling in workflow.yml:15-20

Confirm?
```

### CC agrees, approach needs clarification

Show context, thread, propose solution options via AskUserQuestion.

### CC disagrees with the comment

Show context, thread, argue why the comment is invalid or irrelevant. Ask via AskUserQuestion:

- Accept anyway (describe what will be done)
- Reject (CC argued the case)
- Discuss further

### Outdated comments

CC checks whether the problem is fixed in current code:

- Fixed → add to auto-reply list: "Fixed in subsequent commits"
- Not fixed → process as normal comment

## Phase 5: Implementation and Completion

### Apply changes

- Apply all accepted fixes (batch + individual decisions)
- Group by file to avoid re-reading
- Run lint/format/tests after all changes

### Reply on GitHub

For each processed comment:

```bash
gh api repos/{owner}/{repo}/pulls/{number}/comments/{id}/replies \
  -f body="<text>"
```

Reply format by decision:

| Decision | Reply |
|----------|-------|
| Accepted | `"Fixed: <brief description>"` |
| Rejected | `"Won't fix: <reasoning>"` |
| Outdated, already fixed | `"Fixed in subsequent commits"` |

### Commit and push

```bash
git add <changed-files>
git commit -m "fix(scope): address PR review feedback"
git push origin <branch>
```

Scope follows CLAUDE.md rules (statuskit/flow/no scope).

### Summary report

```
Processed: 7 comments
  Fixed: 5 (U1, U2, U4, C1, C3)
  Rejected: 1 (C2 — false positive, code is safe)
  Already fixed: 1 (U3 — outdated)
```
