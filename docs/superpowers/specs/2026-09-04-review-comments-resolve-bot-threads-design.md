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

**This is a property of that bot, not of bots in general.** CodeRabbit — which the collector's
`is_bot` recognises explicitly — is built for in-thread conversation and answers replies and
`@coderabbitai` mentions. The design must therefore not depend on "a bot never replies"; it only
uses the measurement to justify that resolving a bot thread is low-cost.

## Decision

Resolve a thread when, and only when, all of the following hold:

1. this run **actually posted a reply** into it;
2. the thread was opened by a **bot** (`is_bot`);
3. the platform gives us something to resolve (`resolve_id` is not null).

Resolution is **unconditional** under those conditions — no flag, no prompt, no stored consent.
The decision the thread earned (`fix` / `won't-fix` / `follow-up`) does not gate it.

**Human threads are never resolved.** For people the skill stays strictly reply-only: resolving
marks a reviewer's concern as settled by the author, and that judgement stays with the user.

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
| GitLab, discussion | the discussion id (the same value as `discussion_id`) |

**The name is `resolve_id`, not `thread_id`.** The ledger row already has a `thread_id`, and it
means the *reply* target (`_ledger.thread_id_of`). Reusing that name would eventually send a node
id into `.../comments/{id}/replies` and 404 every reply.

On GitHub the node id comes from a query the collector **already makes**:
`gh_review_thread_resolved_ids` walks `reviewThreads` for `isResolved`. Adding `id` to that same
selection lets the function return both the resolved-id set and a mapping *root comment id → thread
node id*. Pagination and the existing "an unfollowable page is an error, never a partial answer"
rule stay exactly as they are. A thread whose node id is absent from the mapping gets
`resolve_id: null` and is simply never resolved — a missing id degrades, it does not raise.

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

```bash
# GitHub — resolve_id is the thread node id
gh api graphql \
  -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' \
  -f id={resolve_id}

# GitLab — resolve_id is the discussion id
glab api --method PUT \
  "projects/{project}/merge_requests/{iid}/discussions/{resolve_id}" \
  -f resolved=true
```

`resolve_id` is platform-generated and opaque — no reviewer-controlled text reaches these commands
— but it is still passed as its own argument rather than interpolated into a string a shell
re-parses, following the skill's untrusted-data rule by construction.

A failed mutation does **not** abort the loop: the ref is carried to the 5.8 report and the next
thread is processed.

### 4. Reporting and scope text

Phase 5.8 gains two lines:

```
Threads resolved: {count} ({refs — bot threads this run replied to})
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
- Tests: collector coverage for `resolve_id` on both platforms and for the summary/absent-id cases;
  ledger coverage for the field surviving `reconcile` → `get`; skill-contract coverage for the new
  Phase 5.7 step and the changed boundary text.
- `uv run ruff format` / `ruff check` / `ty check` clean.
