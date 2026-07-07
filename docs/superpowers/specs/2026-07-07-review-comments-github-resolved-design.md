# Design: review-comments — honor GitHub thread resolve-state during collection

- **Task:** claude-tools-elf.24
- **Date:** 2026-07-07
- **Skill:** `plugins/flow/skills/review-comments/SKILL.md` (single-file, prompt-only)

## Problem

The GitHub branch of `review-comments` (Phase 2 collection, STEP 2 parse) filters threads by
**`already_replied` only** — "was the last comment mine?". It never looks at the thread's
**resolved** state, because the collection fetch uses REST `pulls/{n}/comments`, which has no
resolve field. The GitLab branch *does* honor resolve (`resolved == true OR already_replied`,
SKILL.md line 202) — an asymmetry between the two platforms.

Consequence: a thread that is **resolved in the UI but whose last comment is a bot** (so
`already_replied` is false — I did not reply last) is surfaced as actionable on **every** run.
Concretely: a user resolves a bot nitpick without replying, or a bot posts a follow-up after my
"Fixed". `already_replied` covers most resolutions (a resolve usually follows a reply), but this
remainder leaks through.

### Why now

Under the review-loop redesign, `review-comments` becomes the **single source of truth** for
"is there work?": review-loop drops its own GraphQL thread count and decides convergence purely
on "was there a new push?". So all resolve-awareness must live in `review-comments` — otherwise
the loop never converges on a resolved-but-bot-last thread. Related: claude-tools-elf.23
(review-loop), where an `isResolved` count was added as compensation.

## Goal

Make GitHub collection drop **resolved** threads entirely — mirror of the GitLab branch — so a
resolved thread never re-surfaces as actionable regardless of who commented last.

## Non-goals

- **GitLab branch** — already honors resolve (line 202); untouched.
- **Resolving/dismissing threads** — the skill stays reply-only; it *reads* resolve-state, it
  does not set it.
- **Thread-native GitHub rewrite** — replacing the REST comments fetch with a full GraphQL
  `reviewThreads` parse (isResolved + isOutdated + comments) is a tempting cleanup but a large,
  higher-risk refactor of a working path. Deliberately deferred; this change is additive.
- **A `(N resolved, skipping)` count** — GitLab drops resolved silently at parse; we match that.
- **Committed tests** — the collection logic is subagent prose, not a unit; validated via
  `superpowers:writing-skills` RED→GREEN, nothing committed.

## Design

Approach: **additive GraphQL side-query** (minimal). The working REST parse logic (thread
reconstruction via `in_reply_to_id`, outdated heuristic, bot detection, line ranges) is left
untouched; we only add resolve-state on the side and use it to drop roots. `gh api graphql` is
covered by the existing `Bash(gh:*)` allow, so **`allowed-tools` is unchanged**. All edits are
inside the GitHub blocks of the Phase 2 collection subagent prompt.

### Change 1 — Fetch resolve-state (STEP 1, GitHub block)

Add a third GitHub fetch (alongside `…/comments` and `…/reviews`): a paginated GraphQL query
for the PR's review threads and their resolve-state.

```bash
gh api graphql --paginate -f query='
query($owner:String!,$repo:String!,$num:Int!,$endCursor:String){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$num){
      reviewThreads(first:100, after:$endCursor){
        nodes{ isResolved comments(first:1){ nodes{ databaseId } } }
        pageInfo{ hasNextPage endCursor }
      }
    }
  }
}' -F owner={owner} -F repo={repo} -F num={number}
```

- `--paginate` follows `pageInfo{ hasNextPage endCursor }` via `after:$endCursor` until
  exhausted — same `--paginate` idiom the REST `…/comments` and GitLab `discussions` fetches
  already use. `first:100` is a **page size, not a cap**; all threads are covered.
- `--paginate` emits **one JSON object per page**; the parse step must **union
  `reviewThreads.nodes[]` across all page objects** before collecting ids.

### Change 2 — Drop resolved roots (STEP 2, GitHub block)

Build `resolved_root_ids` = { `comments.nodes[0].databaseId` for every thread node where
`isResolved == true`, unioned across pages }. A review thread's first comment is always its
root, so that `databaseId` equals the REST root comment `id`.

**Drop any root comment whose `id ∈ resolved_root_ids` before building threads** — a direct
mirror of the GitLab line-202 skip. Resolved roots are removed **entirely**: they appear in
neither the TABLE nor the METADATA.

This is a *harder* skip than `already_replied`, and the two must not be conflated:

| Signal | Behavior |
|---|---|
| `isResolved` (new) | Root removed **entirely** — not in TABLE, not in METADATA (like GitLab). |
| `already_replied` (unchanged) | Root **still emitted** in TABLE (marked) + METADATA; filtered later before Phase 4 (line 271), with its "(N already replied, skipping)" count. |

The STEP 4 METADATA rule "Include ALL root comments/threads, even if already_replied is true"
(line 255) gets a clarifying clause: **except** roots dropped as resolved.

### Change 3 — Mapping table (line 67)

The "Skip as already-done" row, GitHub cell:

- **Before:** `already_replied` heuristic
- **After:** `isResolved` (GraphQL `reviewThreads`) **or** `already_replied`

matching the phrasing of the GitLab cell.

### Robustness / degradation

- **GraphQL call fails** (missing token scope, transient error): fall back to
  `resolved_root_ids = ∅` — i.e. today's `already_replied`-only behavior — and note the
  degradation. Collection is **never aborted** over the resolve side-query.

## Testing & validation

Prompt-only skill; no automated tests. Validate via `superpowers:writing-skills`
RED→GREEN→REFACTOR, nothing committed:

- **RED:** a fake `gh` (including `gh api graphql`) returns one thread with `isResolved=true`
  whose last comment is a **bot** (so `already_replied=false`). Following the **current** prose,
  that thread still lands in TABLE/METADATA.
- **GREEN:** after the edit, the resolved thread is absent from both TABLE and METADATA; an
  open, actionable thread in the same fixture is unaffected.
- **REFACTOR:** tidy wording; a dogfood skeptic checks GitHub↔GitLab consistency (both now skip
  resolved at parse) and that `already_replied` semantics are unchanged.

## Risks

- **Correlation assumption.** `comments(first:1).databaseId` is treated as the thread root's
  REST `id`. This holds because a review thread's first comment is always its root; a thread
  cannot begin with a reply. Low risk.
- **Extra API call per collection.** One additional (paginated) GraphQL request on GitHub.
  Bounded and off the main context (runs inside the haiku collection subagent).
- **GraphQL/REST divergence.** If a thread exists in GraphQL but its root id is absent from the
  REST comments page (or vice versa), the set-difference simply leaves that root as-is — it
  degrades to current behavior rather than mis-dropping.
