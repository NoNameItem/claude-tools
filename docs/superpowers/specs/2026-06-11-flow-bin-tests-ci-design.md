# Gate flow `bin/` tests in CI

**Task:** claude-tools-7sw
**Date:** 2026-06-11
**Status:** Designed

## Problem

The 159 tests in `plugins/flow/bin/tests/` are not executed by any automated gate.

- **Plugin CI** (`.github/workflows/_reusable-claude-code-plugin-ci.yml`) runs only
  `validate-structure` and `lint`. The `lint` job installs ruff via `uv tool install ruff`
  (not `uv sync`), so pytest is not even available there.
- **Pre-commit** (`.pre-commit-config.yaml`) runs `ruff-format`, `ruff`, and
  `single-package-commit`. No pytest hook.
- **Default discovery is blocked too:** root `pyproject.toml` sets
  `testpaths = ["packages/*/tests"]`, which excludes plugin tests even from a bare
  `uv run pytest`. The suite runs only via the explicit manual path
  `uv run pytest plugins/flow/bin/tests/`.

**Impact:** helper regressions are not caught before merge — including the Python 3.9
import-safety gate (`test_py39_compat.py`, guarding claude-tools-dsc), which exists but
never runs in CI.

### Lineage

The `#73` helper-extraction design
(`docs/superpowers/specs/2026-05-13-flow-bin-helpers-design.md`, Risk table and "Done
When") claimed "Pre-commit runs them. CI runs them." That wiring was never added: `#73`
added the helpers and their tests and routed the helper *files* through the lint job, but
added no test execution. This spec adds the missing CI gate. The `#73` document is left
unchanged as a historical record; this spec supersedes its testing-gate claim.

## Goal

A CI gate that runs `bin/tests/` for **any** plugin that has them, under Python 3.11,
failing the required check on regression. The Python 3.9 import-safety guarantee rides
along for free: `test_py39_compat.py` performs a static `ruff check --select FA102
--target-version py39` over the helpers and runs *inside* the suite.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Gates | CI only — no pre-commit hook | Lowest friction; protects contributors without the hook and CI-only environments. |
| Generality | Generic — any plugin with `bin/tests/` | Matches the reusable, plugin-matrixed workflow; future plugins are gated automatically. |
| Python version | Single, 3.11 | Matches root `requires-python >=3.11` and the existing lint job. py39 stays covered by the in-suite FA102 check. |
| Structure | New `test` job in the plugin CI reusable workflow | Mirrors `_reusable-python-ci.yml` (lint + test as sibling jobs); parallel; no caller edits. |

## Design

### The change — one new job

Add a `test` job to `.github/workflows/_reusable-claude-code-plugin-ci.yml`, sibling to
`validate-structure` and `lint`, matrixed over the same `plugins` input:

```yaml
  test:
    name: Test (${{ matrix.plugin }})
    runs-on: ubuntu-latest
    timeout-minutes: 10
    strategy:
      fail-fast: false
      matrix:
        plugin: ${{ fromJson(inputs.plugins) }}
    steps:
      - uses: actions/checkout@v4

      - name: Check for plugin tests
        id: check-tests
        run: |
          if [ -d "plugins/${{ matrix.plugin }}/bin/tests" ]; then
            echo "has_tests=true" >> "$GITHUB_OUTPUT"
          else
            echo "has_tests=false" >> "$GITHUB_OUTPUT"
          fi

      - name: Setup uv
        if: steps.check-tests.outputs.has_tests == 'true'
        uses: astral-sh/setup-uv@v7
        with:
          enable-cache: true
          python-version: '3.11'

      - name: Install dependencies
        if: steps.check-tests.outputs.has_tests == 'true'
        run: uv sync

      - name: Run tests
        if: steps.check-tests.outputs.has_tests == 'true'
        run: uv run pytest "plugins/${{ matrix.plugin }}/bin/tests"
```

### Rationale per choice

- **Runtime `bin/tests/` detection** (rather than a `_reusable-detect.yml` change) keeps
  the generic behavior self-contained: a plugin without tests no-ops; a future plugin that
  adds `bin/tests/` is gated automatically, with no detect/matrix surgery.
- **`uv sync`, not `uv tool install ruff`** — installs pytest *and* puts `ruff` on PATH,
  which `test_py39_compat.py` requires (`shutil.which("ruff")`). One install covers both
  needs.
- **`python-version: '3.11'`** pinned on `setup-uv`, matching the lint job and root
  `requires-python >=3.11`.
- **Explicit path argument** `plugins/<plugin>/bin/tests` overrides the root `testpaths`
  restriction; there are no coverage `addopts` to conflict with, so the command is clean.
- **`fail-fast: false`** mirrors the sibling jobs so one plugin's failure does not mask
  another's.

### Gating — no caller edits

The job lives inside the reusable workflow, so both `pr.yml` and `push.yml` pick it up
automatically:

- **`pr.yml`:** `claude-code-plugin-ci-result` (the branch-protection required check)
  already fails when the reusable workflow fails, so a red `test` job turns the required
  check red. No change needed.
- **`push.yml`:** the reusable workflow's failure flows into the existing notify/badges
  jobs.
- **Tooling-changed info path** (`claude-code-plugin-ci-info`): the `test` job runs but
  stays informational — that caller is not in the required check's `needs`, consistent with
  how `lint` already behaves there.

No changes to `pr.yml`, `push.yml`, `_reusable-detect.yml`, or branch-protection config.

## Scope boundaries

**In scope**
- The single `test` job above.

**Out of scope** (per decisions)
- No pre-commit pytest hook.
- No Python 3.9 *runtime* matrix — the static FA102 gate remains the py39 guarantee.
  (A runtime 3.9 matrix would also fight `requires-python >=3.11`, since `uv sync` would
  not resolve under 3.9.)
- No coverage upload or SonarCloud for plugins — plugins have no `src/` layout and no
  Sonar project.
- No edit to the `#73` historical design doc beyond the lineage note in this spec.

**Edge case**
- If a plugin ever has an empty `bin/tests/` (directory present, no test files), pytest
  exits 5 and the job fails. This is acceptable signal — an empty tests directory is itself
  a mistake — and is not special-cased.

## Verification

1. Trigger the flow path: include a `plugins/flow/` change in the branch and confirm the
   `Test (flow)` check runs and passes.
2. Optionally push a deliberately-broken helper to confirm the check goes red, then revert.
3. Local pre-merge: `uv run pytest plugins/flow/bin/tests/` stays green.

## Done When

- `_reusable-claude-code-plugin-ci.yml` has a `test` job matching the design.
- A PR touching `plugins/flow/` shows a passing `Test (flow)` required check.
- A simulated helper regression makes that check fail.
- No caller workflow, detect workflow, or branch-protection config was modified.
