# CI notifications and merge gate — design

**Task:** claude-tools-5vg.2 (notify-finish doesn't account for review-gate)
**Date:** 2026-07-27
**Status:** approved, pending implementation plan

## Context

`notify-finish` in `.github/workflows/pr.yml:133-151` aggregates only the jobs of its own run:
`validate-pr`, `python-ci-result`, `claude-code-plugin-ci-result`. The Codex merge gate lives in a
separate workflow (`review-gate.yml`, `pull_request_target`), polls for up to 25 minutes
(`TIMEOUT=1500`) and publishes its verdict as a **commit status** `review-gate` on the head SHA —
not as a job. Consequently the "All checks passed" Telegram message can fire while the PR is still
ungated, or already blocked.

Investigating that gap surfaced three adjacent problems, all in scope here:

1. **Merge rules live in two places.** A classic branch protection on `master` and a ruleset
   ("master merge gate") both define "require a PR" and conversation resolution; linear history and
   force-push/deletion blocking exist only in the former, required status checks only in the latter.
   The only required check today is `review-gate`, so a red CI merges fine.
2. **Duplicate check names.** `Python CI` and `Claude Code Plugin CI` each exist as **two** check
   runs — the skipped reusable-workflow call and the summary job — so a required check by that name
   matches ambiguously.
3. **Sonar gates nothing.** `SonarSource/sonarqube-scan-action` runs without
   `sonar.qualitygate.wait`, so the job goes green as soon as the analysis is uploaded; the Quality
   Gate verdict arrives later as an external check that isn't required.

Two facts constrain the design and were verified, not assumed:

- **`on: status` cannot observe our own gate.** `review-gate.yml:103` posts its status with
  `GH_TOKEN: ${{ github.token }}`, and events produced by `GITHUB_TOKEN` do not start new workflow
  runs. `coderabbit-notify.yml` works only because CodeRabbit is a third-party App with its own
  token. Event-driven aggregation must therefore key off workflow completion, not `status`.
- **A required check that never appears blocks the PR forever** (GitHub reports it as
  *"Expected — Waiting for status to be reported"*). This rules out requiring conditionally-present
  checks such as `SonarCloud Code Analysis`, which only exists on PRs with Python changes.

## Goals

- Exactly **two** Telegram notifications per PR: one when the PR is created or updated, one when
  every required check has settled, stating whether the PR is mergeable.
- The same two-message shape for pushes to `master` and for releases, so every CI event reads the
  same way: an opening message, and a reply with the outcome.
- A single source of truth for merge rules, with CI failures actually blocking merges.
- The Quality Gate blocking merges without introducing a conditionally-present required check.

## Non-goals

- Processing Sonar findings inside the flow cycle — tracked separately as `claude-tools-elf.55`.
- Making fork PRs mergeable; they stay blocked, as `review-gate.yml:66-69` already documents.
- Rich Messages experiments beyond what this design uses.

## Part 1 — Merge gate consolidation

The ruleset **"master merge gate"** becomes the only source of truth; the classic branch protection
on `master` is deleted, and its contents move into the ruleset. The configuration is maintained on
GitHub only — it is deliberately **not** mirrored into the repository.

**`pull_request` rule**

| Parameter | Value |
|---|---|
| `required_approving_review_count` | `0` |
| `required_review_thread_resolution` | `true` |
| `dismiss_stale_reviews_on_push` | `false` |
| `require_code_owner_review` | `false` |
| `require_last_push_approval` | `false` |
| `allowed_merge_methods` | `squash`, `rebase` (`merge` dropped: merge commits are disabled repo-wide and conflict with linear history) |

**`required_status_checks` rule** (`strict_required_status_checks_policy: false`, so that "update
branch" does not re-trigger reviewers — see `claude-tools-5vg.4`):

| Context | Always present? |
|---|---|
| `Validate PR` | yes |
| `Python CI Gate` | yes (`if: always()` summary job) |
| `Claude Code Plugin CI Gate` | yes (`if: always()` summary job) |
| `review-gate` | yes for same-repo PRs; absent for forks **by design** |

**Rules migrated from classic protection:** `non_fast_forward`, `deletion`,
`required_linear_history`.

**Not enabled:** `required_signatures`, `required_deployments`, commit-message patterns.

**Bypass:** none — `bypass_actors: []` stays empty.

**Check renaming.** The summary jobs are renamed so required contexts are unambiguous:
`python-ci-result` → name `Python CI Gate`, `claude-code-plugin-ci-result` → name
`Claude Code Plugin CI Gate`. The reusable-workflow calls keep their current names, so child jobs
remain `Python CI / Lint (statuskit)` and the PR checks list is unchanged visually.

## Part 2 — PR notifications

### Model

| Notification | Trigger | Sound |
|---|---|---|
| **PR updated** | `pr.yml` start, on all four events (`opened`, `synchronize`, `reopened`, `edited`) | silent |
| **Result** | every required check has settled | with sound, replying to the first |

`coderabbit-notify.yml` is deleted (the App is disabled separately, outside the repo), so no third
notification stream remains.

### Aggregator

A new reusable workflow `_reusable-pr-summary.yml` with inputs `pr-number` and `head-sha` is called
from **two** places, because there are exactly two producers of required checks:

- `pr.yml` — job `pr-summary`, `needs: [validate-pr, python-ci-result, claude-code-plugin-ci-result]`,
  `if: always()`;
- `review-gate.yml` — a job after `review-gate-poll`, `if: always()`, same-repo PRs only.

The old `notify-finish` job is removed. Whichever producer finishes last sends the notification;
the other exits silently. The algorithm, identical in both call sites:

1. If `head-sha` is no longer the PR's head → **exit silently**. This absorbs the superseded poll
   that `review-gate.yml:155-164` deliberately lets run to completion after a new push.
2. Read required contexts from `GET /repos/{owner}/{repo}/rules/branches/master` — the ruleset thus
   drives both the gate and the notification. For fork PRs, drop `review-gate` from that list.
3. Match them against `commits/{sha}/status` and `commits/{sha}/check-runs`. If any required context
   is missing or non-terminal → **exit silently** (the other producer is still running).
4. Compute the verdict:
   - any required check failed → `failed`, listing the failed contexts and the failed child jobs;
   - all green, unresolved review threads > 0 → `comments` (count only, via GraphQL — REST does not
     expose `isResolved`);
   - otherwise → `ready`.
5. Send, subject to the marker below.

**Concurrency and dedup.** The job declares
`concurrency: group: pr-summary-<head-sha>, cancel-in-progress: false`, which serialises the two
possible simultaneous calls. State lives in a commit status with context `pr-notify` on the head
SHA:

- the **PR updated** notification creates it — `state: pending`, `description: msg:<message_id>`;
- the aggregator reads it to obtain `message_id` for `reply_parameters`, and to learn which verdict
  was already sent;
- after sending, the aggregator sets `state: success` and
  `description: msg:<message_id> v:<verdict>`.

A notification is sent only when the marker is absent **or** the verdict differs from the recorded
one. This is what makes re-runs behave correctly: re-running a failed CI job, or re-running the gate
after its timeout (which `review-gate.yml:174` explicitly instructs the user to do), produces a
fresh, accurate notification, while repeated calls with an unchanged verdict stay quiet.

The marker is deliberately visible in the PR checks list: it doubles as a human-readable verdict.
It is not a required check. Being posted with `GITHUB_TOKEN`, it starts no new workflow runs.

**Permissions.** `pr.yml` gains `statuses: write`; `review-gate.yml` gains `checks: read`.

### Edge cases

| Case | Behaviour |
|---|---|
| New push mid-flight | `pr.yml` is cancelled by `cancel-in-progress`; the surviving gate poll sees a stale SHA and exits silently. The new run notifies for the new SHA. |
| release-please PR | The gate waives itself instantly (`review-gate.yml:118-123`) and finishes first; its aggregator call sees CI still running and exits silently. The `pr.yml` call sends. |
| Fork PR | `review-gate` is dropped from the required list, so the verdict is computed from CI alone; the PR itself remains unmergeable, as today. |
| Gate times out | Terminal `failure` status → verdict `failed`. A manual re-run later flips the verdict and re-notifies. |
| Marker missing | Send without `reply_parameters`. |

### Message format

Both notifications are sent with `sendRichMessage` (Bot API 10.1+) using `InputRichMessage.html`
and `skip_entity_detection: true` — without the latter, `PR 118` and SHAs are auto-linkified as
hashtags. Layout, validated against the iOS and desktop clients:

```html
<h1>{emoji} {PR title}</h1>
<p>{verdict}</p>
{table / details, when there is something to show}
<footer>{repo} · PR {number}</footer>
```

- `h1` is the only heading level iOS renders as a real heading; `h2`–`h4` come out in a serif face
  smaller than body text. Desktop renders all levels similarly, so `h1` is safe for both.
- Emoji carries the status (🚀 / ✅ / ⚠️ / ❌); the verdict is plain text on the next line.
- `updated`: no details, silent. `ready` and `comments`: check table collapsed in `<details>`.
  `failed`: table open, plus an open `<details>` listing the failed jobs.
- `comments` shows the **count only** — locations without the comment text are useless, and quoting
  the comments in a notification is out of proportion.
- Buttons: `Pull request` everywhere; `Checks` only on `failed`.
- The footer goes last, after tables and collapsible blocks.

**Emphasis rule.** Bold marks exactly what needs attention, and nothing else: the failed gate in the
verdict line, the failing rows of the check table, the names of failed jobs (the explanatory tail
such as `— Quality Gate failed` stays regular), and breached Sonar conditions. A green notification
therefore contains no bold at all, which makes "bold = problem" unambiguous.

### Sonar block

For every SonarCloud project analysed on the PR, the result notification carries **two** collapsible
blocks, because Sonar's own PR comment answers "what did we find" but not "what blocks the merge".

**Block 1 — the quality gate**, built from `conditions`. Collapsed when the gate passed, open when it
failed; breached rows in bold:

```
Sonar · statuskit — Quality Gate passed
  ✅ Reliability          A (need A)
  ✅ Security             A (need A)
  ✅ Maintainability      A (need A)
  ✅ Coverage             96.8% (need ≥ 80%)
  ✅ Duplication          0.0% (need ≤ 3%)
  ✅ Hotspots reviewed    100.0% (need ≥ 100%)
  Dashboard
```

Ratings arrive as `1..5` and are mapped to `A..E`; comparators become `need ≥ 80%` / `need ≤ 3%` /
`need A`. The row set is **whatever the API returned for this PR** — not a fixed list. On a
release-please PR only four conditions come back (coverage and duplication are not evaluated when
there is nothing to measure — verified on #114), and that is correct output, not missing data.
A corollary worth having: if the gate gains a condition (see `claude-tools-5vg.8`), it shows up in
Telegram with no code change.

**Block 2 — new code**, always collapsed: the same figures Sonar puts in its PR comment, plus a
severity breakdown it does not provide:

```
Sonar · statuskit — new code
  New issues                6 (critical 5, minor 1)
  Accepted issues           0
  Security hotspots         0
  Coverage on new code      96.8%
  Duplication on new code   0.0%
  New lines                 1357
  Issues on new code
```

The breakdown costs one cheap call (`api/issues/search` with `ps=1&facets=severities`) and is the
part that makes a green gate honest: on PR #112 it surfaces five critical smells that the gate,
correctly, let through.

Both blocks are rendered as **header-less two-column tables**.

**Why not mirror Sonar's comment.** Its icons do not mean "condition satisfied" — on #112 it marked
`6 New issues` green although `new_violations` is not part of the gate at all, and on #114 it showed
`0.0% Coverage on New Code` green although `new_coverage` was not evaluated for that PR. It also
never mentions `Reliability`, `Security` or `Maintainability` — precisely the three conditions
through which code smells can block a merge. Copying that comment would have reproduced its blind
spot.

**Data source: the SonarCloud Web API, not the comment.** The check run's `output.summary` contains
the same figures, but as human-readable markdown (`![](…/passed.svg '') [6 New issues](…)`) — no
contract, and it would have to be parsed with regexes. The API is structured and gives strictly
more:

| | `output.summary` | Web API |
|---|---|---|
| Contract | markdown, may change silently | documented endpoints |
| Gate thresholds | absent | `conditions[].errorThreshold` → `(≥ 80)` |
| Per-metric status | inferred from image filename | `conditions[].status` |
| Extra metrics | none | `new_lines`, anything else on demand |

Three calls per project: `api/qualitygates/project_status` (gate status, thresholds, per-condition
status), `api/measures/component` (metric values) and `api/issues/search` with
`ps=1&facets=severities` (severity breakdown). The project key
does **not** need to be known in advance — it is extracted from the `details_url` of the check run
whose `app.slug == "sonarqubecloud"` (`…/dashboard?id=NoNameItem_statuskit&pullRequest=112`), which
the aggregator already has in the rollup. Monorepo projects therefore each get their own block with
no configuration. Public projects answer anonymously; `SONAR_TOKEN` is passed anyway so private ones
would work too.

Metrics not returned by the API (Sonar omits `new_coverage` and `new_duplicated_lines_density` when
there is nothing to measure — verified on PR #114) are rendered as `—` rather than a fake `0.0%`.

**Degradation.** If the Sonar API is unreachable, the block falls back to the check run's
`output.title` alone (`Quality Gate passed` / `failed`) without metrics. There is deliberately no
second parser: one path for the numbers, and a notification that never fails because of Sonar.

Note that a metric can show a green icon while being non-zero — `new_violations` is not part of this
repo's quality gate (which is built on ratings), so 6 new issues still render as ✅. Icons reflect
the gate, not intuition.

**Fallback.** If `sendRichMessage` fails, the script retries with plain `sendMessage`. That parser
rejects rich tags (`h1`, `table`, `details`, `ul`, `p`, `footer` — verified: *"Unsupported start tag
h3"*), so the fallback is a **separate rendering**, not the same HTML: bold title, verdict line,
`<blockquote expandable>` for details, links as a text line. It is tested alongside the primary one.

### Components

| File | Role |
|---|---|
| `.github/scripts/pr_summary.py` | JSON in (required contexts, rollup, thread count) → verdict out. Mirrors the `review_gate.py` split: bash does I/O, Python decides. |
| `.github/scripts/sonar_pr_status.py` | Sonar check runs from the rollup → project keys → metrics and gate status via the Web API. Degrades to `output.title` on failure. |
| `.github/scripts/telegram_notify.py` | Verdict + PR metadata + Sonar blocks → payload; sends, with fallback. |
| `.github/workflows/_reusable-pr-summary.yml` | Collects the inputs, calls both scripts, maintains the marker. |
| `.github/actions/telegram-notify/action.yml` | Thin wrapper over `telegram_notify.py`; the hand-rolled Markdown escaping (`action.yml:50-60`) is removed. |
| `.github/workflows/push.yml` | Two-message pair; `message_id` passed via job output (Part 4). |
| `.github/workflows/publish.yml` | Same pair, plus release notes and a conditional Sonar block (Part 5). |
| `.github/scripts/release_notes.py` | GitHub release body (markdown) → rich markup. |
| `.github/workflows/coderabbit-notify.yml` | Deleted. |
| `.github/workflows/review-gate.yml` | Add the aggregator call; fix the stale comment at lines 5-6 claiming `claude-review` gates anything — it was removed in `2595a29`. |

## Part 3 — Sonar quality gate

Add `-Dsonar.qualitygate.wait=true` to the scanner args in `_reusable-python-ci.yml:215-222`. The
scanner then polls SonarCloud until the gate is computed and exits non-zero on ERROR, turning
`Python CI / SonarCloud (statuskit)` red, which propagates to the already-required `Python CI Gate`.
No new required context, and no conditionally-present check for the aggregator to reason about.

This applies to `push.yml` as well, since both callers share the reusable workflow — deliberate: a
Quality Gate failure on `master` should be visible.

The external checks `SonarCloud Code Analysis` (Sonar App) and `SonarCloud` (code scanning via
GitHub Advanced Security) keep arriving and stay informational — they are the detail view, while the
blocking verdict comes from our own job. The former is also what the aggregator keys off to discover
which Sonar projects were analysed (see "Sonar block").

Accepted cost: CI gains a dependency on SonarCloud availability, and the job grows by the gate
computation time (~25 s on PR #114). Fork PRs are unaffected — the Sonar job is already skipped
there (`_reusable-python-ci.yml:191-193`).

## Part 4 — Push to master notifications

Same two-message shape as a PR, but the mechanics are far simpler: there is no review gate on a
push, and both messages live in the **same workflow run**, so `notify-start` exposes its
`message_id` as a job output and `notify-finish` replies to it. No aggregator, no commit-status
marker, no cross-run state.

| Message | Trigger | Sound |
|---|---|---|
| **Pushed to master** | `push.yml` start | silent |
| **Result** | `needs: [validate-commits, python-ci, claude-code-plugin-ci]`, `if: always()` | with sound, replying to the first |

```
🚀 feat(statuskit): dynamic per-model usage limits
Pushed to master · a1b2c3d
claude-tools · master
```

```
✅ feat(statuskit): dynamic per-model usage limits
All checks passed
[check table]
[Sonar · statuskit — project state]
claude-tools · master
```

The Sonar verdict already arrives inside `Python CI` thanks to `qualitygate.wait`, so the result
message needs no waiting of its own.

**The Sonar block here shows the overall state of the branch**, not new-code metrics:

```
Sonar · statuskit — project state
  Coverage              93.4%
  Issues                13 (blocker 1, critical 7, major 1, minor 4)
  Vulnerabilities       1
  Reliability           A
  Security              E
  Maintainability       A
  Duplication           0.0%
  Lines of code         2121
```

Two reasons. First, new-code metrics on `master` are currently meaningless: the new-code period is
`previous_version`, and since `sonar.projectVersion` is never sent, every analysis is recorded as
`projectVersion=not provided` — so "new code" on the branch stretches back to **2026-01-26**.
Second, and more importantly, the overall state is the only place where accumulated problems are
visible at all: the project currently carries a **BLOCKER vulnerability** which puts
`security_rating` at **E**, and which no gate will ever surface because the gate only evaluates new
code (see `claude-tools-5vg.8`).

## Part 5 — Release notifications

`publish.yml` already sends a pair (`Publishing...` → result); it adopts the same rich layout, the
reply link, and gains two content blocks.

```
📦 statuskit 0.5.0
Published to PyPI
[Release notes — open]
[Sonar · statuskit — project state]
claude-tools · statuskit-0.5.0
```

**Release notes come from GitHub, not from a diff.** release-please already writes them into the
release body, so `gh api repos/{o}/{r}/releases/tags/{tag} --jq .body` returns finished markdown:

```
## [0.5.0](…/compare/statuskit-0.4.0...statuskit-0.5.0) (2026-07-21)
### Features
* **statuskit:** dynamic per-model usage limits (#112) (291b32e)
```

It is converted to rich markup (`##`/`###` → `<h2>`/`<h3>`, `*` items → `<ul>`, links preserved) and
placed in an open `<details>`. Nothing is computed between tags.

**Sonar in a release notification is conditional.** Only projects that exist in SonarCloud get a
block — the organisation currently holds `NoNameItem_statuskit` and `NoNameItem_read-comics`, so a
`flow` release has no Sonar block at all. `publish.yml`'s existing `resolve` job already yields the
project name to key off.

### `sonar.projectVersion` and seeding

Sonar analyses branches and PRs, never tags, so "metrics at a tag" do not exist as such. They become
available indirectly once analyses are labelled with a version:

- Add `-Dsonar.projectVersion=<version>` to the scanner args in `_reusable-python-ci.yml`. In the
  monorepo each package is its own Sonar project with its own version, so there is no ambiguity:
  the version is read from the analysed package (`{matrix.path}/pyproject.toml`, kept in sync with
  `.release-please-manifest.json` by release-please — both currently say `0.5.0` for statuskit).
- Sonar then records a `VERSION` event whenever the version changes, which
  `api/project_analyses/search?category=VERSION` exposes, and
  `api/measures/search_history` can be queried between two such analyses — giving both the metrics
  of a released version and the **delta against the previous one**
  (`coverage 93.4% → 94.1%`, `issues 13 → 11`).
- As a side effect it repairs the new-code period on `master`, which is what makes branch-level
  new-code metrics meaningful again.

**Seeding is required and easy to forget.** Today there is no version history at all
(`projectVersion=not provided` on every analysis back to January). The first `master` analysis
carrying `projectVersion=0.5.0` creates the anchor point; only the *next* release produces a real
version-to-version delta. Therefore:

1. Land the `projectVersion` change so the current version gets recorded on the next push to
   `master` — this is the seeding step and must not be skipped or deferred.
2. Until a second `VERSION` event exists, the release notification falls back to the current state
   of `master` with no delta. This is not an error state and must not be reported as one — releases
   are cut from `master` immediately after the merge, so the numbers are the released ones anyway.

## Testing

- `pr_summary.py`: table-driven unit tests over every verdict, plus missing context, non-terminal
  context, fork PR (gate dropped), and stale head SHA.
- `sonar_pr_status.py`: project-key extraction from `details_url`; rating mapping (`1..5` → `A..E`);
  metric formatting including the absent-metric `—` case; threshold rendering for both comparators
  (`LT` → `≥`, `GT` → `≤`) and the rating special case (`need A`); a variable condition set (four
  conditions on a release PR, six on a code PR); severity-breakdown assembly from facets;
  degradation when the API returns an error or times out.
- `telegram_notify.py`: golden-output tests for all four verdicts in both renderings; escaping of
  titles containing `<`, `>`, `&`; button composition; `skip_entity_detection` present; the emphasis
  rule (bold present exactly on failures, absent on a green notification).
- Release-notes conversion: markdown headings, nested list items, links and inline code from a real
  release body; an empty body (release with no notes) must not produce an empty `<details>`.
- Manual: one throwaway PR exercising green, red and unresolved-comments paths, plus a gate re-run
  to confirm the verdict flip re-notifies; the push pair on merging it; and the release pair on the
  next release-please merge.

## Rollout order

The order matters — required contexts with the new names only exist after the workflow change is on
`master`:

1. Merge the repository change (renamed summary jobs, aggregator, Sonar wait, `projectVersion`,
   push/release notifications, CodeRabbit removal).
2. Then update the ruleset (new required contexts, migrated rules) and delete the classic branch
   protection.
3. Confirm on the first `master` analysis afterwards that `projectVersion` was recorded (a `VERSION`
   event appears in `api/project_analyses/search`) — the seeding step from Part 5.

Open PRs created before step 1 will lack `Python CI Gate` / `Claude Code Plugin CI Gate` on their
head SHA and will need a push or re-run before they can merge.

## Risks and limitations

- `sendRichMessage` is ~6 weeks old; the fallback path covers an API-side regression, and both
  renderings are tested.
- Commit statuses are keyed by `(SHA, context)`, not by PR, so the `pr-notify` marker inherits the
  same theoretical cross-PR collision that `review-gate.yml:24-27` already documents for shared
  SHAs.
- Reading required contexts from the branch-rules API means a ruleset edit changes notification
  behaviour with no code change — intended, but worth knowing when debugging.
- The Sonar block adds a dependency on `sonarcloud.io` at notification time; it degrades to the gate
  title alone, so an outage costs detail, not the notification.
- The verdict reflects the moment every check settled. Resolving threads afterwards does not
  re-notify: that would require watching review events, which this design deliberately leaves out.
