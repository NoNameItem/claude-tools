# Project-specific CI badges

**Beads task:** claude-tools-wm2
**Date:** 2026-05-12
**Status:** Draft

## Goal

Each project in this monorepo (currently `statuskit`, `flow`; any future project added the same way) gets its own CI status badge in its README that reflects only the last result of its own CI checks on `master`. Adding a new project must NOT require adding any new workflow files.

## Non-goals

- Per-job badges (separate badges for lint vs test vs Sonar). One combined "CI" badge per project.
- PR-level badges. Badges reflect the latest `master` push only.
- Top-level monorepo `README.md` badges. Deferred until the top-level README is rewritten with project descriptions.
- Coverage / quality / Sonar badges. May be added later as separate work; out of scope here.

## Background

`push.yml` orchestrates CI for the whole monorepo via reusable workflows:
- `_reusable-detect.yml` decides which projects changed.
- `_reusable-python-ci.yml` handles Python projects (lint, test matrix, SonarCloud).
- `_reusable-claude-code-plugin-ci.yml` handles Claude Code plugins (validate, lint).

When only tooling files change (`tooling_changed == true`), `*-ci-info` jobs re-run CI for **all** unchanged projects with `info-only: true` (skips SonarCloud, keeps lint and test). This means tooling pushes do exercise every project; the badge mechanism must update on those runs.

The current setup has a single push.yml badge for the whole workflow — it can't distinguish per-project status. We need per-project granularity without losing the generic detect-driven pattern that lets new projects be added without CI surgery.

## Design

### Storage

A dedicated orphan branch `badges-data` in this repository holds one JSON file per project:

```
badges-data (branch root)
├── statuskit.json
└── flow.json
```

Each file is a shields.io endpoint badge:

```json
{ "schemaVersion": 1, "label": "CI", "message": "passing", "color": "brightgreen" }
```

Values used:
| Result | message | color |
|--------|---------|-------|
| All jobs `success` | `passing` | `brightgreen` |
| Any job `failure` / `cancelled` / `timed_out` | `failing` | `red` |
| All jobs `skipped` | (no update — preserves previous file) | — |
| Initial bootstrap | `unknown` | `lightgrey` |

### Update path

A new `publish-badges` job is added to `push.yml`:

```yaml
publish-badges:
  name: Publish badges
  needs: [detect, python-ci, claude-code-plugin-ci, python-ci-info, claude-code-plugin-ci-info]
  if: |
    always() &&
    github.ref == 'refs/heads/master' &&
    github.event.repository.fork == false
  runs-on: ubuntu-latest
  permissions:
    contents: write
  steps:
    - name: Checkout main
      uses: actions/checkout@v4
      with:
        path: main
    - name: Checkout badges-data
      uses: actions/checkout@v4
      with:
        ref: badges-data
        path: badges-data
    - name: Update badge files
      env:
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      run: |
        python main/.github/scripts/publish_badges.py \
          --output-dir badges-data
    - name: Commit and push
      working-directory: badges-data
      run: |
        if [[ -z "$(git status --porcelain)" ]]; then
          echo "No badge changes"
          exit 0
        fi
        git config user.name "github-actions[bot]"
        git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
        git add .
        git commit -m "chore(badges): update CI status [skip ci]"
        git push
```

Key properties:
- `if: always()` — runs even when CI failed (we still need to publish "failing").
- `github.ref == 'refs/heads/master'` — master only.
- `fork == false` — fork PRs don't have token write permission; the job skips itself cleanly.
- `[skip ci]` in the commit message prevents recursive workflow runs.
- The job is not a dependency of `notify-finish`; badge publishing is best-effort and must not block notifications or be reported as a CI failure.

### `publish_badges.py`

Lives at `.github/scripts/publish_badges.py`. Discovers projects from the current workflow run's job list — never from a hardcoded list.

**CLI:**
```
publish_badges.py --output-dir <path> [--repo <owner/repo>] [--run-id <id>]
```
Defaults pull `--repo` from `$GITHUB_REPOSITORY` and `--run-id` from `$GITHUB_RUN_ID`. Auth via `$GITHUB_TOKEN`.

**Algorithm:**
1. Fetch all jobs for `$GITHUB_RUN_ID` via `GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs` (paginated).
2. Filter to jobs with `status == 'completed'`. In-flight jobs (e.g., the parallel `Notify Finish` job that doesn't depend on `publish-badges`) have `conclusion == null` and must not be counted as passes or failures. Skipping them now matches "we don't have data yet" semantics.
3. For each remaining job, attempt to extract a project name from the job name using a single regex anchored at the end:
   ```
   \((?P<project>[\w][\w-]*)(?:, [^)]+)?\)$
   ```
   Examples that match:
   - `Lint (statuskit)` → `statuskit`
   - `Test (statuskit, py3.10)` → `statuskit`
   - `SonarCloud (statuskit)` → `statuskit`
   - `Validate (flow)` → `flow`
   Examples that do NOT match (correctly ignored):
   - `Detect changes`
   - `Validate commits`
   - `Notify Start`, `Notify Finish`
   - `Publish badges`
4. Group matched jobs by project.
5. Per project, compute status:
   - Any `conclusion ∈ {failure, cancelled, timed_out}` → `failing` / red.
   - All `conclusion == success` → `passing` / brightgreen.
   - All `conclusion == skipped` → do nothing (no file write).
   - Mixed `success` + `skipped` → `passing` (success dominates over absent signal).
6. Write `{output_dir}/{project}.json` for each project with a non-skip-only result. Existing files for projects with no jobs in this run remain untouched.
7. Print a summary table to stdout for the workflow log.

**Design constraints:**
- No reads of existing JSON state (idempotent: result depends only on this run's API output).
- No knowledge of which reusable workflow produced a job. `python-ci` and `python-ci-info` invocations both produce `Lint (statuskit)` etc. — identical names, picked up the same way.
- New project added → first master push that runs its CI gets a badge file created automatically. No code changes needed.

**Why job-name parsing over alternatives:**
- Per-project matrix outputs cannot easily aggregate across the matrix into a single output (GitHub Actions doesn't merge matrix outputs natively).
- Per-job artifact upload would invade reusable workflows for cosmetic state.
- The job-name convention is already stable and used as a UI contract by GitHub's check-run display.

### Tests

`.github/scripts/tests/test_publish_badges.py`, following existing test conventions:
- Regex extraction: positive cases (`Lint (foo)`, `Test (foo, py3.11)`, `SonarCloud (foo)`), negative cases (`Detect changes`, `Notify Start`, `Validate commits`, empty parens, no parens).
- Status filtering: in-flight jobs (`status='in_progress'`, `conclusion=null`) are excluded from aggregation.
- Aggregation: all success, any failure, all skipped, mixed success+skipped, mixed success+failure (failure wins), cancelled and timed_out treated as failure.
- Output JSON: schema matches shields.io endpoint format; correct color mapping for each status.
- API client: mocked, no real network. Verify pagination handling on `Link` header.

### Bootstrap

One-time setup, performed in the implementation PR:
1. Create orphan branch `badges-data` (no parent commit, `git switch --orphan badges-data` + `git rm -rf .`).
2. Add initial files:
   - `statuskit.json`: `{"schemaVersion": 1, "label": "CI", "message": "unknown", "color": "lightgrey"}`
   - `flow.json`: same shape.
3. Push the branch.

The first real master push after the PR merges will overwrite these with actual statuses.

### README updates

Both READMEs gain a CI badge with the shields.io endpoint URL pointing at the corresponding badge JSON.

`packages/statuskit/README.md` — add CI badge to existing badge row (above title):
```markdown
[![CI](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/NoNameItem/claude-tools/badges-data/statuskit.json)](https://github.com/NoNameItem/claude-tools/actions/workflows/push.yml)
```
Placement: as the first badge, before the existing PyPI badges.

`plugins/flow/README.md` — the file currently has three static shields.io badges (Version/License/Platform). The implementation should:
- Add the real CI badge as the first item in the row.
- Leave the existing static badges in place for this task. (A separate cleanup of static badges is out of scope.)

```markdown
[![CI](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/NoNameItem/claude-tools/badges-data/flow.json)](https://github.com/NoNameItem/claude-tools/actions/workflows/push.yml)
```

## Behaviors and invariants

| Scenario | Expected behavior |
|----------|------------------|
| Master push with changes only in `flow` | `python-ci` skipped, `claude-code-plugin-ci` runs for flow; script writes `flow.json` only; `statuskit.json` untouched. |
| Master push with changes only in `statuskit` | `python-ci` runs for statuskit; script writes `statuskit.json` only; `flow.json` untouched. |
| Master push touching repo-root tooling (e.g., `pyproject.toml`) only | `*-ci-info` jobs re-run all projects with `info-only: true` (lint + test, no Sonar); script writes both `statuskit.json` and `flow.json` based on those results. |
| Master push touching both `flow` and tooling | `python-ci-info` (statuskit) + `claude-code-plugin-ci` (flow, real); both badges update. |
| CI fails for `statuskit`, passes for `flow` | `statuskit.json` → failing, `flow.json` → passing. |
| Workflow cancelled mid-run | `if: always()` runs the publish job; cancelled jobs → failing for affected projects. |
| New project `widget` added to repo | First master push that runs `Lint (widget)` etc. creates `widget.json` automatically. No CI or script changes. |
| Fork PR | `publish-badges` skipped (`fork == false` guard). No write attempt against fork-token. |
| Non-master push | `publish-badges` skipped (`ref == master` guard). |
| GitHub API rate-limit hit | Script raises; the job fails. CI result for the push is unaffected. Next push retries. |

## Out of scope

- Top-level `README.md` badge placement. The top-level README is currently minimal; placement decisions should be made when that README is rewritten with proper project descriptions.
- Migration of existing static badges in `plugins/flow/README.md`.
- Per-project coverage / Sonar / quality badges.
- PR-level badges (latest open PR status).
- A `badges-data` history retention policy. The branch will accumulate small commits; if this becomes a concern later, periodic squash is an option.

## Implementation summary

Files added:
- `badges-data` branch with `statuskit.json`, `flow.json` (orphan branch, bootstrapped manually)
- `.github/scripts/publish_badges.py`
- `.github/scripts/tests/test_publish_badges.py`

Files modified:
- `.github/workflows/push.yml` — add `publish-badges` job
- `packages/statuskit/README.md` — add CI badge
- `plugins/flow/README.md` — add CI badge

Files NOT modified:
- `.github/workflows/pr.yml` (badges are master-only)
- `.github/workflows/_reusable-*.yml` (job-name convention already provides what we need)
- Top-level `README.md`
- Notification flow (`notify-start`, `notify-finish`)
- Branch protection rules
