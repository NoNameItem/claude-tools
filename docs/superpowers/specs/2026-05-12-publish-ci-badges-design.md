# Publish per-project CI badges from push.yml

**Beads task:** claude-tools-wm2.1
**Parent task:** claude-tools-wm2
**Parent spec:** [`2026-05-12-project-ci-badges-design.md`](./2026-05-12-project-ci-badges-design.md)
**Date:** 2026-05-12
**Status:** Approved

## Goal

Implement the publishing pipeline for project-specific CI badges:
1. One-time bootstrap of the `badges-data` orphan branch with placeholder JSONs.
2. `.github/scripts/publish_badges.py` — fetches the current workflow run's jobs from the GitHub API, aggregates per-project status, writes shields.io endpoint JSON files.
3. Tests for the script.
4. `publish-badges` job added to `.github/workflows/push.yml`.

README badges for `statuskit` and `flow` are out of scope (sub-tasks `claude-tools-wm2.2` and `claude-tools-wm2.3`).

## Non-goals

Inherits from parent spec. Additionally for this sub-task:
- No changes to README files in this PR.
- No coverage / Sonar / quality badges.
- No CI changes outside `push.yml`.

## Decisions resolved by brainstorming

| Decision | Choice | Reason |
|---|---|---|
| HTTP client | stdlib `urllib` | Consistent with existing `.github/scripts/*.py` (no third-party HTTP deps); ~20 lines for pagination |
| Bootstrap timing | Manually, before PR1 opens | One-time-per-repo step. Avoids broken first build on master after merge and avoids dead-code self-bootstrap logic in CI |
| Script structure | Module with importable functions + `main()` CLI | Mirrors `detect_changes.py`. Tests call functions directly; no `subprocess` in test layer |

## Architecture

### Files added

- `.github/scripts/publish_badges.py` — module with functions and `main()` entrypoint.
- `.github/scripts/tests/test_publish_badges.py` — pytest tests.

### Files modified

- `.github/workflows/push.yml` — new `publish-badges` job placed between `claude-code-plugin-ci-info` and `notify-finish`.

### Files created out-of-PR (one-time bootstrap)

- `badges-data` branch on `origin` with two placeholder JSONs:
  - `statuskit.json`
  - `flow.json`

Both have shape `{"schemaVersion": 1, "label": "CI", "message": "unknown", "color": "lightgrey"}`.

### Module structure

```python
# publish_badges.py

def fetch_jobs(repo: str, run_id: str, token: str) -> list[dict]: ...
    # GET /repos/{repo}/actions/runs/{run_id}/jobs?per_page=100
    # Follows Link: rel="next" pagination. Hard cap 10 pages. Raises on HTTP error.

def extract_project_name(job_name: str) -> str | None: ...
    # Regex: \((?P<project>[\w][\w-]*)(?:, [^)]+)?\)$
    # Matches trailing parens. None for job names without recognized project.

def aggregate_status(conclusions: list[str | None]) -> tuple[str, str] | None: ...
    # Returns (message, color) — e.g. ("passing", "brightgreen") or ("failing", "red").
    # Returns None for all-skipped or empty (caller must NOT write a file).

def build_badge_json(message: str, color: str) -> dict: ...
    # {"schemaVersion": 1, "label": "CI", "message": message, "color": color}

def write_badge_file(output_dir: Path, project: str, badge: dict) -> None: ...
    # Writes {output_dir}/{project}.json, indent=2, trailing newline.

def publish_badges(
    repo: str,
    run_id: str,
    token: str,
    output_dir: Path,
) -> dict[str, str]: ...
    # Orchestration. Returns {project: status_label} for stdout summary.
    # status_label is one of "passing", "failing", or "skipped (no write)".

def main() -> int: ...
    # argparse, env vars, calls publish_badges, prints summary table, returns exit code.
```

## Algorithm

### Step-by-step (per parent spec, with details)

1. **Fetch jobs.** `GET /repos/{repo}/actions/runs/{run_id}/jobs?per_page=100`. Pagination via `Link` header, `rel="next"`. Hard cap: 10 pages (~1000 jobs); exceeding raises.
2. **Filter to completed.** Keep only jobs with `status == "completed"`. In-flight jobs (e.g., the parallel `Notify Finish` that doesn't depend on us, or `publish-badges` itself before its own conclusion) have `conclusion == null` and are excluded.
3. **Extract project.** For each remaining job, apply regex `\((?P<project>[\w][\w-]*)(?:, [^)]+)?\)$` to its `name`. Skip jobs that don't match.
4. **Group by project.** `{project: [conclusion, ...]}`.
5. **Aggregate per project.** Compute `(message, color)` via the table below.
6. **Write files.** For each project with a non-`None` aggregate, write `{output_dir}/{project}.json`. Projects that produced no jobs in this run are not touched (their existing badge files on `badges-data` remain).
7. **Print summary.** Stdout table for the workflow log.

### Status mapping

For an individual conclusion:

| GitHub `conclusion` | Class |
|---|---|
| `success` | success |
| `skipped` | skipped (no signal) |
| `failure`, `cancelled`, `timed_out` | failing |
| `neutral`, `action_required`, `stale` | failing (conservative default) |
| `null` (status != completed) | filtered out in step 2 |
| Any other unexpected value | failing (conservative default) |

### Aggregation per project

| Group composition | Result |
|---|---|
| All success | `(passing, brightgreen)` |
| Success + skipped (no failing) | `(passing, brightgreen)` — skipped doesn't downgrade |
| Contains at least one failing-class | `(failing, red)` |
| All skipped | `None` (file not touched) |
| Empty list (project name extracted but 0 completed jobs) | `None` |

### Edge cases verified

- **`publish-badges` job itself** is named `Publish badges` — no parentheses, regex doesn't match, automatically ignored.
- **Concurrency race.** `push.yml` has `concurrency.cancel-in-progress: true`. A second master push cancels the first workflow including its `publish-badges`. At any moment, ≤1 publish job is pushing to `badges-data`. No git push race.
- **Empty job list after filtering.** Script exits 0, writes nothing.
- **Pagination hard cap exceeded.** Raises `RuntimeError` — job fails, surfaces in CI.
- **`Foo ()`** (empty parens) — regex requires `[\w][\w-]*` (≥1 char), so no match.

## CLI

```
publish_badges.py --output-dir <path> [--repo <owner/repo>] [--run-id <id>]
```

| Parameter | Default | Source |
|---|---|---|
| `--output-dir` | required | path to `badges-data` checkout |
| `--repo` | `$GITHUB_REPOSITORY` | env |
| `--run-id` | `$GITHUB_RUN_ID` | env |
| Auth token | `$GITHUB_TOKEN` | env only (not a CLI flag) |

Exit codes:
- `0` — success (even when 0 files were written).
- `1` — API error, parse error, missing required env, or pagination cap exceeded.

Stdout (printed by `main` after `publish_badges` returns):
```
Project     Status               Color
--------------------------------------
statuskit   passing              brightgreen
flow        skipped (no write)   -
```

## push.yml diff

New job placed between `claude-code-plugin-ci-info` and `notify-finish`:

```yaml
  publish-badges:
    name: Publish badges
    needs: [detect, python-ci, claude-code-plugin-ci, python-ci-info, claude-code-plugin-ci-info]
    if: |
      always() &&
      github.ref == 'refs/heads/master' &&
      github.event.repository.fork == false
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      contents: write
      actions: read
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
        run: python main/.github/scripts/publish_badges.py --output-dir badges-data
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

Notes:
- `notify-finish` does NOT add `publish-badges` to its `needs`. Badge publishing is best-effort; a failure must not affect the Telegram notification.
- `permissions: contents: write` is needed to push to `badges-data`. `actions: read` is needed to fetch `/actions/runs/.../jobs`.
- `[skip ci]` in the commit message is defensive; `push.yml` triggers only on `branches: [master]` so pushes to `badges-data` already wouldn't trigger it.

## Bootstrap procedure

One-time, local, before opening PR1:

```bash
# From clean workdir
git switch --orphan badges-data
git rm -rf .

cat > statuskit.json <<'EOF'
{
  "schemaVersion": 1,
  "label": "CI",
  "message": "unknown",
  "color": "lightgrey"
}
EOF
cp statuskit.json flow.json

git add statuskit.json flow.json
git commit -m "chore: bootstrap badges-data branch"
git push -u origin badges-data

# Return to working branch
git checkout chore/claude-tools-wm2.1-publish-badges
```

Verification:
- `git ls-remote --heads origin badges-data` returns a SHA.
- `curl -fsSL https://raw.githubusercontent.com/NoNameItem/claude-tools/badges-data/statuskit.json` returns the placeholder JSON.

## Tests

`.github/scripts/tests/test_publish_badges.py`. All HTTP calls mocked (monkeypatch `urllib.request.urlopen`). No real network.

### `extract_project_name`

| Input | Expected |
|---|---|
| `Lint (statuskit)` | `statuskit` |
| `Test (statuskit, py3.10)` | `statuskit` |
| `SonarCloud (statuskit)` | `statuskit` |
| `Validate (flow)` | `flow` |
| `Lint (flow)` | `flow` |
| `Detect changes` | `None` |
| `Validate commits` | `None` |
| `Notify Start` | `None` |
| `Notify Finish` | `None` |
| `Publish badges` | `None` |
| `Foo ()` | `None` |
| `Bar (baz_qux-123)` | `baz_qux-123` |

### `aggregate_status`

| Conclusions | Expected |
|---|---|
| `["success", "success"]` | `("passing", "brightgreen")` |
| `["success", "skipped"]` | `("passing", "brightgreen")` |
| `["success", "failure"]` | `("failing", "red")` |
| `["cancelled"]` | `("failing", "red")` |
| `["timed_out"]` | `("failing", "red")` |
| `["neutral"]` | `("failing", "red")` |
| `["action_required"]` | `("failing", "red")` |
| `["skipped", "skipped"]` | `None` |
| `[]` | `None` |

### `fetch_jobs`

- **Single page.** Mocked response with `total_count: 5` and 5 jobs, no `Link` header → returns 5 jobs.
- **Two pages.** First response has `Link: <...?page=2>; rel="next"`, second response has no `next` → concatenates both.
- **Hard cap exceeded.** Mock keeps returning `rel="next"` for 10 pages → raises `RuntimeError`.
- **HTTP 4xx.** Mock raises `urllib.error.HTTPError` → propagates.

### `publish_badges` (integration with mocked API)

- **Two projects, all success.** Returns `{"statuskit": "passing", "flow": "passing"}`, two files written with `"message": "passing"`, `"color": "brightgreen"`.
- **One project only-skipped.** Other project gets a badge file; skipped project file is NOT created. Return value reflects `"skipped (no write)"` for that project.
- **No matching projects.** Empty return, no files written.
- **One project failing, one passing.** Both files written with correct statuses.
- **In-flight jobs filtered.** Mock includes one `status: "in_progress", conclusion: null` job for `statuskit`; it's excluded from aggregation.

### `write_badge_file`

- Writes valid JSON, `indent=2`, trailing newline.
- Overwrites existing file.
- Output directory must exist (caller supplies the `badges-data` checkout); function does NOT create it. If missing, raises `FileNotFoundError`.

## Acceptance criteria

1. `badges-data` branch exists on `origin` with `statuskit.json` and `flow.json` containing placeholder content.
2. `uv run pytest .github/scripts/tests/test_publish_badges.py` passes locally and in CI.
3. After PR1 merges, the next master push triggers `publish-badges`. The job completes successfully.
4. `badges-data` receives a new commit `chore(badges): update CI status [skip ci]` with updated JSON for any project whose CI ran in that push.
5. `https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/NoNameItem/claude-tools/badges-data/statuskit.json` renders a valid badge SVG (passing or failing — no longer "unknown") after the first post-merge master push.
6. `pr.yml` does NOT run `publish-badges` (the job lives only in `push.yml`).
7. When CI fails for one project and passes for another, the corresponding JSON files reflect `failing` and `passing` respectively in the next master-push commit on `badges-data`.

## Out of scope (delegated to wm2.2 / wm2.3)

- `packages/statuskit/README.md` modifications.
- `plugins/flow/README.md` modifications.
- Top-level `README.md` badges.
- Migration of existing static badges in `plugins/flow/README.md`.
