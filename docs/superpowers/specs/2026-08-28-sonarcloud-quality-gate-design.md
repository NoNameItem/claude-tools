# Design: SonarCloud quality gate for statuskit

**Task:** claude-tools-5vg.8
**Date:** 2026-08-28

## Problem

`NoNameItem_statuskit` uses the built-in `Sonar way` gate (id 9). All six of its conditions apply
to new code only, and **`new_violations` is not among them**. A PR that introduces new issues
therefore merges as long as they are code smells and the added technical debt stays under 5% of
the diff — so whether the merge is blocked depends on the **size of the diff**, not on the quality
of what was added.

Verified against real PRs via the SonarCloud API:

| PR | New issues | Gate |
|----|-----------|------|
| #112 `feat(statuskit): dynamic per-model usage limits` | 6 (5× `python:S3776` HIGH, 1× `python:S5713` LOW) | **OK** — 1357 new lines gave maintainability rating A |
| #107 `feat(statuskit): show current-branch PR/MR in git module` | 5 | **OK** |

The same findings on a small PR would have failed the gate.

## Evidence gathered (2026-08-28, public SonarCloud API)

### The organisation has two projects and two gates

| | statuskit | read-comics |
|---|---|---|
| Gate | `Sonar way` (id 9, built-in) | `Sonar way no coverage` (id 83786, **org default**) |
| Python profile | `Sonar way` (built-in, 481 rules) | `python` (custom, 222 rules) |
| ncloc | 2 121 | 225 501 |
| `alert_status` | OK | **ERROR** |

`Sonar way no coverage` already carries `new_violations GT 0` **and** four overall conditions —
and on read-comics it is permanently red (`reliability_rating` = D, 220 bugs). A gate that is
always red stops being read; this is the counter-example that shaped the decisions below.

### statuskit measures on master (analysis of 2026-07-31, release 0.5.1)

- overall: `violations` 13, `bugs` 0, `vulnerabilities` 1, `code_smells` 12
- `coverage` 93.4% (110 of 1670 lines uncovered), `duplicated_lines_density` 0.0%
- `sqale_index` 91 min, `sqale_debt_ratio` 0.1%, `sqale_rating` A, `reliability_rating` A
- **`security_rating` E (5.0)** — one BLOCKER vulnerability
- `security_hotspots` 0, therefore `security_hotspots_reviewed` = 100% trivially

The 13 open issues: 7× `python:S3776` (cognitive complexity 17..31 against a threshold of 15),
4× `python:S5713`, 1× `python:S7632`, 1× `pythonsecurity:S2083` (BLOCKER).

### Which ratings actually block, and which do not

- `new_reliability_rating` / `new_security_rating` are severity-based in MQR: **one** new issue of
  the corresponding software quality — at any severity — drops the rating below A and reddens the
  gate. Confirmed by statuskit: a single SECURITY/BLOCKER issue yields `security_rating` = E.
- `new_maintainability_rating` is **not** severity-based. The API describes `sqale_rating` as
  "A-to-E rating based on the technical debt ratio", and statuskit holds rating A while carrying
  seven MAINTAINABILITY/HIGH issues.

**Consequence: the hole is maintainability only.** Bugs and vulnerabilities are already blocked
by the existing gate; code smells are not.

### MQR severity counters do not exist as gate metrics

Of the 165 metrics exposed by `api/metrics/search`, none counts issues by MQR severity
(BLOCKER/HIGH/MEDIUM/LOW). What exists: `new_violations` (all), per-software-quality counters
without severity, and the **legacy** severity counters `new_blocker_violations`,
`new_critical_violations`, `new_major_violations`, `new_minor_violations`, `new_info_violations`.

The legacy-to-MQR mapping holds 1:1 on all 13 statuskit issues:

| Legacy | MQR |
|---|---|
| BLOCKER | BLOCKER |
| **CRITICAL** | **HIGH** |
| MAJOR | MEDIUM |
| MINOR | LOW |

### How a red gate blocks a merge

`_reusable-python-ci.yml` runs the scanner with `-Dsonar.qualitygate.wait=true`, so the scanner
exits non-zero on ERROR → the `sonarcloud` job fails → `python-ci` fails → `Python CI Gate`
(`pr.yml`, `if: always()`) exits 1 → the ruleset **`master merge gate`** (id 18373772, active on
`refs/heads/master`) refuses the merge. Required checks: `Validate PR`, `Python CI Gate`,
`Claude Code Plugin CI Gate`, `Review Gate`.

The chain works; only the gate's conditions need changing.

### New Code Definition

`sonar.leak.period = previous_version`, inherited from the instance level. For a PR the new code
is the PR diff; on master it is the delta since the previous release. Unchanged by this design.

## Goal / success criteria

1. A PR that introduces a BLOCKER or HIGH issue cannot be merged, **regardless of diff size**.
2. MEDIUM and LOW issues never block a merge — they are collected as beads tasks via
   `/flow:sonar-sync`.
3. Accumulated (overall) debt never blocks a feature PR.
4. The gate's composition is written down, so a later drift is at least *detectable* by reading
   this document.

## Design decisions

### D1. New gate `NoNameItem way`, eight conditions, new code only

`Sonar way` is built-in and cannot be edited (`actions.manageConditions = false`); the gate is
created as a copy and bound to `NoNameItem_statuskit`. The name is deliberately project-neutral,
because the gate is intended to become the organisation default later.

| Condition | Operator | Threshold | Status | Rationale |
|---|---|---|---|---|
| `new_blocker_violations` | GT | 0 | **new** | BLOCKER never merges |
| `new_critical_violations` | GT | 0 | **new** | HIGH never merges (legacy CRITICAL ↔ MQR HIGH) |
| `new_security_rating` | GT | 1 | kept | any new vulnerability |
| `new_reliability_rating` | GT | 1 | kept | any new bug |
| `new_maintainability_rating` | GT | 1 | kept | fuse against an avalanche of MEDIUM/LOW |
| `new_coverage` | LT | 80 | kept | tests for new code |
| `new_duplicated_lines_density` | GT | 3 | kept | duplication in new code |
| `new_security_hotspots_reviewed` | LT | 100 | kept | dormant guard, see D5 |

The rule reads as one sentence: **BLOCKER and HIGH do not pass; everything else lives in the
tracker.** `new_maintainability_rating` is the one deliberate exception to that sentence: it can
still fail a PR whose MEDIUM/LOW findings add up to more than 5% of the diff's effort. It is kept
as a fuse, at the price of that asymmetry — and it is the condition to drop first if it ever fires
on a PR that should have passed.

### D2. Why the threshold is BLOCKER/HIGH and not "zero new issues"

Considered and rejected: `new_violations GT 0` (as in `Sonar way no coverage`) and a MEDIUM-and-up
threshold.

MEDIUM is the largest bucket — 131 of 252 active maintainability rules for Python, 212 of 469
overall — so blocking on it approaches "block everything" while being much harder to explain. It
also contains `python:S1134` ("Track uses of FIXME"), which would make a leftover `# FIXME` block
a merge.

The HIGH/MEDIUM boundary is explainable: **HIGH means the code does not do what it looks like it
does** (cognitive complexity, `StopIteration` swallowed inside a generator, an override that
breaks its contract); **MEDIUM means the code is fine but a convention is broken** (naming, style,
a leftover marker).

Cost of the strict threshold: false positives redden the gate. The escape hatch exists and is
verified — an issue marked Accepted or False Positive drops out of the gate counters. statuskit
has 14 issues in total, one of them `FALSE_POSITIVE`, and `violations` = 13.

### D3. No overall conditions

Accumulated debt must not decide the fate of a feature PR. An overall condition would not force
the fix into the feature PR (a dedicated fix PR passes the gate on its own, since the fix restores
the rating), but it would **stop every other PR** until that fix is merged — and a Sonar rule
update can surface several old findings at once. Seven of the current 13 issues appeared in July
on code that had not changed.

Where accumulated state *is* checked instead:

- **Now:** `push.yml` sends the overall branch state to Telegram on every push to master
  (`sonar_pr_status.py --mode branch` reads `vulnerabilities`, `security_issues`,
  `security_rating`, `reliability_rating`, `sqale_rating`). Added 2026-07-30 in PR #119 — one
  month old, so its effectiveness is not yet established.
- **Planned:** an overall check on the release-please PR — see "Follow-up work".

### D4. Muting rules via scanner properties, not a custom profile

Two rules are switched off by decision:

- **`python:S1192`** "String literals should not be duplicated" (threshold 3) —
  MAINTAINABILITY/**HIGH**, so under this gate it *would* block merges. Rejected on substance: it
  replaces a readable literal with a constant declared somewhere else, which hurts readability
  (the failure mode is familiar from serializer field names and query parameters).
- **`python:S107`** "too many parameters" (max 13) — MAINTAINABILITY/MEDIUM, so it never blocks.
  Muted because it fires on constructors that initialise class fields, where a long parameter list
  is normal. Note that ruff's equivalent `PLR0913` is already disabled in `pyproject.toml`.

Mechanism: `packages/statuskit/sonar-project.properties` with `sonar.issue.ignore.multicriteria`.

A custom quality profile was rejected because a profile copy is a **snapshot**: `Sonar way` gains
rules with every analyser release (that is where the seven `S3776` findings came from in July),
and a copy never receives them. Since this design also declines an automated drift check, such an
aging profile would go unnoticed. Properties keep the built-in profile — rules keep arriving, and
only the listed ones are dropped.

The second reason is that the properties file lives in the repository: a mute has a reason, the
reason belongs next to it in a comment, and the change goes through PR review. A profile in the UI
carries no rationale.

Accepted downside: in the SonarCloud UI both rules still look active, and the absence of findings
is only explainable by reading the repository.

**Constraint that must hold:** the scanner applies settings in the order global config → project
file → system properties → environment → **CLI arguments**, so `-D` flags in the workflow override
the file. Verified in `Conf.java` of sonar-scanner-cli **8.0.1.6346** — the exact version the CI
uses. Therefore no `sonar.issue.ignore.*` key may ever be added to `args:` in
`_reusable-python-ci.yml`; muting lives in the properties file alone.

**File placement is load-bearing.** `Conf.java:113` resolves
`getRootProjectBaseDir(...).resolve("sonar-project.properties")`, and `getRootProjectBaseDir`
takes `sonar.projectBaseDir` from the CLI arguments — which the workflow sets to
`packages/statuskit`. The file must therefore sit in `packages/statuskit/`, not at the repository
root.

### D5. `new_security_hotspots_reviewed` is kept

The condition is currently trivially satisfied (0 hotspots), but it is dormant, not dead: a
hotspot is not an issue, it does not affect `security_rating` (hotspots have their own
`security_review_rating`), so this condition is the only thing that would ever force a hotspot to
be reviewed. When Sonar completes the migration of hotspots into security issues, they will fall
under `new_security_rating` automatically and this condition becomes a genuine no-op.

### D6. The ruff/Sonar feedback gap is accepted

The two linters were compared rule by rule (469 active Python rules against the `select`/`ignore`
sets in `pyproject.toml`). **No conflicts exist**: `Sonar way` for Python contains no formatting
rules at all — indentation, whitespace, quotes, line length — so it cannot collide with
`ruff format` or with the rules disabled for the formatter's sake (`E1`, `E2`, `E3`, `W191`,
`ISC001`, the dropped `Q`). The one stylistic overlap checked explicitly agrees: `S9083` wants
fixtures without parentheses (`requireParentheses=false`), and so does ruff `PT001` by default.

The sets are complementary: ruff alone covers `PTH`, `EM`, `ARG`, `TC`, `PERF`, `C4`, `RET`, `UP`,
`I`, `INP`, `SLF`, `PIE`; Sonar alone covers cognitive complexity, exception and special-method
semantics, interprocedural data-flow analysis, regex correctness.

The consequence is a **feedback gap**: 213 active rules carry a BLOCKER or HIGH impact, and 169
remain after excluding the framework-specific ones (numpy, torch, Flask, FastAPI, AWS and the
like — statuskit's only dependency is `termcolor`). Some of those have no ruff counterpart —
`S3776` (ruff's `C90` is not in `select`), `S8572` (`TRY` is not in `select`), `S7487`–`S7514`
(`ASYNC` is not in `select`; statuskit currently has no async code), and the `pythonbugs:*`
data-flow rules. Under the new gate these block a merge while a local `ruff check` stays silent.

Decision: **accept it.** Extending ruff was considered and declined — catching cognitive
complexity in CI is acceptable. Versions are aligned already (`requires-python >= 3.11`, ruff
`target-version = "py311"`, `sonar.python.version` from the same CI matrix).

### D7. No automated drift check

The gate's composition is fixed by this document. A CI check comparing
`api/qualitygates/show` against a reference was considered and declined as infrastructure more
expensive than the object it guards.

## Scope

**In scope (this task):**

1. Create the `NoNameItem way` gate via API and bind it to `NoNameItem_statuskit`.
2. Add `packages/statuskit/sonar-project.properties` with the two mutes and their reasons.
3. This document.

**Out of scope, tracked elsewhere:**

- **Overall check on release** — a job on the release-please PR that reads master's overall
  `security_rating` / `reliability_rating` / `sqale_rating` and fails on threshold breach. Note
  that `python-ci` is skipped for `release-please--*` branches, so Sonar does not analyse the
  release PR at all; the check must read master's measures. `sonar_pr_status.py` already fetches
  them (`--mode branch`), but is a reporter — it has no thresholds and no exit code. The result
  can join the existing `python-ci-result` aggregator as a second `needs`, so the ruleset needs no
  new required check. Separate beads task under `claude-tools-5vg`.
- **`pythonsecurity:S2083` in `setup/hooks.py:49`** — BLOCKER, open since 2026-01-19, the sole
  cause of `security_rating` = E. This gate will not see it (it is not new code). Worth noting:
  its twin — the same rule and the same message in `setup/gitignore.py:62` — is marked
  `FALSE_POSITIVE`. One of two identical findings was dismissed, the other was not. Goes to epic
  `claude-tools-4u3`.
- **read-comics** stays on `Sonar way no coverage`. Its permanently red gate is a separate
  question; note that with this design's conditions it would pass `security_rating` (A) but fail
  `new_coverage` (44% on new code, 21% overall).

## Implementation

1. `POST api/qualitygates/copy` from `Sonar way` → `NoNameItem way`.
2. `POST api/qualitygates/create_condition` for `new_blocker_violations` and
   `new_critical_violations` (GT 0); verify the six inherited conditions match the D1 table.
3. `POST api/qualitygates/select` binding `NoNameItem_statuskit`.
4. `GET api/qualitygates/show` and diff against the D1 table.
5. Add `packages/statuskit/sonar-project.properties`.

Steps 1–4 require a **User Token** (organisation admin rights); a Global Analysis Token cannot
administer gates. The token is used once and can be revoked afterwards.

## Verification

`sonar-project.properties` lives inside `packages/statuskit`, so `detect_changes.py` marks
statuskit as changed and the PR for this task triggers a full analysis. The PR therefore exercises
the new gate on a live run.

Acceptance:

1. `api/qualitygates/get_by_project?project=NoNameItem_statuskit` returns `NoNameItem way`.
2. `api/qualitygates/show` matches the D1 table exactly — eight conditions, no more.
3. The scanner log for the PR shows `Project root configuration file:` pointing at
   `packages/statuskit/sonar-project.properties` (currently `NONE`) — this is the direct proof
   that the mutes are applied.
4. `Python CI Gate` is green on the PR.

## Risks

- **Legacy severity metrics.** `new_blocker_violations` / `new_critical_violations` belong to the
  taxonomy Sonar is phasing out. They carry no `deprecated` flag in the API today, but if they are
  removed, MQR-severity counters must exist by then or the threshold has to be re-expressed. Worth
  re-checking in a year.
- **Accept as an escape hatch.** No `new_accepted_issues` condition is added, deliberately: it
  would close the only exit from a false positive and turn "make the analyser happy" into the only
  way to merge. Abuse is visible — `new_accepted_issues` is already part of `_PR_METRICS` in the
  PR notification.
- **Muted rules become invisible.** See D4.

## References

- `_reusable-python-ci.yml` — the `sonarcloud` job, `-Dsonar.qualitygate.wait=true`
- `pr.yml:405` — the `Python CI Gate` aggregator
- `.github/scripts/sonar_pr_status.py` — `--mode pr` / `--mode branch` / `--mode release`
- `docs/merge-gate-rollout.md` — the merge gate's history
- Hotspot deprecation: https://docs.sonarsource.com/sonarqube-cloud/deprecations-and-removals#deprecation-of-security-hotspots
