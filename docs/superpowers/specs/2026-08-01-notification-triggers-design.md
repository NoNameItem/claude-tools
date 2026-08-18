# Notification triggers — design

Task: `claude-tools-5vg.22` (package 1 of 2). Covers `claude-tools-5vg.15`, `.16`, `.17`, `.18`,
`.19`, `.20`, and — as a consequence of the chosen architecture — `claude-tools-5vg.1`.

Predecessor design: `docs/superpowers/specs/2026-07-27-pr-merge-gate-and-notifications-design.md`
(Parts 1–5). This document supersedes its Part 2 "Aggregator" section and the two-call-site model
it describes; everything else there still holds.

## Context

The notification system shipped in PR #119 works, and its live verification (Step 6 of
`docs/merge-gate-rollout.md`) surfaced six defects, all of them variations on one theme: **who is
allowed to speak, and when**. Two duplicate *Ready to merge* messages for one head SHA; a start
message for a superseded push that nothing ever answered; a `comments` verdict that never clears
when the threads are resolved; six Telegram messages after a single merge, one of them about a
component in which nothing happened; four messages for one release merge; and Codex spending its
budget reviewing bot-generated version bumps.

Every one of these is downstream of a single structural fact:

> `review-gate.yml` runs on `pull_request_target` and `pr.yml` runs on `pull_request`. Neither can
> observe the other's completion, because actions performed with `GITHUB_TOKEN` do not emit events
> that start workflows.

That is why the result notification is called from two places, why it needs commit-status
bookkeeping to coordinate them, and why three successive versions of that bookkeeping each produced
a defect in review, always with the same symptom — a *checks running* message with no reply.

This design removes the structural fact rather than patching its consequences.

## Goals

- One speaker per event. No coordination state whose job is to decide "speak or stay silent".
- Codex reviews are triggered by us, deliberately, on the PRs we choose — not by a connector-wide
  toggle we cannot filter.
- release-please PRs and release merges produce exactly the notifications that carry information.
- A start message is never left without a reply. This is the failure shape that took three review
  rounds to eliminate in PR #119 and must not return.

## Non-goals

- Changing the message layout, the Sonar blocks or the release-notification content. That is
  package 2 (`claude-tools-5vg.23`).
- Protecting the merge gate from a PR that edits its own workflow — see "Accepted trade-off" below.
- Touching `publish.yml` / the release notification path.

## Part 1 — Architecture: one workflow, one speaker

`review-gate.yml` is reworked into `_reusable-review-gate.yml` and called from `pr.yml`. The event
changes from `pull_request_target` to `pull_request`; the reusable workflow keeps the polling loop
and `review_gate.py` unchanged.

```
 on: pull_request [opened, synchronize, reopened, edited] → master
 ─────────────────────────────────────────────────────────────────────────────
              REL  = startsWith(head.ref, 'release-please--')
              TOOL = detect.tooling_changed   (always false on a release PR)
              EDIT = github.event.action == 'edited'
 ─────────────────────────────────────────────────────────────────────────────

  detect ─────────────────────────────────────────────────┐
     │                                                    │
     ▼                                                    │
  validate-pr ★ Validate PR                               │
     │                                                    │
     ├──────────┬──────────────┬─────────────┬────────────┴──────┐
     ▼          ▼              ▼             ▼                   ▼
 python-ci   plugin-ci    python-ci-info  plugin-ci-info    review-gate
 if: changed manifests-   if: TOOL && …   if: TOOL && …     if: !REL
   && !REL     only: REL   (never on a release PR)          nudge + wait
     │          │                                                │
     ▼          ▼                                                ▼
 ★ Python    ★ Claude Code                                  ★ Review Gate
   CI Gate     Plugin CI Gate                                 (wrapper job)
     │          │                                                │
     └──────────┴────────────────────┬───────────────────────────┘
                                     │ needs: [validate-pr, the three gates]
                                     │
                                     ▼
                             pr-summary
                             if: always() && !REL && !EDIT
                             (a release PR gets no PR notification at all)

  notify-start ── in parallel, if: !REL

 ─────────────────────────────────────────────────────────────────────────────
  ★ = required context in the master ruleset

  Separately:  review-thread.yml
               on: pull_request_review_thread [resolved, unresolved]
               → 60 s debounce → _reusable-pr-summary
```

What this buys:

- **No duplicate result message.** Exactly one job reports the outcome of the checks, so
  `claude-tools-5vg.15` is not fixed but dissolved: there is no second speaker to deduplicate
  against, and the verdict record that broke three times does not come back.
- **No polling for the gate's completion.** `pr-summary` reaches its turn through `needs`, by which
  point every required context is terminal by construction.
- **The gate stops being a hand-rolled commit status.** Under `pull_request` a job's check run is
  attributed to the head SHA automatically, so `post_status`, the `trap` that posts `error` on an
  unexpected exit, and the separate "Superseded" status all disappear. They existed only because
  under `pull_request_target` the job's own check run lands on the base commit. The `current_head`
  comparison itself survives — it stops being a guard against greening a superseded SHA and becomes
  the poll's exit condition; see "Concurrency" below.
- **The anchor stops deciding whether to speak.** It keeps carrying the reply address, and that
  stays its only job — see Part 3. Routing the message id through
  `needs.notify-start.outputs.message-id` instead was considered and rejected: the same reusable
  summary is also called from `review-thread.yml`, where no `notify-start` exists in the run and
  the marker is the only possible source. One reader, one source, for both call sites; the race
  "marker not written yet" is impossible by construction, because `pr-summary` sits on
  `needs: notify-start`.

### Gate wrapper jobs publish the contexts

A reusable-workflow call has no parent check run of its own — only child jobs named
`Review Gate / review-gate-poll`. This is why `python-ci-result` and `claude-code-plugin-ci-result`
already exist, and the review gate gets the same treatment:

```yaml
review-gate:
  # Fork guard, like every other secret-bearing job: a fork run gets no CODEX_NUDGE_TOKEN, so the
  # nudge is impossible and the call is skipped rather than failed inside.
  if: |
    !startsWith(github.event.pull_request.head.ref, 'release-please--') &&
    github.event.pull_request.head.repo.full_name == github.repository
  uses: ./.github/workflows/_reusable-review-gate.yml
  secrets: inherit

review-gate-result:
  name: Review Gate
  needs: [review-gate]
  if: always()
  steps:
    - run: |
        # Both a release PR and a fork PR arrive here as `skipped`, and they must resolve
        # differently: a release PR legitimately needs no AI review, while a fork PR must stay
        # unmergeable. Since the ruleset treats `skipped` as passing, the fork case has to be
        # turned into a real failure here.
        if [ "$IS_FORK" = "true" ]; then exit 1; fi
        case "$RESULT" in
          success) exit 0 ;;   # Codex reviewed the head commit
          skipped) exit 0 ;;   # release-please PR — no AI review required
          *)       exit 1 ;;   # failure, cancelled, timed out
        esac
```

The wrapper always runs, so the required context is always published by a job that actually
executed. We therefore never depend on how the ruleset interprets a `skipped` job — which is the
same contract the three existing gates already honour.

`Validate PR` is *not* conditioned on `REL`: checking the title of `chore(statuskit): release 0.5.1`
is meaningful, and the job is cheap.

### Concurrency: a 25-minute poll now lives inside `pr.yml`

`review-gate.yml` deliberately had no `concurrency` at all, because `cancel-in-progress: true`
would let an unrelated event cancel a live poll. Moving the poll into `pr.yml` puts it under that
workflow's existing group — `${{ github.workflow }}-${{ github.ref }}-${{ github.event.action }}`,
`cancel-in-progress: true` — and the `github.event.action` component is load-bearing: it keeps a
burst of `edited` events (which release-please produces on every force-push) from killing a CI run
started by `synchronize`.

**The key is left exactly as it is.** Its one consequence is that a run started by `opened` is not
cancelled by a later `synchronize`, so two polls can be alive at once, each for its own SHA. That
is bounded inside the gate instead: the `current_head != HEAD_SHA` check, which today runs once
before publishing success, moves into the loop body. A poll whose SHA has been superseded exits
within one interval (≤30 s) rather than sitting out the full 25 minutes.

**A superseded poll's `exit 0` is an accepted, undocumented-until-now risk.** It exits
successfully — not a failure — because the summary that follows is silenced by `pr_summary.py`'s
`stale-head` branch and the abandoned thread is closed by the new push's *Superseded* reply, not by
this run. The wrapper job that publishes the `Review Gate` check run cannot distinguish that clean
exit from "Codex actually reviewed the head commit", so a green check run lands on the *abandoned*
SHA — one Codex never reviewed. That is harmless while the SHA stays dead. It stops being harmless
if the SHA is ever made the PR head again (`git reset --hard <old-sha> && git push --force`):
the new run's wrapper job waits on `needs: review-gate` for up to 25 minutes, and during that
window the stale green check run from the old run may be the newest `Review Gate` result GitHub
has for that SHA — whether it actually is depends on when GitHub materialises a check run for a
job still queued behind `needs`, which is **unverified**. Turning the superseded exit into `exit 1`
was considered and deliberately rejected (2026-08-17): it would fail the gate on every ordinary
double-push, which is far more common than a reintroduced SHA, in exchange for closing a window
that is unverified in the first place. See "Risks and limitations" below.

Two consequences follow, and both are load-bearing:

- **`pr_summary.py` keeps its `stale-head` branch.** A superseded run can still reach `pr-summary`
  — the gate exits quickly, but it exits *successfully*, and the summary job then runs. `stale-head`
  is what keeps it silent, and the abandoned thread is closed by the *Superseded* message from the
  new push's `notify-start`, not by this run.
- **A cancelled run never leaves a thread unanswered.** When `cancel-in-progress` does fire (two
  `synchronize` events in a row), the cancelled run's `notify-start` has either not sent anything
  yet — nothing to answer — or has sent and recorded `msg:<id>`, in which case the next push reads
  that marker on `before` and replies *Superseded*.

### Accepted trade-off

Under `pull_request`, GitHub reads the workflow file from the PR branch. A PR can therefore edit
the gate that guards it — replace the job with `exit 0` — and merge without any review. Today that
is impossible, because the gate arrives from the base branch.

This is accepted deliberately:

- Only the repository owner can open PRs directly; there are no other collaborators.
- Fork PRs are unmergeable regardless (the wrapper fails them, and they have no token to nudge
  with).
- The realistic threat is an accidental edit, not a hostile one, and an accidental edit is visible
  in the workflow diff during review.

The alternative — keeping the gate on `pull_request_target` and having `pr-summary` poll for its
status — was rejected: it reintroduces a second polling loop for no security gain against this
threat model. A third option (a base-branch sentinel that blocks PRs touching
`.github/workflows/`) was considered and dropped as solving a problem this repository does not
have.

Note also that `pr.yml` was *already* forgeable in the same way — a PR can gut its own CI jobs into
`exit 0`. The gate was the one remaining thing it could not forge; that asymmetry is what this
change gives up.

**What the gate job now holds while running PR-authored code.** Under `pull_request`,
`actions/checkout` takes the merge ref, so every script the gate runs comes from the PR. In that
same job live `CODEX_NUDGE_TOKEN` (the owner's PAT), `statuses: write` for the `codex-nudge`
marker, and — in `notify-start` and the summary — the Telegram credentials. Today `pr.yml` carries
a ten-line comment explaining why it withholds workflow-level `statuses: write` precisely to keep
PR-authored code away from commit statuses; that reasoning is retired here rather than worked
around.

Two alternatives were weighed and rejected. Checking the gate out from `base.sha` narrows the
surface to the workflow file, but the nudge logic lives in that very file, so a deliberate theft
stays equally possible — it buys protection against an accidental edit only. Moving the nudge into
a separate `pull_request_target` workflow does close it by construction, at the cost of a second
workflow plus a new race (the gate would start polling before the marker carrying its cutoff
exists). Neither is worth it under this repository's threat model: same-repo PRs come only from the
owner and any trusted collaborator who might be added later, and fork PRs never reach these jobs —
the gate is skipped for them and the wrapper fails them.

## Part 2 — Codex review is triggered by us

Automatic Codex reviews are switched off in the connector. The gate requests the review itself, and
only for PRs that deserve one. This closes `claude-tools-5vg.19` (no budget spent on release PRs)
and `claude-tools-5vg.1` (a missed `synchronize` webhook no longer strands the gate) with the same
mechanism.

### Experimental evidence

Measured on live PRs #122 and #123 (2026-07-31), after the owner switched off automatic reviews:

| Step | Action | Result |
|---|---|---|
| 1 | PR #122, body containing the literal phrase `@codex review` | 👀 within seconds — the connector reacts to the phrase in a PR body |
| 2 | PR #123, empty body | nothing at all — automatic reviews are genuinely off |
| 3 | `@codex review` from `github-actions[bot]` (`GITHUB_TOKEN`) | refused: *"To use Codex here, create a Codex account and connect to github"* |
| 4 | `@codex review` from the owner's account (PAT) | 👀 after 8 s, review `COMMENTED` after 2 min 20 s, `review-gate` went green on its own |

The connector attributes a request to the account that wrote the comment and requires that account
to have a Codex subscription. A bot account cannot have one, so **the nudge must be posted with a
PAT belonging to a real user**.

### The nudge

Secret: `CODEX_NUDGE_TOKEN` — a fine-grained PAT of the repository owner, scoped to this repository
only, with `Pull requests: read and write` and `Issues: read and write` (a PR comment is created
through `issues/{n}/comments`, and GitHub checks both permissions depending on the object). It is
deliberately *not* `RELEASE_PLEASE_TOKEN`, which can write to `master`.

Order inside the gate job:

1. **release-please PR** (`head.ref` starts with `release-please--`) — the job is skipped by `if:`
   and the wrapper reports success. Codex is not asked. The comment at `review-gate.yml:113-114`
   claiming "release-please PRs … that Codex never reviews" is corrected: it was false (PR #115 is
   the counter-example), and it becomes true only now, for a different reason.
2. **`codex-nudge` marker on the head SHA**, description `comment:<id>@<cutoff>`. Present → a
   review was already requested for this commit; take the cutoff from the marker and go straight to
   waiting. Absent → delete stale nudges (comments authored by the token's account whose body,
   stripped, is exactly `@codex review`), post a fresh one, and record both the comment id and the
   cutoff.
3. **Wait** — the existing loop: `review_gate.py`, the cutoff from the marker, 30 s interval, 25 min
   cap, plus the in-loop `current_head` check described in Part 1.
4. **Success** → delete our own nudge by `comment:<id>`, leaving the thread clean. **Timeout** →
   keep it deliberately: it distinguishes "we never asked" from "we asked and Codex did not answer".

### Why the cutoff moves into the marker

Today the freshness cutoff is `pull_request.updated_at`, which for `opened`/`synchronize` is exactly
the push time. Under `pull_request` the gate no longer runs only on those two events: `edited`,
`reopened` and a manual re-run all re-execute it for a head SHA that has not changed — and every one
of them advances `updated_at`. A cutoff read from the event would therefore declare the review that
already arrived for this very commit "too old", and the gate would poll for a review nobody is
going to write, for 25 minutes, ending red.

Skipping the gate on those events is not an escape: a job skipped by `if:` still publishes a check
run, the ruleset reads `skipped` as passing, and the required context would go green with no review
at all.

So the cutoff is written once, by the first run that requests a review for this SHA, and read by
every later run for the same SHA. It belongs to the commit, not to the last time somebody touched
the PR. The marker already had to exist for the nudge to be idempotent; it gains one field.

One consequence worth naming: the stale-nudge cleanup deletes comments authored by the token's
account whose body is exactly `@codex review` — including one the owner typed by hand to request a
re-review. That is acceptable (the gate posts its own immediately afterwards) but not obvious.

The marker is what makes a manual re-run after a timeout safe — the documented recovery in
`claude-tools-5vg.1`. The gate sees the marker, does not re-ask Codex, finds the review that has
meanwhile arrived, and goes green.

Deleting stale nudges before posting is self-healing: whatever killed the previous run (timeout,
cancellation, a dead runner), the next push cleans up after it without any state of its own.

### Token expiry

Fine-grained PATs must carry an expiry date, and on that day the gate starts failing on every PR.
Therefore: a failed comment POST is an explicit failure naming the token, not a silent fall-through
into waiting. Otherwise an expired PAT looks exactly like "Codex is not responding".

## Part 3 — PR notifications

### The marker, reduced to bookkeeping

`pr-notify-anchor` stays on the head SHA, with description `msg:<id>`, rewritten to
`msg:<id> replied` once the thread has been answered. It answers three questions — has a start
message already been sent for *this* commit, has its thread been answered, and how far have we
reported commits.

What it no longer does is decide whether the **result** speaks: that decision is now structural
(one producer, ordered by `needs`), which is what the removed verdict record used to arbitrate.
The marker still governs two narrower choices, both on the start side: whether to repeat a start
message for a commit that already has one, and whether an abandoned thread needs a *Superseded*
reply. It has two writers — `notify-start` creates it, `pr-summary` appends `replied` — and they
never run concurrently for one SHA, because the second sits on `needs` of the first.

**`notify-start`** (`if: !REL`):

1. On `synchronize`, read the marker on `github.event.before`. Non-empty and without `replied` →
   that push announced itself and never got an answer: send one silent *Superseded by `<new sha>`*
   into that thread and mark it `replied`. This is `claude-tools-5vg.16`, with no concurrency
   surgery.
2. Read the marker on the current head. Non-empty → a start message for this commit already exists
   (this is a re-run); send nothing.
3. Otherwise build the commit list: walk the PR's commits from the head downwards, find the first
   one carrying `pr-notify-anchor`, and take `compare(<that sha>, <head>)`. Not found within 20
   commits — first push, or the marker sits on a commit that vanished in a rebase — fall back
   to `pull_request.base.sha` and note in the message that history was rewritten. Anchoring on the
   marker rather than on `before` is what guarantees that commits from a push whose run was
   cancelled before `notify-start` are not lost: they appear in the next message.
4. Send *New commit `<sha>`, checks running* with the commit list under the verdict line: up to 5
   commits expanded, more than that in a collapsed block titled `Commits: N`. The list is filled
   while it fits the budget already used by `release_notes.py` (30000 visible characters, 400
   elements, against Telegram's 32768/500) and stops on an element boundary.
5. Write `msg:<id>` on the head SHA.

**`pr-summary`** (`needs` all gates, `if: always() && !REL && !EDIT`): computes the verdict exactly
as today (`failed` / `comments` / `ready`), replies into the thread, then rewrites the marker to
`msg:<id> replied`.

The `!EDIT` guard is what keeps the removal of the verdict record honest. `edited` re-runs the whole
workflow, and with no memory of what was already reported, the summary would answer a second time —
the duplicate that `claude-tools-5vg.15` set out to remove, re-entering through a different door.
The rest of `pr.yml` still runs on `edited`, so every required context is re-published by a job that
actually executed; only the notification is suppressed. The alternative — skipping the heavy jobs
and letting their wrappers report — would turn `skipped` into a green `Review Gate` with no review
behind it.

`pr_summary.py` keeps its shape: it goes on reading head-SHA state through the API rather than from
`needs`, so one implementation serves both entry points (the `pr.yml` job and the review-thread
workflow). Two branches stay load-bearing rather than vestigial:

- **`stale-head`** — a poll for a superseded SHA exits within one interval, but it exits into
  `pr-summary`, and this is what keeps that run silent. Do not remove it on the grounds that
  "there is only one speaker now": the speaker can be speaking for a commit that no longer exists.
- **`waiting`** — unreachable from `pr.yml`, where `needs` guarantees every gate is terminal; kept
  as a safety net for the review-thread entry point, where nothing orders the run against CI.

Two additions: writing `replied` into the marker after a successful send, and the crossing mode
described below. The first one restores `statuses: write` to `_reusable-pr-summary.yml` — a
permission deliberately taken away from it when the verdict marker was removed, and now needed
again for one narrow write. It runs PR-authored scripts while holding it; see the trade-off in
Part 1.

The start message gets its own module, `.github/scripts/pr_start.py`: given the head SHA, the
force-push flag and the commit list from `compare`, it emits the notify spec — verdict line plus the
commits block, expanded or collapsed by count, filled to the budget. Keeping it out of shell means
the count threshold, the budget and the rewritten-history wording are testable without network.

### Behaviour table

| Event | Today | After |
|---|---|---|
| Push | start + reply | same, plus the commit list |
| Two pushes in quick succession | first thread never answered | *Superseded by `<sha>`* into the first thread |
| Re-run failed jobs | a new reply, sometimes duplicated | exactly one new reply in the same thread |
| Re-run all jobs | a second *checks running* | start suppressed; only the reply |
| `edited` | its own *PR updated* message | no message at all — checks re-run, the notification is skipped |
| `reopened` | a second *checks running* | start suppressed by the marker; the verdict lands in the existing thread |
| Last thread resolved | nothing | one *Ready to merge* in the current thread, 60 s after the last Resolve |

The `edited` row is the one deliberate behaviour change beyond the fixes: editing a title or body is
not an event worth its own message — and, with no record of what was already reported, not an event
that may re-answer either. A title edited after the verdict was sent leaves the Telegram message
showing the old title; that is the accepted cost of not speaking twice.

### Re-notification on thread resolution (`claude-tools-5vg.17`)

A new `review-thread.yml` on `pull_request_review_thread` (types `resolved`, `unresolved`) calls
`_reusable-pr-summary.yml`. It deliberately has no `notify-start` — resolving a comment is not a new
run — and it carries the same fork guard as the other secret-bearing jobs.

No memory of the previous verdict is needed, because the transition is derivable from the counter:
`resolved` with zero unresolved threads means "findings are gone", `unresolved` with exactly one
means the opposite crossing. This is a **crossing mode** for `pr_summary.py`, not its default
behaviour, and it has to be built: today `decide()` returns `send=True` for any terminal state with
unresolved threads, so a walk through five findings would report "unresolved comments: 3", then
"…: 2", then "…: 1" on the way to silence. In crossing mode the script speaks only at the two
boundaries and stays silent in between. The mode is passed by the caller — `pr.yml` never uses it.

**Debounce, not a verdict record.** The crossing rule alone does not survive a real review pass:
five clicks on Resolve within ten seconds produce five events, and `_reusable-pr-summary.yml`
serialises them behind `pr-summary-<sha>` with `cancel-in-progress: false`. By the time the queue
reaches the first of them, the count is already zero — so every one of the five sees the crossing
and speaks. `review-thread.yml` therefore carries its own group,
`concurrency: review-thread-<pr-number>` with `cancel-in-progress: true`, and sleeps 60 s as its
first step. A new Resolve cancels the sleeping run; only the last one wakes, counts and speaks, and
it counts the final state rather than a state in motion.

The window is what makes cancellation safe: a cancelled run has sent nothing, because it was
asleep. Cancelling without the window would risk killing a run mid-send, and the Telegram send has
no retry.

Recording "which verdict was already reported" would also close the race, and it is deliberately
not used. That record is what broke three times in PR #119 — always by turning into silence where a
reply was owed. Sixty seconds of sleep buy the same property without reintroducing state that can
strand a thread.

## Part 4 — release-please PRs

### How release-please actually behaves here

Established from the live repository on 2026-07-31, not assumed:

- `release-please.yml` runs on every push to `master`. With `separate-pull-requests: true` each
  component gets its own PR on branch `release-please--branches--master--components--<component>`.
- **Every** pending release PR is force-pushed on **every** merge to master, not just the one whose
  component changed.
- On a pure rebase the only change inside the CHANGELOG is the date in the section heading:
  `## [3.2.0](…) (2026-07-30)` → `(2026-07-31)`. Compared four consecutive head SHAs of PR #115:
  `526fb92e` → `b1ad1dcd` (merge of a statuskit PR) changed only that date, while
  `b1ad1dcd` → `98a86ec4` (merge of flow PR #118) added a new entry.
- Therefore the blob SHA of the CHANGELOG changes on every force-push and is useless as a signal;
  the **set of entries in the top section** is the signal.
- The author of a release PR is `NoNameItem`, not a bot (release-please runs under
  `RELEASE_PLEASE_TOKEN`), so author-based filtering is not available. The reliable markers are the
  branch prefix (already used by the gate) and the `autorelease: pending` label.
- Version is not a usable signal either: two consecutive fixes leave it unchanged while the release
  contents grow.
- The flow PR also carries a second commit from `pin_marketplace_refs.py`, so its head is the pin
  commit rather than the release commit.

### Checks on a release PR

- `python-ci` is not called at all: the release commit changes one version string in
  `pyproject.toml`, so tests and lint would run against unchanged code. `Python CI Gate` reports
  success from a `skipped` dependency, as it already does today.
- `claude-code-plugin-ci` **is** called, with a new input `manifests-only: true` that skips the
  `lint` and `test` jobs and keeps `validate-structure`. This is the only check capable of catching
  an error made by release-please itself: it rewrites `plugin.json`, `.codex-plugin/plugin.json` and
  both `marketplace.json` files, and `validate_plugin.py` checks exactly their consistency.
- `review-gate` is skipped; the wrapper reports success.
- `*-info` jobs need no new condition: `detect_changes.py:163-164` clears `tooling_changed` as soon
  as any project file changed, and a release PR always changes files inside a project — so they are
  already off.

### The release PR notification — dropped (2026-08-19)

There is none. The design originally added a `release-pr-summary` job in `pr.yml` calling a
`_reusable-release-pr-summary.yml`, which compared the top CHANGELOG section at `before` and
`after` (via a new `changelog_section.py`) and announced only the component the push actually
touched. It was built, reviewed on PR #124, and then removed before merge.

The reason is that it carried almost no information the other notifications did not. Its changelog
entry is the subject of the PR whose merge into master was announced a minute earlier by `push.yml`,
and the same changelog arrives again as *Release notes* from `publish.yml` when the release goes
out. The only unique payloads were the version number release-please decided on and the gate status
of a bot-authored PR that virtually never fails — not worth a message on every merge to master.

It also had a defect that made keeping it more expensive than it looked. `pr.yml`'s concurrency
group cancels the in-flight `synchronize` run on every new force-push, and release-please force-pushes
each pending release PR on every merge; a cancelled run's changelog delta is simply lost, because the
next run compares against a `before` that already contains those entries. Observed in this repo's own
history: three double force-pushes 4-7 s apart across ~10 release updates. Fixing that would have
required a persistent marker of what was already announced, mirroring `pr-notify-anchor` — real work
for a message that duplicates two others.

So a release PR is now silent on both ends: `notify-start` skips it (it always did) and `pr-summary`
excludes it. Release information reaches Telegram exclusively through the release notifications
(Publishing… / Published to PyPI). `changelog_section.py` and its tests are removed with the job.

## Part 5 — push notifications on a release merge (`claude-tools-5vg.20`)

A release merge is detected by `.release-please-manifest.json` being touched: only release-please
writes that file, which makes the signal semantic rather than a guess at the commit subject.

The test runs over **the whole push**, not over its head commit: `github.event.commits[].modified`
is already in the event payload, so no checkout, no history depth and no git command are involved.
Reading only the head commit would have been enough under squash merges and wrong under a rebase
merge — the flow release PR carries a second commit from `pin_marketplace_refs.py`, so its head is
the pin commit and the manifest is one commit further back. The repository is now squash-only (see
Rollout), which makes that case unreachable today; the range test is used anyway, so the detection
does not silently depend on a merge policy somebody may widen again. The payload's 20-commit cap is
irrelevant here — a release merge is one or two commits.

- `notify-start` is skipped on a release merge.
- `notify-finish` sends **only** when the verdict is `failed`. On the green path the merge produces
  exactly the release pair (*Publishing…* / *Published to PyPI*).

The rationale for suppressing the pair is that a release merge does not change the state of master
in any meaningful way — it carries versions, CHANGELOG entries and marketplace pins, and the
manifests were already validated on the release PR. The failure exception covers what that argument
does not: a flaky test, an unreachable SonarCloud, an infrastructure hiccup. Without it, a red
master would be announced nowhere while the release message cheerfully reports success.

**CI itself is not switched off on a release push.** `-Dsonar.projectVersion` is set in
`_reusable-python-ci.yml:239`, so the VERSION event in SonarCloud is registered precisely by the
Python CI run on push to master. Both events for `NoNameItem_statuskit` (0.5.0 and 0.5.1) came from
there, `claude-tools-5vg.10` (package 2) depends on them, and `publish-badges` hangs off the same
jobs.

## Components

| File | Change |
|---|---|
| `.github/workflows/pr.yml` | calls the review gate; `REL` condition on `python-ci`, `notify-start`, `review-gate`, `pr-summary`; `EDIT` condition on `pr-summary`; `Review Gate` wrapper; `concurrency` key left as-is (see Part 1) |
| `.github/workflows/review-gate.yml` | becomes `_reusable-review-gate.yml`; `pull_request_target` machinery removed; nudge and `codex-nudge` marker (`comment:<id>@<cutoff>`) added; `current_head` check moved into the poll loop |
| `.github/workflows/_reusable-pr-summary.yml` | `statuses: write` restored (writes `replied`); new `crossing-mode` input for the review-thread entry point; called from `pr.yml` and `review-thread.yml` |
| `.github/workflows/review-thread.yml` | new — `pull_request_review_thread` → 60 s debounce → summary; own `concurrency` group with `cancel-in-progress: true` |
| `.github/workflows/_reusable-claude-code-plugin-ci.yml` | new input `manifests-only` |
| `.github/workflows/push.yml` | release-merge detection over `github.event.commits[].modified`; start suppressed, finish only on failure |
| `.github/scripts/pr_start.py` | new — start-message spec: verdict line + commits block |
| `.github/scripts/pr_summary.py` | writes `replied` into the marker after sending; crossing mode for re-notification; `stale-head` kept and its purpose documented |
| `.github/scripts/review_gate.py` | unchanged decision logic; the cutoff it receives now comes from the marker, not from the event |
| `.github/scripts/tests/` | coverage for the above |
| `AGENTS.md` | the review-gate security note is rewritten to describe the new model |
| `docs/merge-gate-rollout.md` | Steps 2, 6 and 7 and the ruleset step updated (see below) |

## Testing

Unit tests (pure functions, no network): CHANGELOG section parsing — top section extracted, date
ignored in comparison, entries compared as an ordered list, missing file; commit-list assembly and
its budget;
anchor semantics — start suppressed when the marker is present, *Superseded* emitted when the
marker on `before` lacks `replied`, nothing emitted when it has it; the gate wrapper's mapping of
`skipped` / fork / failure onto exit codes; the `codex-nudge` marker — cutoff round-tripped through
`comment:<id>@<cutoff>`, a malformed marker degrading to "ask again" rather than crashing; crossing
mode — speaks at zero unresolved and at exactly one, silent at every intermediate count, and
unaffected in default mode; release-merge detection over a commit list, including the two-commit
shape where the manifest is not in the head commit.

What becomes verifiable inside its own PR — a change from the previous design, where half the
system could only be checked after merge because `review-gate.yml` always came from master: the
gate, the nudge and both notification tracks now live in `pr.yml`, which on a `pull_request` event
is read from the PR branch. Only `push.yml` (release-merge suppression) and the ruleset remain
post-merge.

## Rollout order

0. **Already done, before this design was finalised** (2026-08-13): the merge policy is narrowed to
   squash-only — the ruleset's `allowed_merge_methods` is `["squash"]` and the repository has
   `allow_rebase_merge: false` (merge commits were already off). Rolling back means putting
   `"rebase"` back into that array and re-enabling `allow_rebase_merge`; nothing in this design
   depends on the narrowing, which is why the release-merge detection reads the whole push anyway.
   Step 2 of `docs/merge-gate-rollout.md` is updated to match.
1. **Before the merge:** create `CODEX_NUDGE_TOKEN` and add it to repository secrets. Without it the
   gate cannot nudge, including on this PR itself.
2. **The PR runs under the old ruleset**, which requires the `review-gate` context — a commit status
   still published by the base version of `review-gate.yml` until the merge. So the PR merges
   normally, with both gates active on it: the old one from base and the new one from the branch.
   Two side effects of that overlap, both expected and both temporary:
   - **Notifications arrive doubled on this PR.** `_reusable-pr-summary.yml` is called from the base
     copy of `review-gate.yml` *and* from the branch copy of `pr.yml`, and neither knows about the
     other. This is the last PR on which that happens.
   - **Automatic Codex reviews have been off since 2026-07-31.** Until this branch lands, every
     ordinary PR needs a hand-written `@codex review` from the owner's account, because nothing on
     `master` nudges yet. On *this* PR the branch's own gate does the nudging, and the base gate
     sees the same review.
3. **Immediately after the merge — update the ruleset:** replace the required context `review-gate`
   with `Review Gate`. This is mandatory and time-critical: nothing publishes the old status any
   more, so until it is done every new PR sits at *"Expected — waiting for status to be reported"*.
   Do not open new PRs between the merge and this step.

   Naming the wrapper job `review-gate` instead — so the check run satisfies the existing required
   context and the ruleset needs no edit at all — was considered and rejected: the time-critical
   window is acceptable when nothing else is in flight, and the capitalised name matches the other
   three gates.
4. **Verify** on the next ordinary PR (nudge, thread, *Superseded*, re-run behaviour, silence on
   `edited`), on the next release PR (silence when somebody else's merge force-pushes it and only
   the changelog date moves; one message when its entries actually change), and on the next release
   merge (no push pair).

## Risks and limitations

- **PAT expiry.** The gate fails on every PR the day the token expires; mitigated by making a failed
  comment POST an explicit, named failure.
- **The Codex connector is an external dependency.** If it stops honouring `@codex review`, the gate
  times out on every PR. The way back is cheap and code-free: switch automatic reviews back on; the
  nudge becomes redundant but harmless.
- **The gate is forgeable by a PR that edits `pr.yml`.** Accepted — see Part 1.
- **The gate job runs PR-authored code while holding the owner's PAT**, `statuses: write` and the
  Telegram credentials. Accepted on the same grounds and recorded in Part 1: same-repo PRs come
  only from trusted developers, fork PRs never reach these jobs.
- **A run cancelled mid-send loses its notification.** `cancel-in-progress` fires on two pushes in
  a row, and the Telegram send has no retry. The thread is never left unanswered — the next push's
  *Superseded* covers it — but a result message can be lost. On the re-notification path this is
  neutralised by the 60 s debounce, which puts the cancellable window before the send rather than
  around it.
- **Two behaviours depend on undocumented connector semantics**: that a nudge from a PAT keeps
  working, and that the connector keeps reacting to the phrase in a comment. Both were measured, not
  assumed, and both are recorded here with dates so a future reader can re-measure.
- **A superseded poll's `exit 0` can green-light an unreviewed SHA if that SHA is ever reintroduced
  as the PR head** (`git reset --hard <old-sha> && git push --force`). See "Concurrency" above for
  the mechanism, the reintroduced-SHA scenario, and the unverified window during which the stale
  check run may read as the newest `Review Gate` result. `exit 1` was considered and deliberately
  not taken (2026-08-17): it would fail the gate on the common case (an ordinary double-push) to
  close a window that is unverified to exist at all.

## Task mapping

| Task | Outcome |
|---|---|
| `claude-tools-5vg.15` | dissolved — one speaker, so no duplicate to suppress; the verdict record does not return. The two remaining duplicate paths are closed structurally: `edited` skips the summary, a burst of Resolve clicks is debounced |
| `claude-tools-5vg.16` | fixed — *Superseded by `<sha>`* closes the abandoned thread |
| `claude-tools-5vg.17` | fixed — `review-thread.yml`, crossing mode over the counter, 60 s debounce |
| `claude-tools-5vg.18` | ~~fixed — release PR notifies only when its changelog entries actually changed~~ → **dropped before merge**: the deduplicated message was still one more message per merge to master, duplicating the push notification and the later release notes. The fan-out is eliminated by removing the notification, not by deduping it — see "The release PR notification — dropped" |
| `claude-tools-5vg.19` | fixed — automatic reviews off, the gate nudges only non-release PRs; the false comment corrected |
| `claude-tools-5vg.20` | fixed — push pair suppressed on a release merge, except on failure |
| `claude-tools-5vg.1` | fixed as a side effect — an explicit nudge replaces reliance on the `synchronize` webhook |
