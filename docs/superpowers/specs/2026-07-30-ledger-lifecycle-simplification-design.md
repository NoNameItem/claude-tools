# Review-ledger lifecycle simplification — design

**Date:** 2026-07-30
**Status:** approved, pending implementation plan
**Task:** claude-tools-elf.39 (lands inside PR #118, before the ledger is ever released)
**Amends:** `docs/superpowers/specs/2026-07-22-review-ledger-design.md` — see "What this supersedes"

## Problem

The shipped ledger tracks a row's lifecycle with five statuses (`open`, `skipped`, `pending`,
`done`, `deleted`), a three-valued platform `resolved` flag, and `thread_mark`, written from
seven places. A full audit of the state machine (code, prose, tests) found the complexity is not
buying anything, and that one write site is actively wrong.

**The disease: two axes share one field.** `status` is written both by us (our decision) and by
the platform (`apply_resolution`, `mark_absent`). `apply_resolution`
(`plugins/flow/bin/flow-review-ledger:150-151`) sets `row["status"] = "done"` from **any** prior
status the moment the platform reports `resolved: true`, with no check that we ever acted:

1. A row recorded `pending` (decision made, reply withheld because the push was skipped or failed)
   is silently settled when a human clicks "Resolve conversation". The promised reply is never
   posted and the row never re-surfaces. `SKILL.md:802-804` states the opposite contract —
   `pending` becomes `done` only when the reply lands.
2. A `skipped` row becomes `done`, contradicting the 2026-07-22 spec's own terminality clause
   (`:256-258`, "`skip` is **not** terminal").
3. `SKILL.md:218-224` claims resolution "does not change `status` at all" and that the platform's
   verdict and ours are "tracked separately". Both claims are false in the common case.

**The redundancy.** `is_working` (`plugins/flow/bin/_ledger.py`) already excludes a row whose
`resolved` is `True`, so writing `status` on resolve buys nothing and costs the three failures
above. `pending` and `skipped` are read in exactly one place — the `stats` render line
(`flow-review-ledger:441-442`) — and are fully derivable from `decision`, which the row already
carries. No logic anywhere branches on them; `reopen_if_advanced` ignores them outright (its gate
is `status == "done"`).

**Unenforced invariants.** `validate_decisions` checks only that `status` and `decision` are known
enum members. A `done` entry with an absent or null `thread_mark` on a threaded row is accepted,
after which `id_advanced(current, mark=None)` returns `True` and the row re-opens on our own just-
posted reply — an infinite re-triage loop that `SKILL.md:1049-1056` describes as catastrophic and
mitigates only by prose aimed at the calling agent.

**Nothing has run.** `~/.cache/flow/review-ledger/` contains zero files: `/flow:*` executes the
installed plugin release (3.1.0), which has no ledger code, so the feature has never touched a
real PR. Everything known about it comes from tests and reading. This has two consequences: there
is nothing to migrate, and until a release exists the test suite is not a safety net for manual
verification — it is the *only* verification.

## The model

Fields grouped by **who writes them**. This grouping is the fix: no field has two writers, and no
writer spans both axes.

| Group | Fields | Sole writer |
|---|---|---|
| Identity (set on insert, never changes) | `thread_id`, `platform`, `ref`, `kind` | `new_row` |
| **Our axis** | `status` ∈ {`open`, `done`}; `decision` ∈ {`fix`, `wont_fix`, `follow_up`, `outdated`} \| null; `reason`; `followup_task_id`; `thread_mark` | `cmd_record` (seeded by `new_row`; `reopen_if_advanced` writes `status` only) |
| **Platform axis** | `platform_state` ∈ {`live`, `resolved`, `absent`} | `reconcile` |
| Snapshot (rebuilt every round, never durable) | `user`, `is_bot`, `path`, `start_line`, `line`, `outdated`, `already_replied`, `diff_hunk`, `snippet`, `side`, `position`, `body`, `thread` | `refresh_snapshot` |
| Bookkeeping | `first_seen_round`, `last_round`, `head` | `reconcile` / `cmd_record` |

Working-set membership collapses to one predicate over two independent facts:

```python
def is_working(row) -> bool:
    return row["status"] == "open" and row["platform_state"] == "live"
```

### What is removed

- **`resolved` as a stored field.** It becomes an input mapped into `platform_state`; it leaves
  `SNAPSHOT_FIELDS`.
- **`pending`, `skipped`, `deleted` from `STATUSES`.** The first two are derivable from `decision`;
  the third moves to the platform axis as `absent`.
- **`skip` from `DECISIONS`** (and from `DECISION_LABELS`, `flow-review-ledger:379-385`).
- **`TERMINAL_STATUSES`** — a one-element set is just `status == "done"`.
- **`apply_resolution` entirely.** It wrote `status`, and it also advanced `thread_mark` on
  resolve. Its own comment justified that advance as protection against a later round whose
  resolution side-query degraded to unknown; degraded rounds no longer exist (see "Collector
  failure semantics"), so the advance is unnecessary and **`thread_mark` is written only by
  `cmd_record`**.

### How the removed cases now behave

| Case | Behavior |
|---|---|
| Thread resolved, we never decided | `platform_state = resolved`, `status` stays `open` — out of the working set on the platform axis. We do not touch `status` because we decided nothing. |
| Thread un-resolved later | `platform_state = live`, `status` still `open` — the row returns by itself. Zero status transitions. |
| Thread vanishes, then reappears | `absent` → `live`. Zero status transitions, and `decision` / `reason` / `followup_task_id` survive (today the revival routes the row through `deleted` back to `open`, losing what it meant). |
| Decision made, action did not land | `status: open` with `decision` (+ `reason`) recorded. This is the whole of what `pending` used to carry; the next round has the decision as context and simply delivers it. |

### Considered and rejected: deriving the re-open

Re-opening on a thread advance (`done → open`) stays an explicit `status` write rather than a
derived predicate. Deriving it would leave `status` with a single durable writer, but the ledger
on disk would stop being self-describing: a row reading `status: done` would in fact be working,
and every consumer would have to call a predicate with the right inputs to find out. The existing
code already carries a comment about three call sites answering "is this row still work?"
separately and disagreeing; a derived re-open re-opens that door.

## Write sites and transitions

`platform_state` is a pure function of this round's observation. Aborting on an undetermined
resolution (below) collapses the rule to two lines — there is no "could not determine" branch:

```python
def platform_state_of(item: dict) -> str:
    return "resolved" if item.get("resolved") else "live"
```

`resolved` is a bool for everything with a resolvable thread. `None` stays legal for exactly one
input — a GitHub review-body summary, which has no thread and never consults the side-query — and
maps to `live`, because "not applicable" for such a row means "live until we settle it". Before
this change `None` meant both "not applicable" and "could not determine"; the second meaning
ceases to exist and a comment must say so, or the two will be conflated again.

**`reconcile`, per snapshot item:**

```
key, thread_id — if either is None the row is not trackable; skip
seen.add(key)
row missing  → new_row(...)                    # seed
otherwise    → reopen_if_advanced(row, item)   # status: done → open
               refresh_snapshot(row, item)     # snapshot fields
row["platform_state"] = platform_state_of(item)
row["last_round"] = round_no
```

Then one pass over rows absent from `seen`:

```
row["platform_state"] = "absent"    # status untouched; decision/reason/followup_task_id survive
```

**Write sites — four, none sharing a field:**

| Site | Writes | When |
|---|---|---|
| `new_row` | identity; `status` = `done` if `already_replied` else `open`; `thread_mark` = last reply id; `decision`/`reason`/`followup_task_id` = null | first sight of the row |
| `refresh_snapshot` | snapshot fields only | every round, existing row |
| `reopen_if_advanced` | `status` only, `done → open` only | the thread advanced past `thread_mark` |
| `cmd_record` | `status`, `decision`, `reason`, `followup_task_id`, `thread_mark` | our explicit decision |
| (absence pass in `reconcile`) | `platform_state` = `absent` | the row is not in the snapshot |

`platform_state` has exactly one writer by construction: `new_row` does **not** set it, because the
flow above assigns it unconditionally for new and existing rows alike, and the absence pass is the
same function. Nothing reads the row between the two statements.

`new_row` no longer seeds `done` from `resolved`. A row first seen already-resolved gets
`status: open` + `platform_state: resolved`: out of the working set, but if the thread is
un-resolved it arrives for triage instead of staying closed by someone else's verdict forever.

**Both state machines:**

- Our axis: `open → done` (`record`), `done → open` (`record`, or a thread advance). That is all.
- Platform axis: `live` / `resolved` / `absent`, recomputed from each round's observation with no
  history; any value may follow any other.

### The `thread_mark` invariant

`cmd_record` rejects an entry that yields `status: "done"` with `thread_mark = None`, unless the
row is threadless. Threadlessness is now expressible from stored fields:
`platform == "github" and kind == "summary"` — the only combination on either platform with
neither a reply target nor resolvability (see the platform table below).

The rejection covers the **whole batch** — `decisions.json` is not applied at all and the ledger
is untouched — matching the existing treatment of `status: null`. This is a caller programming
error, not reviewer data, and a partial application would leave a round in a state nobody can
explain.

This also disarms the `id_advanced(current, mark=None) → True` footgun: the only way to reach
`done` with an empty mark on a threaded row was through `record`, which now refuses.

## Collector failure semantics

**One rule: every API call either returns data or aborts the run.** No partial answers, no
"unknown" in the collector's output.

In `gh_review_thread_resolved_ids` (`plugins/flow/bin/flow-review-collect:209`) both current
returns of `None` are removed — the blanket `except` (`:262-267`) and the
`hasNextPage: true`-with-null-`endCursor` anomaly (`:253-259`). Its return type becomes
`set[str]`, and item `resolved` becomes a plain bool.

Exit code **4** (3 is taken by "PR not open") lets `flow:review-loop` distinguish "try later" from
"wrong state". The skill only needs the rule "non-zero → report and stop"; because the round never
started, `reconcile` never ran and no row changed.

**Why aborting is acceptable, and its one risk.** The side-query returns `None` on structural
failures too, not only network ones. A host where the query fails *permanently* — e.g. GitHub
Enterprise on a GraphQL schema without `fullDatabaseId` — becomes unusable instead of degrading.
That is a **capability** problem (resolution is unsupported on this host, a constant) rather than a
transient one, and its fix is a per-host constant, not an "unknown" value in every row. We do not
build it now (YAGNI); the error message must be specific enough that whoever hits it can tell what
happened.

### Retries

A retry wrapper around `run`, used by `gh_api` / `glab_api` — the **read path only**. Every
collector call is idempotent (listings, `user`, `repo view`, `pr view`, the GraphQL query), so a
retry is safe. Reply posting in Phase 5 goes through a direct `gh api` from the skill, not through
`_git.py`, and must never be retried — a second attempt double-posts a comment. The wrapper's
docstring must say so, or it will eventually be reused for a write.

- 3 attempts, sleeping 1 s then 4 s: ~5 s added to an interactive wait in the worst case.
- Retry `TimeoutExpired` and any non-zero exit, **except** a short deny-list of clearly permanent
  failures: authentication (`gh auth login`, `401`, `Bad credentials`), `404` / `Not Found` /
  `Could not resolve to a`, GraphQL schema errors (`Field ... doesn't exist`). The deny-list is
  matched as case-insensitive substrings against the failed call's **stderr** — the CLIs expose no
  HTTP status, so stderr text is the only signal available.
- The bias is deliberately "retry by default": mistaking a transient failure for a permanent one
  aborts the run, while mistaking a permanent one for transient costs five seconds.
- Rate limiting (`API rate limit exceeded`, `secondary rate limit`, `429`) retries with a longer
  pause — the only case where a short one is known to be useless.
- After the last attempt the exception propagates; the message names the failed call and carries
  the CLI's stderr.

## Reply targets and resolvability by platform

The "no reason required" rule keys on the **absence of a reply target**, not on non-resolvability.

| | Reply target | Resolvable by platform | How it leaves the working set |
|---|---|---|---|
| GitHub inline / file | yes | yes | our reply, or a resolve |
| **GitHub review-body summary** | **no** | **no** | **only our own `done` — otherwise never** |
| GitLab inline / file | yes | yes | our reply, or a resolve |
| GitLab general (`(summary)`) | yes (`discussion_id`, `flow-review-collect:487`) | no (`resolvable` is empty, so `resolved` is always `False`, `:458`) | our reply |

GitLab has no dead end: a general discussion is not resolvable by the platform but can be replied
to, so we can always settle it. The single row with no way out is the GitHub review-body summary,
which is why it is the sole exception in the `thread_mark` invariant and the sole case where a
`won't-fix` needs no reason.

## Skill changes

`plugins/flow/AGENTS.md` mentions neither statuses nor the ledger and is unaffected.
`plugins/flow/skills/done/SKILL.md` is unaffected — its purge gate keys on the PR's state and has
nothing to do with a row's lifecycle.

### `review-comments/SKILL.md`

**Phase 2 — the large-PR cap is removed entirely**: the subset-selection prompt, the category-free
selection table, the "carry the working set as its list of refs" instruction, and the "Very Large
Number of Comments" edge case. The ledger is what made the cap unnecessary: rounds no longer
re-import settled findings, so a round carries only what is new or re-opened. The membership rule
becomes `status == "open" and platform_state == "live"`. A new edge case covers the collector
aborting on an API failure: report it, stop, note that the ledger was not touched, retry later.

**Phase 3** — the dispatch instruction must separate three shapes of row instead of conflating two
of them (`SKILL.md:308-312` currently declares any non-null `decision` to mean "re-surfaced
because its thread advanced", which is false for a row whose action never landed):

| Row shape | Meaning | Instruction |
|---|---|---|
| `decision is None` | new finding | analyze from scratch |
| `decision` set, `resurfaced` true | the thread advanced | prior verdict as context; read the new replies as what changed |
| `decision` set, `resurfaced` false | decided, action did not land (infrastructure failure) | **do not re-litigate** — deliver it |

**Phase 4** — triage outcomes are `fix` / `won't-fix` / `follow-up`; `skip` is gone as a
user-facing option, and invariant 3 with it.

- `won't-fix` requires a reason **iff a reply target exists**. A reason exists in order to be
  published; where there is nowhere to publish it, it is not required.
- A row with no reply target (GitHub `kind == "summary"`) defaults, after being shown once, to
  `won't-fix` → `done`, with no reason and no reply. Shown once and not auto-settled at seeding:
  a summary body can carry real content.
- A comment that *can* be replied to never gets a bare skip. Not wanting to act on it is
  `won't-fix`, with a rationale.

**Phase 5** — aborted outcomes stop mapping to `skip` and are recorded as "decision kept, status
`open`":

| Situation | Recorded as |
|---|---|
| apply failed (the 5.2 demotion) | `status: open`, `decision: fix`, `reason`: what failed |
| follow-up batch cancelled (`no`) | `status: open`, `decision: follow_up`, no `followup_task_id` |
| push skipped, so `Fixed:` is withheld | `status: open`, `decision: fix`, `reason`: push deferred |
| task filed, reply not yet posted (the 5.4 checkpoint) | `status: open`, `decision: follow_up`, `followup_task_id` set |

The last row is the per-ref checkpoint added earlier in this PR; it works exactly as before, and
writes `open` instead of `pending`. The 5.7a outcome table shrinks accordingly — `status` is only
ever `done` or `open`.

### Computed `resurfaced`

The rule separating a re-opened row from an undelivered one must not live in prose alone — that is
precisely the code/prose drift this redesign is cleaning up. `flow-review-ledger get` and
`flow-comment-card` therefore emit a computed `resurfaced` boolean, produced by one helper in
`_ledger.py`. The subagent derives nothing; the helper is unit-tested.

**Definition:** `resurfaced` is `id_advanced(last_reply_id(row["thread"]), row["thread_mark"])` —
the **same** helper `reopen_if_advanced` uses, not a second rule. "Did the thread advance?" must
have one implementation, or the flag and the re-open will eventually disagree about the same row.
Its existing semantics carry over unchanged: a threadless row is never advanced (`current` is
None), a freshly seeded row is not (its mark *is* the current last reply), and a null mark on a
thread that has replies is advanced — honest, since such a reply is by definition unaccounted for.

The flag stays true from the re-open until `record` writes a fresh mark, because
`reopen_if_advanced` deliberately does not advance the mark — only `record` does.

### `stats`

```
Done: N  (fix 3 · won't-fix 2 · follow-up 1)
Open: N  (decided but not delivered: M)
Resolved upstream: N        # only when non-zero
Deleted upstream: N         # only when non-zero
```

`Pending` and `Skipped` disappear as counters; "decided but not delivered" is derived from
`decision is not None` on an `open` row — the same information without the stored statuses.

### `review-loop/SKILL.md`

Prints `stats` at convergence: labels change, logic does not.

## Testing

Because nothing has run against a real PR and cannot until a release exists, the suite is the
verification rather than a net under it.

**The centerpiece: the whole transition table.** The model is now small enough to cover
exhaustively instead of case-by-case: `status` (2) × `platform_state` (3) × this round's
observation (present-unresolved / present-resolved / absent) = 18 combinations, each asserting the
resulting (`status`, `platform_state`, `is_working`). Exhaustiveness holds by construction — adding
a value to either axis stops the table from covering everything unless it is extended
deliberately. The audit found six uncovered transitions precisely because tests were written one
per noticed case.

**New invariant tests:**

- `test_reconcile_never_writes_status_from_platform_state` — a row with a decision; the platform
  walks `live` → `resolved` → `absent` → `live`; `status`, `decision`, `reason` and
  `followup_task_id` stay byte-identical.
- `test_record_never_writes_platform_state` — `record` with every field set leaves it alone.
- `test_a_decided_but_undelivered_row_is_not_settled_by_a_platform_resolve` — the bug that started
  this: record `open` + `decision: fix` + `reason: push deferred`; the next round reports the
  thread resolved; `status` is still `open`, the decision intact, the row out of the working set on
  the platform axis only, and back with its decision once un-resolved.
- `test_done_without_thread_mark_is_rejected_on_a_threaded_row` — whole batch rejected, ledger
  unchanged; plus `test_done_without_thread_mark_is_allowed_for_a_github_summary`.
- `test_collect_aborts_when_resolution_cannot_be_determined` — exit 4, nothing written; plus the
  pagination-anomaly variant.
- Retry wrapper, with `sleep` patched: success on the second attempt; exhaustion raising after
  three; fast failure on a deny-list signature **without** sleeping; the longer pause on rate
  limiting.
- The `resurfaced` helper, directly.

**Deleted** (the behavior no longer exists): `test_pending_and_skipped_are_written_verbatim`,
`test_pending_and_skipped_rows_stay_in_the_working_set`, the three tri-state `resolved` tests
(`test_resolved_none_leaves_a_done_rows_status_untouched`,
`test_resolved_none_leaves_an_open_rows_status_untouched`,
`test_an_unknown_round_does_not_erase_the_remembered_resolution`), the collector tests asserting
`resolved: None` on a failed side-query, and
`test_settling_a_row_by_resolution_accounts_for_the_replies_already_in_the_thread`.

**Rewritten** (same intent, new representation): the resolve / un-resolve and vanish / reappear
tests assert `platform_state` transitions and working-set membership instead of `status`;
`test_resolved_true_seeds_a_new_row_as_done` becomes "seeds `open` + `platform_state: resolved`";
the two tests that currently pin the empty-mark re-open loop become rejection tests.

**Contract tests** (`test_flow_skill_contracts.py`): update those keyed on removed prose (the cap
section, the `skip` invariant, the 5.7a table) and add ones pinning the new prose — the three-way
Phase 3 dispatch, the reason-required-iff-reply-target rule, the absence of a cap, and the
collector-abort edge case.

Order of magnitude: ~15 tests deleted or rewritten, 15–20 added; the exact count falls out of
implementation.

## What this supersedes

From `docs/superpowers/specs/2026-07-22-review-ledger-design.md`, the following are **cancelled**;
that document stays as the record of what was decided then and is not rewritten:

- `:244-252` — the status enum and its "in working set?" table. Statuses are now `open` / `done`;
  membership is `status == "open" and platform_state == "live"`.
- `:254` — "Working set = every non-`done` row." Superseded by the predicate above.
- `:256-258` — the terminality clause naming `skipped` and `pending` as non-terminal re-surfacing
  statuses. Both statuses are gone; the states they described are `open` rows carrying a
  `decision`.
- `:532-534` — resolution tracking listed as out of scope (elf.48). It shipped, and this document
  is its specification.

The 2026-07-22 document also never described the `deleted` status or the `resolved` field at all —
both were added during implementation. Neither exists after this change (`deleted` becomes
`platform_state: absent`, `resolved` becomes `platform_state: resolved`), so the drift closes
rather than needing a retrofit.

Unchanged from that document: identity and ref allocation (allocate-once, gappy working set), the
ledger's location outside the working tree, atomic temp+rename writes, the no-locking concurrency
decision (`:476-489`), and — as amended earlier in this PR — the purge gate keyed on the PR's
terminal state.

## Non-goals and accepted edges

- **No format migration.** Zero ledgers exist. `SCHEMA` is not bumped and no schema check is added:
  a guard that never fires in production is not worth testing. The `schema` field stays in the
  document, since that is the part that cannot be added retroactively. If the format changes again
  before release, the remedy is `rm -rf ~/.cache/flow/review-ledger`.
- **A resolved row that then vanishes becomes `absent`,** losing the knowledge that it had been
  resolved; in `stats` it moves from "Resolved upstream" to "Deleted upstream". That is an accurate
  description of reality — the thread is gone — and if it returns unresolved we fall to `live` and
  re-triage.
- **Per-host resolution capability is not built.** See "Collector failure semantics".
- **Concurrency is still unsupported**, per the 2026-07-22 decision: two `review-comments` runs on
  one PR corrupt the platform replies regardless of any ledger locking.
