# Persistent per-PR review ledger — design

**Task:** claude-tools-elf.39 (Persistent per-PR review ledger for flow:review-comments)
**Date:** 2026-07-22 (redesigned 2026-07-23 after empirical review; refined 2026-07-24 —
`get` read primitive, `kind` field, stable cross-round refs)
**Status:** approved, pending implementation plan

## Revision note (why this design was rewritten)

The original design centred on a **content-key recurrence detector**:
`content_key = sha256(path + normalize(body))`, used to spot a reviewer re-flagging the same
finding under a fresh id, with a `normalize()` that stripped `<details>` blocks, markdown links,
digit/hex runs, etc. An empirical review of real PR data killed that approach:

- **Sample:** six Codex PRs (#113, #112, #107, #100, #96, #109 — ~90 bot root findings) and three
  CodeRabbit PRs (#85, #86, #82).
- **Literal recurrence ≈ 0.** Zero findings were re-flagged under exact `(path+title)` or content
  hash across all six Codex PRs (confirmed deterministically and by five independent semantic
  passes). Codex does not re-post a finding; after each fix it emits a **new, distinct**
  "evidence-driven follow-up" finding (new title, body, line, sometimes path). A content-key
  recurrence detector would fire **~0 %** of the time and is contested even conceptually (is an
  evidence-driven follow-up a "recurrence" to suppress, or a legitimate new defect? reviewers
  disagree — and the key catches neither).
- **`<details>` stripping is actively wrong for CodeRabbit.** All of CodeRabbit's actionable
  content (nitpicks, outside-diff findings, suggested-fix diffs) lives **inside** `<details>`;
  stripping it collapses every summary to `Actionable comments posted: N` — distinguished only by a
  small integer — causing false-positive collisions across rounds and across PRs. The naive
  `<details>.*?</details>` regex is also broken on CodeRabbit's up-to-4-level nesting.
- **`commit_id` is not a round marker** — it is the blame-anchor commit of the commented line, not
  the reviewed HEAD (one commit id appears on comments from four different dates on PR #113).
- **Won't-fix ping-pong not observed** — across all six PRs no declined finding was re-raised by the
  bot in a later round, so the classic "suppress a re-raised finding" case never triggered.
- **Codex summaries are pure boilerplate** (621-char body, identical modulo the commit SHA);
  **CodeRabbit summaries are the opposite** (content inside `<details>`) — a normalizer cannot serve
  both.

The redesign therefore **drops content-key / normalization entirely** and repurposes the ledger as
**durable per-PR working memory keyed only by thread-id**, promoted to the **single working surface**
for `flow:review-comments` (the ephemeral collector snapshot is consolidated into it). This still
closes elf.31 (deterministically, via thread-id on rerun), gives the analysis agent prior-decision
history for free, and adds durable status tracking, stats, and post-completion cleanup — without any
fragile content matching.

## Goal

Give `flow:review-comments` durable, per-PR memory of every finding and what was decided about it,
surviving `/clear`, new sessions, and re-runs, so that across rounds it:

1. **Excludes** findings already terminally handled (durable, no re-triage on rerun).
2. **Re-surfaces** a finding when its thread advances — a reviewer objects, a reviewer acknowledges,
   or **the human posts an instruction** — and hands the agent the full prior context.
3. **Does not create duplicate follow-ups** for a re-imported summary on rerun (subsumes elf.31),
   deterministically via thread-id.
4. Reports cumulative per-PR statistics at the end of a round and at loop convergence.
5. Gives every finding a **stable `ref`** that identifies it across all rounds, so history, stats,
   and re-surfaced threads can reference a finding from an earlier round unambiguously.

And makes the ledger the one surface the skill's phases read, instead of juggling a separate
collector snapshot plus a side cache.

## Non-goals (empirically justified)

- **Content-key / semantic recurrence detection.** Fires ~0 % on real data; normalization is
  unserviceable across Codex and CodeRabbit. Cut.
- **Suppressing "evidence-driven follow-ups."** These are legitimately distinct findings; the ledger
  must *not* collapse them.
- **Won't-fix ping-pong suppression as a dedicated mechanism.** Not observed; the generic
  thread-advance / history model covers it if it ever occurs.
- **Edit detection of an existing comment body.** Reviewers should file a new comment, not edit;
  we ignore body edits (a changed body under an existing reply id does not re-surface — only a *new*
  reply id does). This is lost in manual review too.

## Architecture — the ledger is the single working surface

```
flow-review-collect ──(transient metadata.json)──► reconcile ──► LEDGER (pr-<n>.json)
                                                                    │
                              Phases 2–5 read one row at a time via `get` / flow-comment-card
                                                                    │
                                                    record ──► LEDGER (write-back)
```

- The collector stays a **pure fetch → stdout** tool; it knows nothing about the ledger. Its output
  (`metadata.json`) is demoted from "the skill's working file the phases read" to **the transient
  input of `reconcile`**.
- `reconcile` ingests the collector output and **upserts it into the ledger**: it refreshes the
  *current-snapshot* fields on each row, preserves the *durable* fields, **allocates a stable `ref`
  on first insert** (never reassigned), advances the round counter, and emits the working set (ref
  list + counts) to stdout.
- Downstream phases never open the whole ledger. Each reads **one row at a time by stable `ref`**
  through a single row-lookup: the Phase-3 subagents consume a per-ref extract emitted by
  `flow-review-ledger get`; the Phase-4 cards use `flow-comment-card` (same lookup); the Phase-5
  replies read the row's reply target the same way. A per-PR ledger holds only a few dozen rows, but
  it is durable and grows across rounds (it also carries `done` rows and full thread histories), so a
  single-row extract keeps subagent context small and the read robust as the document grows.
- `record` writes status transitions back to the ledger after the replies.

### Graceful degradation

`reconcile` rebuilds the current-snapshot fields from the fresh collector output **every round**, so
a missing / corrupt / purged ledger degrades cleanly: current working data is always reconstructed
from the platform; only durable memory (prior decisions / history) is lost. The platform is the
source of truth for what exists now.

## Storage

**Path.** `<cache-base>/flow/review-ledger/<host>/<project-path…>/pr-<n>.json`

- `<cache-base>` is resolved cross-platform, stdlib only (no `platformdirs`):
  - Windows (`os.name == "nt"`): `%LOCALAPPDATA%` (fallback `~/AppData/Local`).
  - POSIX: `$XDG_CACHE_HOME` (fallback `~/.cache`).
  The `flow:*` **skills** remain POSIX-only per `plugins/flow/README.md` (that is out of scope to
  change here); the **helper** is path-portable so it never crashes and uses the idiomatic Windows
  cache if ever run there. Under WSL the Linux path applies.
- `<host>/<project-path…>` are **nested directories mirroring the repo path**, derived from
  `unit.url`, so collisions are impossible by construction (no flattening, no hash):
  - GitHub `https://github.com/owner/repo/pull/42` → `github.com/owner/repo/`.
  - GitLab `https://gitlab.com/group/sub/proj/-/merge_requests/7` → `gitlab.com/group/sub/proj/`.
  - The route marker (`/pull/` or `/-/merge_requests/`) delimits the project path; the host is
    included (so `github.com/foo/bar` and a GHE `foo/bar` never collide); host is lowercased, path
    segments keep their API-canonical case; each segment is minimally sanitised (reject `.`, `..`,
    empty). Windows reserved device names (`con`, `nul`, …) as a segment are an accepted,
    documented native-Windows-only edge — not special-cased.
- `<n>` is the PR number (GitHub) / MR **iid** (GitLab). The iid is project-scoped but the project
  directory already disambiguates it, so `pr-<iid>.json` never collides across GitLab projects.

**Why outside the working tree (unchanged, still decisive).** The ledger must never be committable
or pushable: committing it would advance the head SHA (breaking `flow:review-loop`, whose
convergence is decided purely by head advancement) and put a ledger-about-the-PR inside the PR diff.
`~/.cache` (etc.) is a **structural** guarantee — no `git` operation from the repo can stage it.
Precedent: statuskit already writes to `~/.cache/statuskit/`.

**Format: a single JSON document per PR**, rewritten in place (load-modify-write), keyed by
`thread_id`. JSONL's append/merge rationale is gone (we mutate one row per thread, refresh nested
threads, and never fold); a single JSON document fits load-modify-write, O(1) lookup by thread-id,
and nested threads natively. Rejected: SQLite (overkill, opaque, migrations for a few-dozen-row
per-PR cache), TOML/YAML (config formats / non-stdlib).

**Writes are atomic** — temp file + `os.replace` (mirroring statuskit's
`NamedTemporaryFile(dir=cache_dir)` → `.replace()`), so a crash mid-write never yields a half-written
file. A corrupt document is read as an empty ledger (degrade path above).

**No locking.** There is no legitimate concurrent-write scenario (see Concurrency), so atomicity
(anti-corruption) is sufficient; lost-update under true concurrency is out of scope by construction.

## Ledger schema

Top-level document:

```jsonc
{
  "schema": 1,
  "unit": { "platform": "github", "number": 96,
            "url": "https://github.com/NoNameItem/claude-tools/pull/96" },
  "round": 3,
  "next_ref": { "U": 2, "C": 8 },
  "rows": { "<thread_id>": { /* one row per thread, shape below */ } }
}
```

- `round` — a per-PR **round counter**, incremented once per `reconcile` (i.e. once per
  review-comments run on this PR). This is the round marker (replacing wall-clock / `commit_id`,
  which are unreliable).
- `next_ref` — per-PR **monotonic ref counters**, one per prefix (`U` for humans, `C` for bots).
  `reconcile` draws from these to stamp a **stable** `ref` on a row the first time it is inserted,
  then increments the counter; an existing row keeps its `ref` forever (see *Stable refs* below).

Row (keyed by `thread_id`):

```jsonc
{
  "thread_id": "3517637493",
  "platform": "github",

  // set-on-insert, immutable identity fields
  "ref": "C1",
  "kind": "inline",

  // current-snapshot fields — refreshed by reconcile every round
  "path": "plugins/flow/bin/x", "start_line": 50, "line": 61,
  "outdated": false, "is_bot": true, "already_replied": false,
  "diff_hunk": "...", "snippet": null, "side": "RIGHT", "position": null,
  "body": "...current root body...",
  "thread": [ { "user": "...", "body": "...", "id": "3518155060",
               "created_at": "...", "is_bot": true } /* , more replies */ ],

  // durable fields — preserved by reconcile, written by record
  "status": "done",
  "decision": "fix",
  "reason": "...rationale (feeds history + reply text)...",
  "followup_task_id": null,
  "thread_mark": "3518155060",
  "first_seen_round": 1, "last_round": 3,
  "head": "...last head that touched the row (reference)..."
}
```

- **`thread_id`** — the platform thread id: `comment_id` (GitHub inline), `discussion_id` (GitLab),
  or `summary_id` (GitHub review body). The **only** identity key (no content key).
- **Set-on-insert, immutable fields** (stamped when the row is first inserted, never changed
  afterwards):
  - **`ref`** — the row's **stable** handle (`U`/`C` prefix + number from `next_ref`). Allocated once
    on first insert and never reassigned or reused, so it identifies the same finding across every
    round (see *Stable refs*).
  - **`kind` ∈ {`inline`, `file`, `summary`}** — the comment's shape, from the collector: `inline`
    (anchored to a line), `file` (GitHub `subject_type: file` — path set, no line), `summary` (review
    body / general discussion — no thread). This is the **logical** discriminator: "has a thread" =
    `kind != summary`; the analysis branches (summary / file-level / inline) and the re-surface rule
    key on it, replacing indirect tests like `path == "(summary)"` or `thread_mark == null`. (The
    `"(summary)"` string survives only as a card *location* label, not as a logical signal.)
- **Current-snapshot fields** (refreshed by `reconcile` every round from the collector):
  `path`, `start_line`, `line`, `outdated`, `is_bot`, `already_replied`, `diff_hunk`,
  `snippet`, `side`, `position`, `body`, `thread`.
- **Durable fields** (preserved by `reconcile`, written by `record`):
  `status`, `decision`, `reason`, `followup_task_id`, `thread_mark`, `first_seen_round`,
  `last_round`, `head`.
- **`thread_mark`** — id of the last thread reply we have accounted for. `null` for a `summary` (no
  thread). Drives re-surfacing (below).

### Stable refs (allocate-once)

A `ref` is a **durable per-PR handle to a thread**, not a per-round display index. `reconcile`
allocates it **once**, from `next_ref[prefix]`, the first time a thread is inserted (`prefix = C` if
`is_bot` else `U`, stable for the thread's lifetime), then increments that counter. An existing
row's `ref` is never reassigned and a number is never reused, so:

- **Cross-round reference works.** "The C3 that was won't-fixed in round 1" still means C3 in round
  5. History, `stats`, and the re-surface flow can cite a ref and mean one specific finding —
  which is the whole point of a durable ledger. Per-round reassignment (the prior draft) actively
  broke this: `C1` meant a different finding each round.
- **`done` rows keep their ref.** Every thread that ever entered the ledger retains its number even
  after exclusion, so nothing dangles when history points back at it.
- **A re-opened row returns with its original ref.** When a `done` thread re-surfaces (reviewer
  objects, human instructs), it re-enters the working set as its original `C3`, not a fresh number.

**Cost, accepted.** The per-round working set is the sparse `status != done` subset of all rows, so
the refs shown in a round's cap table are **no longer contiguous** — a round may display `C2, C5,
C7` because `C1/C3/C4/C6` are already `done`. This replaces the prior draft's promise that "refs are
contiguous and never point at excluded rows". The gaps are informative (a gap = a settled finding);
display **order** is unchanged (Phase 2's file/severity ordering), only the numbers are now stable.

## Status model

`status ∈ { open, skipped, pending, done }`, plus `decision ∈ { fix, wont_fix, follow_up, outdated,
skip } | null`.

| status | meaning | in working set? |
|---|---|---|
| `open` | collected, not yet triaged (fresh finding) | yes |
| `skipped` | user triaged "not now" — honestly marked, re-surfaces | yes |
| `pending` | decided, but the reply/action was withheld (push skipped) — re-surfaces to complete | yes |
| `done` | decided **and** the action completed (reply posted / task filed / no reply target) | **no** (excluded) |

**Working set = every non-`done` row.** Exclusion from the next round = `status == done`.

**Terminality:** a row is `done` only for `decision ∈ {fix, wont_fix, follow_up, outdated}` with the
action completed. `skip` is **not** terminal (it re-surfaces as `skipped`); a withheld action is
**not** terminal (it re-surfaces as `pending`).

### Re-surfacing via `thread_mark` (the thread lifecycle)

A `done` inline row re-opens **iff a new reply appears** — i.e. the current thread contains a reply
with `id > thread_mark`. This single rule handles all three real thread continuations uniformly:

| Last message in thread | reconcile | agent |
|---|---|---|
| reviewer **objects** | new reply id → reopen | reconsiders → fix / won't-fix → reply → `done` |
| reviewer **acknowledges** (e.g. PR #96 Codex "already fixed") | new reply id → reopen | "nothing to do" → `done` + advance `thread_mark` |
| **human posts an instruction** | new reply id → reopen | reads the instruction from the thread → executes → reply → `done` |

Two subtleties this design pins down, both grounded in real PR #96 data:

- **No reopen loop.** When the agent settles a re-opened row it records the **new** `thread_mark`
  (for a settle-without-reply, the current last reply id; for a reply, the id of the reply the agent
  just posted). Next reconcile sees `thread_mark` unchanged → the row stays `done`. Without this, a
  bot's acknowledgement (which leaves the bot as the latest replier forever) would re-open every
  round indefinitely.
- **Same-account instructions are visible.** The agent's replies and the human's manual comments
  come from the **same** authenticated account, so `already_replied` (latest == me) cannot
  distinguish them. Keying re-surfacing on the reply **id** (not authorship) means a human
  instruction posted after the agent's reply is a new id → reopen, exactly like a reviewer reply.

A `summary` (`kind == summary`) has no thread → a `done` summary never re-opens. On a **rerun**
(same head) a re-imported GitHub summary carries the **same** `summary_id` (review ids are stable
and immutable), so its row is already `done` → excluded → **no duplicate follow-up** (this is the
elf.31 fix, deterministic, no content matching). On a **new round** a genuinely new summary review
has a **new** `summary_id` → a new `open` row → shown; the agent uses `followup_task_id` from prior
rows (visible in history) to avoid duplicating a task if it chooses.

### `already_replied`

Demoted to a **seeding signal only**: when `reconcile` inserts a row for a comment not yet in the
ledger but the platform reports `already_replied == true` (we replied before the ledger existed, or
after a purge), it seeds the row as `done` with `thread_mark` = current last reply id, instead of
`open`. It is **not** the re-surface trigger (that is `thread_mark`), which keeps the model correct
for future long threads.

## Subcommands: `flow-review-ledger`

A new standalone helper (`plugins/flow/bin/flow-review-ledger`), pure stdlib.

### `reconcile --meta metadata.json`

- Resolves the ledger path from `metadata.json`'s `unit.url` + `unit.number` (`$XDG_CACHE_HOME` /
  `%LOCALAPPDATA%` honoured; tests point it at a tmp cache).
- Increments `round`.
- Upserts each `comments[]` item into `rows` by `thread_id`: inserts (stamping `ref` + `kind`,
  seeding status via `already_replied`), carries `pending`/`skipped`, re-opens `done` rows whose
  thread advanced (`id > thread_mark`), refreshes current-snapshot fields on all.
- **Allocates a stable `ref` on first insert only** — draws from `next_ref[prefix]` (`prefix = C` if
  `is_bot` else `U`), stamps the row, increments the counter. Existing rows keep their `ref`; a
  re-opened `done` row re-enters the working set with its original `ref`. Nothing is reassigned per
  round, so the working set's refs are the sparse (gappy) `status != done` subset (see *Stable
  refs*).
- Writes the ledger atomically; emits the working set (ref list + `counts`) to stdout for the skill.
- Missing / corrupt ledger → treated as empty (all findings `open`, or `done` by seeding). Never
  crashes.

### `get --ref <ref> [--meta metadata.json | --url <u> --number <n>]`

- Resolves the ledger path (from `--meta`'s `unit`, or explicit `--url --number`), finds the row
  whose `ref` matches, and prints **that one row as JSON** to stdout. Ref not found → non-zero exit
  with a stderr message.
- Emits the **raw row** (all fields), not a rendered card: the Phase-3 analysis subagent needs the
  structured fields — `body`, `thread`, `diff_hunk`, `snippet`, `path`, `line`, plus the durable
  `decision` / `reason` / prior-thread history for a re-opened finding.
- This is the read primitive that keeps every consumer off the whole document: the skill runs
  `get --ref C1 > row-C1.json` and the subagent Reads the small extract, instead of opening the
  growing per-PR ledger and hand-locating a ref.
- **Shared lookup.** `get` and `flow-comment-card --ledger … --ref` resolve a row through the **same**
  `load_ledger` + `find_row_by_ref` code (one implementation, two entry points), so the row a
  subagent analyses and the row a card renders can never diverge.
- Read-only; no untrusted data reaches a shell (path in, JSON out).

### `record --meta metadata.json --decisions decisions.json --head <sha>`

- Reads a per-ref decisions file the skill writes:
  `{ "<ref>": { "status", "decision", "reason", "followup_task_id", "thread_mark" } }`.
- Applies the transitions to the matching rows (by `ref` → `thread_id`), stamps `last_round` and
  `head`, writes atomically.
- Free-text (`reason`) arrives via file, never a shell (untrusted-data rule).

### `stats --url <u> --number <n> [--last-round]`  (or `--meta metadata.json`)

- Folds the ledger; prints a cumulative per-PR summary. `--last-round` filters to
  `last_round == round` for the most recent pass's delta.
- Takes explicit `--url --number` because it is also called where no `metadata.json` exists
  (review-loop convergence); `--meta` is a convenience inside review-comments.

```
Ledger PR #96 (github.com/NoNameItem/claude-tools) — round 5
  Tracked: 18 findings
  Done: 14  (fix 9 · won't-fix 3 · follow-up 1 · outdated 1)
  Pending: 1   Skipped: 1   Open: 2
  Follow-ups filed: 1 (claude-tools-elf.42)
```

### `purge --url <u> --number <n>`

- Resolves the ledger path and unlinks `pr-<n>.json`. Idempotent (missing file → no-op, exit 0).
- Path + unlink only; no untrusted data. Called from `flow:done`.

## `flow:review-comments` SKILL.md integration (phase by phase)

**Phase 0–1 (detect / pull):** unchanged. `baseline-dirty.txt` unchanged.

**Phase 2 (Collect → Reconcile):**
- `flow-review-collect … > metadata.json` (now the transient input to reconcile).
- `flow-review-ledger reconcile --meta metadata.json` → working set (ref list + counts).
- Working set = non-`done` rows (`open`/`skipped`/`pending`). Empty → stop with
  "X already replied, Y handled (ledger), nothing to act on".
- Large-PR cap table built from **ledger rows** (`ref`, `is_bot`, `path:lines`, `outdated`, brief).
  Refs are the **stable** ones from reconcile, so the table may show gaps (`C2, C5, C7`) as findings
  settle — display order is Phase 2's usual file/severity ordering.
- `assign_refs` moves from the collector into `reconcile`, and becomes **allocate-once** (a row's ref
  is stamped on first insert, not recomputed per round).

**Phase 3 (Analyze):**
- The skill materialises a per-ref extract — `flow-review-ledger get --ref C1 >
  $FLOW_RC_DIR/row-C1.json` (one file per ref; for a grouped call, one per listed ref) — and the
  balanced-tier subagent **Reads that single-row file**, not the whole ledger. The row carries the
  current fields *and* the durable `decision`/`reason`/`thread` history, so a re-opened won't-fix
  shows the subagent both the prior verdict and the new reviewer/human reply — no separate history
  subcommand.
- Verdicts remain transient sidecars `$FLOW_RC_DIR/verdict-{ref}.json` (per-round, not durable).
- The existing analysis branches now key on **`kind`** (`summary` / `file` / `inline`) plus the
  `outdated` / deleted-file current fields refreshed by reconcile — preserved, but off the
  `path == "(summary)"` sentinel.

**Phase 4 (Triage):**
- TOC + one card at a time. `flow-comment-card --ledger pr-<n>.json --ref C1 --verdict …` (reads the
  ledger row instead of `--meta metadata.json`; snippet↔diff_hunk override unchanged).
- Decisions accumulate into `$FLOW_RC_DIR/decisions.json` for `record`'s closing sweep (5.7a); the
  refs that produce an external side effect are recorded earlier, as they land (below).

**Phase 5 (Execute + write-back):**
- 5.1–5.3 (fix/apply/self-review) untouched.
- 5.4 follow-up: read the row first — a non-empty `followup_task_id` means an earlier round already
  filed the task, so **reuse it instead of calling `bd create`** — then `bd create` for the rest and
  **checkpoint each created task immediately** (`status: pending`, `followup_task_id`), before the
  next ref. `pending`, not `done`: the task exists but this round's reply is not posted yet.
- 5.7 reply: target (`comment_id`/`discussion_id`) + `platform` read from the ledger row;
  **checkpoint each ref the moment its reply is accepted**.
- **Both loops are sequential and their side effects are irreversible**, so a single `record` after
  the whole batch would lose everything already done when ref *k* fails — and the next round would
  re-file the task / re-post the reply. Hence the per-ref checkpoints, with
  **5.7a — `flow-review-ledger record --meta … --decisions decisions.json --head <HEAD>`** closing
  the round for whatever the checkpoints did not cover: per row set `status`
  (`done`/`pending`/`skipped`), `decision`, `reason`, `followup_task_id`, and `thread_mark` (id of
  the reply the agent just posted, else the current last reply id). Re-recording an
  already-checkpointed ref is a no-op, so the invariant is "no ref left unrecorded", not "each ref
  written once".
- Push skipped → those rows become `pending` (the existing "Reply deferred" line).
- 5.8 report: existing per-run summary **unchanged** + a cumulative `stats` block appended.
- `allowed-tools`: add `Bash(flow-review-ledger:*)` (review-comments already grants `Write`,
  `Read`, `gh`, `glab`, …).

## `flow:review-loop` SKILL.md changes

- Remove the in-session repeat-tracking prose (`SKILL.md` ~171–176 and ~227–230) and the
  `⚠️ <ref> — повторно` round-indicator: recurrence detection was cut, terminally-handled threads
  are now excluded (`done`) before they reach round output, and no won't-fix ping-pong was observed.
  The round indicator itself (round number + head) stays.
- At **clean convergence**, print `flow-review-ledger stats --url … --number …` (cumulative over all
  rounds — the natural end-of-loop summary).
- `allowed-tools`: add `Bash(flow-review-ledger:*)`.

## `flow:done` SKILL.md changes (ledger purge)

- Extend Step 1's `gh pr view --json state,url` → `--json state,url,number`; capture `PR_NUMBER`,
  `PR_URL` + `PR_STATE`. The number is available exactly when purge is relevant (feature branch with
  a PR; a generic branch short-circuits Step 1 and has no PR).
- Fold ledger removal into **Step 8**'s existing single cleanup confirmation, listing the ledger
  among "associated resources". On yes → `flow-review-ledger purge --url "$PR_URL" --number
  "$PR_NUMBER"` (idempotent, non-blocking). **The purge is gated on `PR_STATE` being terminal
  (`MERGED`/`CLOSED`), never on branch deletion** — a branch is routinely kept on purpose after a
  merge (history, re-reading what happened in review), which must not keep a settled PR's ledger
  alive, and a deleted branch says nothing about whether the PR is still taking review. An open
  PR's ledger is retained whatever happened to the branches; an abandoned one self-expires (no GC).
- `allowed-tools`: add `Bash(flow-review-ledger:*)`. No shell `rm`/`mkdir` — the helper unlinks in
  Python.
- **Accepted edge:** a task with multiple `Git:` branches purges only the current branch's ledger;
  the others self-expire (proper multi-branch handling is tracked as **claude-tools-elf.51**;
  GitLab support as **claude-tools-elf.50**).

## `flow-review-collect` change (minimal)

Two additions, both pure platform-state fetch (SRP intact):

- Enrich each `thread[]` reply from `{user, body}` to `{user, body, id, created_at, is_bot}` (GitHub
  `gh_collect`, GitLab `gl_collect`) — lets `reconcile` compute `thread_mark` by reply id.
- Emit **`kind` ∈ {`inline`, `file`, `summary`}** per comment, from the shape the collector already
  distinguishes: a GitHub review-body summary → `summary`; `subject_type: file` → `file`; an anchored
  inline comment → `inline` (GitLab: a discussion with a position → `inline`, a note without one →
  `summary`). `reconcile` copies it onto the row at insert as the immutable `kind`.

No other collector change.

## `flow-comment-card` change

Read the finding from the ledger row: `--ledger pr-<n>.json --ref C1` replaces `--meta metadata.json
--ref C1`, resolving the row through the **same `load_ledger` + `find_row_by_ref`** used by
`flow-review-ledger get` (one lookup, two entry points — the analysed row and the rendered card can't
diverge). The verdict merge (`--verdict`) and the snippet↔diff_hunk override are unchanged; the
fields simply live on the ledger row now. The `(summary)` location label still renders for
`kind == summary`, but comes from `kind`, not from a `path == "(summary)"` sentinel.

## Untrusted-data handling

Unchanged invariant: reviewer/human text (bodies, thread replies, paths, `reason`) is **data, never
shell source**. The helper reads `metadata.json` / `decisions.json` / the ledger by path and builds
argv lists; `get` emits a per-ref row extract that the subagent Reads **by path** (as it read
`metadata.json` before); `ref` / `thread_id` are our own / platform ids, never reviewer-controlled,
so passing `--ref C1` on a command line is safe. Nothing reviewer-controlled reaches a command line.

## Concurrency (no locks)

Writers: `reconcile` (Phase 2), `record` (Phase 5), `purge` (flow:done). The ledger is per-PR
(`pr-<n>.json`), so contention is only possible on the same PR:

- `reconcile`/`record` within one run are sequential phases; Phase-3 subagents **do not** write the
  ledger (invariant — writes go only through single `reconcile`/`record`/`purge` calls from the main
  skill).
- Two `review-comments` on the **same** PR at once is unsupported (self-inflicted; it also corrupts
  the platform replies, not just the ledger).
- Different PRs → different files, no contention.

So there is no legitimate concurrent write. Atomic temp+rename covers the only real risk (crash
mid-write); no locking is added.

## Testing (TDD)

Unit tests for `flow-review-ledger` (`plugins/flow/bin/tests/test_flow_review_ledger.py`):

- Path resolution: GitHub, GitLab (nested groups), GHE host, `pr-<iid>` non-collision across GitLab
  projects; cross-platform cache base (`XDG_CACHE_HOME` on POSIX, `LOCALAPPDATA` on `nt`); degrade
  on empty/missing `unit.url`.
- `reconcile`: insert as `open`; seed `done` from `already_replied`; carry `pending`/`skipped`;
  re-open a `done` inline row when a new reply id appears; **no** re-open when `thread_mark`
  unchanged (the ack-loop case); a `kind == summary` `done` row never re-opens; round counter
  increment; current-field refresh; corrupt document → empty, no crash.
- **Stable refs (allocate-once):** a new row is stamped from `next_ref[prefix]` and the counter
  increments; an existing row keeps its `ref` across a second `reconcile`; a `ref` freed by no row
  is never reused; a re-opened `done` row re-enters the working set with its **original** `ref`; the
  round working set is the sparse (gappy) `status != done` subset; `U`/`C` prefix follows `is_bot`.
- **`kind`:** stamped on insert from the collector, immutable across rounds; `summary` rows get
  `thread_mark == null`; the re-surface / analysis branching keys on `kind`, not `path`.
- `get`: `--ref` hit prints exactly the matching row as JSON; miss → non-zero exit; resolves the path
  from both `--meta` and explicit `--url --number`; shares `find_row_by_ref` with `flow-comment-card`
  (same row for the same ref).
- `record`: status transitions by ref→thread_id; `thread_mark` write-back; `last_round`/`head`
  stamps; atomic write.
- elf.31: a summary follow-up recorded `done` is excluded on rerun (same `summary_id`) → no
  duplicate task.
- `stats`: cumulative and `--last-round` counts.
- `purge`: unlink + idempotent no-op on missing file.

Skill-contract tests (`test_flow_skill_contracts.py`): the `reconcile`/`get`/`record`/`stats`
invocations and `Bash(flow-review-ledger:*)` grants are present in `review-comments`/`review-loop`;
Phase 3 dispatches over a `get`-materialised `row-{ref}.json` (not `metadata.json`); the `purge`
invocation and grant are present in `done` with Step 1's `number` field; the removed repeat-tracking
prose is gone from `review-loop`; `flow-comment-card` is invoked with `--ledger`.

## Related work

- **elf.31** (duplicate summary follow-ups) — closed here, deterministically, via thread-id `done`
  on rerun.
- **flow:review-loop in-session repeat-tracking** — replaced by durable status exclusion; the
  fragile in-memory repeat set is dropped.
- **elf.50** (flow:done GitLab support) and **elf.51** (flow:done multi-branch) — filed separately;
  this design's `flow:done` purge is GitHub-first and single-branch, generalised by those features.
- **elf.48** (auto-resolve answered threads) — still out of scope, but the ledger is a clean input:
  it records, per row, whether a reply was posted (`status`/`thread_mark`) and the thread ids.

## Open questions / accepted edges

- **Reply-deletion vs `thread_mark`.** Deleting a thread reply (rare; bots don't, humans seldom)
  could leave `thread_mark` pointing at a gone id; because we compare `id > thread_mark` and ids are
  monotonic, this at worst misses a re-surface, never loses data. Accepted.
- **Multi-branch `flow:done` purge** and **GitLab `flow:done`** — tracked as elf.51 / elf.50.
- **Windows reserved device-name segments** (`con`/`nul`/…) — native-Windows-only, astronomically
  rare, documented not special-cased.
