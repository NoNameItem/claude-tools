# flow:review-comments — resolve the bot threads it answered

**Task:** claude-tools-elf.61 (supersedes claude-tools-elf.48, closed as a duplicate)
**Date:** 2026-09-04
**Status:** approved, pending implementation plan

## Problem

`/flow:review-comments` posts a reply into every triaged thread and leaves it open. Both skills
state this as a deliberate rule:

- `plugins/flow/skills/review-comments/SKILL.md`, "This Skill Does NOT" — "Resolve/dismiss threads
  on either platform (reply-only — on GitLab it never resolves discussions, even though `resolved`
  is available)".
- `plugins/flow/skills/review-loop/SKILL.md` — the frontmatter `description` ("Reply-only: it never
  resolves threads or merges"), the "When NOT to use" section, and a red flag ("Convergence means
  it's ready — I'll resolve the threads and/or merge → No").

The cost is concentrated on bot threads. On PR #139 three rounds produced 54 bot-opened threads;
every one was answered and every one stayed open. The reviewer bot opens **new** threads each
round rather than replying into old ones, so answered-but-open threads accumulate and the PR page
stops showing at a glance which feedback is still live. Resolving is also the signal a human
reviewer reads: an answered-but-open thread looks unaddressed.

### Measurement: bots do not converse in threads

Checked across seven PRs of this repository (125, 130, 137, 138, 139, 140, 141):

| | value |
|---|---|
| root threads | 81 |
| thread replies | 70 |
| replies authored by a bot | **0** |

Every root comment but one came from `chatgpt-codex-connector[bot]` (the exception was opened by
the PR author); every in-thread reply came from the PR author. The bot never returns to a thread it
opened.

**This is a property of that bot, not of bots in general.** CodeRabbit — a GitHub App, which the
platform reports as a bot account — is built for in-thread conversation and answers replies and
`@coderabbitai` mentions. The design must therefore not depend on "a bot never replies"; it only
uses the measurement to justify that resolving a bot thread is low-cost.

## Decision

Resolve a thread when, and only when, all of the following hold:

1. this run **actually posted a reply** into it;
2. the thread was opened by a **bot** — by the platform's **account type**, never by the login
   name (see *Bot identity* below);
3. the platform gives us something to resolve (`resolve_id` is not null);
4. **no human other than us has spoken in the thread** — a bot-opened thread a person has replied
   into is that person's thread now, not the bot's.

Conditions 2 and 4 are decided on the thread **as it is on the platform at resolve time**, read
live immediately before the mutation — not on the Phase-2 snapshot, which by Phase 5.7 is
minutes old (see *Live resolve gate* below).

Resolution is **unconditional** under those conditions — no flag, no prompt, no stored consent.
The decision the thread earned (`fix` / `won't-fix` / `follow-up`) does not gate it.

**Human threads are never resolved — whether a human opened the thread or only joined one a bot
opened.** For people the skill stays strictly reply-only: resolving marks a reviewer's concern as
settled by the author, and that judgement stays with the user.

### Why unconditional, and what it costs

A bot does not argue back, so closing a `won't-fix` argument unilaterally costs nothing that a
human reviewer would notice — and the alternative (a prompt) reintroduces exactly the round-trips
this plugin's skills have been removing. The rule "we close someone else's finding on our own
verdict, without asking" now holds for bots. It does not hold for people, at all.

Two consequences are accepted deliberately, not overlooked:

- A withheld reply resolves nothing. A `Fixed:` reply deferred because the push was skipped (or
  because the branch is ahead of the remote) never reaches the resolve step, because it never
  posts. This falls out of the ordering rather than needing its own guard.
- A GitHub review-body summary has no thread, so it has nothing to resolve.

## Non-goals

- No `--resolve` flag, no prompt, no per-round mode. The behaviour is one rule.
- No record of our own resolution in the ledger, and no exception in `is_working` (see Risks).
- No change to `flow:review-loop`'s mechanics: it invokes `flow:review-comments` verbatim, so
  resolution simply happens inside each round.
- Merging and approval stay out of scope on both skills, unchanged.

## Design

### 1. Collector — a new `resolve_id` field

`flow-review-collect` adds `resolve_id` to every item in `comments[]`, beside the existing
`comment_id` / `discussion_id` / `summary_id`. It is the **resolve target**, which on GitHub is a
different identifier from the reply target:

| Row | `resolve_id` |
|---|---|
| GitHub, inline thread | the review thread's GraphQL **node id** (`PRRT_…`) |
| GitHub, review-body summary | `null` — no thread exists |
| GitLab, discussion with a resolvable note | the discussion id (the same value as `discussion_id`) |
| GitLab, discussion with no resolvable note (a general MR note — an individual note, `resolvable: false`, exactly the shape a review bot's summary takes on GitLab) | `null` — nothing `PUT .../discussions/{id}` can resolve |

**The name is `resolve_id`, not `thread_id`.** The ledger row already has a `thread_id`, and it
means the *reply* target (`_ledger.thread_id_of`). Reusing that name would eventually send a node
id into `.../comments/{id}/replies` and 404 every reply.

On GitHub the node id comes from a query the collector **already makes**:
`gh_review_thread_resolved_ids` walks `reviewThreads` for `isResolved`. Adding `id` to that same
selection lets the function return both the resolved-id set and a mapping *root comment id → thread
node id*. Pagination and the existing "an unfollowable page is an error, never a partial answer"
rule stay exactly as they are. A thread whose node id is absent from the mapping gets
`resolve_id: null` and is simply never resolved — a missing id degrades, it does not raise.

### 1a. Bot identity — the platform's account type, not the login

*Added after the PR #142 review (Codex, finding "use authoritative account type before resolving a
thread").* Until then `is_bot` came from a login-name heuristic (`[bot]`, `coderabbit`, a `-bot` /
`_bot` suffix). That was tolerable while `is_bot` only ordered the triage agenda; once it gates a
destructive call it has to be the platform's own answer. Measured on github.com, gitlab.com and a
self-hosted GitLab 18.11:

| Platform | Where the account type lives | Notes |
|---|---|---|
| GitHub REST | `user.type` on every comment, review and reply object (`"Bot"` / `"User"` / `"Organization"`) | already in the responses the collector fetches — no new call |
| GitHub GraphQL | `author.__typename == "Bot"` | the bot's GraphQL `login` **drops the `[bot]` suffix** (`chatgpt-codex-connector` vs REST `chatgpt-codex-connector[bot]`), so a login is never compared across REST and GraphQL |
| GitLab REST | **nowhere** — a note's `author` carries only `id, username, name, state, locked, avatar_url, web_url` (+ `public_email`); `GET /users/:id` has no `bot` field for a non-admin | |
| GitLab GraphQL | `UserCore.bot` on each note's `author` | a discussion's GraphQL id is `gid://gitlab/Discussion/<id>`, where `<id>` equals the REST discussion id (verified 7/7) |

The heuristic was wrong on GitLab **in both directions**. Project and group access-token bots are
named `project_<N>_bot_<hash>` / `group_<N>_bot_<hash>` — the `_bot` suffix test misses every one
(100 of 100 bot accounts on the self-hosted instance). And `gitlab-bot` on gitlab.com is a regular
account (`bot: false`) that the `-bot` suffix test called a bot — the unsafe direction, the one that
would resolve a person's thread.

So the collector drops the heuristic:

- **GitHub:** `is_bot` is `user.type == "Bot"` for thread roots, thread replies and review-body
  summaries alike.
- **GitLab:** one paginated GraphQL pass over the MR's discussions builds a *username → bot* map,
  applied to the REST notes by username. A note author the pass did not see (a discussion with more
  notes than one page holds) defaults to not-a-bot.
- **GitLab failure policy:** if that GraphQL pass fails — transient, or a self-hosted schema that
  rejects it — the collector **degrades** every GitLab author to `is_bot: false` with a warning on
  stderr, rather than aborting the round. "Not a bot" is the safe direction for the only
  destructive consumer (nothing gets resolved), the agenda merely loses its humans-first order for
  one round, and the live gate below re-checks the account type anyway.

Ledger refs are allocated once, so an existing GitLab token-bot row keeps its `U` prefix while its
`is_bot` flips to `true`; only new rows get the `C` prefix. No migration is attempted.

### 2. Ledger — one snapshot field, no behaviour

`resolve_id` joins `_ledger.SNAPSHOT_FIELDS`, so it is refreshed from the fresh snapshot every
round and returned by `flow-review-ledger get`, which is where Phase 5.7 reads it.

No schema bump: `_structure_is_sound` does not enumerate row fields, and an existing row acquires
the key on its next `reconcile`.

Nothing else in the ledger changes. `is_working`, `platform_state_of` and `reopen_if_unseen` are
untouched — the fact that *we* resolved a thread is not stored and does not affect the working set.

### 3. Skill — the resolve step inside Phase 5.7

Resolution is folded into the existing sequential reply loop, immediately after the checkpoint:

> reply accepted → `flow-review-ledger record` (checkpoint) → resolve

That order means a failed resolve can never cost the record of a reply that was already posted.

#### Live resolve gate

*Added after the PR #142 review (Codex, finding "re-fetch replies before applying the
human-participation gate").* The first version checked condition 4 against the `thread` the ledger
row carried — the Phase-2 snapshot. Between that snapshot and the mutation lie Phase 3, the whole
card-by-card triage, the fixes and the push confirmation: minutes of wall-clock during which a person
can reply into a bot thread, and the snapshot would not show it. The check has to read the platform
at the moment it matters.

A new helper, `flow-review-resolve-gate`, holds that check in tested code rather than in skill
prose:

```bash
flow-review-resolve-gate --meta "$FLOW_RC_DIR/metadata.json" --resolve-id {resolve_id}
```

It reads `platform`, `me` and the unit number from `metadata.json`, fetches **one thread live**, and
prints a single JSON line `{"resolve": true|false, "reason": "…"}`:

- **GitHub:** `node(id: $resolve_id)` as a `PullRequestReviewThread` — `isResolved` and
  `comments(first: 100) { author { login __typename } }`.
- **GitLab:** a GraphQL walk of the MR's discussions to the one whose id is
  `gid://gitlab/Discussion/<resolve_id>` — `resolved` and
  `notes(first: 100) { system author { username bot } }` (system notes are ignored).

| Exit | Meaning | 5.7 does |
|---|---|---|
| `0` | the opener is a bot by account type, every other author is a bot or `me`, the thread is still open | the mutation |
| `3` | the live thread forbids it: a human opener, a human other than `me` has replied, a deleted (null) author — counted as a human, or the thread is already resolved | nothing; the ref goes to 5.8 `Resolve withheld` with the reason |
| `4` | the thread could not be verified: an API error, the thread was not found, or it has more comments/notes than one page (a partial thread is never judged) | nothing; same `Resolve withheld` line |

It fails **closed**: every path that is not a positive, complete answer refuses. The row's `is_bot`
stays in 5.7 as a cheap pre-filter, so a human-opened row never costs an API call; the gate is the
authority. It is a read — routed through `_git.api_run` and its retries — and never performs the
mutation itself, so the mutation commands below stay visible in the skill.

```bash
# GitHub — resolve_id is the thread node id
gh api graphql \
  -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' \
  -f id={resolve_id}

# GitLab — resolve_id is the discussion id
glab api --method PUT \
  "projects/{project}/merge_requests/{iid}/discussions/{resolve_id}" \
  -F resolved=true
```

`-F`, not `-f`: `glab api` sends a `-f`/`--raw-field` value as a string and a `-F`/`--field` value
with its type inferred — the reverse of `gh api`'s convention — so `resolved=true` needs `-F` to
reach the platform as a boolean rather than the string `"true"`.

`resolve_id` is platform-generated and opaque — no reviewer-controlled text reaches these commands.
On GitHub it is passed as its own GraphQL variable (`-f id={resolve_id}`), never interpolated into
the query string. On GitLab it **is** interpolated into the request URL (inside double quotes) —
practically safe, because these ids are platform-generated and never carry reviewer text, but that
is a narrower claim than "passed as its own argument": the GitLab call does not get the same
shell-re-parsing protection the GitHub call gets by construction.

A failed mutation does **not** abort the loop: the ref is carried to the 5.8 report and the next
thread is processed.

### 4. Reporting and scope text

Phase 5.8 gains two lines:

```
Threads resolved: {count} ({refs — bot threads this run replied to})
Resolve withheld: {count} ({ref → the live gate's reason: a human joined, already resolved, could not verify})
Resolve failed: {count} ({refs whose reply posted but whose resolve call failed})
```

`This Skill DOES` gains: resolves the bot threads it replied to, on both platforms.

`This Skill Does NOT` — the current line ("Resolve/dismiss threads on either platform (reply-only
…)") is replaced by: resolve threads opened by **humans** — for people the skill stays strictly
reply-only. The merge/approval entries are unchanged.

A red flag is added: *"the human's comment is settled, I'll resolve that thread too" → never.*

`flow:review-loop` keeps its mechanics and updates three now-false statements — the frontmatter
`description`, the "When NOT to use" section, and the "Convergence means it's ready — I'll resolve
the threads and/or merge" red flag. All three narrow the same way: reply-only applies to humans,
bot threads it answered are resolved each round, and **merging is still never**.

## Risks

**A reply into a thread we resolved is swallowed.** `is_working` is `status == open` **and**
`platform_state == live`. If a bot (or a human) later posts into a thread we resolved,
`reopen_if_unseen` sets `status: open`, but `platform_state` stays `resolved`, so the row does not
re-enter the working set. The ledger's "an unseen reply always resurfaces" invariant therefore
stops being unconditional.

Accepted, because: only bot threads are resolved; the bot in use never returns to a thread (81
threads, 0 bot replies); and if one does — a conversational bot such as CodeRabbit, or a reviewer
with something to add — un-resolving on the platform returns the row to `live` and it resurfaces on
the next round. The alternative (a `resolved_by_us` marker plus an exception inside `is_working`)
would put a special case into the single function that answers "is this row still work?", which is
the one place in the ledger that has earned staying simple.

**The fourth resolve condition (no human other than us has spoken in the thread) is what keeps
this trade confined to bots.** A thread already carrying a human reply is never resolved in the
first place, so the swallowed-reply risk above only applies to a *bot* returning to a thread it
opened — never to a human's remark, which the gate keeps live by refusing to resolve the thread at
all. The gate reads the thread **live**, immediately before the mutation (see *Live resolve gate*),
so a human reply posted at any point up to that read — during triage, the fixes or the push
confirmation — blocks the resolve. What remains uncovered is a human's *first* reply posted in the
seconds between the gate's read and the mutation, or after we already resolved a thread that had
none: that reply still falls under this same accepted risk, because the gate is checked once, at
resolve time, not watched afterward. Closing that gap would mean polling platform state after the
resolve call rather than before it — out of scope here, same as the rest of this risk.

## Acceptance

- Default and only behaviour: bot threads that received a reply this run are resolved; human
  threads are never resolved; nothing is resolved for a reply that was withheld.
- GitHub: `resolve_id` carries the thread node id and reaches `resolveReviewThread`.
- GitLab: resolution goes through `discussion_id`.
- A GitHub review-body summary has `resolve_id: null` and is never resolved.
- A failed resolve is reported and does not abort the reply loop or lose a checkpoint.
- Phase 5.8 reports how many threads were resolved.
- The Scope Boundaries entry, the "This Skill Does NOT" list, the red flags, and `review-loop`'s
  three statements are updated rather than left contradicting the behaviour.
- `is_bot` is the platform's account type on both platforms; no login heuristic remains. A GitLab
  GraphQL failure degrades every author to `is_bot: false` with a stderr warning.
- The resolve decision is taken on the live thread by `flow-review-resolve-gate`, which fails
  closed; a refusal is reported on the 5.8 `Resolve withheld` line.
- Tests: collector coverage for `resolve_id` on both platforms and for the summary/absent-id cases;
  collector coverage for account-type `is_bot` (a human login ending in `-bot`, a GitLab token bot
  `project_N_bot_<hash>`, the GitLab degrade path); gate coverage for every exit-3 and exit-4 case on
  both platforms; ledger coverage for the field surviving `reconcile` → `get`; skill-contract
  coverage for the new Phase 5.7 step (including that it names the live gate), the changed boundary
  text and the new report line.
- `uv run ruff format` / `ruff check` / `ty check` clean.
