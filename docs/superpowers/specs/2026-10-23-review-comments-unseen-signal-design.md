# flow:review-comments — one signal for "needs a look": unseen messages

**Task:** claude-tools-elf.68

**Supersedes parts of:**
- `2026-07-22-review-ledger-design.md` — the status model and the `already_replied` seeding rule;
- `2026-07-30-ledger-lifecycle-simplification-design.md` — the `status` axis, "Decision made, action
  did not land", and "Considered and rejected: deriving the re-open";
- `2026-08-01-review-ledger-seen-set-design.md` — "Why our own replies arrive already seen" (the
  login rule and its recorded cost) and the seeding of a new row's thread;
- `2026-09-04-review-comments-resolve-bot-threads-design.md` — the resolve gate's exemption for
  `me`, and the Risks paragraph built on it.

Everything those documents say that this one does not contradict still holds.

## Why

The decision "does this thread need a look this round?" is spread over five signals in the
collector and the ledger, each added for a real case:

| Signal | Where | Added so that |
|---|---|---|
| `already_replied` (last replier is `me`) → a new row is seeded `status: done` | `flow-review-collect`, `new_row` | a lost or purged ledger does not send every answered thread back for triage |
| `is_ours` (reply author is `me`) → reply arrives `seen` | `_ledger.is_ours`, `merge_thread`, `seed_thread` | a reply we posted but failed to report does not come back as foreign and draw a second reply |
| per-reply `seen` | `merge_thread`, `paint_seen` | a `done` row re-opens on a new reply, not on any growth of the thread |
| `status` (`open` / `done`) + `reopen_if_unseen` | ledger | our verdict, and a decided-but-undelivered action, survive between rounds |
| `platform_state` (`live` / `resolved` / `absent`) | `reconcile` | a resolved or deleted thread leaves the loop |

Three of them — `already_replied`, `is_ours`, and the seeding of `seen` — equate "posted from the
login `me`" with "posted by the agent". The PR owner uses that same account. On PR #151 the owner
answered a fresh Codex inline comment (id 4331923290) from the web UI between two runs; the next
run seeded the new row `done`, painted the owner's reply `seen`, and never showed the thread. On
release 3.1.0 the same thread is dropped by `already_replied` alone. The user noticed; the skill
did not.

**What the owner actually does in a thread.** The owner writes things like "maybe this check is
not needed" or "better do the check this way" — an opinion on the finding, and they expect Claude,
when it processes that finding, to say whether it agrees and why. When the owner is sure a finding
is not worth doing, they resolve the thread instead of commenting.

## Goals

1. **One selection rule.** A thread is in the working set if and only if it is **not resolved on
   the platform** and it holds **at least one message the workflow has not acted on yet** — the
   comment itself or any reply (`seen: false`). Nothing else takes part in selection.
2. **The owner's comment always counts.** A comment the owner posts from the shared account brings a
   live thread into the working set, whether the thread is brand new or the agent already answered
   it.
3. **The agent's replies are recognised by a marker the agent writes**, never by the login.
4. **No deferred state.** Every outcome the round can deliver is delivered in that round. An outcome
   that did not happen (an apply that failed, a follow-up batch the user cancelled) leaves the thread
   unseen, and the next round triages it again with the prior decision as context.
5. **Claude answers the comments in the thread.** For every message in the thread that is new to the
   workflow and not the agent's own, the verdict states whether Claude agrees and why, and the card
   shows that as its own block.

## Non-goals

- **Resolving stays as it is**, apart from one added refusal (see "The resolve gate"): the agent
  still resolves a bot thread after replying to it, and still never resolves a human thread.
- **Edits stay ignored.** An edit in place reaches us only as a new reply, as today.
- Storage location, the untrusted-data rules, atomic writes and the no-locks stance are unchanged.
- **No ledger migration.** The ledger was never released: `af1f02f` (#118) is not an ancestor of
  `flow-3.1.0`, the installed release is 3.1.0, and `~/.cache/flow/review-ledger/` holds no files.
  A ledger written by a development build of master may be dropped (it degrades to an empty
  ledger by the existing `load_ledger` contract) or read as-is; nothing has to be converted.

## Transition from 3.1.0

**Accepted as a one-time cost (owner's decision).** Replies release 3.1.0 posted on a PR/MR that is
still open when the new version is installed carry no marker and come from `me`. On the first run
of the new version every such thread that is not resolved enters the working set, the card labels
the old `Fixed: …` / `Won't fix: …` replies as the owner's, and whatever is decided posts another
reply. No legacy recogniser (for example by the agent's reply prefixes) is added. The release notes
say so, and that finishing or merging open PRs before upgrading avoids it.

## Anti-goals

The change fails, even if every test passes, when it:

- posts a **second public reply to messages the agent already answered** — a reply when nothing new
  arrived since our last one (a lost reply report, a lost ledger). A reply to a message that arrived
  after our last reply is not a duplicate; it is the point of the change;
- lets an owner's comment in a **live** thread pass without the thread reaching the working set;
- grows a new **"pending" / "deferred" / "status"-like signal** back into selection;
- files a **second follow-up task** for the same finding.

## The model

### Selection

```python
def has_unseen(row) -> bool:
    return not row["seen"] or any(not reply["seen"] for reply in row["thread"])

def is_working(row) -> bool:
    return row["platform_state"] == "live" and has_unseen(row)
```

`is_working` stays the one answer to "is this row still work?" — `reconcile`, `counts_of` and
`fold_stats` all go through it, as today.

**`platform_state` stays stored**, written only by `reconcile` from the snapshot (`live`,
`resolved`, or `absent` for a tracked thread missing from the snapshot). It is a fact about the
platform, not a judgement, and it has to be on the row because `stats` and `review-loop` read the
ledger without a fresh snapshot.

**Removed:** `status` and `STATUSES`; `reopen_if_unseen`; `already_replied` (collector item,
collector `counts`, `SNAPSHOT_FIELDS`); `_ledger.is_ours` and every login comparison used to set
`seen`; the "do not re-litigate" branch of Phase 3.

**On the earlier rejection of a derived re-open** (lifecycle doc): the objection was that a stored
`status: done` would contradict a row that is in fact working. With no `status` on disk there is
nothing to contradict: the stored `seen` bits are the state, and `is_working` reads them.

### The comment itself carries `seen`

Today only replies have the bit, so a new thread's novelty is expressed through `status: open`. The
row gets a `seen` bit for the comment itself, with the same meaning as a reply's: *the workflow has
acted on this thread with this message in front of it.* A new row starts `seen: false`.

My call: a row-level `seen` next to `body`. The builder may instead store the comment as the first
entry of the message list if that simplifies consumers, as long as the semantics are identical.

### Who writes `seen`

Three writers. None of them looks at the login alone.

1. **`record`, when the round delivered the thread's outcome** — a reply was posted, or the thread
   was settled with no reply (a GitHub review-body summary, which has no reply target). It paints
   the comment and every stored reply `seen`, and appends the posted reply `seen`, as `paint_seen`
   does today. **When the outcome was not delivered** — the apply failed, the follow-up batch was
   cancelled — `record` stores `decision` / `reason` / `followup_task_id` and **paints nothing**, so
   the thread is back next round with its decision as context. Which of the two applies is an
   instruction on the `record` call (for example, the presence of `reply`, or an explicit
   `"settled": true` in the decisions entry) and is never stored on the row; the API shape is the
   builder's call.
2. **`reconcile`, on arrival.** A reply that carries the agent marker **and** is authored by `me`
   arrives `seen` — this is what replaces `is_ours`: a reply we posted but failed to report still
   cannot come back as foreign. Every other reply arrives unseen, **including the owner's**.
3. **`new_row`, for a thread the ledger never held.** If the thread already contains an
   agent-marked reply, the comment and every reply up to and including the last agent-marked reply
   arrive `seen`; replies after it arrive unseen. This replaces the `already_replied` seeding.
   - It applies **only to new rows.** Applied to a row the ledger already holds it would bring back
     C2 from the seen-set doc: a reviewer reply posted during triage would be painted by our later
     reply.
   - In practice it fires on a lost ledger (cache cleared, or a corrupt file degraded to empty):
     the collector refuses merged PRs and `flow:done` purges only on `MERGED`. It is kept anyway,
     because the failure it prevents is public — re-triaging every answered thread posts a second
     reply into each.
   - It does **not** fire for threads answered by release 3.1.0: those replies carry no marker. See
     "Transition from 3.1.0".

The C2 race stays closed by the same mechanism as today: `record` paints only what the row stores,
and a reply posted after the round's collect is not stored yet, so it arrives next round unseen.

### The agent marker

- Every reply the agent posts ends with a fixed, invisible marker — an HTML comment such as
  `<!-- flow:review-comments -->`. It is added in **one place** that every reply path goes through
  (a helper, or a single step in 5.7), so no path can forget it.
- It counts **only together with `author == me`**: a bot that quotes our reply cannot make its own
  message look like ours.
- **The builder verifies on GitHub**, on this task's own PR, that the API returns the reply body
  with the marker byte-for-byte and that the web UI does not render it — post a test reply, check
  both, delete it. If either fails, stop and bring it back rather than inventing a different marker
  silently. **GitLab is not re-checked:** the owner already verified, in another project's skill,
  that GitLab keeps such markers in the API body and does not render them.
- `flow-comment-card` strips the marker before rendering and labels the reply as the agent's.
- Where the marker is recognised (a per-reply flag set by the collector, or a check in `reconcile`)
  is the builder's call — one place.

### The resolved prefilter

A resolved thread never enters the working set, whatever its `seen` bits. Replies that arrive in a
resolved thread are still stored, unseen, so if the thread is un-resolved later they bring it back.
**Behaviour change, accepted by the owner:** un-resolving a thread in which everything is already
seen no longer returns it — there is nothing new in it to look at. Today un-resolving alone returns
the row.

## The resolve gate

Today `flow-review-resolve-gate` refuses when a human **other than `me`** replied. Under this model
that exemption reproduces the bug through another door: the owner comments in a bot thread while a
round is in progress, after collect; the gate sees only `me`, the thread is resolved, and the
prefilter hides the owner's comment for good.

**Added refusal:** the gate refuses when the live thread holds a message authored by `me` **without
the agent marker** that **this round did not hold** — not present in `metadata.json`'s thread for
that item. The gate's live query therefore needs the comment ids and bodies, not only the authors
it reads today.

**My call:** an owner message the round **did** hold does not block resolving a bot thread. The
owner triaged that finding with their own comment on the card and chose the outcome; the thread is
theirs to close, and they closed it through the decision. A human other than `me` still blocks, as
today.

## Phase 3 and the card: answering the thread

- **Row extract.** Every message carries `seen`. Each reply is identifiable as the agent's (author
  `me` + marker), the owner's (author `me`, no marker), another person's, or a bot's.
- **Verdict.** For every **unseen reply that is not the agent's** — the owner's, another reviewer's,
  or a bot's pushback — the verdict carries Claude's stance on it (agree / disagree / partly) with
  the reasoning. The recommendation (fix / won't-fix / follow-up) is decided from the finding and
  those replies together. If the owner proposed how to fix it and Claude agrees, the fix follows the
  owner's proposal. The comment itself is answered by the verdict as a whole, as today. The exact
  verdict field shape is the builder's call.
- **Row shapes in Phase 3** shrink from three to two: `decision` null → analyse from scratch;
  `decision` set → take `decision` + `reason` as the prior verdict, read the unseen messages as what
  changed since, decide from both. The "decision set, not resurfaced → do not re-litigate" branch is
  deleted: there is no deferred state left to deliver.
- **Card.** The thread renders as today, with `[new]` on every unseen message — **the comment itself
  included** — and the owner's replies labelled as the owner's, the agent's as the agent's. A
  separate block after the thread lists each answered reply with Claude's stance and reasoning,
  then the take and the recommendation follow. Illustration only; the layout is the builder's:

  ```
  ↳ [new] NoNameItem (you): maybe this check is not needed — the path is always ours
  ...
  On the thread:
    you — partly agree: the path is ours today, but setup() also accepts --config; keep the check
          for that entry point only.
  ```

## Phase 5: no deferred state

Every reply goes out in the round its decision is made. The one reply that today waits for a push
gets an honest variant instead:

| Outcome this round | Reply | Thread painted `seen` |
|---|---|---|
| fix, pushed | `Fixed: …` | yes |
| fix, push skipped or failed | a local-commit variant — states the fix is committed locally (short sha) and not yet pushed | yes |
| `outdated_fixed`, branch not ahead of remote | `Fixed in subsequent commits` | yes |
| `outdated_fixed`, branch ahead of remote | the same local-commit variant | yes |
| won't-fix | `Won't fix: …` | yes |
| follow-up filed | `Filed as follow-up: {task-id}` | yes |
| GitHub review-body summary (no reply target) | none | yes |
| apply failed | none | **no** — `decision` + `reason` recorded |
| follow-up batch cancelled | none | **no** — `decision` recorded |

- The local-commit wording is the builder's; it must never claim the change is on the remote.
- **A threaded row has no no-reply settlement** (owner's decision). The "acknowledgement with
  nothing to do → settled with no reply" line of today's 5.7a goes, and Phase 4 keeps its three
  options. A thread that comes back on a bare acknowledgement ("Thanks!", "LGTM") is handled like
  any other: bot threads are resolved automatically after the agent's reply, and the owner resolves
  any other thread by hand when it needs no answer. The GitHub review-body summary, which has no
  reply target at all, stays the only row settled without a reply.
- **The public reply states the outcome for the finding** (my call). Claude's stance on the
  owner's own comment lives on the card, which the owner reads; when another reviewer's reply
  brought the thread back, the reply text may address it, as today.
- **A follow-up filed whose reply was never posted** (the session died between 5.4 and 5.7) leaves
  a row with `followup_task_id` set and nothing painted. The next round triages it again. If the
  decision is `follow_up` again, 5.4 **reuses the stored `followup_task_id`** and only the reply is
  posted — no second task. If the decision changes, the stored id is cleared as today, and 5.8
  reports the task as possibly orphaned.
- The 5.4 and 5.7 checkpoints stay: each irreversible side effect is recorded the moment it lands.
- A bot thread may be resolved after any posted reply, the local-commit variant included.
- 5.7a's decisions file loses `status`. The "Reply deferred (push skipped)" line in 5.8 goes; a
  "committed locally, not pushed" count may replace it.

## `stats`

The four buckets still partition the rows:

| Bucket | Rows |
|---|---|
| Settled | nothing unseen (any `platform_state`) |
| Open | `is_working` — live and something unseen |
| Resolved upstream | resolved, something unseen |
| Deleted upstream | absent, something unseen |

Decision tallies count settled rows. "Decided but not delivered" becomes "open with a decision" —
the apply-failed and cancelled cases. Wording is the builder's.

## Consumers to update

- `flow-review-collect`: `already_replied` on every item and in `counts`; the module docstring.
- `flow-review-ledger`: `new_row`, `seed_thread`, `merge_thread`, `reopen_if_unseen`,
  `validate_decisions` / `RECORD_FIELDS` (`status`), `paint_seen`, `counts_of`, `fold_stats`,
  `render_stats`, the module docstring and the `record` parser description.
- `_ledger.py`: `STATUSES`, `SNAPSHOT_FIELDS` (`already_replied`), `is_working`, `is_ours`,
  `unseen` / `resurfaced` (the comment's own bit).
- `flow-review-resolve-gate`: the added refusal and the richer live query.
- `flow-comment-card`: `[new]` on the comment itself, owner / agent labels, marker stripping, the
  "on the thread" block.
- `review-comments/SKILL.md`: the Flow-shape overview; Phase 2's empty-working-set message and the
  "`done` is the only terminal status … never assigned by `reconcile`" paragraph; the Phase 3
  row-shape table and the "An instruction you post from our own account does not re-open a settled
  row" paragraph; the 5.6 withholding rule; the 5.7 reply table and the `already_replied` paragraph
  (~line 1040); the 5.7 resolve-gate description; the 5.7a tables and example (including the
  "acknowledgement with nothing to do" settlement, which goes); 5.8's lines; Red
  Flags and Rationalizations that mention withholding; the "All Comments Already Replied" edge case.
- `review-loop/SKILL.md`: its references to `stats` output and to withheld replies, if any.
- Tests: `test_flow_review_collect.py`, `test_flow_review_ledger.py`,
  `test_flow_review_resolve_gate.py`, `test_flow_comment_card.py`, and the SKILL.md contract tests
  in `test_flow_skill_contracts.py`.

## Testing

Regression first — each of these fails on master today or guards a removed signal:

1. **PR #151.** A new bot thread holding one reply by `me` without the marker, with no ledger row →
   in the working set; the comment and the reply are both unseen; the card shows the reply as the
   owner's, `[new]`.
2. **Owner answers an answered thread.** A row painted seen, then a new unmarked reply by `me` →
   back in the working set.
3. **Lost reply report.** Our marked reply arrives with an id the row does not hold → `seen`, the
   thread stays out of the working set.
4. **Spoof.** A bot reply quoting the marker → unseen.
5. **Lost ledger.** No ledger, a thread ending in our marked reply → nothing unseen, out of the
   working set; the same with a reviewer reply after ours → only that reply unseen.
6. **C2 race.** A reply posted after collect, before `record` → unseen next round.
7. **Resolved prefilter.** A resolved thread with unseen messages → out; un-resolved → in.
   Un-resolving a fully seen thread → out.
8. **Failed outcomes.** `record` without a delivered outcome stores `decision` / `reason` and paints
   nothing → in the working set next round with the decision.
9. **Push skipped.** The local-commit reply is posted with the marker and the thread is painted
   seen.
10. **Follow-up reuse.** A row with `followup_task_id` and nothing painted, decided `follow_up`
    again → no new task (skill contract).
11. **Resolve gate.** A live unmarked `me` message the round did not hold → exit 3; one it did hold
    → no refusal on that account; another human → exit 3 as today.
12. **`stats`** partitions every row into exactly one bucket.

## Acceptance

- The PR #151 scenario, replayed against fixtures, puts the thread in the working set and the card
  shows the owner's reply.
- Selection reads only `platform_state` and `seen`; no login comparison decides `seen` anywhere.
- No code path or SKILL.md section withholds a reply waiting for a push.
- Every reply the agent posts carries the marker; verified on GitHub (this task's PR) that the
  marker survives the API and is not rendered.
- Phase 3 verdicts and the card answer each unseen non-agent reply with a stance and reasoning.
- `uv run pytest` (all three suites), `uv run ruff check`, `uv run ty check` pass.
