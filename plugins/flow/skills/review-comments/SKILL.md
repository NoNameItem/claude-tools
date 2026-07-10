---
name: review-comments
description: Process unresolved review comments on a GitHub Pull Request or GitLab Merge Request — collect them, analyze each with subagents, apply accepted fixes, argue against invalid ones, and reply on the platform. Use when addressing PR/MR review feedback. Pass a PR/MR number to target a specific one.
allowed-tools: Bash(git:*) Bash(gh:*) Bash(glab:*) Bash(bd:*) Bash(flow-comment-card:*) Bash(flow-sync:*) Bash(cat:*) Bash(grep:*) Bash(head:*) Bash(tail:*) Bash(cut:*) Bash(tr:*) Bash(wc:*) Bash(echo:*) Bash(test:*) Bash(ls:*) Bash(cd:*) Bash(jq:*) Agent Read
---

# Flow: Review Comments

## Overview

**Core principle:** Analyze before acting. Cite code to dismiss. Fix the class, not the instance. **Show the code on every card — the user triages in the terminal, never the web UI.**

This skill makes every unresolved review comment reviewable and triageable **inside Claude Code**: for each comment it shows the **anchored code** (syntax-highlighted), the **full comment text + thread**, and the **agent's take** (category + short honest assessment) as a per-comment **card**, then lets the user decide **fix / won't-fix / follow-up** per comment. It applies accepted fixes, argues against invalid comments, files follow-ups as beads tasks, and replies on the platform. It works on **GitHub Pull Requests** (`gh`) and **GitLab Merge Requests** (`glab`), against both hosted (github.com / gitlab.com) and **self-hosted / Enterprise** instances. The platform is auto-detected (Phase 0). Code is written by Claude Code, reviewed by the user and a bot (e.g. CodeRabbit).

**Flow shape:** Phase 2 collects comments **with their code** (GitHub `diff_hunk`; GitLab `position` + a reconstructed snippet) and the **full** body. Phase 3 analyzes **all** non-replied comments up front (parallel sonnet) so every take is code-backed. Phase 4 shows a table of contents, then **one card at a time**, collecting a per-comment decision. Phase 5 acts **once**, grouped by outcome (fix / won't-fix / follow-up), then commits, pushes (with confirmation), and reports.

Throughout this skill, **"PR/MR"** means "Pull Request on GitHub, Merge Request on GitLab"; use the platform-appropriate word in user-facing output. GitLab MRs are referenced by **iid** (the `!42` number), GitHub PRs by number.

**Command:** `/flow:review-comments [number] [--platform github|gitlab]`

- `[number]` — PR number (GitHub) or MR iid (GitLab).
- `--platform` — optional override when auto-detection is ambiguous.

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 0. Detect platform | GitHub vs GitLab from remote + CLI auth | See Platform Support; `--platform` overrides |
| 1. PR/MR Detection | Detect unit, sync branch | Argument or autodetect; branch by platform |
| 2. Collect **+ capture code** | Subagent: fetch + parse threads, keep `diff_hunk`/`position` + **full** body | Haiku subagent; code + full text reach main context |
| 3. Analyze **all** | Parallel sonnet subagents over all non-replied comments | Verdict gains `category`/`thought`/`suggested`; dismissal needs CLAIM + EVIDENCE; large-PR cap only |
| 4. Card-by-card triage | TOC agenda, then one `flow-comment-card` at a time → plain-text fix/won't-fix/follow-up | Emit each card **UNWRAPPED**; humans first, bots second; collect decisions |
| 5. Batch act | fix (generalize → apply → self-review) / won't-fix / follow-up → reply → commit → push | Fix the class; skeptic pass before push; follow-up = a beads task |

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
| Code for the card | `diff_hunk` on each `pulls/{n}/comments` item (already fetched — no extra call) | no `diff_hunk`; store `position` and reconstruct a `snippet` from the current file around `new_line` (via `sed`, **inside the subagent**) |
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

### Phase 2: Collect Comments + Capture Code (Single Haiku Subagent)

Use a **single haiku subagent** to fetch all comments and return structured data. This keeps raw API responses out of the main context. Unlike the old flow, this phase now **captures the code each comment is anchored to** and returns the **full** comment body — the card in Phase 4 shows both, so the user never opens the web UI.

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
  - CODE — capture "diff_hunk": copy the root comment's "diff_hunk" field VERBATIM from
    the pulls/{number}/comments response you already fetched (no extra API call). It is the
    exact code the reviewer saw and works even when the comment is outdated. Store it as-is
    (multi-line string). If a "(summary)" item has no diff_hunk, set diff_hunk = null.

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
  - CODE — store "position": copy position.new_path, position.new_line, position.old_line,
    and position.line_range verbatim into a "position" object. GitLab discussions carry NO
    diff_hunk, so set diff_hunk = null and RECONSTRUCT a snippet here, inside this subagent:
      * If new_line is set (not outdated): read the current file at new_path around new_line
        with context, e.g. `sed -n '{new_line-4},{new_line+4}p' {new_path}`. Put the text in a
        "snippet" object {"lang": LANG, "text": SED_OUTPUT}, where LANG is derived from the file
        extension (.py→python, .js→javascript, .ts→typescript, .yml/.yaml→yaml, .sh→bash;
        unknown extension → empty string "") and SED_OUTPUT is the sed text.
      * If new_line is null (outdated): try old_line context from the MR diff if you have it;
        otherwise set snippet = null (the card degrades to no code block + an outdated note).
      * If the file read yields nothing usable (deleted/moved file), set snippet = null — do
        NOT fail; the card degrades gracefully.
    A "(summary)" / general item (no position) has diff_hunk = null and snippet = null.

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
  {"platform": "github", "id": 12345, "ref": "U1", "user": "username", "is_bot": false, "path": "workflow.yml", "start_line": null, "line": 22, "body": "Add contents: read for the whole job — the full, untruncated comment text goes here.", "outdated": false, "already_replied": false, "comment_id": 12345, "discussion_id": null, "thread": [{"user": "author", "body": "reply text"}], "diff_hunk": "@@ -20,3 +20,4 @@ jobs:\n   build:\n     runs-on: ubuntu-latest\n+    permissions:", "position": null, "snippet": null},
  ...
]

Rules for TABLE:
- Humans first (U1, U2...), bots second (C1, C2...)
- "Comment (brief)" column: truncate to ~40 chars (the TABLE stays terse; the FULL body lives in METADATA)
- Outdated column: "⚠️" if outdated, empty otherwise
- Summary/general items: show "(summary)" as file, "—" as lines

Rules for METADATA JSON:
- "platform": "github" or "gitlab" — the same value for every item
- "comment_id": GitHub root comment id (number); null on GitLab
- "discussion_id": GitLab discussion id (string); null on GitHub
- "body": the **FULL, UNTRUNCATED** comment text. Do NOT cap it — the card shows it whole.
  (Only the TABLE "Comment (brief)" column is truncated.)
- "thread": array of {user, body} for all replies in the thread (full bodies)
- "diff_hunk": GitHub — the root comment's diff_hunk string (may be null); GitLab — null
- "position": GitLab — {new_path, new_line, old_line, line_range} (may be null); GitHub — null
- "snippet": GitLab-reconstructed {lang, text} current-file context (may be null); GitHub — null
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
2. Store the JSON metadata array (with `body`, `diff_hunk`/`position`/`snippet`, `thread`) — Phase 3 analyzes it and Phase 4 assembles cards from it
3. Filter out comments where `already_replied` is true — mention count: "({N} already replied, skipping)"
4. If no actionable comments remain after filtering, report and stop
5. Do **not** print a "process all?" gate here — the decision surface is the per-comment card in Phase 4. (The only gate is the large-PR cap in Phase 3.)

### Phase 3: Analyze ALL Comments (Parallel Sonnet Subagents)

Analyze **every** non-`already_replied` comment up front — there is **no pre-analysis
"process all? yes/select/no" gate** anymore. The per-comment card (Phase 4) is the decision
surface, and its take must be a real, code-backed assessment; a take written without reading
the code is exactly the shallow dismissal this skill fights.

**Large-PR cap (the only pre-analysis gate).** If there are **more than ~20** non-replied
comments, first display the Phase 2 TABLE and ask, in **plain text**, and wait for the answer
(plain text by design — a structured dialog auto-submits on the AFK timeout; claude-tools-6q4):

```
{N} comments — analyze all, or select a subset? (all / <comma-separated refs>)
```

- **all** → analyze all.
- **refs** (e.g. "U1, U3, C2") → analyze only those.

Below the threshold, analyze **all** silently (no prompt).

For each comment to analyze (or group of comments in the same file with overlapping line
ranges), launch a **sonnet subagent**. Analysis is where a shallow read does the most damage —
a misdiagnosed dismissal costs a full rework round — so it runs on **sonnet**, not haiku.

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

5. If the comment is NOT outdated and the reviewer's diff_hunk is absent or too thin to
   understand the change on its own, ALSO return a SNIPPET: read the current file at the
   commented lines with a little context (e.g. `sed -n '{start-4},{end+4}p' {path}`) and
   return it as a fenced block tagged with the file's language. This is the current-file
   context the card shows when there is no usable diff_hunk. Omit SNIPPET if the diff_hunk
   is already clear, or if the file/lines no longer exist.

6. Return the verdict in this EXACT structured form. Every verdict has CATEGORY, THOUGHT,
   and SUGGESTED lines. `disagree` and `outdated_fixed` ALSO need CLAIM and EVIDENCE lines.
   SNIPPET is optional (step 5).

   VERDICT: agree_obvious | <one-line description of fix>
   CATEGORY: <correctness|security|logic|style|nitpick|doc>
   THOUGHT: <one short honest paragraph — your real take, shown on the card>
   SUGGESTED: <fix | won't-fix | follow-up>

   VERDICT: agree_unclear | <2-3 options separated by " OR ">
   CATEGORY: <correctness|security|logic|style|nitpick|doc>
   THOUGHT: <one short honest paragraph>
   SUGGESTED: <fix | won't-fix | follow-up>

   VERDICT: disagree
   CLAIM: <the comment's specific claim, restated in your own words>
   EVIDENCE: <file:line + exact snippet that moots THAT claim, or why the suggestion is worse>
   CATEGORY: <correctness|security|logic|style|nitpick|doc>
   THOUGHT: <one short honest paragraph — becomes the "Won't fix: …" reasoning>
   SUGGESTED: <fix | won't-fix | follow-up>

   VERDICT: outdated_fixed
   CLAIM: <the comment's specific claim, restated in your own words>
   EVIDENCE: <file:line + current code that already fixes it>
   CATEGORY: <correctness|security|logic|style|nitpick|doc>
   THOUGHT: <one short honest paragraph — why the current code already handles it>
   SUGGESTED: <fix | won't-fix | follow-up>

   SNIPPET: (optional, step 5)
   ```<lang>
   <current-file context lines>
   ```

   How to pick SUGGESTED (the recommended default the user sees on the card):
   - agree_obvious / agree_unclear → `fix` (or `follow-up` if the change is large, risky, or
     out of this PR's scope — big enough to defer rather than do inline).
   - disagree → `won't-fix`.
   - outdated_fixed → `fix` (already fixed in current code; the card's THOUGHT says so, and
     Phase 5 replies "Fixed in subsequent commits" instead of applying anything).

Return ONLY the verdict block (VERDICT/CLAIM/EVIDENCE/CATEGORY/THOUGHT/SUGGESTED and the
optional SNIPPET). No other output.
```

**Launch all subagents in parallel** (independent comments have no dependencies).

**After all subagents return:**

Collect verdicts. For `disagree` / `outdated_fixed`, the CLAIM and EVIDENCE are load-bearing —
a dismissal is only as good as the code it cites. **If an EVIDENCE line does not cite code that
addresses the specific CLAIM (it just names a related mechanism, or restates the author's
assertion), treat it as a shallow dismissal: re-analyze it, landing on
`agree_obvious`/`agree_unclear`.** Keep each verdict's `category`, `thought`, `suggested`, and
optional `snippet` — they feed the Phase 4 card. Do **not** print a grouped-by-type verdict dump
here; the verdicts are surfaced one card at a time in Phase 4.

### Phase 4: Card-by-Card Triage

This is the decision surface. Show the whole set as a table of contents, then walk **one card
at a time**, collecting a fix / won't-fix / follow-up decision for each. **Do not execute
anything yet** — decisions are collected here and acted on in Phase 5.

#### 4.1. Agenda (table of contents)

Print one compact table so the user sees the whole set before the cards start — humans first,
bots second:

```
Triaging {N} comments (humans first, then bots):

| ref | source | path:lines            | category    | brief                        | ⚠️ |
|-----|--------|-----------------------|-------------|------------------------------|----|
| U1  | human  | config.py:15          | nitpick     | Missing type annotation      |    |
| C1  | bot    | git.py:42             | correctness | Crashes on detached HEAD     |    |
| C3  | bot    | utils.py:10           | correctness | Unused import                | ⚠️ |
```

#### 4.2. One card at a time

For each comment (in TOC order), **assemble the card JSON** by merging the Phase 2 metadata
item with its Phase 3 verdict, then render it with `flow-comment-card`. The card fields:

| Card field | Source |
|------------|--------|
| `ref`, `path`, `start_line`, `line`, `outdated`, `body`, `thread`, `diff_hunk`, `snippet` | Phase 2 metadata (map `author` = metadata `user`; `source` = "bot" if `is_bot` else "human") |
| `category`, `thought`, `suggested` | Phase 3 verdict |
| `snippet` | Phase 3 verdict's SNIPPET if present, else Phase 2 metadata `snippet` (GitLab) |

Build one JSON object and pipe it in. Example (any equivalent assembly works — the helper reads
one comment object on stdin):

```bash
card=$(jq -n \
  --argjson meta "$(jq '.[] | select(.ref=="C1")' <<<"$METADATA")" \
  --arg category  "correctness" \
  --arg thought   "Agrees — real crash on detached HEAD; the guard is one frame too low." \
  --arg suggested "fix" \
  '$meta + {author: $meta.user,
            source: (if $meta.is_bot then "bot" else "human" end),
            category: $category, thought: $thought, suggested: $suggested}')
echo "$card" | flow-comment-card
```

**⚠️ NO OUTER FENCE — emit the card UNWRAPPED.** `flow-comment-card` output already *contains*
```` ```diff ````/```` ```lang ```` fences and markdown blockquotes. Print its output **directly
into your reply, with no surrounding ```` ``` ```` fence.** Wrapping it in an outer fence turns
the whole card into a literal code dump — the syntax highlighting, the `+/-` diff coloring, and
the blockquotes all stop rendering, which defeats the entire feature. This is the **opposite** of
`flow-task-card`, whose ASCII-box output you *do* reproduce inside a fence. Same helper family,
opposite wrapping rule — do not wrap this one out of habit.

After emitting the card, ask — in **plain text** — for the decision on **this** comment,
defaulting to the card's `suggested`, and wait for the answer (plain text by design — a
structured dialog auto-submits on the AFK timeout; claude-tools-6q4):

```
C1 → fix / won't-fix / follow-up?  (default: fix)
```

- Empty / Enter → take the default (`suggested`).
- **agree_unclear:** the take is genuinely ambiguous — present the 2-3 fix options inline here
  (from the verdict's `agree_unclear | A OR B OR C`) and let the user pick which fix (or skip)
  **before** moving to the next card. Record the chosen option with the `fix` decision.

Record `{ref → decision}` (and the chosen option for `agree_unclear`), then show the next card.
Do **not** apply, reply, or commit during the loop.

### Phase 5: Batch Execution

The Phase 4 decisions are now executed **once**, grouped by outcome. Order matters: apply all
fixes first (so replies describe the final code), create follow-ups, then reply to every
comment, then commit and push. This preserves fix-the-class, a single skeptic pass, and one
commit/push — the reason triage and execution are split.

#### 5.1. Fix — generalize the class (fix the class, not the instance)

Take the comments the user decided **`fix`** on in Phase 4 (this includes an `agree_unclear`
whose option was chosen, and an accepted `disagree` the user overrode to `fix`). An
`outdated_fixed` comment the user kept as `fix` has **nothing to apply** — it is already fixed
in current code; skip it here and just reply "Fixed in subsequent commits" in 5.5. **Before
applying** the rest, check whether each is one instance of a class. Patching only the literal
line is how one defect gets re-flagged round after round (fixed for one event type, still
broken for the next).

For each fix, launch a **sonnet subagent**:

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

Record the confirmed sites for 5.2 and the CLASS name for the 5.5 reply.

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

- `NO MATERIAL FINDINGS` → continue silently.
- Material findings → present them as an addendum batch and confirm before applying (a plain-text
  per-item accept/skip). Apply each item the user accepts via a 5.2 apply subagent, then re-run
  the Phase 5.2 final verification (`ruff check` on the changed files) so the addendum code is
  checked too. Do **not** re-run the skeptic — a single pass, then proceed.

Runs **before** the reply (5.5) so replies describe the final code.

#### 5.4. Follow-up — create beads tasks

For each comment the user decided **`follow-up`** on, create a beads task so the deferred work
is tracked, then reply "Filed as follow-up: {task-id}" in 5.5.

**Parent epic — infer from the comment's path** (repo convention; the user confirms/overrides):

| Comment path starts with | Parent epic |
|--------------------------|-------------|
| `packages/statuskit/` | `claude-tools-5dl` |
| `plugins/flow/` | `claude-tools-elf` |
| `.github/` · `docs/` · repo root (or `(summary)` / no path) | `claude-tools-5vg` |

**Type:** `bug` for `category ∈ {correctness, security, logic}`, else `task`.
**Priority:** default **P2**.
**Title:** concise, from the comment's substance (e.g. "Guard branch_name against detached HEAD").
**Description:** the PR/MR URL, `path:lines`, the reviewer's comment text, and a brief note of the
agent's take.

**Confirm the whole follow-up batch in one plain-text prompt** and wait for the answer (plain
text by design — claude-tools-6q4):

```
Creating {N} follow-ups:
  C3 → bug  P2  under claude-tools-5dl — Guard branch_name against detached HEAD
  U4 → task P2  under claude-tools-elf — Extract retry helper for flow-sync
Proceed? (yes / edit / no)
```

On **yes**, create them **sequentially** (embedded Dolt is single-writer — do NOT parallelize
`bd create`). For special characters in the description, prefer `--body-file -` (stdin) or
single-quote it:

```bash
bd create --title "Guard branch_name against detached HEAD" --type bug --priority 2 \
  --parent claude-tools-5dl --description "**PR:** {url}
**Location:** packages/statuskit/src/statuskit/modules/git.py:42
**Reviewer (coderabbitai):** {full comment text}

**Take:** real crash on detached HEAD; deferred to its own task."
```

After creating all follow-ups, **persist to the shared beads store**:

```bash
flow-sync push
```

Record `{ref → task-id}` for the 5.5 reply and the 5.8 summary line.

#### 5.5. Reply on the platform

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

| Decision (from Phase 4) | Reply |
|-------------------------|-------|
| fix (change applied) | `"Fixed: {brief description of what was changed}"` |
| fix, generalized | `"Fixed: {change}; applied across the class ({class}) at {N} sites."` |
| fix, but `outdated_fixed` (already fixed in current code, nothing applied) | `"Fixed in subsequent commits"` |
| won't-fix | `"Won't fix: {reasoning}"` — the reasoning is the card's `thought` |
| follow-up | `"Filed as follow-up: {task-id}"` (the beads task from 5.4) |

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
- **GitHub:** a `(summary)` item has `comment_id == null` (it comes from the review body, not an inline thread) — there is no inline reply target. Record its decision in the 5.8 summary report; do NOT attempt a reply. (A follow-up filed from a GitHub summary item is still created — only the reply is skipped.)
- **GitLab:** a `(summary)` / general item still has a `discussion_id`, so reply to it normally with the GitLab command.

#### 5.6. Commit

Stage only changed files:

```bash
git add {specific files that were modified}
```

Commit message follows CLAUDE.md scope rules:

- Changes in `plugins/flow/` → `fix(flow): address PR review feedback`
- Changes in `packages/statuskit/` → `fix(statuskit): address PR review feedback`
- Changes across scopes → separate commits per scope (single-package-commit hook enforces this)

#### 5.7. Push

**MANDATORY: confirm before pushing with a plain-text prompt, then wait for the answer.** Do **not** use a structured multiple-choice dialog — it auto-submits its pre-selected option after the AFK idle timeout (`CLAUDE_AFK_TIMEOUT_MS`, default 60s), which on a push prompt is an unattended `git push` without consent (claude-tools-6q4). A no-response is not approval; never push until the user answers.

```
Push to origin/{branch}?

Changes: {N} files modified, {M} comments addressed
Commits: fix(scope): address PR review feedback

Options:
1. Push
2. Skip
```

#### 5.8. Summary Report

```
Processed: {total} comments
  Fixed: {count} ({list of refs})
  Generalized: {count} ({ref → class → N sites}, if any)
  Won't fix: {count} ({list of refs with brief reason})
  Already fixed: {count} ({list of refs})
  Follow-ups created: {count} ({ref → task-id})
  Skipped: {count} ({list of refs user chose to skip})
Self-review: {ran / skipped (nitpick round)}; {N} extra fixes applied
```

## Scope Boundaries

### This Skill DOES:
- Detect the platform (GitHub / GitLab), then the PR/MR from current branch or argument
- Sync branch with remote
- Collect all unresolved inline comments and review summaries **with their anchored code** (GitHub `diff_hunk`; GitLab `position` + a reconstructed snippet) and the **full** comment text
- Analyze **all** non-replied comments with parallel sonnet subagents (dismissals must cite the moot code)
- Apply higher skepticism to nitpick/style comments
- Show a **per-comment card** (via `flow-comment-card`) with the code, full text + thread, and the agent's take — emitted **unwrapped** so it renders
- Let the user triage each comment **fix / won't-fix / follow-up**, one card at a time
- Generalize an accepted fix to its whole class (siblings across event types, call sites, files), with user-confirmed scope
- Apply accepted fixes grouped by file
- Run an adversarial pre-push self-review on correctness/logic/security rounds
- **Create a beads follow-up task** for deferred comments (parent epic inferred from the path), then `flow-sync push`
- Reply on the platform (GitHub or GitLab) with appropriate messages
- Commit with proper scope
- Push with user confirmation
- Show summary report

### This Skill Does NOT:
- Resolve/dismiss threads on either platform (reply-only — on GitLab it never resolves discussions, even though `resolved` is available)
- Modify files outside the scope of comments — **except** sibling sites within a user-confirmed generalized fix (Phase 5.1), which are in scope by definition
- Handle PR/MR approval or merge
- Process comments from closed/merged PRs/MRs
- Auto-push without confirmation
- Auto-apply without showing the card and collecting a per-comment decision first
- Reply to comments that already have a reply from the authenticated user
- Wrap the `flow-comment-card` output in an outer ``` fence (that breaks its rendering)

## Red Flags - STOP

If you're thinking any of these, STOP and follow the workflow:

- "It's probably GitHub, I'll skip platform detection" → Run Phase 0 first. Never assume.
- "gh works everywhere" → `gh` only talks to GitHub hosts; a GitLab remote needs `glab`.
- "I'll reply on GitLab using the comment id" → GitLab keys replies by `discussion_id`, not a comment id.
- "I'll wrap the card in a ``` fence so it's clearly a card" → NO. The card already contains ```-fences; wrap it and the highlighting, diff colors, and blockquotes stop rendering. Emit it UNWRAPPED.
- "The comment text is enough, skip the code block" → The card MUST carry the anchored code (`diff_hunk` or reconstructed `snippet`); showing the code in the terminal is the whole point.
- "I'll truncate the long comment on the card" → Show the FULL body. Only the TOC brief is truncated.
- "I'll just analyze the comments that look important" → Analyze ALL non-replied comments (below the large-PR cap). The take must be code-backed.
- "I'll apply all fixes without showing the card"
- "This nitpick is valid, just apply it"
- "Skip the subagent, I'll read the file inline"
- "I'll reply on GitHub before applying fixes"
- "Push without asking, user wants it done"
- "Skip outdated comments entirely" → Outdated keeps its diff + ⚠️; analysis still runs (outdated ≠ fixed).
- "Reply to already-replied comments anyway"
- "Apply straight from the card without collecting the decision" → Collect all decisions in Phase 4; execute once in Phase 5.
- "Follow-up? I'll just fix it inline to save a round" → If the user chose follow-up, file the beads task; don't override their triage.
- "Commit all changes in one go regardless of scope"
- "This disagree is obviously right, I'll skip the CLAIM/EVIDENCE" → Every dismissal cites the exact moot code, or it becomes agree.
- "A related mechanism exists, so it's handled" → Not evidence. Show the code addresses the SPECIFIC claim, not just the topic.
- "The author's reply says it's handled, so disagree" → A thread reply is a claim to verify against code, not evidence.
- "Just fix the line the comment points at" → Check for siblings first; fix the class, not the instance.
- "Code round, but I'll skip the self-review to save time" → Run it whenever a correctness/logic/security fix was applied. That's the round that shifts bugs.

**All of these mean: Follow the workflow. Analyze before acting. Show the card. User triages.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Repo's probably GitHub, skip detection" | Always run Phase 0. The wrong CLI fails on the first command. |
| "gh works everywhere" | `gh` only speaks to GitHub hosts. Use `glab` for GitLab (incl. self-hosted). |
| "Reply by comment id on GitLab" | GitLab keys replies by `discussion_id` (a new note in the discussion), not a comment id. |
| "Nitpick is obviously correct" | Nitpicks deserve skepticism. Evaluate if change genuinely improves code. |
| "Skip subagents for small PRs" | Subagents keep context clean. Always use them for file reads and analysis. |
| "Apply fixes then show the card" | Show the card FIRST. The user triages each comment before any change. |
| "Wrap the card in a fence for clarity" | The card contains its own ```-fences; wrapping kills the highlighting and blockquotes. Emit it UNWRAPPED (opposite of `flow-task-card`). |
| "Show the comment text, skip the code" | Every card carries the anchored code (`diff_hunk`/`snippet`). Seeing the code in the terminal is the point. |
| "Truncate the long comment" | Show the FULL body on the card; only the TOC brief is truncated. |
| "Analyze only the interesting comments" | Analyze ALL non-replied comments (below the large-PR cap) so every take is code-backed. |
| "One commit is cleaner" | Single-package-commit hook enforces scope. Respect it. |
| "Push is implied" | Push requires explicit confirmation per CLAUDE.md. Always ask. |
| "Already replied = skip entirely" | Skip replying, but still analyze it (analysis covers all non-replied comments). |
| "Outdated = irrelevant" | Outdated might not be fixed. Card keeps the diff + ⚠️; check current code before dismissing. |
| "Follow-up is just a slow fix, do it now" | Follow-up is the user's choice to defer. File a beads task; don't override the triage. |
| "Group all comments together" | Group by file for applying, but show and triage each comment on its own card. |
| "CodeRabbit summary is noise" | Summary may contain valid points not in inline comments. Check it. |
| "I'll auto-reject bot nitpicks" | Bots catch real issues too. Analyze each comment on merit. |
| "This dismissal is clearly correct" | Then citing the moot code is trivial. If you can't cite it, it isn't clear — agree (`agree_obvious`/`agree_unclear`). |
| "A timestamp/null/guard already exists" | The topic being handled ≠ the claim being handled. Show the code addresses the SPECIFIC claim. |
| "The author reply already explained it's fine" | A thread reply is a claim to verify, not evidence. Check it against the code. |
| "Fix the one line the comment names" | One instance of a class re-flags next round. Enumerate siblings, fix the class. |
| "Fixes applied, push now" | On a code/logic/security round, run the skeptic first — it catches the shifted bug before the reviewer does. |

## Examples

### BAD: Grouped verdict dump, no code, coarse gate

```
User: "/flow:review-comments"
Agent: [Fetches 5 comments]
       Process all 5 comments? (yes / select / no)
User: yes
Agent: Obvious fixes: U1, C1.  Disagree: U2.  Outdated: U3.
       Apply all? (yes / no)
```

**Problems:**
- No code shown — the user can't see what any comment is anchored to; they open the web UI.
- Full comment text never surfaced (truncated brief only).
- One coarse yes/no gate instead of a per-comment fix / won't-fix / **follow-up** decision.
- No follow-up path for the big items.

### GOOD: Full workflow (TOC → per-card triage → batch act)

```
User: "/flow:review-comments"
Agent: [Detects PR #42, syncs branch]
       [Haiku subagent collects comments WITH diff_hunk + full body]
       [3 non-replied comments → below the ~20 cap → analyzes ALL in parallel sonnet]

       Triaging 3 comments (humans first, then bots):

       | ref | source | path:lines   | category    | brief                     | ⚠️ |
       |-----|--------|--------------|-------------|---------------------------|----|
       | U1  | human  | config.py:15 | nitpick     | Missing type annotation   |    |
       | C1  | bot    | git.py:42    | correctness | Crashes on detached HEAD  |    |
       | C2  | bot    | (summary)    | doc         | Consider retry logic      |    |

       [Emits C1's card directly, UNWRAPPED (no outer fence). Its raw markdown —
        which Claude Code renders with a highlighted diff and blockquote — is:]

         ### 🔴 C1 · correctness · .../statuskit/modules/git.py:42
         > **@coderabbitai:** This still crashes on a detached HEAD. resolve_branch()
         > calls branch_name() before the detached check runs — move the guard up or
         > make branch_name total.  (full body, untruncated)
         (then a ```diff fenced block with the reviewer's hunk: - return head.name /
          + return head.name if not head.is_detached else "(detached)")
         **Thought:** Real crash on a detached HEAD; the guard is one frame too low.
         **Suggested:** fix

       C1 → fix / won't-fix / follow-up?  (default: fix)

User: fix

Agent: [Emits U1's card unwrapped … ] U1 → fix / won't-fix / follow-up? (default: fix)
User: won't-fix
Agent: [Emits C2's card unwrapped, header "### 🔵 C2 · doc · (summary)", no code block]
       C2 → fix / won't-fix / follow-up? (default: won't-fix)
User: follow-up

Agent: [Phase 5 — acts once, grouped by outcome]
       [fix: generalizes C1 → guard also in resolve_branch:66; applies; code round →
        runs pre-push self-review skeptic over the diff]
       [follow-up: infers parent claude-tools-5vg for the summary item]

       Creating 1 follow-up:
         C2 → task P2 under claude-tools-5vg — Add retry logic to network calls
       Proceed? (yes / edit / no)

User: yes

Agent: [bd create … ; flow-sync push]
       [Replies sequentially:
         U1: "Won't fix: the module uses camelCase consistently; renaming one breaks it"
         C1: "Fixed: guard branch_name against detached HEAD; applied across the class at 2 sites."
         C2: (GitHub summary, comment_id == null → no reply; recorded in summary)]
       [Commits: fix(statuskit): address PR review feedback]

       Push to origin/feature/add-config?
       Changes: 1 file modified, 3 comments addressed
       1. Push
       2. Skip

User: Push

Agent: [Pushes]
       Processed: 3 comments
         Fixed: 1 (C1)   Generalized: C1 → detached-HEAD guard → 2 sites
         Won't fix: 1 (U1 — module is camelCase)
         Follow-ups created: 1 (C2 → claude-tools-5vg-NN)
```

**Correct because:**
- Collected the code (`diff_hunk`) and full body, so each card is self-contained
- Analyzed ALL non-replied comments up front (below the large-PR cap) → code-backed takes
- Showed a TOC, then one card at a time, each emitted UNWRAPPED so it renders
- Collected a per-comment fix / won't-fix / **follow-up** decision; executed once in Phase 5
- Generalized the accepted fix and ran the pre-push self-review on the code round
- Filed the deferred item as a beads task under the path-inferred epic, then `flow-sync push`
- Replied to every comment except the GitHub null-`comment_id` summary; asked before push

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

### Outdated Comments (and All-Outdated)

"Outdated" means the commented line **moved** in the diff — NOT that the concern
was addressed. Do **not** skip analysis and bulk-reply "Fixed in subsequent
commits"; that is the shallow dismissal Phase 3 exists to prevent.

- **Card:** an outdated comment still shows its **historical `diff_hunk`** as a ` ```diff `
  block (GitHub keeps `diff_hunk` even when outdated), the header carries the **⚠️ outdated**
  marker, and the take should note "line moved/removed in current code". The code is still shown.
- **Analysis:** run each outdated thread through the Phase 3 `outdated_fixed` path: the verdict
  must cite EVIDENCE (file:line in the current code) that actually fixes the concern. Only
  threads that clear that bar reply "Fixed in subsequent commits"; the rest are analyzed and
  triaged like any other comment — they may still be valid.

```
3 comments are marked outdated. Verifying each against current code before triaging…
```

### Summary / General Item (no position)

A `(summary)`/general item has no anchored line, so its **card has no code block** — header
shows `(summary)`, and it carries the full text + take only. It is still triageable (including
**follow-up**). Reply targets differ:

- **GitHub:** a summary item comes from the review body, so `comment_id == null` — there is **no
  reply target**. Record its decision in the 5.8 summary report; do **not** attempt a reply. (A
  follow-up task is still created if chosen.)
- **GitLab:** a summary/general item still has a `discussion_id`, so reply to it normally.

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

- Treat as outdated; the card has **no reconstructed snippet** (nothing to read). GitHub may
  still carry the historical `diff_hunk` — show it. GitLab degrades to no code block.
- Verdict: `outdated_fixed` with note "file was removed"
- Reply: "Fixed in subsequent commits (file removed)"

### GitLab Thin / Absent Snippet

GitLab has no `diff_hunk`; the snippet is reconstructed from the current file (Phase 2). If that
read yields nothing usable (moved/renamed file, `new_line` out of range), **render the card
without a code block** and note the `position` in the take — **degrade, don't fail**. The card
still shows source + full text + take.

### Very Large Number of Comments (large-PR cap)

The pre-analysis gate exists **only** for large PRs (see Phase 3). If there are **more than ~20**
non-replied comments:

1. Show the full TABLE.
2. Ask, in plain text: "{N} comments — analyze all, or select a subset? (all / <refs>)".
3. If the user selects a subset, analyze and triage only those.

Below the threshold, analyze **all** and go straight to card-by-card triage — no gate.

## The Bottom Line

**Show the code on every card. Analyze before acting. Cite code to dismiss. Fix the class. Skeptic pass before push.**

Every comment gets a card with its anchored code (`diff_hunk`/`snippet`), full text, and take — emitted **UNWRAPPED** (never inside an outer ``` fence, or the rendering breaks). The user triages each: **fix / won't-fix / follow-up**. Execution is batched at the end; follow-up files a beads task.

To dismiss a comment, restate its specific claim and cite the exact code that moots it — a related mechanism existing is not enough, and a thread reply is a claim to verify, not evidence. If you can't prove it moot, agree (as `agree_obvious`/`agree_unclear`).

Fix the class, not the instance: enumerate siblings and apply with confirmed scope. On any correctness/logic/security round, run the pre-push self-review — it catches the shifted bug before the next reviewer does.

Nitpicks deserve extra scrutiny — if it doesn't improve readability, correctness, or maintainability, argue against it.

Never auto-apply. Never skip the card. Never push without asking.
