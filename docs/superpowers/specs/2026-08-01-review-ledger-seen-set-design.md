# Review ledger: per-reply `seen` bits instead of a `thread_mark` high-water mark

**Task:** claude-tools-elf.56
**Supersedes parts of:** `2026-07-22-review-ledger-design.md`, `2026-07-30-ledger-lifecycle-simplification-design.md`

## Problem

The ledger answers one question every round: *has this thread advanced since we last acted on
it?* Today it answers with a scalar high-water mark — `thread_mark`, the id of the last reply we
accounted for — compared by `_ledger.id_advanced`.

A scalar answers "is there anything newer than X". The question we actually need answered is
"which replies have I not seen". Those differ whenever replies arrive out of the order we look at
them, and the gap produces the three defects below — two raised in review, one found while
auditing the write sites for this design.

### C2 — a reply that races the agent is skipped permanently

Raised on PR #118 round 4 against `plugins/flow/skills/review-comments/SKILL.md:970-973`.

Phase 2 collects a thread ending at reply 100. While the human triages — arbitrary wall-clock
time, possibly hours — a reviewer posts 105. Phase 3 and Phase 4 never see it. Phase 5 posts the
agent's own reply, which lands at 110, and 5.7a records `thread_mark: 110` exactly as the table
instructs.

Next `reconcile`: `last_reply_id` is 110, equal to the stored mark, so `id_advanced` is False and
`reopen_if_advanced` never fires. Reply 105 sits inertly in the row and the finding stays `done`
— functionally dropped, until some later reply happens to re-open the row for unrelated reasons.

The obvious cheap patch — record the last *analysed* id instead of the posted one — is wrong: the
agent's own reply would then always sit past the mark and re-open the finding every round, which
is the infinite re-triage loop SKILL.md warns about two paragraphs below.

### C3 — no recording rule for a threadless summary that was not a follow-up

Raised on PR #118 round 4 against `plugins/flow/skills/review-comments/SKILL.md:975`.

The 5.7a table ties the `fix` / `outdated` / `wont_fix` rows to "replied" and "id of the reply
just posted". But Phase 5.7 forbids replying to a GitHub `kind == "summary"` row — a review body
has no inline reply endpoint. The threadless pattern (`done` with `thread_mark: null`) appears on
the `follow_up` row only. An agent walking the table for a summary item it decided `wont_fix` on
finds no matching row, and can leave the row unsettled — re-triaged every round.

Damage is bounded (no reply target means no duplicate reply; `follow_up` is the one covered case,
so no duplicate task), which is why it was deferred here rather than patched.

### A withheld decision stays `resurfaced` and gets re-litigated

Not a review comment — found while auditing the write sites for this design, and unnumbered on
purpose so it is not mistaken for one of PR #118's refs.

When a round decides a finding but cannot deliver it (push skipped, apply failed), 5.7a records
`status: open` with the decision and **omits** `thread_mark`. The row therefore keeps its
pre-re-open mark, and `resurfaced` stays true — as `_ledger.resurfaced`'s own docstring states:
"It stays true from the re-open until `record` writes a fresh mark."

Next round, Phase 3's table routes a row with `decision` set and `resurfaced` true to "read the
newest thread replies as what changed" — a re-litigation of a verdict the agent already reached
*after* reading those very replies. The intended branch is the neighbouring one: `decision` set,
`resurfaced` false → "do not re-litigate it — the verdict stands; the round's job is to deliver
it."

## Model

`thread` stops being a snapshot field and becomes a durable, append-only log. It leaves
`_ledger.SNAPSHOT_FIELDS`; `refresh_snapshot` no longer touches it.

Each reply is stored in the shape `flow-review-collect` already builds, plus one bit:

```json
{ "user": "coderabbitai[bot]", "body": "…", "id": 3518155060,
  "created_at": "2026-07-30T09:14:22Z", "is_bot": true, "seen": false }
```

`seen` reads as: **we have already acted on this thread with this reply in front of us.**

Two writers, and they do not overlap:

- `reconcile` appends forge replies whose ids we do not hold, with `seen: false`. It never
  touches a stored reply — neither the bit nor the body.
- `record` paints every stored reply `seen: true` and appends our own posted reply, also
  `seen: true`.

Re-surfacing is then a property of the row alone:

```python
def resurfaced(row: dict) -> bool:
    return any(not reply.get("seen") for reply in row.get("thread") or [])
```

### Why "append-only, never prune"

A reply deleted on the forge stays in our copy forever. That is deliberate, and it is what makes
the model safe rather than merely simple.

If we pruned, a reply that arrived and was deleted before we ever looked at it would vanish from
the record — and with it, the reviewer's argument that the agent may need to answer. Keeping it
costs a few hundred bytes and lets a later round quote what was said.

The obvious objection is that an unseen-and-deleted reply would pin the row open forever. It does
not, because `record` paints **everything we store**, not everything the forge returns. Such a row
re-surfaces exactly once, the agent reads it on that round (which is the point of keeping it), and
the next `record` marks it seen along with the rest.

### Why edits to stored replies are ignored

`reconcile` drops forge replies whose ids it already holds, rather than refreshing their bodies.
This extends a decision already in force for the comment body itself: a reviewer who edits text
in place gets no reaction, and is expected to post a new reply instead. Making thread replies
behave differently from the comment they hang off would be the inconsistency, not the other way
round.

### Id comparison

Ids are normalised through `str()` on both sides. GitHub returns a numeric `.id`; if the agent
hands the same id back as a string, a naive comparison misses, `reconcile` appends our own reply a
second time with `seen: false`, and the finding re-surfaces every round forever.

## Write sites

### `reconcile`

**Insert.** A new row takes the item's thread whole, and every reply's `seen` bit takes the same
value that decides the row's status:

```python
already = bool(item.get("already_replied"))
"status": "done" if already else "open"
# and, for every reply copied from the item: "seen": already
```

A row seeded `done` is seeded with its thread fully accounted for — we replied into that thread
before this ledger existed, or before a purge. Without this, the next `reconcile` re-opens it
immediately and the seeding is worthless: a re-run against a live PR after
`flow:done` purged its ledger would send every settled finding back for triage. A row seeded
`open` honestly takes `false`; it costs nothing, since the row is in the working set on
`open + live` regardless.

**Merge.**

```python
def merge_thread(row: dict, item: dict) -> None:
    known = {str(reply.get("id")) for reply in row.get("thread") or []}
    for reply in item.get("thread") or []:
        if str(reply.get("id")) not in known:
            row.setdefault("thread", []).append({**reply, "seen": False})
```

**Order.** `merge_thread(row, item)` → `reopen_if_unseen(row)` → `platform_state`. The current
order is the reverse (`reopen_if_advanced` before `refresh_snapshot`) because the decision was
made from the fresh `item`. It is now made from the merged row, so the merge must come first.

`reopen_if_unseen` takes no `item`:

```python
def reopen_if_unseen(row: dict) -> None:
    if row.get("status") == "done" and _ledger.resurfaced(row):
        row["status"] = "open"
```

This is the same `_ledger.resurfaced` that `cmd_get` and `flow-comment-card` call. Today "did the
thread advance?" has two callers reading two different inputs — `reconcile` from the fresh item,
`get` from the stored row — held together only by both routing through `id_advanced`. After this
change it is one function of one input, with nothing left to diverge on.

### `record`

The decisions file gains one key:

```json
{ "C1": { "status": "done", "decision": "fix",
          "reply": { "id": 3518155060, "user": "artem.vasin",
                     "body": "Fixed: …", "created_at": "2026-08-01T11:02:44Z" } },
  "C7": { "status": "done", "decision": "follow_up",
          "followup_task_id": "claude-tools-elf-12" } }
```

`reply` is **not** a stored field and takes no part in the `NULLABLE_FIELDS` merge semantics. It
is a one-round instruction: "here is the reply I just posted." `C7` above is a GitHub review-body
summary — no reply target, so no `reply` key, and no per-row-shape rule anywhere.

For every ref it touches, `record`:

1. paints every stored reply `seen: true`;
2. appends `reply` (if present, and if its id is not stored already) with `seen: true`.

Painting is **unconditional on `status`**. A ref in the decisions file went through Phase 4, where
the card showed it the whole thread; that is what "seen" asserts, and it is true whether or not
the round managed to deliver the verdict. This is what fixes the re-litigation defect: the
withheld-decision row lands on `resurfaced: false` with its `decision` intact, which is the branch
that tells the next round to deliver rather than re-argue.

The append is **idempotent by id**. Phase 5 records the same ref more than once by design — 5.7
checkpoints it the moment its reply is accepted, and a re-run of a checkpoint file after a partial
failure is expected behaviour, not misuse. Appending blindly would store the same reply twice and
the card would render it twice. Re-supplying a reply already in the thread is a no-op: painting
has already set its bit.

**Validation is shape-only:** if `reply` is present it must be an object with a non-null `id`;
otherwise the whole batch is rejected and the file is left untouched, per the existing
all-or-nothing contract. The `id` is the sole basis of matching — a reply stored without one gets
appended again by the next `reconcile` as if new, and the row re-surfaces forever.

### The `done`-without-a-mark guard is deleted

`cmd_record`'s guard, and `_ledger.threadless` with it, has no detectable case left. `done` with
no reply is now legal for every row shape: a threadless GitHub summary, and an acknowledgement
with nothing left to do, both settle on `status: done` alone.

The one remaining failure — a reply was posted and not reported — was undetectable before this
change too. That is the "stale mark" half the 2026-07-30 spec recorded explicitly: the guard read
the row's value after the merge, so it caught only a row with no mark at all, never one whose mark
was merely out of date. The difference now is that this is the absence of a guard rather than a
hole in one, and the discipline sits in 5.7, where the id comes from the API response that just
returned.

`flow-review-collect`'s comment on elf.31 determinism must be rewritten. The guarantee — a GitHub
review-body summary never re-opens — survives, but it now rests on the row having an empty thread
(nothing can be unseen) rather than on `id_advanced(None, mark)` being unconditionally False.

## Skill changes

`plugins/flow/skills/review-comments/SKILL.md`, via `superpowers:writing-skills` with a failing
contract test ahead of each change.

**Phase 3.** The `decision` set / `resurfaced` true row currently says to read "the newest thread
replies" as what changed. It becomes: replies with `seen: false` are what appeared since the agent
last acted on this thread; the rest is the history of the argument, and all of it is worth
reading. `seen` is a **marker, not a filter** — hiding earlier rounds would cost the agent the
context that makes a considered verdict possible. The existing instruction that `resurfaced` comes
from `flow-review-ledger get` and is never re-derived by hand stays, pointed at the bits.

**Card.** `flow-comment-card` marks unseen replies:

```
> **coderabbitai[bot]**
> The retry loop swallows the last exception.
↳ **artem.vasin**: Won't fix: the caller re-raises.
↳ [new] **coderabbitai[bot]**: It doesn't — `api_run` returns None there.
```

On a row's first triage every reply carries the marker, because nothing in that thread has been
acted on yet — which reads correctly and needs no special case. The `**Resurfaced:**` line stays;
its wording changes from "the thread advanced past the reply we last accounted for" to a count of
replies that appeared since our last action.

**Phase 5.7.** "Capture the posted reply's id" becomes "capture the created object". Both forges
return it from the POST:

```bash
# GitHub
gh api repos/{owner}/{repo}/pulls/{number}/comments/{thread_id}/replies \
  -f body="$(cat "$FLOW_RC_DIR/reply-C1.txt")" \
  --jq '{id, user: .user.login, body, created_at}'

# GitLab — jq separately: glab's flag set varies by version
glab api --method POST \
  "projects/{project}/merge_requests/{iid}/discussions/{thread_id}/notes" \
  --raw-field body="$(cat "$FLOW_RC_DIR/reply-C1.txt")" \
  | jq '{id, user: .author.username, body, created_at}'
```

That object goes into the ref's checkpoint under `reply` — the same checkpoint 5.7 already writes
the moment a reply is accepted. No new discipline is introduced; the existing one now carries four
fields instead of one.

**Phase 5.7a.** The `thread_mark` column becomes `reply`, and seven rows collapse to three
distinguishable cases:

| Outcome this run | `status` | `decision` | `reply` |
|---|---|---|---|
| reply posted (fix / outdated / won't-fix / follow-up) | `done` | the decision it earned | the posted reply object |
| settled with no reply (GitHub summary; acknowledgement with nothing to do) | `done` | the decision it earned | absent |
| decided, delivery did not happen | `open` | the decision it earned | absent |

The "GitHub `kind == summary` → `thread_mark: null`" row disappears because it stopped differing
from its neighbour, not because the case went away. The twenty-line paragraph explaining how
omitting the key differs from writing an explicit `null`, and why both break the loop, is deleted
outright — there is nothing left to distinguish. So is the sentence in 5.7 that explains
`already_replied` in terms of the thread advancing "past `thread_mark`".

## What is deleted

| Deleted | Replaced by |
|---|---|
| `_ledger.id_advanced` | `_ledger.resurfaced` reading per-reply bits |
| `_ledger.last_reply_id` | — (no consumer) |
| `_ledger.threadless` | — (its only consumer was the deleted guard) |
| `thread_mark` row field | per-reply `seen` |
| `reopen_if_advanced(row, item)` | `reopen_if_unseen(row)` |
| `cmd_record`'s done-without-a-mark guard | shape-only validation of `reply` |
| `thread` in `SNAPSHOT_FIELDS` | `merge_thread` |

## Testing

| Behaviour | Why this one |
|---|---|
| a reply arriving between `reconcile` and `record` re-surfaces next round | C2, the originating defect |
| a GitHub summary settles with no reply under **every** decision, `wont_fix` and `fix` included | C3 — the old table covered `follow_up` only |
| a withheld decision lands on `resurfaced: false` with its `decision` intact | the re-litigation defect |
| recording the same `reply` twice stores it once | 5.7 checkpoints, then 5.7a closes the round |
| a deleted reply re-surfaces **once**, then is painted with the rest | the append-only contract |
| our own posted reply never re-surfaces its own finding | otherwise an infinite re-triage loop |
| ids match whether given as `3518155060` or `"3518155060"` | otherwise our reply is appended twice |
| a row seeded from `already_replied` does not re-surface on the next `reconcile` | otherwise a post-purge run re-triages a whole settled PR |
| an edited reply body on the forge does not overwrite the stored one | "ignore retroactive edits" is a decision, not a side effect |
| `record` paints `seen` on `status: open` entries too | the re-litigation fix depends on it |
| a `reply` without an `id` rejects the whole batch, file untouched | all-or-nothing |
| the card marks unseen replies | the Phase 3 / card contract above |

Plus contract tests over the prose: the 5.7a table in its new shape, the Phase 3 wording, and the
absence of `thread_mark` anywhere in the skill.

The exhaustive `status` × `platform_state` transition table from PR #118 stays as it is. Neither
axis changes here — only the trigger that moves `done` back to `open`.

## Non-goals and recorded decisions

**No schema version gate, no migration.** `load_ledger` does not compare `schema` today, and this
change does not add the comparison. There is no population to migrate: the ledger has never
shipped in a release, so no ledger written by the old model exists anywhere. The transitional case
is empty by construction rather than tolerated.

**Concurrency is still unguarded.** `save_ledger`'s atomic temp+rename gives crash safety, not
mutual exclusion. Two overlapping `review-comments` runs on one PR remain last-writer-wins, and
would corrupt the platform replies as well as the ledger. Re-affirmed from
`2026-07-22-review-ledger-design.md` ("Concurrency (no locks)") rather than inherited silently:
this change moves thread state from one scalar to a per-reply list, which alters nothing about the
whole-document rewrite both `reconcile` and `record` perform.

**Storage growth is accepted.** Never pruning means the stored thread is a superset of the forge's
— by however many replies were deleted over the PR's life. Review threads are short and the ledger
is one JSON file per PR; the memory is worth more than the bytes.

**Reply-level `is_bot` is not consumed.** The card renders `user` and `body`; `alloc_ref` and
`working_entry` read the row's `is_bot` (the comment's author), never a reply's. Our appended
reply carries the four fields above and no more.
