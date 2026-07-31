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
                     ┌───────────────┴───────────────┐
                     ▼                               ▼
             pr-summary                      release-pr-summary
             if: always() && !REL            if: always() && REL

  notify-start ── in parallel, if: !REL

 ─────────────────────────────────────────────────────────────────────────────
  ★ = required context in the master ruleset

  Separately:  review-thread.yml
               on: pull_request_review_thread [resolved, unresolved]
               → _reusable-pr-summary
```

What this buys:

- **No duplicate result message.** Exactly one job reports the outcome of the checks, so
  `claude-tools-5vg.15` is not fixed but dissolved: there is no second speaker to deduplicate
  against, and the verdict record that broke three times does not come back.
- **No polling for the gate's completion.** `pr-summary` reaches its turn through `needs`, by which
  point every required context is terminal by construction.
- **The gate stops being a hand-rolled commit status.** Under `pull_request` a job's check run is
  attributed to the head SHA automatically, so `post_status`, the `trap` that posts `error` on an
  unexpected exit, the re-check of `current_head` before publishing success, and the separate
  "Superseded" status all disappear. They existed only because under `pull_request_target` the
  job's own check run lands on the base commit.
- **The anchor stops carrying the reply address.** Start and result are now in the same run, so the
  message id travels through `needs.notify-start.outputs.message-id`, exactly as `push.yml` already
  does. What remains of the marker is described in Part 3, and it no longer decides whether to
  speak.

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
2. **`codex-nudge` marker on the head SHA.** Present → a review was already requested for this
   commit; go straight to waiting. Absent → delete stale nudges (comments authored by the token's
   account whose body, stripped, is exactly `@codex review`), post a fresh one, and record
   `codex-nudge` = `comment:<id>`.
3. **Wait** — the existing loop: `review_gate.py`, cutoff at `pushed_at`, 30 s interval, 25 min cap.
4. **Success** → delete our own nudge by `comment:<id>`, leaving the thread clean. **Timeout** →
   keep it deliberately: it distinguishes "we never asked" from "we asked and Codex did not answer".

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
reported commits — and it no longer participates in the decision to speak.

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

**`pr-summary`** (`needs` all gates, `if: always() && !REL`): computes the verdict exactly as today
(`failed` / `comments` / `ready`), replies into the thread, then rewrites the marker to
`msg:<id> replied`.

`pr_summary.py` keeps its shape: it goes on reading head-SHA state through the API rather than from
`needs`, so one implementation serves both entry points (the `pr.yml` job and the review-thread
workflow). Its `waiting` branch remains as a safety net but is unreachable from `pr.yml`. The only
addition is writing `replied` into the marker after a successful send.

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
| `edited` | its own *PR updated* message | no message; a changed verdict lands in the current thread |
| Last thread resolved | nothing | *Ready to merge* in the current thread |

The `edited` row is the one deliberate behaviour change beyond the fixes: editing a title or body is
not an event worth its own message.

### Re-notification on thread resolution (`claude-tools-5vg.17`)

A new `review-thread.yml` on `pull_request_review_thread` (types `resolved`, `unresolved`) calls
`_reusable-pr-summary.yml`. It deliberately has no `notify-start` — resolving a comment is not a new
run — and it carries the same fork guard as the other secret-bearing jobs.

No memory of the previous verdict is needed, because the transition is derivable from the counter:
`resolved` with zero unresolved threads means "findings are gone", `unresolved` with exactly one
means the opposite crossing. Resolving five threads one by one therefore produces one message, not
five.

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

### The release PR notification

A separate job `release-pr-summary` in `pr.yml` (`if: always() && REL`), calling a new
`_reusable-release-pr-summary.yml`. It is a separate job rather than a separate workflow because a
separate workflow could not use `needs` and would have to poll. There is no start message: it would
say nothing, and there is no thread to maintain.

1. The component comes from the branch name; the CHANGELOG path comes from
   `release-please-config.json`, not from a hard-coded constant.
2. On `synchronize`: read the CHANGELOG at `before` and at `after` through the Contents API
   (`?ref=<sha>` returns content even for a commit made unreachable by a force-push — verified
   against live SHAs), take the top version section, drop the heading line with its date, and
   compare the remaining entries. Identical → a pure rebase caused by somebody else's merge → stay
   silent. This is what "notify only about the component the last push actually touched" means in
   practice.
3. On `opened`: always send.
4. The message: PR title as the heading, the checks outcome as the verdict line
   (`Ready to merge` / `Checks failed: …`), a collapsed *Changelog* block with the entries of the
   new version, and a button to the PR. The block is rendered by the existing `release_notes.py`,
   which already converts release-please markdown into Telegram rich markup within its budgets.

Parsing the CHANGELOG moves into a new `.github/scripts/changelog_section.py` returning
`{version, date, entries}` for the top section — a pure function over text, used by both the
comparison and the block, and covered by pytest without network.

Effect on the 31 July sequence: the merge of #120 produces one message about the statuskit release
instead of six, and the flow PR — whose only change was the date — says nothing.

## Part 5 — push notifications on a release merge (`claude-tools-5vg.20`)

A release merge is detected by the commit touching `.release-please-manifest.json`: only
release-please writes that file, which makes the signal semantic rather than a guess at the commit
subject. One `git show --name-only` in the existing checkout.

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
| `.github/workflows/pr.yml` | calls the review gate; `REL` condition on `python-ci`, `notify-start`, `review-gate`; two mutually exclusive summary jobs; `Review Gate` wrapper |
| `.github/workflows/review-gate.yml` | becomes `_reusable-review-gate.yml`; `pull_request_target` machinery removed; nudge and `codex-nudge` marker added |
| `.github/workflows/_reusable-pr-summary.yml` | unchanged contract; called from `pr.yml` and `review-thread.yml` |
| `.github/workflows/_reusable-release-pr-summary.yml` | new — the release PR notification |
| `.github/workflows/review-thread.yml` | new — `pull_request_review_thread` → summary |
| `.github/workflows/_reusable-claude-code-plugin-ci.yml` | new input `manifests-only` |
| `.github/workflows/push.yml` | release-merge detection; start suppressed, finish only on failure |
| `.github/scripts/changelog_section.py` | new — top-section parser |
| `.github/scripts/pr_start.py` | new — start-message spec: verdict line + commits block |
| `.github/scripts/pr_summary.py` | writes `replied` into the marker after sending |
| `.github/scripts/tests/` | coverage for the above |
| `AGENTS.md` | the review-gate security note is rewritten to describe the new model |
| `docs/merge-gate-rollout.md` | Step 7 and the ruleset step updated (see below) |

## Testing

Unit tests (pure functions, no network): CHANGELOG section parsing — top section extracted, date
ignored in comparison, entry sets compared, missing file; commit-list assembly and its budget;
anchor semantics — start suppressed when the marker is present, *Superseded* emitted when the
marker on `before` lacks `replied`, nothing emitted when it has it; the gate wrapper's mapping of
`skipped` / fork / failure onto exit codes.

What becomes verifiable inside its own PR — a change from the previous design, where half the
system could only be checked after merge because `review-gate.yml` always came from master: the
gate, the nudge and both notification tracks now live in `pr.yml`, which on a `pull_request` event
is read from the PR branch. Only `push.yml` (release-merge suppression) and the ruleset remain
post-merge.

## Rollout order

1. **Before the merge:** create `CODEX_NUDGE_TOKEN` and add it to repository secrets. Without it the
   gate cannot nudge, including on this PR itself.
2. **The PR runs under the old ruleset**, which requires the `review-gate` context — a commit status
   still published by the base version of `review-gate.yml` until the merge. So the PR merges
   normally, with both gates active on it: the old one from base and the new one from the branch.
3. **Immediately after the merge — update the ruleset:** replace the required context `review-gate`
   with `Review Gate`. This is mandatory and time-critical: nothing publishes the old status any
   more, so until it is done every new PR sits at *"Expected — waiting for status to be reported"*.
   Do not open new PRs between the merge and this step.
4. **Verify** on the next ordinary PR (nudge, thread, *Superseded*, re-run behaviour), on the next
   release PR (silence on a rebase, one message with the changelog), and on the next release merge
   (no push pair).

## Risks and limitations

- **PAT expiry.** The gate fails on every PR the day the token expires; mitigated by making a failed
  comment POST an explicit, named failure.
- **The Codex connector is an external dependency.** If it stops honouring `@codex review`, the gate
  times out on every PR. The way back is cheap and code-free: switch automatic reviews back on; the
  nudge becomes redundant but harmless.
- **The gate is forgeable by a PR that edits `pr.yml`.** Accepted — see Part 1.
- **Two behaviours depend on undocumented connector semantics**: that a nudge from a PAT keeps
  working, and that the connector keeps reacting to the phrase in a comment. Both were measured, not
  assumed, and both are recorded here with dates so a future reader can re-measure.

## Task mapping

| Task | Outcome |
|---|---|
| `claude-tools-5vg.15` | dissolved — one speaker, so no duplicate to suppress; the verdict record does not return |
| `claude-tools-5vg.16` | fixed — *Superseded by `<sha>`* closes the abandoned thread |
| `claude-tools-5vg.17` | fixed — `review-thread.yml`, transitions derived from the counter |
| `claude-tools-5vg.18` | fixed — release PR notifies only when its changelog entries actually changed |
| `claude-tools-5vg.19` | fixed — automatic reviews off, the gate nudges only non-release PRs; the false comment corrected |
| `claude-tools-5vg.20` | fixed — push pair suppressed on a release merge, except on failure |
| `claude-tools-5vg.1` | fixed as a side effect — an explicit nudge replaces reliance on the `synchronize` webhook |
