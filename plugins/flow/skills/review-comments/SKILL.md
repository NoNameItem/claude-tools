---
name: review-comments
description: Process unresolved review comments on a GitHub Pull Request or GitLab Merge Request — collect them, analyze each with subagents, apply accepted fixes, argue against invalid ones, and reply on the platform. Use when addressing PR/MR review feedback. Pass a PR/MR number to target a specific one.
allowed-tools: Bash(git:*) Bash(gh:*) Bash(glab:*) Bash(cat:*) Bash(grep:*) Bash(head:*) Bash(tail:*) Bash(cut:*) Bash(tr:*) Bash(wc:*) Bash(echo:*) Bash(test:*) Bash(ls:*) Bash(cd:*) Bash(jq:*) Agent Read
---

# Flow: Review Comments

## Overview

**Core principle:** Analyze before acting. Cite code to dismiss. Fix the class, not the instance.

This skill processes all unresolved review comments in one pass — applies fixes, argues against invalid comments, and replies on the platform. It works on **GitHub Pull Requests** (`gh`) and **GitLab Merge Requests** (`glab`), against both hosted (github.com / gitlab.com) and **self-hosted / Enterprise** instances. The platform is auto-detected (Phase 0). Code is written by Claude Code, reviewed by the user and a bot (e.g. CodeRabbit).

Throughout this skill, **"PR/MR"** means "Pull Request on GitHub, Merge Request on GitLab"; use the platform-appropriate word in user-facing output. GitLab MRs are referenced by **iid** (the `!42` number), GitHub PRs by number.

**Command:** `/flow:review-comments [number] [--platform github|gitlab]`

- `[number]` — PR number (GitHub) or MR iid (GitLab).
- `--platform` — optional override when auto-detection is ambiguous.

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 0. Detect platform | GitHub vs GitLab from remote + CLI auth | See Platform Support; `--platform` overrides |
| 1. PR/MR Detection | Detect unit, sync branch | Argument or autodetect; branch by platform |
| 2. Collect | Subagent: fetch + parse threads | Haiku subagent; platform-specific fetch + parse |
| 3. Categorize | Show table, user confirms | Humans first, bots second |
| 4. Analyze | Parallel sonnet subagents per comment | Dismissal needs CLAIM + EVIDENCE |
| 5. Implement | Confirm + generalize → apply → self-review → reply → commit | Fix the class; skeptic pass before push |

## Platform Support

This skill supports two platforms. Detect once (Phase 0), store `PLATFORM` (`github` | `gitlab`), and use the matching CLI/commands everywhere. The phases below give the concrete commands for each platform; this section is the shared reference.

### Detection algorithm (used by Phase 0)

Resolve `PLATFORM` in this order — stop at the first that decides:

1. **Explicit override:** `--platform github|gitlab` argument → use it.
2. **Remote host:** parse the host from `git remote get-url origin`. Handle both forms:
   - SSH: `git@HOST:group/repo.git`
   - HTTPS: `https://HOST/group/repo(.git)`
3. **Match host against each CLI's authenticated hosts:**
   ```bash
   gh auth status      # lists authenticated GitHub hosts (incl. GitHub Enterprise)
   glab auth status    # lists authenticated GitLab hosts (incl. self-hosted)
   ```
   - HOST appears in `gh auth status` → `github`.
   - HOST appears in `glab auth status` → `gitlab`.
   - **This is what makes self-hosted work** — it does not rely on the literal `github.com` / `gitlab.com` strings.
4. **Fallback heuristic:** HOST contains `github` → `github`; contains `gitlab` → `gitlab`. Warn that the CLI may not be authenticated for that host (and suggest `gh auth login` / `glab auth login --hostname HOST`).
5. **Still ambiguous / unknown** → ask in plain text (GitHub / GitLab?) and wait for the answer, or tell the user to pass `--platform`. (Plain text by design — a structured dialog auto-submits on the AFK timeout; claude-tools-6q4.)

### GitHub ↔ GitLab mapping

| Concept | GitHub (`gh`) | GitLab (`glab`) |
|---|---|---|
| Unit | Pull Request, number | Merge Request, **iid** (the `!42` number) |
| Repo identifier | `owner/repo` (`gh repo view --json nameWithOwner -q .nameWithOwner`) | **URL-encoded** project path `group%2Frepo` (from remote URL path; `/` → `%2F`) |
| Detect unit for current branch | `gh pr view --json number,title,headRefName,url` | `glab mr view <iid> --output json` (fields: `iid`, `title`, `source_branch`, `web_url`, `state`) |
| Fetch threads | `gh api repos/{o}/{r}/pulls/{n}/comments --paginate` + `…/reviews` + `gh api graphql` `reviewThreads` (resolve-state) | `glab api --paginate "projects/{id}/merge_requests/{iid}/discussions"` (one endpoint returns all) |
| Thread model | flat comments linked by `in_reply_to_id` | each `discussion.notes[]` IS the thread; `notes[0]` = root, `notes[1:]` = replies |
| Authenticated user | `gh api user -q .login` | `glab api user -q .username` |
| Reply | `gh api repos/{o}/{r}/pulls/{n}/comments/{comment_id}/replies -f body=…` | `glab api --method POST "projects/{id}/merge_requests/{iid}/discussions/{discussion_id}/notes" --raw-field body=…` — keyed by **`discussion_id`, not comment id** |
| Skip as already-done | `isResolved` (GraphQL `reviewThreads`) **or** `already_replied` | `resolved == true` **or** `already_replied` |
| Outdated detection | `line == null && original_line` set | diff note where `position.new_line == null` (with `old_line` set) — the line no longer exists in the latest version; a note with no `position` is a general comment, not outdated. Do **not** use `head_sha` — it over-flags after a pull |
| Bot / summary | `user.login` is `coderabbitai` / contains `[bot]` | `author.username` matches `coderabbit` / contains `bot`; a bot's summary/walkthrough is just a non-`position` discussion → `(summary)` bucket |
| System notes | n/a | skip notes where `system == true` (e.g. "changed the description") |

> **`glab` command verification:** the exact `glab` flags (`--output json`, `--method`, `--raw-field`, `--paginate`) and whether the `projects/:id` shorthand resolves the current repo can vary by `glab` version. If a documented command fails, fall back to the explicit URL-encoded project path (`projects/group%2Frepo/...`) and verify with `glab api --help` / `glab mr --help`.

## Workflow

Follow these steps **in order**. Do not skip steps.

### Phase 0: Detect Platform

Resolve `PLATFORM` (`github` | `gitlab`) using the **Detection algorithm** in Platform Support above. Store it for all later phases.

- If `glab`/`gh` is needed but **not installed or not authenticated** for the detected host, stop with the error shown in Edge Cases (do not guess credentials).
- Report what was detected, e.g. "Detected GitLab (host `gitlab.example.com`) — using `glab`."

### Phase 1: PR/MR Detection & Branch Sync

#### 1.1. Get the repo identifier

**GitHub:**

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

Store as `{owner}/{repo}` for all subsequent `gh api` calls.

**GitLab:**

```bash
glab repo view --output json   # then read .path_with_namespace
# fallback: derive group/repo from `git remote get-url origin`
```

Store the project path and **URL-encode every `/`**, including nested subgroups:
`group/repo` → `group%2Frepo`, `group/subgroup/repo` → `group%2Fsubgroup%2Frepo`. Use this
encoded path in all subsequent `glab api` calls.

#### 1.2. Detect the PR/MR

The argument is a **PR number** (GitHub) or an **MR iid** (GitLab); strip a leading `!` if the user typed `!42`.

**GitHub — without argument:**

```bash
gh pr view --json number,title,headRefName,url
```

**GitHub — with number:**

```bash
gh pr view <number> --json number,title,headRefName,url
```

The PR branch is `headRefName`.

**GitLab — without argument:**

```bash
glab mr view --output json        # current branch's MR
```

**GitLab — with iid:**

```bash
glab mr view <iid> --output json
```

The MR branch is `source_branch`; the iid is `iid`; the URL is `web_url`. Only process `state == "opened"` MRs.

**Both platforms:**

- Found: show number/iid, title, URL — continue.
- Not found: report "No PR/MR for current branch" — stop.
- Compare the PR/MR branch with the current branch:
  ```bash
  git branch --show-current
  ```
  - Match: continue.
  - Mismatch: `git checkout <branch>` (GitHub) / `glab mr checkout <iid>` (GitLab).

#### 1.3. Sync with remote

In all cases after PR/MR detection:

```bash
git pull origin <branch>
```

### Phase 2: Collect Comments (Single Haiku Subagent)

Use a **single haiku subagent** to fetch all comments and return structured data. This keeps raw API responses out of the main context.

**Subagent:** `subagent_type="Bash"`, `model="haiku"`

**Subagent prompt:**

```
Run these steps and return results in the EXACT format specified at the end.

Platform: {PLATFORM}            (github or gitlab — do ONLY the block for this platform)
GitHub identifiers: owner/repo = {owner}/{repo}, PR number = {number}
GitLab identifiers: project (URL-encoded) = {project}, MR iid = {iid}

=== STEP 1 — Fetch (only your platform's block) ===

If Platform is github:
  a. Inline review comments:
     gh api repos/{owner}/{repo}/pulls/{number}/comments --paginate
  b. Reviews (for bot summary):
     gh api repos/{owner}/{repo}/pulls/{number}/reviews
  c. Authenticated user: gh api user -q .login
  d. Thread resolve-state (REST comments has NO resolve field — GraphQL is the only source):
     gh api graphql --paginate -f query='
       query($owner:String!,$repo:String!,$num:Int!,$endCursor:String){
         repository(owner:$owner,name:$repo){ pullRequest(number:$num){
           reviewThreads(first:100, after:$endCursor){
             nodes{ isResolved comments(first:1){ nodes{ fullDatabaseId } } }
             pageInfo{ hasNextPage endCursor } }}}}' \
       -F owner={owner} -F repo={repo} -F num={number}
     --paginate follows pageInfo and emits ONE JSON object PER PAGE; union
     reviewThreads.nodes[] across every page. If this call errors (e.g. token scope,
     transient), proceed with NO resolved ids — i.e. fall back to already_replied only.
     NEVER abort collection over this side-query.

If Platform is gitlab:
  a. Discussions (inline + general + system notes, all in one):
     glab api --paginate "projects/{project}/merge_requests/{iid}/discussions"
  b. Authenticated user: glab api user -q .username

=== STEP 2 — Parse into threads (only your platform's block) ===

If Platform is github:
  - Keep only root comments (in_reply_to_id is null or absent).
  - resolved_root_ids = { str(comments.nodes[0].fullDatabaseId) for every reviewThreads
    node (Step 1d, unioned across pages) whose isResolved == true }. A thread's first
    comment is its root, so that id equals the REST root comment id. Use fullDatabaseId
    (a BigInt returned as a STRING), NOT the deprecated Int32 databaseId — GitHub review
    comment ids already exceed 2^31 and databaseId can't represent them reliably.
  - SKIP resolved threads: drop any root whose str(id) ∈ resolved_root_ids — compare as
    STRINGS (REST id is a number, fullDatabaseId a string; normalize both). Mirror of the
    GitLab branch below. Resolved roots are removed ENTIRELY: not in the TABLE, not in
    METADATA. (This is a HARDER skip than already_replied, which stays visible-and-marked.)
  - For each remaining root, collect thread replies (comments with in_reply_to_id == root.id).
  - Outdated: comment has "original_line" but "line" is null.
  - Source: user.login contains "[bot]" or equals "coderabbitai" → bot; else human.
  - Lines: single → "file.py:42"; range → "file.py:42-58" (use start_line and line).
  - already_replied: latest reply author == authenticated user.
  - Reply target: comment_id = root comment id; discussion_id = null.

If Platform is gitlab:
  - Each discussion = one thread. Drop notes where system == true.
    notes[0] (first non-system note) = root, notes[1:] = replies.
  - SKIP resolved threads: a discussion whose resolvable notes have resolved == true.
  - Inline vs general: root note has a "position" object → inline; no "position" → general
    comment (treat like a summary item: file = "(summary)", lines = "—").
  - Lines: position.new_line (single) or position.line_range start/end (range) →
    "file:42" / "file:42-58"; if new_line is null, use old_path/old_line.
  - Outdated: the diff line no longer exists in the latest version — position.new_line is
    null while position.old_line is set. (Do NOT use head_sha for this: after the Phase 1.3
    pull, still-valid comments also have an older head_sha and would be wrongly flagged.)
  - Source: author.username matches "coderabbit" or contains "bot" → bot; else human.
  - already_replied: latest note author == authenticated user.
  - Reply target: discussion_id = discussion.id (string); comment_id = null.

=== STEP 3 — Bot summary ===
  - GitHub: find the review whose user.login is "coderabbitai" / contains "[bot]"; if its
    body has actionable items not in the inline comments, add them as items with
    path="(summary)", line="—".
  - GitLab: a bot's summary/walkthrough is just a general (no-position) note already
    captured in Step 2 as a "(summary)" item — no separate fetch.

=== STEP 4 — Return in this EXACT format (two sections, blank line between) ===

TABLE:
## @{username} ({count} comments)
| #  | File          | Lines  | Comment (brief)               | Outdated |
|----|---------------|--------|-------------------------------|----------|
| U1 | workflow.yml  | 22     | Add contents: read            |          |
| U2 | projects.py   | 32-45  | Legacy code, needed?          | ⚠️       |

## {Bot} ({count} comments)
| #  | File          | Lines  | Comment (brief)               | Outdated |
|----|---------------|--------|-------------------------------|----------|
| C1 | workflow.yml  | 15-20  | Missing error handling        |          |
| C2 | (summary)     | —      | Consider adding retry logic   |          |

METADATA:
[
  {"platform": "github", "id": 12345, "ref": "U1", "user": "username", "is_bot": false, "path": "workflow.yml", "start_line": null, "line": 22, "body": "Add contents: read for...", "outdated": false, "already_replied": false, "comment_id": 12345, "discussion_id": null, "thread": [{"user": "author", "body": "reply text"}]},
  ...
]

Rules for TABLE:
- Humans first (U1, U2...), bots second (C1, C2...)
- "Comment (brief)" column: truncate to ~40 chars
- Outdated column: "⚠️" if outdated, empty otherwise
- Summary/general items: show "(summary)" as file, "—" as lines

Rules for METADATA JSON:
- "platform": "github" or "gitlab" — the same value for every item
- "comment_id": GitHub root comment id (number); null on GitLab
- "discussion_id": GitLab discussion id (string); null on GitHub
- "body": truncate to ~200 chars
- "thread": array of {user, body} for all replies in the thread
- "already_replied": true if the latest thread reply is from the authenticated user
- Include ALL root comments/threads, even if already_replied is true (table will mark them) —
  EXCEPT roots dropped as resolved in Step 2 (GitHub) / Step 2 (GitLab), which are excluded entirely
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

### Phase 4: Analyze Comments (Parallel Sonnet Subagents)

For each selected comment (or group of comments in the same file with overlapping line ranges), launch a **sonnet subagent**. Analysis is where a shallow read does the most damage — a misdiagnosed dismissal costs a full rework round — so it runs on **sonnet**, not haiku.

**Grouping rule:** Comments in the same file where line ranges overlap or are within 10 lines of each other → single subagent. This avoids reading the same file section multiple times.

**Subagent:** `subagent_type="Bash"`, `model="sonnet"`

**Subagent prompt (per comment/group):**

```
Analyze this PR/MR review comment and return a structured verdict.

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
   If understanding the code needs a value defined elsewhere (a variable, a
   constant, what a helper actually compares against), trace it — do not stop at
   the local lines. The bug is often in WHAT is compared, not whether a
   comparison exists.

2. Identify the comment's SPECIFIC claim — the exact thing it says is wrong, in
   one sentence. Not the topic ("freshness"), the claim ("committer_date is the
   wrong signal; must compare the head SHA").

3. Decide the verdict. To return `disagree` or `outdated_fixed`, you MUST cite
   the exact code (file:line + snippet) that makes THAT specific claim moot.

   A related mechanism existing is NOT evidence the claim is moot:
   - "a timestamp comparison exists" does NOT refute "timestamps are the wrong
     signal" — show the code compares the RIGHT thing.
   - "a null check exists somewhere" does NOT refute "this path is unguarded" —
     show the guard is on THIS path.
   Do NOT invent supporting facts to dismiss a comment. A thread reply that
   asserts "already handled" is a claim to verify against the code, not evidence.
   If you cannot cite code that moots the SPECIFIC claim → do NOT dismiss. Return a
   structured agree — `agree_obvious` if the requested change is clear, otherwise
   `agree_unclear` — never a bare "agree". When unsure, prefer agreeing over dismissing.

4. For nitpick/style comments: does the change genuinely improve readability,
   correctness, or maintainability? If not → disagree (still fill CLAIM +
   EVIDENCE showing why the current code is fine or the suggestion is worse).

5. Return the verdict in this EXACT structured form. Every verdict has a CATEGORY
   line. `disagree` and `outdated_fixed` ALSO need CLAIM and EVIDENCE lines.

   VERDICT: agree_obvious | <one-line description of fix>
   CATEGORY: <correctness|security|logic|style|nitpick|doc>

   VERDICT: agree_unclear | <2-3 options separated by " OR ">
   CATEGORY: <correctness|security|logic|style|nitpick|doc>

   VERDICT: disagree
   CLAIM: <the comment's specific claim, restated in your own words>
   EVIDENCE: <file:line + exact snippet that moots THAT claim, or why the suggestion is worse>
   CATEGORY: <correctness|security|logic|style|nitpick|doc>

   VERDICT: outdated_fixed
   CLAIM: <the comment's specific claim, restated in your own words>
   EVIDENCE: <file:line + current code that already fixes it>
   CATEGORY: <correctness|security|logic|style|nitpick|doc>

Return ONLY the verdict block. No other output.
```

**Launch all subagents in parallel** (independent comments have no dependencies).

**After all subagents return:**

Collect verdicts and group by type. For `disagree` / `outdated_fixed`, show the
CLAIM and EVIDENCE — a dismissal is only as good as the code it cites. **If an
EVIDENCE line does not cite code that addresses the specific CLAIM (it just names
a related mechanism, or restates the author's assertion), treat it as a shallow
dismissal: re-analyze it, landing on `agree_obvious`/`agree_unclear`.**

```
Analysis complete:

Obvious fixes (auto-apply):
  U1: remove unused import in utils.py  [nitpick]
  C1: add error handling in workflow.yml:15-20  [correctness]

Needs clarification:
  U2: rename variable — Option A: camelCase OR Option B: snake_case OR keep  [style]

Disagree:
  C3 [style]
    CLAIM: variable should be snake_case
    EVIDENCE: config.py:1-40 — module uses camelCase throughout; renaming one breaks consistency

Already fixed (outdated):
  U3 [correctness]
    CLAIM: import order triggers a circular import
    EVIDENCE: utils.py:1-5 — imports already reordered; no cycle remains
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

For each `agree_unclear` comment, ask in plain text and wait for the answer (plain text by design — claude-tools-6q4):

```
U2: {comment brief}
File: {path}:{lines}

Options:
1. {Option A description}
2. {Option B description}
3. Skip this comment
```

**Disagree** — ask one by one:

For each `disagree` comment, ask in plain text and wait for the answer (plain text by design — claude-tools-6q4):

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

##### Generalize accepted fixes (fix the class, not the instance)

Once the user has accepted fixes (`agree_obvious` / `agree_unclear` / an accepted
`disagree`) and **before applying them**, check whether each is one instance of a
class. Patching only the literal line is how one defect gets re-flagged round
after round (fixed for one event type, still broken for the next).

For each accepted fix, launch a **sonnet subagent**:

**Subagent:** `subagent_type="Bash"`, `model="sonnet"`

**Subagent prompt (per accepted fix):**

```
The accepted fix is: {fix description} at {path}:{lines}.

Find siblings — other places with the SAME underlying issue: other event types,
call sites, inputs, or files that share the pattern. Grep for the relevant
identifier/pattern, then READ each candidate to confirm it truly shares the
defect (do not over-match on a name).

Return:
CLASS: <short name for the class, e.g. "freshness computed from committer_date">
SITES:
- {path}:{line} — {one-line why it shares the defect}
- ...
If there are no siblings, return exactly:
CLASS: (instance only)
SITES: none
```

`CLASS` is deliberately a separate field from the Phase 4 verdict `CATEGORY` —
the 5.3 self-review gate keys on `CATEGORY ∈ {correctness, logic, security}`, so
the class name must never overwrite it.

Skip the subagent for pure `doc` / `nitpick` fixes with no plausible siblings
(e.g. a typo). When siblings exist, present the expanded scope and let the user
choose — never widen the blast radius silently:

```
U1 (add `contents: read`) generalizes to a class: 3 sites
  - .github/workflows/a.yml:12
  - .github/workflows/b.yml:8
  - .github/workflows/c.yml:20
Apply to: all / original only / select
```

Record the confirmed sites for 5.2 and the CLASS name for the 5.4 reply.

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

#### 5.3. Pre-Push Adversarial Self-Review

Simulate the next reviewer round locally, before the single push — this is what
stops a fix that shifted the bug into the adjacent case from being discovered one
push later.

**Gate (by verdict nature):** run this step only if at least one accepted finding
has `CATEGORY ∈ {correctness, logic, security}`. Skip pure style/nitpick/doc
rounds — there is no logic to shift. State which applies ("code round → running
self-review" / "nitpick round → skipping self-review").

**Skeptic:** one fresh **sonnet subagent** over the applied diff. Fresh means it
did not analyze or apply any of these fixes — it only tries to break the result.

**Subagent:** `subagent_type="Bash"`, `model="sonnet"`

**Subagent prompt:**

```
You are a fresh skeptic reviewing an applied fix BEFORE it is pushed. Do not
rubber-stamp — your job is to catch what the next review round would flag.

Applied changes — review ALL of them, including newly created files:
  git diff                                    (modified files — read every hunk)
  git status --short --untracked-files=all    (every NEW file marked ?? — the `=all` also lists files INSIDE a brand-new directory, which plain `git status` collapses to a single `dir/` entry)
  Read each new (??) file in full — it is part of the applied fix too.

Findings this diff was meant to close:
{list of accepted findings with their file:line}

For EACH finding answer:
  (a) Does the fix FULLY close it?
  (b) Does it shift the problem to an adjacent case — other event types, call
      sites, inputs, or files that share the same defect?
  (c) What would the next review round most likely flag?

Return ONLY material findings (worth fixing before pushing), each as:
  {path}:{line} — {specific gap} — {suggested fix}
If the fixes are complete and don't shift the problem, return exactly:
  NO MATERIAL FINDINGS
```

**Handle the result (surface → mini-confirm):**

- `NO MATERIAL FINDINGS` → continue to 5.4 silently.
- Material findings → present them as an addendum batch (same confirmation UX as
  5.1). Apply each item the user accepts via a 5.2 apply subagent, then re-run the
  Phase 5.2 final verification (`ruff check` on the changed files) so the addendum
  code is checked too. Do **not** re-run the skeptic — a single pass, then proceed.

Runs **before** the reply (5.4) so replies describe the final code.

#### 5.4. Reply on the platform

For each processed comment, post a reply into its thread. Execute **sequentially** (avoid rate limiting). Use the metadata's `platform` to pick the command:

**GitHub** (reply addressed by `comment_id`):

```bash
gh api repos/{owner}/{repo}/pulls/{number}/comments/{comment_id}/replies \
  -f body="<reply text>"
```

**GitLab** (reply addressed by `discussion_id`, NOT a comment id — a new note in the discussion):

```bash
glab api --method POST \
  "projects/{project}/merge_requests/{iid}/discussions/{discussion_id}/notes" \
  --raw-field body="<reply text>"
```

**Reply format by decision** (identical on both platforms):

| Decision | Reply |
|----------|-------|
| Accepted (fixed) | `"Fixed: {brief description of what was changed}"` |
| Accepted, generalized | `"Fixed: {change}; applied across the class ({class}) at {N} sites."` |
| Rejected | `"Won't fix: {reasoning}"` |
| Outdated, already fixed | `"Fixed in subsequent commits"` |

**Do NOT reply to comments where `already_replied` is true.**

**Multi-line or special-character bodies** (a long "Won't fix: …" rationale, or text with backticks / `$` / quotes): build the body with a quoted heredoc and pass it as a variable so the shell does not interpolate it — works for both platforms:

```bash
body=$(cat <<'EOF'
Won't fix: the current loop is already clear; extracting a helper
adds indirection without improving readability.
EOF
)
gh   api repos/{owner}/{repo}/pulls/{number}/comments/{comment_id}/replies -f body="$body"                        # GitHub
glab api --method POST "projects/{project}/merge_requests/{iid}/discussions/{discussion_id}/notes" --raw-field body="$body"   # GitLab
```

**Summary / general items:**
- **GitHub:** a `(summary)` item has `comment_id == null` (it comes from the review body, not an inline thread) — there is no inline reply target. Record its verdict in the Phase 5.7 summary report; do NOT attempt a reply.
- **GitLab:** a `(summary)` / general item still has a `discussion_id`, so reply to it normally with the GitLab command.

#### 5.5. Commit

Stage only changed files:

```bash
git add {specific files that were modified}
```

Commit message follows CLAUDE.md scope rules:

- Changes in `plugins/flow/` → `fix(flow): address PR review feedback`
- Changes in `packages/statuskit/` → `fix(statuskit): address PR review feedback`
- Changes across scopes → separate commits per scope (single-package-commit hook enforces this)

#### 5.6. Push

**MANDATORY: confirm before pushing with a plain-text prompt, then wait for the answer.** Do **not** use a structured multiple-choice dialog — it auto-submits its pre-selected option after the AFK idle timeout (`CLAUDE_AFK_TIMEOUT_MS`, default 60s), which on a push prompt is an unattended `git push` without consent (claude-tools-6q4). A no-response is not approval; never push until the user answers.

```
Push to origin/{branch}?

Changes: {N} files modified, {M} comments addressed
Commits: fix(scope): address PR review feedback

Options:
1. Push
2. Skip
```

#### 5.7. Summary Report

```
Processed: {total} comments
  Fixed: {count} ({list of refs})
  Generalized: {count} ({ref → class → N sites}, if any)
  Rejected: {count} ({list of refs with brief reason})
  Already fixed: {count} ({list of refs})
  Skipped: {count} ({list of refs user chose to skip})
Self-review: {ran / skipped (nitpick round)}; {N} extra fixes applied
```

## Scope Boundaries

### This Skill DOES:
- Detect the platform (GitHub / GitLab), then the PR/MR from current branch or argument
- Sync branch with remote
- Collect all unresolved inline comments and review summaries
- Categorize by source (human vs bot)
- Analyze each comment with parallel sonnet subagents (dismissals must cite the moot code)
- Apply higher skepticism to nitpick/style comments
- Present grouped verdicts for batch confirmation
- Generalize an accepted fix to its whole class (siblings across event types, call sites, files), with user-confirmed scope
- Apply accepted fixes grouped by file
- Run an adversarial pre-push self-review on correctness/logic/security rounds
- Reply on the platform (GitHub or GitLab) with appropriate messages
- Commit with proper scope
- Push with user confirmation
- Show summary report

### This Skill Does NOT:
- Resolve/dismiss threads on either platform (reply-only — on GitLab it never resolves discussions, even though `resolved` is available)
- Create beads tasks from comments
- Modify files outside the scope of comments — **except** sibling sites within a user-confirmed generalized fix (Phase 5.1), which are in scope by definition
- Handle PR/MR approval or merge
- Process comments from closed/merged PRs/MRs
- Auto-push without confirmation
- Auto-apply without showing verdicts first
- Reply to comments that already have a reply from the authenticated user

## Red Flags - STOP

If you're thinking any of these, STOP and follow the workflow:

- "It's probably GitHub, I'll skip platform detection" → Run Phase 0 first. Never assume.
- "gh works everywhere" → `gh` only talks to GitHub hosts; a GitLab remote needs `glab`.
- "I'll reply on GitLab using the comment id" → GitLab keys replies by `discussion_id`, not a comment id.
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
- "This disagree is obviously right, I'll skip the CLAIM/EVIDENCE" → Every dismissal cites the exact moot code, or it becomes agree.
- "A related mechanism exists, so it's handled" → Not evidence. Show the code addresses the SPECIFIC claim, not just the topic.
- "The author's reply says it's handled, so disagree" → A thread reply is a claim to verify against code, not evidence.
- "Just fix the line the comment points at" → Check for siblings first; fix the class, not the instance.
- "Code round, but I'll skip the self-review to save time" → Run it whenever a correctness/logic/security fix was applied. That's the round that shifts bugs.

**All of these mean: Follow the workflow. Analyze before acting. User decides.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Repo's probably GitHub, skip detection" | Always run Phase 0. The wrong CLI fails on the first command. |
| "gh works everywhere" | `gh` only speaks to GitHub hosts. Use `glab` for GitLab (incl. self-hosted). |
| "Reply by comment id on GitLab" | GitLab keys replies by `discussion_id` (a new note in the discussion), not a comment id. |
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
| "This dismissal is clearly correct" | Then citing the moot code is trivial. If you can't cite it, it isn't clear — agree (`agree_obvious`/`agree_unclear`). |
| "A timestamp/null/guard already exists" | The topic being handled ≠ the claim being handled. Show the code addresses the SPECIFIC claim. |
| "The author reply already explained it's fine" | A thread reply is a claim to verify, not evidence. Check it against the code. |
| "Fix the one line the comment names" | One instance of a class re-flags next round. Enumerate siblings, fix the class. |
| "Fixes applied, push now" | On a code/logic/security round, run the skeptic first — it catches the shifted bug before the reviewer does. |

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

Agent: [Dispatches 4 parallel sonnet subagents]
       [Groups U1+C1 for config.py, others separate]

       Analysis complete:

       Obvious fixes (auto-apply):
         U1: add type annotation to config_path parameter  [nitpick]
         C1: add None check before accessing .name  [correctness]

       Disagree:
         U2 [style]
           CLAIM: the parse loop should be extracted into a helper
           EVIDENCE: parser.py:42-58 — single loop, clear names; a helper adds
                     indirection without improving readability or testability

       Already fixed (outdated):
         U3 [correctness]
           CLAIM: unused import `os` should be removed
           EVIDENCE: utils.py:1-8 — import already removed in a previous commit

       Low value (nitpick):
         C2: retry logic is out of scope for this PR  [nitpick]

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
       [Code round (C1 is correctness) → runs pre-push self-review skeptic over the diff]

       Self-review found 1 issue:
         config.py:30 — the None check guards `.name`, but the sibling access
         `.label` two lines down is still unguarded — same defect.
         1. Apply (guard `.label` too)
         2. Skip

User: 1

Agent: [Applies the self-review fix]
       [Replies on GitHub sequentially:
         U1: "Fixed: added type annotation for config_path"
         U2: "Won't fix: current logic is clear, helper adds indirection"
         U3: "Fixed in subsequent commits"
         C1: "Fixed: added None checks before accessing .name and .label"
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
- Used parallel sonnet subagents for analysis
- Showed grouped verdicts with CLAIM + EVIDENCE behind each dismissal
- Asked for each unclear/disagree item
- Applied skepticism to nitpick (C2)
- Ran the pre-push self-review on the code round and caught an unguarded sibling before pushing
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
       VERDICT: disagree
       CLAIM: configPath should be renamed to snake_case
       EVIDENCE: config.py:1-40 — the module uses camelCase consistently;
                 renaming one variable breaks that consistency
       CATEGORY: style
```

**Correct because:** Restated the claim, then cited the exact code (the module's consistent camelCase) that makes it a net-negative — not a vague "follows conventions".

### BAD: Shallow dismissal (a related mechanism exists → "handled")

```
Comment (C3): "committer_date is the wrong signal for freshness — it survives
rebases. Use the head SHA."
Thread reply (author): "Already handled — we compare against the latest commit date."

Agent: VERDICT: disagree | The reviewer misunderstands committer_date; comparing
       against the latest commit date already rejects stale approvals.
```

**Problem:** Pattern-matched "a date comparison exists" and deferred to the author's
reply. Never checked WHAT is compared — `committer_date` is exactly the wrong signal
the comment named. The dismissal invents a rebuttal instead of citing moot code.
This is the failure that costs a full rework round.

### GOOD: Prove it moot, or agree

```
Agent: VERDICT: agree_obvious | compare the reviewed head SHA against the PR head
       SHA instead of max(committer_date), which is rebase-rewritable and stale-prone
       CATEGORY: correctness
```

**Correct because:** Tried to cite code that makes the SPECIFIC claim moot, found
none (the code uses the very signal the comment flags), and agreed. A thread reply
asserting "already handled" is a claim to verify, not evidence.

## Edge Cases

### No PR/MR for Current Branch

```
No PR/MR found for current branch `feature/work-in-progress`.

Create a PR (GitHub) / MR (GitLab) first, then run /flow:review-comments.
```

Stop. Do not proceed.

### No Unresolved Comments

```
No unresolved review comments found on PR/MR #42.

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

"Outdated" means the commented line **moved** in the diff — NOT that the concern
was addressed. Do **not** skip analysis and bulk-reply "Fixed in subsequent
commits"; that is the shallow dismissal Phase 4 exists to prevent.

Run each outdated thread through the Phase 4 `outdated_fixed` path: the verdict
must cite EVIDENCE (file:line in the current code) that actually fixes the
concern. Only threads that clear that bar get "Fixed in subsequent commits"; the
rest are analyzed like any other comment — they may still be valid.

```
3 comments are marked outdated. Verifying each against current code before replying…
```

### Platform CLI / API Error

```
{gh|glab} API error: {error message}

Check that:
- The CLI is authenticated for this host (gh auth status / glab auth status --hostname HOST)
- You have access to this repository
- The PR/MR number is correct
```

Stop. Do not retry automatically.

### CLI Not Installed or Not Authenticated

If the detected platform's CLI is missing or has no auth for the host:

```
This looks like a GitLab repo (host `gitlab.example.com`), but `glab` is not
authenticated for it.

Run: glab auth login --hostname gitlab.example.com

(For GitHub: install/authenticate `gh` with `gh auth login`.)
```

Stop. Do not guess credentials or fall back to the other platform.

### Ambiguous Platform

If detection can't decide (host matches neither CLI's known hosts, or matches both):

- Ask in plain text (GitHub / GitLab?) and wait for the answer — a structured dialog auto-submits on the AFK timeout (claude-tools-6q4), **or**
- Tell the user to re-run with `--platform github|gitlab`.

Never silently assume GitHub.

### Self-Hosted / Enterprise Host

A non-`github.com` / non-`gitlab.com` host is normal (self-hosted GitLab, GitHub
Enterprise). Detection relies on CLI-auth-host matching, not the literal hostname — so a
self-hosted host that is authenticated in `glab auth status` resolves to GitLab correctly.
The only requirement is that the matching CLI is authenticated for that host.

### Mixed Scopes (Multiple Packages Changed)

If accepted fixes span multiple scopes (e.g., both `plugins/flow/` and `packages/statuskit/`):

1. Apply all fixes
2. Create **separate commits** per scope:
   - `fix(statuskit): address PR review feedback`
   - `fix(flow): address PR review feedback`
3. Push once after all commits

### PR/MR Number Provided But Branch Mismatch

```
PR/MR #42 is on branch `feature/add-auth` but you're on `master`.

Switching to feature/add-auth...
[GitHub: git checkout feature/add-auth | GitLab: glab mr checkout 42]
[git pull origin feature/add-auth]

Continuing with #42.
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

**Analyze before acting. Cite code to dismiss. Fix the class. Skeptic pass before push.**

Always collect with subagent. Always show verdicts before applying. Always ask before pushing.

To dismiss a comment, restate its specific claim and cite the exact code that moots it — a related mechanism existing is not enough, and a thread reply is a claim to verify, not evidence. If you can't prove it moot, agree (as `agree_obvious`/`agree_unclear`).

Fix the class, not the instance: enumerate siblings and apply with confirmed scope. On any correctness/logic/security round, run the pre-push self-review — it catches the shifted bug before the next reviewer does.

Nitpicks deserve extra scrutiny — if it doesn't improve readability, correctness, or maintainability, argue against it.

Never auto-apply. Never skip confirmation. Never push without asking.
