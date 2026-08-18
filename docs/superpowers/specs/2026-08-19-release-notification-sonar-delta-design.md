# Release notification: Sonar delta and block presentation — design

Tasks: `claude-tools-5vg.10` (version-to-version delta) and `claude-tools-5vg.21` (make the Sonar
block readable at a glance), both children of the consolidation container `claude-tools-5vg.23`.
The container's third task, `claude-tools-5vg.14` (pin the notification implementation to a trusted
revision), is deliberately **not** covered here: it is a security change with a shape already fixed
in `docs/merge-gate-rollout.md`, Step 7, and lands as the last commit of the same branch.

Predecessor design: `docs/superpowers/specs/2026-07-27-pr-merge-gate-and-notifications-design.md`,
Part 5. This document supersedes Part 5's "the release notification falls back to the current state
of `master` with no delta" as the *end state* — that fallback survives, but only as degradation.

## Context

The release notification today answers "was it published?" and not "is the released code healthy?".
Its Sonar block is titled `Sonar · statuskit — project state`, is collapsed, and carries absolute
metrics with nothing to compare them against:

```
📦 statuskit 0.5.1
Published to PyPI
▲ Release notes            ← expanded
▼ Sonar · statuskit — project state    ← collapsed, title says nothing
```

Four findings from investigating the live system shaped every decision below.

### Finding 1 — publish races the analysis, and loses

`publish.yml` is triggered by `release.published`; the Sonar analysis of the release commit runs in
a *different* workflow (`push.yml` → `_reusable-python-ci.yml`) triggered by the push to `master`.
Neither waits for the other. On the statuskit 0.5.1 release the publish run finished at
`12:53:02Z` and the analysis carrying `projectVersion=0.5.1` landed at `12:53:12Z` — ten seconds
too late to be seen.

`-Dsonar.qualitygate.wait=true` (already set, `_reusable-python-ci.yml:245`) does not help: it
synchronises the *scanner* with the Sonar server inside the analysis job, not one workflow run with
another.

The analysis record carries the commit it was produced from:

```json
{"date": "2026-07-31T12:53:12+0000", "projectVersion": "0.5.1",
 "revision": "dab4b1f00b091b8c2bd1f7fa402500a42e77d059"}
```

`dab4b1f` is exactly the commit the `statuskit-0.5.1` tag points at, so waiting can be precise
rather than heuristic.

### Finding 2 — the new-code period on `master` is now the release window

Seeding `sonar.projectVersion` had a side effect worth more than the delta it enabled. The new-code
period on `master` is `previous_version`:

```json
{"index": 1, "mode": "previous_version", "date": "2026-07-31T12:06:46+0000", "parameter": "0.5.0"}
```

So the Quality Gate on `master` already judges precisely the code the release adds, and
`api/qualitygates/project_status?projectKey=…&branch=master` returns a real verdict
(`"status": "OK"`) with per-condition thresholds. The release path can carry the same gate verdict
the PR path already shows, with no new computation.

### Finding 3 — the version history contains one poisoned entry

`api/project_analyses/search?category=VERSION` returns three events: `0.5.1`, `0.5.0`, and
`not provided` (2026-07-21, from before `projectVersion` was set). Any baseline selection must
reject `not provided` explicitly — it is a version name, not an absent field.

### Finding 4 — Telegram renders no colour except emoji

Probed against the live Bot API and confirmed visually in the client: `<span style="color:…">`,
`<font color="…">` and a `color` attribute on `<td>` are all *accepted* by `sendRichMessage` and
then silently dropped — those rows render identically to unmarked text. What does render: emoji
(🔴 🟢 carry real colour), monochrome arrows (▲ ▼), and `<b>`.

Colour therefore has to come from an emoji marker in the cell, and `<b>` stays reserved for its
existing meaning (`telegram_notify.py`: *"bold marks exactly what needs attention … so bold =
problem stays unambiguous"*).

## Scope

**In:** the release notification only (`publish.yml`).

**Out:** the push notification on `master` (`push.yml`) keeps today's `--mode branch` block
unchanged. The delta is measured *since the previous release*, which answers a question a push
notification is not asking — there the reader wants "did my commit break anything", not "what has
accumulated since 0.5.0". PR notifications are untouched as well; collapsing is deliberate there
(`claude-tools-5vg.21` acceptance).

## Architecture

A new `--mode release` in `.github/scripts/sonar_pr_status.py`, alongside `pr` and `branch`. Not a
flag on `branch`: the shape differs (deltas instead of absolute values, a gate block, a trend in the
title) and so do the inputs (released version, tag revision). `branch` stays byte-for-byte what
`push.yml` consumes.

Call site in `publish.yml`, replacing today's `--mode branch` invocation:

```bash
python3 .github/scripts/sonar_pr_status.py --mode release \
  --project-keys "$(jq -nc --arg p "$PROJECT_NAME" '["NoNameItem_" + $p]')" \
  --branch master --version "$VERSION" --revision "$GITHUB_SHA" > sonar.json
```

On a `release` event `github.sha` is the commit the tag points at — the value Sonar stores as
`revision`. The waiting loop lives inside the script rather than in a workflow step: it is then unit
testable, and the YAML stays declarative.

### Data flow

1. **Wait for the release revision's analysis.** Poll `api/project_analyses/search?project=<key>`
   until an analysis with `revision == <tag sha>` appears. Interval 15 s, ceiling **10 minutes**.
   In practice the wait is around a minute (publish takes ~2.5 min, the analysis landed ~10 s
   after it).
2. **Pick the baseline.** From the same response, the most recent `VERSION` event whose name is
   neither the released version nor `not provided`. That is the previous release; its analysis date
   is the left edge of the window.
3. **Read both ends.** One call to
   `api/measures/search_history?component=<key>&metrics=…&from=<baseline date>`. The response gives
   each metric a list of dated points; the baseline value is the point at the baseline analysis
   date, the head value is the point at the head analysis date (the last point if the head date is
   absent).
4. **Read the gate.** `api/qualitygates/project_status?projectKey=<key>&branch=master` — status plus
   conditions, rendered by the existing `build_gate_block`.

Severity breakdowns (`critical 7, minor 4`) come from `issues/search` facets and remain
**current-state only**: Sonar exposes no history for them. A row reads as "was 13, is 15, and here
is what today's 15 consists of".

## Rendering

### Two blocks

```
▼ Sonar · statuskit — Quality Gate passed
▼ Sonar · statuskit — since 0.5.0 · 🔴 2 worse, 🟢 2 better
```

The gate block is `build_gate_block` unchanged — conditions with their thresholds
(`✅ Coverage — 96.2% (need ≥ 80%)`), which is what makes "how close are we to failing" legible.
The delta block carries absolute project metrics.

They are two blocks rather than one table because they use different coordinate systems: gate
conditions are about **new code** (`new_coverage`, `new_violations`, ratings on new code), the delta
is about the **whole project**. Merging them puts `Coverage 94.1%` next to a `need ≥ 80%` that
belongs to a different measurement of a different set of lines.

Both verdicts stay visible while collapsed, because each block's summary line carries its own.

**Open state:**

- gate block — open when the gate failed (already `build_gate_block`'s rule: `"open": not passed`);
- delta block — open when there is at least one regression (🔴 count > 0);
- otherwise collapsed.

### Delta rows

The metric set is the branch block's (`_BRANCH_METRICS`) — coverage, issues, vulnerabilities, the
three ratings, duplication, lines of code — including its conditional `Hotspots` row, which appears
only while a non-zero count exists. Only the right-hand value changes shape:

| Case | Rendering |
|---|---|
| changed, polarity known | `🟢 93.4% → 94.1%` / `🔴 13 → 15 (critical 7, minor 4)` |
| changed, no polarity | `2121 → 2280` |
| unchanged | `93.4%` — exactly as today |
| one end missing | current value, no arrow |

Polarity: up is good only for `coverage`; up is bad for `violations`, `vulnerabilities`,
`security_hotspots`, `duplicated_lines_density` and the three ratings (Sonar encodes them `1..5`
with `1` = A, so a numeric rise is a downgrade — `🔴 A → B`); `ncloc` is neutral.

No bold anywhere in either block's rows beyond what `build_gate_block` already does for breached
conditions.

### Titles

Delta block: `Sonar · <project> — since <baseline version> · <trend>`.

The trend segment counts only metrics that carry polarity — neutral rows never move a counter. Its
three forms:

- regressions present: `🔴 2 worse, 🟢 2 better` (red first, green omitted when zero);
- improvements only: `🟢 3 better`;
- nothing changed: the segment is omitted entirely.

Message title: `Release <project> <version>` (today: `<project> <version>`). On the path where
`resolve` failed and neither name nor version exists, `Release <tag>` — the tag is the only
identifier left.

Everything else about the message is unchanged: the `📦` icon from `status: released`, the verdict
line (`Published to PyPI`), the expanded release notes, footer, buttons, and the reply link to the
`Publishing…` message.

## Degradation

The module's existing posture holds: a Sonar outage costs detail, never the notification.

| Case | Behaviour |
|---|---|
| project absent from SonarCloud (a `flow` release) | no Sonar blocks at all — unchanged |
| `measures` unavailable | no Sonar blocks; the message ships with release notes only |
| `project_status` unavailable | gate block omitted, delta block still rendered |
| no usable baseline (one `VERSION` event, or only `not provided`) | delta block degrades to today's `Sonar · <project> — project state`: absolute values, collapsed, no trend segment |
| wait exceeds 10 minutes | head becomes the latest available analysis; a degradation line goes to stderr |
| a metric exists at only one end of the window | row shows the current value with no arrow |

The no-baseline degradation is the same rendering as the first release of any project, which is why
it needs no separate "unavailable" presentation.

## Testing

Unit tests extend `.github/scripts/tests/test_sonar_pr_status.py`, following its existing
class-per-function layout:

- `search_history` parsing into baseline/head pairs, including a head date absent from the history;
- polarity per metric, ratings included (`1..5`, up is worse) and the neutral `ncloc`;
- marker rendering for all four row cases in the table above;
- trend-segment assembly in all three forms, and the counter ignoring neutral metrics;
- open-state rules for both blocks;
- baseline selection: `not provided` rejected; head already carrying the released version (baseline
  is then the second-newest event) and head not yet carrying it (baseline is the newest);
- the wait loop, success and timeout, with the sleep injected so tests do not actually wait;
- degradation paths, matching the table above.

**Live check before any release.** The new mode can be exercised against real data immediately:
`NoNameItem_statuskit` has both `VERSION` events and the `statuskit-0.5.1` tag revision is known
(`dab4b1f`). `--mode release --version 0.5.1 --revision dab4b1f…` must return blocks whose delta is
zero on every metric, because 0.5.0 and 0.5.1 are numerically identical (`coverage 93.4`,
`violations 13`, `ncloc 2121` at both ends). A non-zero delta there means the window was picked
wrongly.

**Final check:** the first release notification after this lands.

## Documentation corrections

Two comments assert that new-code metrics on `master` are meaningless until `projectVersion` seeds
the period — `push.yml` (step 3 of the spec assembly) and the module docstring of
`sonar_pr_status.py`. The period was seeded on 2026-07-31 and the release gate now stands on it, so
both mislead the next reader and are corrected as part of this work.

`docs/merge-gate-rollout.md`, Step 5, tells the reader that release notifications legitimately fall
back to "no delta" until a second `VERSION` event exists. That remains true as a description of the
degradation, and gains a pointer to this document.
