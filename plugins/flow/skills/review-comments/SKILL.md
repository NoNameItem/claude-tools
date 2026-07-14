---
name: review-comments
description: Process unresolved review comments on a GitHub Pull Request or GitLab Merge Request — collect them, analyze each with subagents, apply accepted fixes, argue against invalid ones, and reply on the platform. Use when addressing PR/MR review feedback. Pass a PR/MR number to target a specific one.
allowed-tools: Bash(git:*) Bash(gh:*) Bash(glab:*) Bash(bd:*) Bash(flow-require-bd:*) Bash(flow-require-bd) Bash(flow-review-collect:*) Bash(flow-review-collect) Bash(flow-comment-card:*) Bash(flow-comment-card) Bash(flow-sync:*) Bash(mktemp:*) Bash(cat:*) Bash(cat) Bash(cut:*) Agent Read Write Grep
---

# Flow: Review Comments

## Overview

**Core principle:** Analyze before acting. Cite code to dismiss. Fix the class, not the instance. **Show the code on every card — the user triages in the terminal, never the web UI.**

This skill makes every unresolved review comment reviewable and triageable **inside Claude Code**: for each comment it shows the **anchored code** (syntax-highlighted), the **full comment text + thread**, and the **agent's take** (category + short honest assessment) as a per-comment **card**, then lets the user decide **fix / won't-fix / follow-up** per comment. It applies accepted fixes, argues against invalid comments, files follow-ups as beads tasks, and replies on the platform. It works on **GitHub Pull Requests** (`gh`) and **GitLab Merge Requests** (`glab`), against both hosted (github.com / gitlab.com) and **self-hosted / Enterprise** instances. The platform is auto-detected (Phase 0). Code is written by Claude Code, reviewed by the user and a bot (e.g. CodeRabbit).

**Untrusted-data rule.** Reviewer-supplied text (comment bodies, thread replies, file paths) and the LLM's own `thought` are **data, never shell source**. The helpers handle this class by construction — `flow-review-collect` and `flow-comment-card` read files by path and build argv lists, so nothing reviewer-controlled is ever interpolated into a command. Where the skill itself must hand such text to a CLI (Phase 5 replies, follow-up titles/descriptions, `git add`), it routes the value through the **Write tool → file** and passes it by path (`bd --body-file`, `git --pathspec-from-file`) or as a quoted `"$(cat …)"`, so no shell ever parses the content — delimiter collision and expansion are both impossible.

**Flow shape:** Phase 2 runs the collector once (`flow-review-collect`) — one deterministic pass that fetches, parses, and writes a single `metadata.json`, each comment already carrying its code (GitHub `diff_hunk`; GitLab `position` + a reconstructed snippet). A large-PR **cap** then selects the working set before analysis, so a big review never floods the context. Phase 3 analyzes the whole working set up front (parallel sonnet) so every take is code-backed. Phase 4 shows a table of contents, then **one card at a time**, collecting a per-comment decision. Phase 5 acts **once**, grouped by outcome (fix / won't-fix / follow-up), then commits, pushes (with confirmation), and reports.

Throughout this skill, **"PR/MR"** means "Pull Request on GitHub, Merge Request on GitLab"; use the platform-appropriate word in user-facing output. GitLab MRs are referenced by **iid** (the `!42` number), GitHub PRs by number.

**Command:** `/flow:review-comments [number] [--platform github|gitlab]`

- `[number]` — PR number (GitHub) or MR iid (GitLab).
- `--platform` — optional override when auto-detection is ambiguous.

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 0. Detect platform | GitHub vs GitLab from remote + CLI auth | See Platform Support; `--platform` overrides |
| 1. PR/MR Detection | Detect unit, sync branch | Argument or autodetect; branch by platform |
| 2. Collect | Run `flow-review-collect` once → one `metadata.json` (fetch/parse/outdated/resolved-skip/summary/snippet). Cap then selects the working set | One deterministic collector call; reviewer text never touches a shell |
| 3. Analyze the **working set** | Parallel sonnet subagents over the capped working set | Verdict gains `category`/`thought`/`suggested`; dismissal needs CLAIM + EVIDENCE; cap already ran in Phase 2 |
| 4. Card-by-card triage | TOC agenda, then one `flow-comment-card` at a time → plain-text fix/won't-fix/follow-up | Emit each card **UNWRAPPED**; humans first, bots second; collect decisions |
| 5. Batch act | fix (generalize → apply → self-review) / won't-fix / follow-up → commit → push → reply | Fix the class; skeptic pass before push; a `Fixed:` reply only after the push; follow-up = a beads task |

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
| Fetch / threads / outdated / resolved-skip / bot-summary / authenticated user | handled by the collector (`flow-review-collect`) — see the Phase 2 `metadata.json` schema | same collector, same schema (GitLab `discussions` endpoint, `position`/`new_line`, `system`-note skip) |
| Reply | `gh api repos/{o}/{r}/pulls/{n}/comments/{comment_id}/replies -f body=…` | `glab api --method POST "projects/{id}/merge_requests/{iid}/discussions/{discussion_id}/notes" --raw-field body=…` — keyed by **`discussion_id`, not comment id** |

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
  - Mismatch: check out the PR/MR branch. On GitHub the branch name is **PR-author-controlled** and may
    contain shell metacharacters (`git check-ref-format --branch 'foo$(id)'` succeeds), so bind it to a
    variable and reference it **quoted** — never paste the raw name into `git checkout` (a quoted variable
    expansion is not re-scanned for `$()`/backticks, so this stays injection-safe even for a hostile name):
    ```bash
    branch="$(gh pr view --json headRefName -q .headRefName)"   # GitHub
    git checkout "$branch"                                       # GitLab: glab mr checkout <iid>
    ```

#### 1.3. Sync with remote

In all cases after PR/MR detection, sync with the remote. The branch is PR-author-controlled, so the raw
form `git pull origin <branch>` would run an embedded `$()`/backtick before git saw the ref — bind the
branch to a variable and reference it **quoted** (same rule as 1.2 and 5.7):

```bash
branch="$(gh pr view --json headRefName -q .headRefName)"   # GitHub — GitLab: glab mr view <iid> --output json --jq .source_branch
git pull origin "$branch"
```

### Phase 2: Collect Comments

Run the collector once — it does all fetch/parse/outdated/resolved-skip/summary/snippet work
deterministically and writes one JSON document. Reviewer-supplied values never touch a shell
(the collector uses argv lists and reads files by path), so the whole untrusted-data class is
handled in tested code, not prose.

```bash
FLOW_RC_DIR="$(mktemp -d)"
# Baseline: paths already dirty BEFORE this run (nothing has mutated the tree yet). 5.5 refuses
# path-level staging when an applied file overlaps this set — that is what stops a pre-existing
# unrelated edit from being swept into a "Fixed:" commit. `-uall` lists individual untracked files:
# without it an untracked file inside an untracked dir collapses to the dir name (baseline records
# `generated/`, not `generated/out.py`), so 5.5's exact-path overlap check would miss the pre-existing
# file and sweep it into the commit.
git status --porcelain -uall | cut -c4- > "$FLOW_RC_DIR/baseline-dirty.txt"
flow-review-collect {number-if-any} --platform {PLATFORM} > "$FLOW_RC_DIR/metadata.json"
```

Pass the Phase-0 `{PLATFORM}` explicitly so the collector honors an override / interactive
disambiguation instead of re-detecting from scratch (its own detection would drop a `--platform`
override on an ambiguous host — exactly the case the override exists for).

`metadata.json` schema: `{platform, unit:{number,branch,url}, me, counts:{total,already_replied,
actionable}, comments:[…]}`. Each `comments[]` item carries `ref` (humans `U1…`, bots `C1…`),
`user`, `is_bot`, `path`, `start_line`, `line`, `outdated`, `already_replied`, `comment_id` /
`discussion_id` / `summary_id`, `body`, `thread`, `diff_hunk`, `position`, and `snippet`
(reconstructed for GitLab notes and thin/absent GitHub hunks; `null` otherwise).

Read `counts` from the JSON:
- `counts.actionable == 0` → report ("{already_replied} already replied, nothing to act on") and stop.
- Otherwise the **working set** is every item with `already_replied == false`.

**Large-PR cap (the only pre-analysis gate).** If `counts.actionable` > ~20, print a **category-free
selection table** built straight from `metadata.json` — every column below exists **before** any
analysis — and ask, in **plain text** (a structured dialog auto-submits on the AFK timeout —
claude-tools-6q4):

```
| ref | source | path:lines   | ⚠️ | brief                          |
|-----|--------|--------------|----|--------------------------------|
| U1  | human  | config.py:15 |    | Missing type annotation        |
| C1  | bot    | git.py:42    |    | Crashes on detached HEAD       |
| C3  | bot    | utils.py:10  | ⚠️ | Unused import                  |
```

`source` = `is_bot` (human / bot); `path:lines` from `path` + `start_line`-`line` (or `(summary)`);
`⚠️` = `outdated`; `brief` = the truncated `body`. Do **not** add a `category` column here — that
field is a Phase 3 verdict and does not exist yet; the categorized agenda is the Phase 4.1 TOC,
printed **after** analysis.

```
{actionable} comments — analyze all, or select a subset? (all / <comma-separated refs>)
```

- `all` → working set = all actionable items.
- refs (e.g. "U1, U3, C2") → working set = only those.

At ≤ ~20 there is no prompt — the working set is all actionable items. Carry the working set as its
list of `ref`s; every later phase looks each ref up in `metadata.json`.

### Phase 3: Analyze the Working Set (Parallel Sonnet Subagents)

Analyze **every** comment in the working set selected in Phase 2 — the large-PR cap already
selected that set, so there is **no** further "process all? yes/select/no" gate here. The
per-comment card (Phase 4) is the decision surface, and its take must be a real, code-backed
assessment; a take written without reading the code is exactly the shallow dismissal this skill
fights. (Below the ~20 cap the working set is simply all actionable comments.)

For each comment to analyze (or group of comments in the same file with overlapping line
ranges), launch a **sonnet subagent**. Analysis is where a shallow read does the most damage —
a misdiagnosed dismissal costs a full rework round — so it runs on **sonnet**, not haiku.

**Grouping rule:** Comments in the same file where line ranges overlap or are within 10 lines of each other → single subagent. This avoids reading the same file section multiple times.

**Subagent:** `subagent_type="Bash"`, `model="sonnet"`

**Subagent prompt (per comment/group):**

````
Analyze this PR/MR review comment and return a structured verdict.

Read comment `{ref}` from the collector output at `{FLOW_RC_DIR}/metadata.json` — its `body`,
`thread`, `diff_hunk`, `snippet`, `path`, and `line`/`start_line`. (For a grouped call, read every
listed ref.) The collector already reconstructed `snippet` wherever the reviewer `diff_hunk` was
thin or absent, so you neither build nor fence one.

Comment ref: {ref} (by {user})
File: {path}
Lines: {start_line}-{line} (just {line} if no start_line; "(none)" for a summary / file-level comment where both are null)
Outdated: {yes/no}

Steps:
1. **Locate the code to read — branch on whether the comment anchors to a line:**
   - **`path == "(summary)"` or `path` is null** (a review-body summary / general discussion): there is
     **no** file line to read — do **not** call Read on `(summary)`. Triage from the comment `body` and
     `thread`; if the body names specific files/paths, Read those for context, otherwise assess the body
     directly.
   - **`path` is a real file but `line` is null** (a GitHub file-level comment — `subject_type: file`,
     both `line` and `original_line` null): Read the file's **header / top region** (`offset = 1`, a
     bounded `limit` such as 60) and assess the file-level concern; do **not** compute a window around a
     non-existent line. (No collector change is needed — `attach_snippet` already yields `snippet == null`
     for these; this branch is what makes them analyzable.)
   - **`path` is set but the file no longer exists on disk** (the `Read` of `{path}` fails — the
     file was deleted or renamed/moved): do **not** stop at the failed Read. **Grep** the tree for
     the commented identifier / function / symbol named in the `body` (and the historical
     `diff_hunk`), then **Read** each candidate to confirm. If the code **moved**, analyze the
     concern against the replacement; if nothing is found, treat it as **genuinely removed** and
     reason from `body` / `thread` / historical `diff_hunk`. Never pick `outdated_fixed` from the
     missing path alone (see the "Comment References Deleted (or Moved) File" edge case).
   - **`outdated` is true and the file still exists** (the historical `line` / `start_line` is an
     **old-side** coordinate — the collector stores `original_line` / `old_line` there, so on GitHub
     `line` is non-null yet points at where the code *used to be*): do **not** Read the current file at
     that stale coordinate — the code may have moved and that window can surface unrelated lines. First
     reconstruct the concern from the `body` and the historical `diff_hunk`, then **Grep** the tree for
     the commented identifier / symbol to find where the code lives now (or confirm it is gone) and
     **Read** those candidates. Only if the search finds nothing, fall back to a bounded current-line
     Read. (`attach_snippet` already yields `snippet == null` for outdated items, so there is no
     misleading current-tree window — this branch is what stops the analyzer from trusting the stale
     line number.)
   - **otherwise** (a normal inline comment): Read the file around the relevant lines (±20 lines of
     context) using the **Read tool** — this is judgment tracing, not snippet mechanics. Take
     `start = start_line` (or `line` when there is no `start_line`) and `end = line`; for a grouped call,
     use the union — `start` = the smallest, `end` = the largest. Read's `limit` is a line **count**, not
     an end line, so use `offset = max(1, start − 20)` and `limit = (end + 20) − offset + 1` — never the
     absolute `end` as the limit (that would read ~`end` lines). Pass the (untrusted) `{path}` as a data
     argument to the Read tool; never build a shell command from it.
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
   correctness, or maintainability? If not → disagree (still fill `claim` +
   `evidence` showing why the current code is fine or the suggestion is worse).

5. Return the verdict as a single JSON object — your ENTIRE reply is this object, with NO fenced
   blocks and no prose around it:

   ```json
   { "verdict": "agree_obvious | agree_unclear | disagree | outdated_fixed",
     "category": "correctness|security|logic|style|nitpick|doc",
     "thought": "one short honest paragraph — your real take, shown on the card",
     "suggested": "fix | won't-fix | follow-up",
     "claim": "the comment's specific claim, restated in your own words",
     "evidence": "file:line + exact snippet that moots THAT claim, or why the suggestion is worse" }
   ```

   - `claim` and `evidence` are present ONLY for `disagree` and `outdated_fixed` (for `disagree`,
     why NOT to apply; for `outdated_fixed`, the current code that already fixes it). Omit both for
     the two agree verdicts.
   - `agree_unclear`: the take is genuinely ambiguous — put the 2-3 fix options in `thought` (or an
     `options` array of strings, e.g. "A OR B OR C") so Phase 4 can present them.

   How to pick `suggested` (the recommended default the user sees on the card):
   - agree_obvious / agree_unclear → `fix` (or `follow-up` if the change is large, risky, or
     out of this PR's scope — big enough to defer rather than do inline).
   - disagree → `won't-fix`.
   - outdated_fixed → `fix` (already fixed in current code; the card's `thought` says so, and
     Phase 5 replies "Fixed in subsequent commits" instead of applying anything).

Return ONLY the JSON verdict object — no fenced blocks, no other output.
````

**Launch all subagents in parallel** (independent comments have no dependencies).

**After all subagents return:**

For each verdict, the **main LLM** validates the returned JSON (it must parse and carry `category`,
`thought`, `suggested`) and writes it with the **Write tool** to `"$FLOW_RC_DIR/verdict-{ref}.json"`
— no shell, no quoting, so a reviewer's text or the LLM's own `thought` never reaches a command line.

For `disagree` / `outdated_fixed`, the `claim` and `evidence` are load-bearing — a dismissal is only
as good as the code it cites. **If an `evidence` value does not cite code that addresses the specific
`claim` (it just names a related mechanism, or restates the author's assertion), treat it as a
shallow dismissal: re-analyze it, landing on `agree_obvious`/`agree_unclear`.** The
`category`/`thought`/`suggested` fields feed the Phase 4 card (assembled by `flow-comment-card
--meta/--verdict`); the collector-attached `snippet` already lives in `metadata.json`, so Phase 3
writes no snippet. Do **not** print a grouped-by-type verdict dump here; the verdicts are surfaced
one card at a time in Phase 4.

A JSON verdict written to a file removes the three Phase-3 bug classes at once — no fenced snippet to
collide, no jq/heredoc to inject through, no snippet offset/limit to miscompute — because the
collector owns the card snippet and `flow-comment-card` reads `--meta`/`--verdict` by path in Phase
4.2. (The subagent's own ±20-line judgment-tracing Read still uses `offset`/`limit`; that is code
tracing, not snippet mechanics.)

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

For each comment (in TOC order), render its card by pointing `flow-comment-card` at the two files —
no shell-assembled JSON, no jq:

```bash
flow-comment-card --meta "$FLOW_RC_DIR/metadata.json" --ref C1 --verdict "$FLOW_RC_DIR/verdict-C1.json"
```

The helper reads the `comments[]` item for that `ref` from `metadata.json`, merges the verdict's
`category`/`thought`/`suggested` from `verdict-{ref}.json`, and applies the snippet↔diff_hunk
override (a collector-attached `snippet` — present exactly when the GitHub `diff_hunk` was thin or
absent, and always on GitLab — wins, and `diff_hunk` is dropped; otherwise the `diff_hunk` shows).
Both arguments are **file paths**, so no reviewer `body`/`thread` and no LLM `thought` is ever
assembled into a shell command (untrusted-data rule).

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
  (read them from the verdict JSON's `thought`, or its `options` array when present) and let the
  user pick which fix (or skip) **before** moving to the next card. If the user picks a fix option,
  record it with the `fix` decision; if the user picks "skip", record the decision as `skip`
  (invariant 3), not `fix`.
- **disagree → fix (accept-anyway):** a `disagree` verdict carries only CLAIM / EVIDENCE / THOUGHT —
  it explains why NOT to apply, so it has **no fix action**. If the user overrides it to `fix`, Phase
  5.1 would otherwise call the apply flow with an empty patch plan. Before recording the `fix`
  decision, ask — plain text — WHAT the accept-anyway change should be, and record that concrete
  action alongside the decision (Phase 5.1 uses it as the fix description). Never carry a `disagree`
  into apply without a patch plan.

Record `{ref → decision}` (and the chosen option for `agree_unclear`, or the accept-anyway action
for an overridden `disagree`), then show the next card.

**Decision invariants (verdict ≠ decision ≠ reply source).** The verdict is the analysis; the
decision is the user's choice (`fix` / `won't-fix` / `follow-up` / `skip`); the reply text has its
own source. Record per decision:

1. `fix` ⇒ a concrete **action** exists: `agree_obvious` → the verdict one-liner; `agree_unclear` →
   the option the user picked; `disagree` → the accept-anyway action collected above. Never enter
   apply without one.
2. `won't-fix` ⇒ a **rejection reason** exists. Reuse the card's `thought` as that reason ONLY when
   the verdict was `disagree` (there the thought is already anti-fix). For any other verdict
   overridden to `won't-fix`, ask — plain text — for an explicit reason and record THAT.
3. `skip` ⇒ its own outcome: no apply, no reply, recorded skipped. An `agree_unclear` where the user
   picks "skip" is recorded as `skip`, not `fix`.
4. `follow-up` ⇒ a **task-id must exist** before 5.7 posts "Filed as follow-up: {task-id}". If 5.4 is
   answered `edit`/`no` and a ref gets no task, record that ref as skipped and post no follow-up reply.

| verdict → decision (override) | extra data to record at triage |
|---|---|
| `disagree` → `fix` | accept-anyway action |
| `agree_*` → `won't-fix` | explicit rejection reason (thought is pro-fix) |
| `agree_unclear` → `skip` | none — record outcome = skip |
| any → `follow-up`, task not created | record outcome = skip; no reply |

Do **not** apply, reply, or commit during the loop.

### Phase 5: Batch Execution

The Phase 4 decisions are now executed **once**, grouped by outcome. Order matters: apply all
fixes first, run the skeptic, create follow-ups, then **commit and push** — and only **then reply**
to every comment, so a `Fixed:` reply never claims a change the remote does not yet have
(**commit/push are skipped when no files changed** — 5.5). This preserves fix-the-class, a single
skeptic pass, and one commit/push — the reason triage and execution are split.

#### 5.1. Fix — generalize the class (fix the class, not the instance)

Take the comments the user decided **`fix`** on in Phase 4 (this includes an `agree_unclear`
whose option was chosen, and an accepted `disagree` the user overrode to `fix`). An
`outdated_fixed` comment the user kept as `fix` has **nothing to apply** — it is already fixed
in current code; skip it here — its "Fixed in subsequent commits" reply is handled in 5.7, which gates it on the fix being on the remote. **Before
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

`CLASS` is deliberately a separate field from the Phase 3 verdict `CATEGORY` —
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

Record the confirmed sites for 5.2 and the CLASS name for the 5.7 reply.

**Record `APPLIED_FILES`** — the exact set of paths the apply subagents **created, modified, deleted,
or renamed** (5.1/5.2 already operate on "specific files"). Include a **deleted** path and, for a
**rename**, **both** the old and the new path: 5.5 stages exactly this set, and `git add <path>`
stages a deletion as well as a change, so a delete-only fix that omitted the removed path would skip
the commit entirely, and a rename that omitted the old path would commit the new file while leaving
the old one dangling — both while the run still reports the comment fixed. This set, not the git
working tree, is the authoritative signal of whether this run changed anything; 5.5 gates on it.

#### 5.2. Apply Changes

Group accepted fixes by file. For each file (or group of related files), launch a **haiku subagent**:

**Subagent:** `subagent_type="Bash"`, `model="haiku"`

**Subagent prompt:**

```
Apply these fixes to {path}:

{list of fixes with line numbers and descriptions}

Return: "OK" if all applied successfully, or describe what failed.
```

After all file subagents complete, run the **project's configured formatter/linter** on the changed
files, in the main context — **only if the project defines one**. This skill is language- and
tool-agnostic: it does **not** assume Python, `ruff`, `uv`, or any specific toolchain. What to run is
the project's concern, documented for the agent in the repo (e.g. its `CLAUDE.md` / `AGENTS.md` /
contributing guide — a `pre-commit run` on the changed files, a lint/format script, or a language
toolchain). If the repo documents such a command, run it on the changed files and fix what it
reports; if it documents none, skip this step and rely on the project's commit hooks / CI. Never
hard-code a formatter here.

After the apply subagents return, prune `APPLIED_FILES` to the files they actually reported as changed
(drop any whose apply failed), so a failed apply leaves no phantom path for 5.5 to stage.

**A failed apply also demotes its decision.** A ref keeps its `fix` decision (→ a `Fixed: …` reply
in 5.7) **only if the apply subagent reported `OK` for every file that ref's fix touches** — a
generalized fix spans several files/sites, and 5.2 applies per file, so one ref can be part-applied.
If **any** of a ref's files failed, change that ref's Phase 4 decision from `fix` to `skip` (a
*failed apply*): Phase 5.7 posts `Fixed: …` for **every** pushed `fix` ref, so a ref left as `fix` after a
failed/partial apply would be reported fixed with nothing (or only part) behind it. A demoted ref
gets **no** `Fixed:` reply and appears on the 5.8 `Failed:` line. The files that *did* apply cleanly
stay in `APPLIED_FILES` and are still committed — they are real improvements and the commit records
exactly them — but the comment is not reported fixed, and the human finishes it next round from the
`Failed:` line. Never claim a fix that was not fully applied.

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
  per-item accept/skip). Apply each item the user accepts via a 5.2 apply subagent, **add every
  path the addendum created, modified, deleted, or renamed to `APPLIED_FILES`** (both the old and new
  path for a rename — same rule as the 5.1 definition; 5.5 stages exactly that set — an addendum path
  left out would be verified and replied to but never committed/pushed), then re-run
  the Phase 5.2 project format/lint step (if the project configures one) on the changed files so the
  addendum code is checked too. Do **not** re-run the skeptic — a single pass, then proceed.

Runs **before** the commit (5.5) so the code that is committed, pushed, and later described by the replies is already final.

#### 5.4. Follow-up — create beads tasks

For each comment the user decided **`follow-up`** on, create a beads task so the deferred work
is tracked, then reply "Filed as follow-up: {task-id}" in 5.7.

**First — guard bd (before any `bd create`).** Follow-up creation is the only bd-using path in this
skill, so run the version guard here, once, at the START of the batch:

```bash
flow-require-bd
```

If it exits non-zero, **STOP the follow-up batch**: print its stderr message, create **no** tasks,
and **record every `follow-up` ref as `skip` (invariant 4)** so Phase 5.7 does not post a
"Filed as follow-up" reply for a ref that has no `{task-id}` (flow requires `bd >= 1.0.0` — see
`plugins/flow/README.md`, "bd requirements and migration"). Keep it in its own block so a failed
guard cannot fall through to `bd create`. The fix / won't-fix paths need no bd; only the follow-up
path is blocked.

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

- **edit** → adjust the batch (drop/retarget refs) per the user, then re-confirm. Any ref removed
  from the batch is recorded as `skip` (invariant 3/4) — it gets no task and no follow-up reply.
- **no** → create nothing; record every ref in the batch as `skip`.

On **yes**, create them **sequentially** (embedded Dolt is single-writer — do NOT parallelize
`bd create`). **Both the title and the description derive from the reviewer's comment** (the title
from its substance — see above), and that text is **untrusted** (untrusted-data rule) — it routinely
contains backticks, `$HOME`, `$(...)`, or even a line that is exactly a heredoc delimiter. **Never
build the title or description from a shell heredoc or an unquoted argument:** a quoted heredoc stops
`$`/backtick expansion, but a reviewer comment containing a line equal to the delimiter still closes it
early and silently truncates the task body (this repo's own review comments contain the literal
`FLOW_RC_EOF`, so this is not hypothetical).

**Materialize each free-text value with the Write tool, then pass it by file** — the Write tool takes
the content as a tool argument that no shell ever parses, so delimiter collision and expansion are both
impossible. Write the title to `$FLOW_RC_DIR/title-{ref}.txt` and the full description (PR/MR URL,
`path:lines`, the reviewer's comment text read from `metadata.json`, and the agent's take) to
`$FLOW_RC_DIR/desc-{ref}.md`, then:

```bash
bd create --title "$(cat "$FLOW_RC_DIR/title-C3.txt")" --type bug --priority 2 \
  --parent claude-tools-5dl --body-file "$FLOW_RC_DIR/desc-C3.md"
```

`--body-file <path>` reads the description straight from the file — its content is never shell-parsed.
The title has no file flag, so pass it as `"$(cat …)"`: a **quoted** command substitution captures the
file's bytes as a single argument with no re-parsing, so backticks / `$` / a `FLOW_RC_EOF` line reach
`bd` verbatim.

After creating all follow-ups, **persist to the shared beads store**:

```bash
flow-sync push
```

Record `{ref → task-id}` for the 5.7 reply and the 5.8 summary line.

#### 5.5. Commit

**First, gate on whether the apply phase changed anything.** If `APPLIED_FILES` (Phase 5.1) is
**empty** — the fix bucket was empty or held only `outdated_fixed` / won't-fix / follow-up / skip
decisions — there is nothing to commit. Skip **both** this step and the push (5.6) and go straight to
the reply step (5.7): `Won't fix:` and `Filed as follow-up:` assert **no** change landed this run, so
they do not depend on a push. `Fixed in subsequent commits` is **not** unconditional here — it still
passes the 5.7 branch-not-ahead gate (`git rev-list --count "origin/$branch..HEAD"`); skipping 5.5/5.6
does not skip that check, which lives in 5.7. Gate on the
apply-set, NOT the git working tree: `git status --porcelain` over-includes unrelated pre-existing
edits, while a tracked-diff check (`git diff`) drops a fix that only creates a new untracked file — the
apply-set has neither failure. Otherwise, stage exactly `APPLIED_FILES`:

**Guard against sweeping in pre-existing edits (before staging).** `git add <path>` stages the **whole
file**, not just this run's hunks. If a file in `APPLIED_FILES` also has edits that pre-date this run,
staging its path would commit those unrelated changes under a `Fixed:` message. Compare `APPLIED_FILES`
against the pre-run dirty set captured in Phase 2 (`$FLOW_RC_DIR/baseline-dirty.txt`): if they
**overlap**, **STOP** — do not stage, commit, or push — and report, in plain text:

```
⚠️ These files had uncommitted changes before this run: {overlap}.
Staging them would sweep unrelated edits into a "Fixed:" commit.
Commit or stash those changes, then re-run /flow:review-comments.
```

A dirty file that is **not** in `APPLIED_FILES` is fine and must not block the run — only the overlap is
the hazard. No overlap → each applied file's only diff is this run's fix, so path-level staging is safe.

Stage exactly the applied set. `APPLIED_FILES` holds PR file paths (reviewer-controlled) → feed them
to git as **data, never as shell words** (untrusted-data rule): inlined into shell source a path
like `x$(cmd).py` would run `cmd`, and a path with spaces would word-split, before `git add` saw it.
**Write the applied paths (one per line, verbatim) to `$FLOW_RC_DIR/applied-files.txt` with the Write
tool** — no shell parses them — then feed that file to git. `--literal-pathspecs` makes git treat every
line as a **literal path**, not a pathspec, so a reviewer-controlled file named `:(glob)*.py` or one
with leading `:` magic cannot expand the staged set beyond the exact files the apply phase changed:

```bash
git --literal-pathspecs add --pathspec-from-file="$FLOW_RC_DIR/applied-files.txt"
```

Commit message follows CLAUDE.md scope rules:

- Changes in `plugins/flow/` → `fix(flow): address PR review feedback`
- Changes in `packages/statuskit/` → `fix(statuskit): address PR review feedback`
- Changes across scopes → separate commits per scope (single-package-commit hook enforces this)

**Commit only the applied paths — never the whole index.** A bare `git commit` commits **everything**
staged, so any change the user had **already staged before this run** (a file outside `APPLIED_FILES`)
gets swept into the `Fixed:` commit. Commit the applied set explicitly with `--only`, which commits
those paths' content and **disregards anything else in the index** (leaving the user's pre-staged work
untouched, still staged):

```bash
git --literal-pathspecs commit --only --pathspec-from-file="$FLOW_RC_DIR/applied-files.txt" \
  -m "fix(flow): address PR review feedback"
```

For the across-scopes case, run one such `--only` commit per scope, each fed a per-scope
`applied-files-{scope}.txt`, so every commit carries only its own files.

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

**The reply step (5.7) gates on this outcome.** A `Fixed: …` reply claims the change is on the remote, so it may go out **only after a successful push**. If the user selects **Skip** (or the push fails), the commit stays local: **withhold every `Fixed: …` reply** and report those refs on the 5.8 `Reply deferred (push skipped)` line — a later push (then re-run) posts them once the fix is actually on the remote. The non-fix replies (`Won't fix:` / `Filed as follow-up:`) still post in 5.7; `Fixed in subsequent commits` posts only when the branch is not ahead of the remote (5.7 gates it).

#### 5.7. Reply on the platform

Post replies **after** the push (5.6) so each reply reflects the remote's actual state. For each comment with a `fix` / `won't-fix` / `follow-up` decision — comments recorded as `skip` get no reply (invariant 3); omit them from this loop — post a reply into its thread. Execute **sequentially** (avoid rate limiting). Use the metadata's `platform` to pick the command:

**Gate `Fixed:` replies on the push (5.6).** A `Fixed: {change}` reply (including the generalized form) asserts the change is **landed on the remote** — post it **only if the 5.6 push succeeded**. If the push was **skipped or failed**, post **no** `Fixed:` reply for a fix applied this run; carry those refs to the 5.8 `Reply deferred` line.

**`Fixed in subsequent commits` (the `outdated_fixed` case) also asserts the fix is on the remote** — it claims an *earlier* commit already fixed the issue, which reviewers can only see if that commit is on `origin/{branch}`. Do **not** assume it: Phase 1 only *pulled*, so local commits can sit ahead of origin unpushed. **Verify the branch is not ahead of the remote** before posting.

**Bind the branch to a variable and reference it quoted — never paste the raw name into the command.** Git ref names may contain shell metacharacters (`git check-ref-format --branch 'foo$(id)'` succeeds) and the branch is PR-author-controlled, so the raw form `origin/{branch}..HEAD` would run the substitution before `git` sees the ref. A quoted variable expansion is not re-scanned for `$()`/backticks, so this stays injection-safe even for a hostile branch name:

```bash
branch="$(gh pr view --json headRefName -q .headRefName)"   # GitHub — GitLab: glab mr view {iid} --output json --jq .source_branch
git rev-list --count "origin/$branch..HEAD"   # 0 → branch not ahead; the fix is on the remote
```

Count **0** → post `Fixed in subsequent commits`. **Non-zero** → the fixing commit may be local-only and invisible to reviewers: treat it exactly like a skipped push — **withhold the reply** and carry the ref to the 5.8 `Reply deferred (push skipped)` line until a push makes the fix visible.

Replies that assert **no** change landed this run post regardless of the push: `Won't fix:` (nothing was changed) and `Filed as follow-up:` (work is only tracked).

For each reply, **write the body to `$FLOW_RC_DIR/reply-{ref}.txt` with the Write tool first**, then pass
it as a **quoted** command substitution `"$(cat …)"` — which captures the file's bytes as a single
argument with no shell re-parsing, so a `Won't fix:` rationale that quotes reviewer text (backticks, `$`,
or a `FLOW_RC_EOF` line) reaches the API verbatim and cannot truncate or break out.

**GitHub** (reply addressed by `comment_id`):

```bash
gh api repos/{owner}/{repo}/pulls/{number}/comments/{comment_id}/replies \
  -f body="$(cat "$FLOW_RC_DIR/reply-C1.txt")"
```

**GitLab** (reply addressed by `discussion_id`, NOT a comment id — a new note in the discussion):

```bash
glab api --method POST \
  "projects/{project}/merge_requests/{iid}/discussions/{discussion_id}/notes" \
  --raw-field body="$(cat "$FLOW_RC_DIR/reply-C1.txt")"
```

**Reply format by decision** (identical on both platforms):

| Decision (from Phase 4) | Reply |
|-------------------------|-------|
| fix (change applied, pushed) | `"Fixed: {brief description of what was changed}"` |
| fix, generalized (pushed) | `"Fixed: {change}; applied across the class ({class}) at {N} sites."` |
| fix, but `outdated_fixed` (already fixed in current code, nothing applied) | `"Fixed in subsequent commits"` |
| won't-fix | `"Won't fix: {reasoning}"` — the reasoning is the **recorded rejection reason** (= the card's `thought` only when the verdict was `disagree`; otherwise the explicit reason collected at triage, invariant 2) |
| follow-up | `"Filed as follow-up: {task-id}"` (the beads task from 5.4) |

**Do NOT reply to comments where `already_replied` is true.**

**Multi-line or special-character bodies** (a long "Won't fix: …" rationale, or text with backticks /
`$` / quotes, including quoted reviewer text) need no special handling — the Write-tool-to-file +
`"$(cat …)"` pattern above already carries them verbatim on both platforms. **Never** assemble a reply
body from a shell heredoc: a reviewer line equal to the delimiter would truncate it (the same failure
as 5.4).

**Summary / general items:**
- **GitHub:** a `(summary)` item has `comment_id == null` (it comes from the review body, not an inline thread) — there is no inline reply target. Record its decision in the 5.8 summary report; do NOT attempt a reply. (A follow-up filed from a GitHub summary item is still created — only the reply is skipped.)
- **GitLab:** a `(summary)` / general item still has a `discussion_id`, so reply to it normally with the GitLab command.

#### 5.8. Summary Report

```
Processed: {total} comments
  Fixed: {count} ({list of refs})
  Generalized: {count} ({ref → class → N sites}, if any)
  Won't fix: {count} ({list of refs with brief reason})
  Already fixed: {count} ({list of refs})
  Follow-ups created: {count} ({ref → task-id})
  Skipped: {count} ({list of refs skipped})
  Failed: {count} ({list of refs whose apply failed — demoted from fix in 5.2, not reported fixed})
  Reply deferred (push skipped): {count} ({fix refs whose `Fixed:` reply was withheld because 5.6 was skipped/failed, plus `outdated_fixed` refs whose `Fixed in subsequent commits` was withheld because the branch is ahead of the remote})
Self-review: {ran / skipped (nitpick round)}; {N} extra fixes applied
```

## Scope Boundaries

### This Skill DOES:
- Detect the platform (GitHub / GitLab), then the PR/MR from current branch or argument
- Sync branch with remote
- Collect all unresolved inline comments and review summaries with the `flow-review-collect` collector (one `metadata.json`), then apply the large-PR cap to select the working set — each comment already carries its anchored code (GitHub `diff_hunk`; GitLab `position` + a reconstructed snippet)
- Analyze the capped **working set** (all non-replied comments, or the selected subset on a large PR) with parallel sonnet subagents (dismissals must cite the moot code)
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
       [flow-review-collect → metadata.json; 3 non-replied, below the ~20 cap → working set = all 3]
       [Analyzes ALL 3 in parallel sonnet, each subagent reading its comment from metadata.json]

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
       [Commits: fix(statuskit): address PR review feedback]

       Push to origin/feature/add-config?
       Changes: 1 file modified, 3 comments addressed
       1. Push
       2. Skip

User: Push

Agent: [Pushes]
       [Replies sequentially — only after the successful push:
         U1: "Won't fix: the module uses camelCase consistently; renaming one breaks it"
         C1: "Fixed: guard branch_name against detached HEAD; applied across the class at 2 sites."
         C2: (GitHub summary, comment_id == null → no reply; recorded in summary)]
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

The collector emits a summary/general item with `path: "(summary)"` and no `line`, so its **card
has no code block** — the header shows `(summary)` and it carries the full text + take only. It is
still triageable (including **follow-up**). Reply targets differ:

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

### Comment References Deleted (or Moved) File

When a comment's `path` no longer exists in the working tree, the collector emits `snippet: null`
(the file read degraded) — GitHub may still carry the historical `diff_hunk`, GitLab has no code
block. A missing path is **not**, by itself, evidence the concern is resolved: the file may have
been deleted (concern likely moot) **or renamed / its code moved elsewhere** (concern may still be
live in the replacement). Do **not** shortcut to `outdated_fixed` from the missing path alone — that
bypasses the Phase 3 evidence rule ("cite the code that moots the SPECIFIC claim") and can falsely
close a still-valid concern in the moved code.

Analyze instead:
- Treat the missing path as **no current snippet / no current context** — reason from the comment
  `body`, `thread`, and any historical `diff_hunk`.
- Determine what happened to the commented code: **Grep** the tree for the commented identifier /
  function / symbol (renamed file, moved symbol), then Read each candidate to confirm. If it
  **moved**, read the replacement and analyze the concern there.
- Choose the verdict from evidence, like any other comment:
  - Code genuinely **removed** and the concern no longer applies → `outdated_fixed`, note "file
    removed", reply "Fixed in subsequent commits (file removed)". For `evidence`, record what the
    search covered and its negative result (e.g. "grepped for the class/function repo-wide, no
    match — code and file both gone"), not a file:line (none exists).
  - Code **moved/renamed** and the concern still holds → a real `agree_*` verdict against the
    replacement (fix or follow-up), **not** `outdated_fixed`.

### GitLab Thin / Absent Snippet

GitLab has no `diff_hunk`, so the collector reconstructs the snippet from the current file. If that
read yields nothing usable (moved/renamed file, `new_line` out of range), it emits `snippet: null`
and the card **renders without a code block** (the take notes the `position`) — **degrade, don't
fail**. The card still shows source + full text + take.

### Very Large Number of Comments (large-PR cap)

The pre-analysis gate exists **only** for large PRs (see Phase 2). The collector always returns the
full `metadata.json`, but the cap decides how much of it enters analysis, so a big review never
floods the main context. If `counts.actionable` is **more than ~20**:

1. Print the **category-free** selection table (refs, source, path:lines, ⚠️ outdated, brief — no
   `category` and no full bodies yet; `category` is a Phase 3 verdict that does not exist pre-analysis).
2. Ask, in plain text: "{N} comments — analyze all, or select a subset? (all / <refs>)".
3. Analyze/triage **only** the selected subset (look each ref up in `metadata.json`). The categorized
   Phase 4.1 TOC (with `category`) is printed here, after analysis.

Below the threshold, the working set is all actionable comments — go straight to card-by-card
triage; no prompt.

## The Bottom Line

**Show the code on every card. Analyze before acting. Cite code to dismiss. Fix the class. Skeptic pass before push.**

Every comment gets a card with its anchored code (`diff_hunk`/`snippet`), full text, and take — emitted **UNWRAPPED** (never inside an outer ``` fence, or the rendering breaks). The user triages each: **fix / won't-fix / follow-up**. Execution is batched at the end; follow-up files a beads task.

To dismiss a comment, restate its specific claim and cite the exact code that moots it — a related mechanism existing is not enough, and a thread reply is a claim to verify, not evidence. If you can't prove it moot, agree (as `agree_obvious`/`agree_unclear`).

Fix the class, not the instance: enumerate siblings and apply with confirmed scope. On any correctness/logic/security round, run the pre-push self-review — it catches the shifted bug before the next reviewer does.

Nitpicks deserve extra scrutiny — if it doesn't improve readability, correctness, or maintainability, argue against it.

Never auto-apply. Never skip the card. Never push without asking.
