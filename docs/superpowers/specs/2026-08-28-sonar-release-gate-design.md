# Design: Sonar release gate on release-please PRs

**Task:** claude-tools-5vg.25
**Date:** 2026-08-28

## Problem

`NoNameItem way` (the gate designed in `2026-08-28-sonarcloud-quality-gate-design.md`) judges new
code only. That is D3 of that design and it stays: accumulated debt must not decide the fate of a
feature PR. The consequence, however, is that accumulated debt is judged **nowhere** — `python-ci`
is skipped for `release-please--*` branches, so SonarCloud does not analyse a release PR at all,
and the release ships whatever master happens to carry.

The live example the task was filed for: `pythonsecurity:S2083` in `setup/hooks.py:49` — BLOCKER,
open since 2026-01-19, the sole reason overall `security_rating` is E. The merge gate does not see
it and never will.

The policy this design implements: **the release bar is stricter than the merge bar.** A problem
may be merged into master to unblock other work; it may not be released.

## Evidence gathered (2026-08-28, public SonarCloud API)

### Overall conditions are inert on pull-request analyses

`read-comics` runs on `Sonar way no coverage` (id 83786), whose nine conditions include four
overall ones: `security_rating`, `reliability_rating`, `sqale_rating`, `security_hotspots_reviewed`.

| Analysis | `reliability_rating` | `security_hotspots_reviewed` | Gate |
|---|---|---|---|
| branch `main` | **ERROR**, actual `4` | **ERROR**, actual `0.0` | ERROR |
| branch `develop` | **ERROR**, actual `4` | **ERROR**, actual `0.0` | ERROR |
| PR #107 (`develop` → `main`, 2026-01-14) | OK, **no `actualValue`** | OK, **no `actualValue`** | ERROR — from `new_violations` (11) and `new_security_hotspots_reviewed` alone |

`reliability_rating` on `main` reads `4.0` at every one of its 106 history points (2023-05-06 →
2025-12-01), and `develop` — the PR's own source branch — reports `4` today. The overall state was
therefore already broken when PR #107 was analysed, yet its overall conditions carry **no measured
value at all** and resolve to OK.

**Consequence:** one gate carries two strictness levels. Its new-code half applies to pull requests
and to branches; its overall half applies to branch analyses only. Since SonarCloud binds exactly
one gate per project, this is the only mechanism by which a release bar can differ from a merge bar
— and it is precisely the mechanism this design needs.

### An analysis is addressable by revision

`api/project_analyses/search?project=…&branch=master` returns, per analysis, both `key` and
`revision` (full SHA). `api/qualitygates/project_status?analysisId=<key>` returns the verdict **of
that analysis**, not of the branch's current head. Verified against `NoNameItem_statuskit`
(`revision` `effda08…` = master head, `analysisId` query returns its conditions).

### The gate verdict is computed at analysis time and stored

It is not recomputed per request. Editing a gate's conditions therefore changes nothing about
already-stored verdicts; the new composition takes effect with the next analysis. This dictates
the rollout order below.

### statuskit on master, current state

| overall metric | value |
|---|---|
| `violations` | 13 — 1 BLOCKER, 7 CRITICAL, 1 MAJOR, 4 MINOR |
| `security_rating` | **E (5.0)** (`pythonsecurity:S2083`) |
| `reliability_rating` | A |
| `sqale_rating` | A (`sqale_debt_ratio` 0.1%) |
| `coverage` | 93.4% |
| `duplicated_lines_density` | 0.0% |
| `security_hotspots` | 0 |

`NoNameItem way` is id 159229 and holds the eight new-code conditions of D1, unchanged.

### Release PRs are per component

`release-please-config.json` sets `separate-pull-requests: true`, so each component gets its own PR
on `release-please--branches--master--components--<component>` titled
`chore(<component>): release <version>`. Components today: `statuskit` (a Python package, analysed
by Sonar) and `flow` (a Claude Code plugin, **not** a Sonar project). PR #115 —
`chore(flow): release 3.2.0` — is open right now and must not be blocked by a Sonar check.

## Goal / success criteria

1. A release PR for a Sonar-analysed component cannot be merged while that component has any open
   violation, coverage below 80%, or duplication above 3%.
2. The merge bar for feature PRs is unchanged — no overall condition can redden a PR.
3. Master CI does not turn red for accumulated debt that the policy deliberately allows in.
4. The verdict is legible in the check's own summary: release PRs are silent in Telegram by design
   (`notify-start` and `pr-summary` both skip `release-please--*`), so the check run is the only
   place a human reads it.
5. The check cannot pass on an analysis that predates the code being released.

## Design decisions

### D1. Strictness lives in the gate, not in our code

Three overall conditions are added to `NoNameItem way`:

| Condition | Operator | Threshold | Current | Verdict today |
|---|---|---|---|---|
| `violations` | GT | 0 | 13 | ❌ |
| `coverage` | LT | 80 | 93.4% | ✅ |
| `duplicated_lines_density` | GT | 3 | 0.0% | ✅ |

`violations` counts every open issue regardless of severity, and the ratings are derived from open
issues — with zero violations, `security_rating`, `reliability_rating` and `sqale_rating` cannot be
anything but A, and `blocker_violations` / `critical_violations` cannot be anything but 0. One
condition therefore replaces five. What remains are the two properties that issues do not express:
coverage and duplication.

The gate now reads as one sentence: **master accepts anything that adds no new BLOCKER or HIGH; a
release accepts no open violation at all.**

Thresholds for coverage and duplication mirror the new-code half (80 / 3) rather than tightening to
90 / 1. A PR legitimately passes at 80% coverage on its new code; an overall threshold above that
would let a legal merge push the product under the release bar, discoverable only at release time
and with no signal on the PR that caused it.

**Limitation to remember:** one gate per project means one threshold per metric. "New code needs
80% to merge but 90% to release" is not expressible; strictness is expressible *only* by adding
overall conditions. Anything finer would mean thresholds back in our own code.

**Cost at adoption:** the 13 open issues block the next statuskit release (previous release 0.5.1,
2026-07-31). None of them is tracked in beads yet — epic `claude-tools-4u3` is empty; `/flow:sonar-sync`
exists for exactly this.

**Constraint this creates:** D1 of the earlier design noted that `NoNameItem way` was named
project-neutrally so it could become the organisation default later. With `violations GT 0` it
cannot be bound to read-comics (220 open bugs) without making that project's gate permanently red.

### D2. `qualitygate.wait` becomes an input; master pushes stop blocking

A push to master is a *branch* analysis, where overall conditions are evaluated, and
`_reusable-python-ci.yml` runs the scanner with `-Dsonar.qualitygate.wait=true` — the scanner exits
non-zero on ERROR. Left as is, every push touching Python code would fail `sonarcloud` → `Python CI`
and arrive in Telegram as "Checks failed" for as long as any debt is open.

That punishes master for exactly what the policy permits, and it manufactures the failure mode the
earlier design already named: a gate that is always red stops being read.

`_reusable-python-ci.yml` gains a `qualitygate-wait` input (default `true`). `pr.yml` keeps `true`
— that is the merge gate. `push.yml` passes `false`; the merge has already happened and there is
nothing left to block.

**Consequence:** `wait=true` incidentally guaranteed that the analysis was computed by the time the
push notification assembled its Sonar block. That guarantee is restored explicitly —
`sonar_pr_status.py --mode branch` gains an optional `--revision <sha>` and waits for the analysis
of that revision, reusing `wait_for_analysis` (written for `--mode release`, poll 15 s). `push.yml`
passes `$GITHUB_SHA`.

### D3. The verdict is addressed by revision, never by branch

The race, as reported: a push lands on master → its scan starts → release-please updates the
release PR → the release PR's CI asks Sonar → the scan finishes. A branch-scoped read
(`project_status?branch=master`) answers with the *previous* analysis and passes a release whose
code was never judged.

The check therefore resolves an analysis first and reads that analysis's verdict:

1. `base_sha` = `github.event.pull_request.base.sha` — the master state the release is built from.
   The job checks out with `fetch-depth: 0`.
2. Walk `project_analyses/search?branch=master` (newest first) for the first analysis whose
   revision `R` satisfies both: `R` is an ancestor of `base_sha`
   (`git merge-base --is-ancestor R base_sha`), and `git diff --quiet R base_sha -- packages/<component>`
   reports **no difference** — nothing Sonar analyses changed between the analysed state and the
   released one. A tree comparison, not a history walk: a commit-plus-revert pair or merge-commit
   history simplification can make `git log` answer "changed" for a tree that did not.
3. Read `project_status?analysisId=<key>` for that analysis. A newer scan finishing mid-run cannot
   change the answer, because the answer is bound to a revision.
4. No such analysis yet → sleep 15 s and repeat, to a ceiling of 10 minutes; then fail with
   "master's analysis lags behind the release commit". Both constants already exist in
   `sonar_pr_status.py` (`_POLL_INTERVAL_SECONDS`, `_POLL_CEILING_SECONDS`).

Step 2 does both jobs at once. An in-flight scan shows up as "the package changed after `R`" and is
waited for; master moving ahead on docs or plugin commits leaves the package untouched, so the
older analysis stays valid and the release does not hang on a commit Sonar will never analyse.

### D4. Freshness is "nothing relevant changed", not "analysis of head"

Requiring the analysis to sit exactly on master's head would block every release permanently after
the first docs commit, because such a commit produces no analysis at all. The relevant path set is
the one that makes `push.yml` run `python-ci` with the scanner for that project — the package's own
directory. Tooling-only changes route to `python-ci-info` (`info-only: true`, scanner skipped) and
correctly do not count as staleness.

### D5. Fail closed

Sonar unreachable after 3 attempts with backoff, or no usable analysis within the ceiling, or no
analysis at all → exit 1. "Sonar did not answer" is not a statement about code quality, releases
are roughly monthly, and a re-run is one click. This is symmetric with the cost already accepted
for `-Dsonar.qualitygate.wait=true` in the merge gate.

The single exception is structural rather than a failure: a component with no Sonar project (`flow`)
skips with exit 0. Anything else would make plugin releases impossible.

### D6. A new script, not a fourth mode of `sonar_pr_status.py`

That module's contract is written into its docstring: it never raises out of `main`, always exits 0,
and degrades to less detail on any API failure — a Sonar outage must cost detail, not the
notification. A release gate needs the exact opposite contract. Mixing the two in one entry point
would make the "never fails" promise conditional on a flag, which is how such promises get broken.

`.github/scripts/sonar_release_gate.py` therefore stands on its own and imports what it shares:
`fetch_json`, `format_measure`, `format_threshold`, `wait_for_analysis`, `find_analysis`,
`revision_matches`.

Interface:

```
python3 .github/scripts/sonar_release_gate.py --component statuskit [--branch master] \
    --base-sha <sha>
```

Output: a table (condition · threshold · actual · status) on stdout and in `$GITHUB_STEP_SUMMARY`,
one `::error::` per breached condition, plus the resolved analysis (revision, date) so a reader can
tell *what* was judged. Exit 1 on ERROR or on any of the D5 cases.

### D7. The component comes from the head ref, not from `detect`

`release-please--branches--master--components--<component>` answers "what is being released";
`detect` answers "what changed in this PR". On a release PR they coincide, but only because
release-please happens to touch just the released component's files — that is a coincidence, not a
contract.

Component → project: `discover_projects()` from `projects.py` yields `ProjectInfo.kind`; only a
`package` maps to a Sonar key, formed as `NoNameItem_<component>` exactly as `push.yml` does.

### D8. The result joins the existing aggregator

`python-ci-result` (context `Python CI Gate`) is already `if: always()` and already treats `skipped`
as success, so the new job enters as a second `needs` and the `master merge gate` ruleset needs no
new required context — the same reasoning that gave the reusable-workflow calls their wrappers.

The job itself is guarded like every other secret-bearing job in `pr.yml`: it runs only on
`release-please--*` head refs and only for same-repo PRs (it reads `SONAR_TOKEN`, which GitHub
withholds from fork-origin runs). Its permissions are `contents: read` — a checkout and `git diff`
are all it needs; the check run publishing the context is created by Actions itself.

## Scope

**In scope (this task):**

1. Three overall conditions on `NoNameItem way` via the API (needs a user token with admin rights,
   as in the previous design).
2. `.github/scripts/sonar_release_gate.py` plus `.github/scripts/tests/test_sonar_release_gate.py`.
3. Job `release-sonar-gate` in `pr.yml`, wired into `python-ci-result`.
4. `qualitygate-wait` input in `_reusable-python-ci.yml`; `push.yml` passes `false`.
5. `--revision` wait in `sonar_pr_status.py --mode branch`; `push.yml` passes `$GITHUB_SHA`.
6. This document.

**Out of scope:**

- Fixing the 13 open issues — epic `claude-tools-4u3`, populated via `/flow:sonar-sync`.
- `security_hotspots_reviewed` as an overall condition. statuskit has 0 hotspots, and read-comics
  shows the metric reporting `0.0` (permanent ERROR) rather than a dormant 100 — so it is not the
  harmless sleeper D5 of the earlier design assumed. Revisit when hotspots actually appear.
- read-comics and its gate.
- Any non-GitHub platform.

## Implementation

Order matters, because of the stored-verdict property:

1. **Ship the CI change first** — script, job, `qualitygate-wait`, `--revision`. With the gate
   unchanged the new job is green, which proves the plumbing (component resolution, analysis
   resolution, summary rendering) without the debt in the way.
2. **Add the three conditions** through `api/qualitygates/create_condition` on gate 159229; verify
   with `api/qualitygates/show` that the gate holds 11 conditions.
3. **Re-run master's push CI** so an analysis is produced under the new composition. Until then
   every stored verdict still reflects the old gate.
4. **Confirm the new state**: `project_status?branch=master` is ERROR on `violations`.

Adding the conditions before step 1 would redden every master push in the interval, since
`wait=true` is still in force there.

## Verification

Acceptance:

1. `api/qualitygates/show?name=NoNameItem way` returns 11 conditions — the eight new-code ones of
   the earlier design's D1 plus the three overall ones of D1 above, and nothing else.
2. A feature PR opened after step 2 stays green in `sonarcloud`. This is the live falsification test
   for the read-comics evidence: if overall conditions did apply to PRs, statuskit's 13 violations
   would redden it instantly.
3. A statuskit release PR shows `Release Sonar Gate` red, with `violations 13 (need ≤ 0)` in the
   step summary and the resolved analysis revision printed next to it; `Python CI Gate` is red in
   consequence.
4. A flow release PR (#115) skips the job and keeps `Python CI Gate` green.
5. A push to master touching Python code: `sonarcloud` is green despite the overall ERROR, and the
   push notification still carries its Sonar block (the `--revision` wait).
6. Unit tests cover component mapping, the skip path, stale-analysis resolution (including the
   ancestor and path checks), the API-failure exit code, and table rendering.

## Risks

- **Stored verdicts hide gate edits.** Any future change to the gate is invisible until the next
  analysis of each branch. Step 3 handles it here; the property is worth remembering.
- **A ten-minute ceiling may be short.** Master's Python CI runs tests and coverage before the scan;
  a slow run could exceed it and redden a release check that a re-run would pass. Chosen over an
  unbounded wait, which would hide a genuinely broken master CI.
- **`violations GT 0` is a ratchet.** An analyser update that surfaces old findings blocks releases
  until they are fixed or marked Accepted. That is the intended behaviour, and Accepted is visible
  in the UI — unlike a quietly lowered threshold.
- **The staleness check assumes the analysed path set.** `git diff R base -- packages/<component>`
  mirrors what triggers an analysis today. If `projectBaseDir` or `sonar.sources` change, this check
  must change with them.
- **`base_sha` is a payload snapshot, not the merge target at run time.** The gate judges
  `github.event.pull_request.base.sha` — the release base as it stood when the PR event fired. The
  ruleset sets `strict_required_status_checks_policy: false` (`docs/merge-gate-rollout.md`), so
  branches are not required to be up to date, and merging the release PR merges into whatever
  master is at that moment. If a commit touching the released package lands on master after the
  last `synchronize` AND does not cause release-please to re-open the PR (a type hidden from
  `changelog-sections`, e.g. `chore:`/`refactor:`/`test:`), the release carries code the gate never
  judged. This is narrow: it needs a same-window master push whose commit type release-please
  ignores, on a package a release PR for that same component is already open against. The option
  not taken is deriving the base from the checked-out merge ref's `HEAD^1` instead, which is
  recomputed when the job runs and is therefore fresher than the payload value — left for the
  repository owner to revisit, since it would also change what "the release base" means for every
  other guard that reads `base.sha`.

## References

- `docs/superpowers/specs/2026-08-28-sonarcloud-quality-gate-design.md` — D1 (gate composition), D3
  (why no overall conditions on the merge gate)
- `.github/workflows/pr.yml` — `python-ci-result`, the release-PR guards
- `.github/workflows/_reusable-python-ci.yml` — the `sonarcloud` job and `qualitygate.wait`
- `.github/workflows/push.yml` — the branch-state Sonar block
- `.github/scripts/sonar_pr_status.py` — shared helpers and the "never fails" contract
- `release-please-config.json` — `separate-pull-requests`, component naming
- `docs/merge-gate-rollout.md` — the required-context history
