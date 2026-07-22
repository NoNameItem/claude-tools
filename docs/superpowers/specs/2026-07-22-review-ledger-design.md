# Persistent per-PR review ledger — design

**Task:** claude-tools-elf.39 (Persistent per-PR review ledger for flow:review-comments)
**Date:** 2026-07-22
**Status:** approved, pending implementation plan

## Context

`flow:review-comments` treats its working directory (`$FLOW_RC_DIR`, a `mktemp -d`) as an
ephemeral buffer — collected findings and verdicts are discarded at the end of each run. Across
multiple rounds on the same PR/MR this loses history:

- **No durable record of which comments were already processed.** Dedup relies solely on the
  platform's `already_replied` heuristic (the latest thread reply is from the authenticated user).
  When that heuristic misses, an already-handled thread is re-triaged.
- **No detection of RECURRING findings.** A reviewer (e.g. Codex) re-flags the same issue after a
  new commit under a **fresh** `comment_id`; the agent has no memory it already triaged/rejected it
  and re-analyses from scratch, re-disputes it, and wastes a round. This happened repeatedly on
  PR #109.
- **Stale summary reviews reappear each round.** A GitHub review-body `(summary)` triaged as
  `follow-up` posts no inline reply (no thread target), so a rerun re-imports it → duplicate
  follow-up tasks (this is bug **claude-tools-elf.31**, subsumed here).

This design promotes the ephemeral working state to a **persistent per-PR review ledger**: a
machine-readable log, keyed per PR/MR, that survives across rounds, `/clear`, and sessions. It
records every processed finding and its final decision, and on later rounds classifies current
platform comments as **new / already-seen / recurring** so the skill can skip what is done and
short-circuit what is a re-flag.

## Goal

Give `flow:review-comments` durable, per-PR memory of what was already decided, so that across
rounds it:

1. **Drops** comments whose exact thread was already handled (durable `already_replied`).
2. **Recognises recurrence** — the same finding re-flagged under a new id — and defaults its
   triage to the prior decision without re-spending analysis.
3. **Does not create duplicate follow-ups** for a re-imported summary (subsumes elf.31).

And upgrades `flow:review-loop`'s fragile in-session repeat-tracking to this durable mechanism.

## Scope

**In scope**

- New helper `plugins/flow/bin/flow-review-ledger` with two subcommands: `classify` and `record`.
- Ledger storage in the XDG cache, keyed per repo + PR/MR.
- `flow:review-comments` SKILL.md integration: classify after collection (Phase 2), skip analysis
  for recurring refs (Phase 3), default triage to prior decision (Phase 4), reuse follow-up
  task-ids (Phase 5.4), write-back after replies (Phase 5).
- `flow:review-loop` SKILL.md: replace in-session repeat-tracking prose with ledger-driven
  recurrence.
- Unit tests for the helper; skill-contract tests.

**Closes together with elf.39**

- **elf.31** — summary follow-ups aren't idempotent on rerun. The ledger records each summary
  finding's decision + follow-up task-id; on rerun the recurrence/seen match reuses the existing
  task-id instead of creating a duplicate.
- **flow:review-loop in-session repeat-tracking** — replaced by durable, content-keyed recurrence
  that survives `/clear`/sessions and ref-renumbering.

**Out of scope (YAGNI)**

- **elf.48** (optional auto-resolve of answered threads) — NOT implemented here. But the ledger is
  designed as a clean input for it: it records, per finding, whether we posted a reply this run
  (`replied`) and accumulates the platform thread-ids. The resolve mutation + flag remain elf.48.
- **elf.41** (skip bot boilerplate) — orthogonal collector-side content filter; independent.
- Team-shared / committed ledger — deliberately per-machine (see Storage rationale).
- Garbage-collection of old ledger files — tiny JSONL in a cache; not worth it.
- Semantic / LLM-based recurrence matching — non-deterministic, does not belong in a helper.

## Storage

Path: `$XDG_CACHE_HOME/flow/review-ledger/<repo-slug>/pr-<n>.jsonl`
(fallback `~/.cache` when `$XDG_CACHE_HOME` is unset).

- `<repo-slug>` derived from the collector's `unit.url` (a filesystem-safe slug of `owner/repo` /
  the GitLab project path).
- `<n>` is the PR number (GitHub) / MR iid (GitLab).
- Format: **JSONL** — append/merge-friendly, one record per processed finding per round, machine
  source of truth (lives in a cache, not meant for human eyes).

**Why outside the working tree (the decisive constraint).** The ledger must **never** be
committable or pushable:

- Committing it to the PR branch would advance the head SHA — which breaks `flow:review-loop`,
  whose convergence is decided purely by whether the head advanced.
- It would appear in the PR diff and be reviewed by the bots (a ledger about the PR, inside the PR).

A worktree-local file guarded by `.gitignore` is only a **soft** guarantee (one bad ignore rule,
or a `git add -A` before the rule exists, leaks it). Placing the ledger under `~/.cache` is a
**structural** guarantee: it is outside the repository directory entirely, so no `git` operation
from the repo can ever stage or push it, independent of any ignore rule. Precedent: statuskit
already writes to `~/.cache/statuskit/`.

Per-machine (not team-shared) is acceptable: this is effectively a single-maintainer repo, and the
ledger **degrades gracefully** to today's `already_replied`-only behaviour when absent (e.g. a
teammate on another machine, or a fresh clone).

**Lifecycle.** The ledger only needs to live while the PR/MR is under review. It is created on the
first round (by `record`) and naturally goes stale after merge. `flow:done` (which removes the
worktree) runs post-merge, when the ledger is already moot; the cache location means the ledger is
independent of the worktree anyway.

## Finding identity

Two distinct keys, because "have I handled this exact thread?" and "is this a re-flag of a finding
I already decided?" are different questions:

1. **Thread identity** — the platform id: `comment_id` (GitHub inline), `discussion_id` (GitLab),
   or `summary_id` (GitHub review body). Stable per thread. Answers "seen this exact thread". A
   record accumulates every thread-id observed for a finding across rounds (`thread_ids`).

2. **Content identity** (the recurrence key) — `sha256(path + "\0" + normalize(body))`. A
   recurrence arrives under a **new** thread-id, so identity must be content-based. **The line
   number is deliberately excluded** — it shifts between commits.

### `normalize(body)`

Deterministic normalisation (in the helper, unit-tested against real PR #109 / #112 bodies):

1. Strip `<details>…</details>` blocks (bot boilerplate).
2. Strip markdown links → keep the link text.
3. Strip `Reviewed commit: …` / similar commit-anchor lines.
4. Lowercase.
5. **Replace runs of digits / hex** with a placeholder — neutralises embedded line numbers and
   commit SHAs, which bots routinely quote in the body ("line 42: …").
6. Collapse whitespace.

Rationale — **asymmetric error cost makes moderate normalisation safe:**

- A **false negative** (missed recurrence, e.g. a bot rephrased the finding) simply falls back to
  normal re-analysis — today's behaviour, no regression.
- A **false positive** (two distinct comments hash equal) is harmless **because recurrence is
  advisory** — the card is still shown and the user still triages; worst case is a slightly
  misleading "recurring" note, never lost data.

Reliability tracks bot determinism: Codex / CodeRabbit typically re-emit near-identical text, so
the normalised hash catches the common case. The most painful case — a re-flagged **won't-fix** —
is also the most reliable to match: since we did not change the code, both the body and the
anchored code stay stable across rounds.

## Ledger record schema

One JSON object per line; one line appended per processed finding per round. Reading the ledger =
fold by `content_key`, last record wins.

```json
{
  "content_key": "<sha256>",
  "path": "plugins/flow/bin/flow-review-collect",
  "platform": "github",
  "thread_ids": ["12345", "67890"],
  "head": "<head SHA of the run that wrote this record>",
  "decision": "won't-fix",
  "reason": "module is camelCase consistently; renaming one breaks it",
  "followup_task_id": null,
  "replied": true,
  "deferred": false
}
```

- `head` stamps the observation for ordering (round numbers are known only to `review-loop`; the
  head SHA is always available and gives a stable order).
- `decision` ∈ `fix | won't-fix | follow-up | outdated_fixed | skip`.
- `followup_task_id` — set when `decision == follow-up`; enables the elf.31 dedup.
- `replied` — did this run post a platform reply for the finding (feeds `seen` and elf.48).
- `deferred` — the reply was withheld this round (push skipped / `Fixed:` deferred). Distinguishes
  "handled" from "decided but not yet replied" so a deferred reply re-surfaces next round.

## Architecture: `flow-review-ledger` helper

A new standalone script (the collector `flow-review-collect` is **not** touched — it stays a pure
"fetch current platform state" tool; mixing in local-cache state would muddy its
single-responsibility and complicate its tests). Two subcommands.

### `flow-review-ledger classify --meta <metadata.json>`

- Resolves the ledger path itself from the metadata's `unit.url` + `unit.number` (honours
  `$XDG_CACHE_HOME`; tests point it at a tmp cache).
- Missing ledger file → **first review**: every ref is `new` (this is the base case, **not** a
  degrade path).
- Folds the ledger by `content_key` (last record wins).
- For each `comments[]` ref, emits `{ "status": "new" | "seen" | "recurring", "prior": {…} | null }`:

  | status | condition | action in the skill |
  |---|---|---|
  | `seen` | this comment's thread-id is already in the ledger as **terminally handled** | **exclude from the working set** — no card, no re-reply |
  | `recurring` | `content_key` matches a handled finding but the thread-id is **new** | show the card; default = prior decision; skip Phase 3 analysis |
  | `new` | neither | normal flow |

  **Terminally handled** (the `seen` rule): the thread-id's latest record carries a `decision`
  **and** (`replied == true` **or** the item has no reply target by construction — a GitHub
  `(summary)` with `comment_id == null`). A record with `deferred == true` (reply withheld) is
  **not** `seen` → it re-surfaces so the withheld reply can be posted.

- `prior` (for `seen`/`recurring`) carries `{decision, reason, followup_task_id, head, replied}`.
- Corrupt JSONL line → skip it + warn to stderr; never crash (mirrors the collector's degrade
  philosophy). Reviewer text is read from files by path — never interpolated into a shell.

### `flow-review-ledger record --meta <metadata.json> --decisions <decisions.json> --head <sha>`

- Reads `metadata.json` + a per-ref decisions file the skill writes
  (`{ref: {decision, reason, followup_task_id, replied, deferred}}`).
- Appends one record per processed ref, stamped with `--head`.
- **Creates** the ledger directory + file when missing (first round).
- Free-text values come from files, never a shell (untrusted-data rule).

## `flow:review-comments` SKILL.md integration

- **Phase 2 (after collect):** run `flow-review-ledger classify --meta metadata.json` →
  `$FLOW_RC_DIR/ledger-classify.json`. A classify **failure** (not a missing ledger) degrades to
  treating all refs as `new`.
  - **Working set** = `already_replied == false` **AND** `status != seen`.
  - Report counts separately: "X already replied, Y already handled (ledger), Z to triage".
- **Phase 3 (analysis):** for `recurring` refs, **skip** the balanced reviewer subagent; synthesise
  `verdict-{ref}.json` from the prior decision — `suggested = prior.decision`, and `thought`
  carries the recurrence note: `↺ Recurring — previously {decision} @ {head:0:7}: {reason}`.
  `flow-comment-card` is **not** changed (the banner rides inside the synthesised verdict).
- **Phase 4.2 (triage):** the card's decision default is already the verdict's `suggested`, which
  for a recurring ref is the prior decision — so recurrence naturally pre-selects it. The card is
  still shown and the user still confirms (invariant: never auto-apply, always show the card).
- **Phase 5.4 (follow-ups):** if a `recurring`/`seen` follow-up has a `prior.followup_task_id`, **do
  not** create a new task — reuse the existing id in the reply. This is the elf.31 fix.
- **Phase 5 (write-back, after replies in 5.7):** run
  `flow-review-ledger record … --head <HEAD>` to persist this round's decisions and follow-up
  task-ids. A withheld/deferred `Fixed:` reply is recorded with `replied:false, deferred:true`.

## `flow:review-loop` SKILL.md changes

Remove the in-session repeat-tracking prose (the "set of refs seen across iterations; no API
queries, no persistence" mechanism, ~lines 173-177 and 228-230) and the `⚠️ <ref> — повторно`
round-indicator line derived from it. Recurrence is now surfaced durably by `flow:review-comments`
itself via the ledger — it survives `/clear`, new sessions, and ref-renumbering, which the
in-session set never did. The round indicator itself (round number + head) stays; only the fragile
in-memory repeat set is dropped.

## Untrusted-data handling

Consistent with the existing skill invariant: reviewer-supplied text (comment bodies, thread
replies, paths) is **data, never shell source**. The helper reads `metadata.json` / decisions /
ledger by path and builds argv lists; `content_key` is a hash. Nothing reviewer-controlled reaches
a command line.

## Testing (TDD, via superpowers:writing-skills / writing-plans)

Unit tests for `flow-review-ledger` (`plugins/flow/bin/tests/test_flow_review_ledger.py`):

- `normalize_body` on real PR #109 / #112 bodies (boilerplate strip, link strip, digit/SHA
  neutralisation, whitespace).
- `classify`: `new` on missing ledger; `seen` excludes a terminally-handled thread-id; `recurring`
  on a content match under a new thread-id; a `deferred` record is **not** `seen`.
- `record`: append + fold-by-`content_key`; creates dir/file on first round; stamps `head`.
- Ledger path resolution honouring `$XDG_CACHE_HOME`.
- Degradation: corrupt JSONL line skipped + warned, no crash.
- Follow-up `task-id` reuse (elf.31): a recorded summary follow-up is not duplicated on rerun.

Skill-contract tests (`test_flow_skill_contracts.py`): the new helper invocations are present with
matching `allowed-tools` grants in `review-comments` (and the removed repeat-tracking prose is gone
from `review-loop`).

## Open questions / assumptions

- **Normalisation aggressiveness** is a tunable; the digit/hex-run neutralisation is the riskiest
  step (could merge distinct numeric findings) but is safe under the advisory-recurrence model.
  Start with the rules above; adjust if real recurrences slip through.
- **`repo-slug` derivation** from `unit.url` must be filesystem-safe and stable across rounds; unit
  tests pin it for both GitHub and GitLab URL shapes.
