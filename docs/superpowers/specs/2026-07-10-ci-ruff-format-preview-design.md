# CI: align ruff-format check with the stable formatter (drop `--preview`)

- **Task:** claude-tools-abf
- **Date:** 2026-07-10
- **Type:** bug (repo-level, CI)
- **Scope:** `.github/workflows/_reusable-python-ci.yml` — the "Ruff format check" step only

## Problem

The CI "Ruff format check" step runs the formatter in **preview** mode:

```yaml
uv run ruff format --check --preview --output-format=rdjson -- ${{ steps.filter.outputs.py_files }} 2>&1 | \
  reviewdog -f=rdjson -name="ruff-format" -reporter="${REVIEWDOG_REPORTER}" -filter-mode=nofilter -fail-level=any
```

The local pre-commit hook and the `CLAUDE.md` pre-commit workflow use the **stable** formatter
(`ruff format`, no `--preview`). Preview-only style rules (e.g. hug-parens for nested calls such as
`write_text(json.dumps({...}))`) reformat code that the stable formatter considers already-formatted.
As a result, code that passes local format checks fails CI. This was hit twice on PR #107
(claude-tools-5dl.20), forcing test code to be restructured both times.

## Root cause

`--preview` is a single switch that turns on **two** things at once:

1. The preview **interface** — `ruff format --output-format=<fmt>` is preview-gated. Confirmed on
   both the pinned `ruff==0.15.19` and the latest `0.15.21`: without `--preview`, ruff prints
   `warning: The --output-format flag for the formatter is unstable and requires preview mode to use`
   and falls back to the default `full` text output.
2. The preview **style** — newer/stricter formatting rules. This is the actual bug.

The step needs (1) to feed machine-readable output to reviewdog, but (1) is only available under
`--preview`, which unavoidably drags in (2). The two cannot be separated: unlike the linter, where
preview rules can be selected/ignored individually, the formatter's preview style is all-or-nothing.

Note the asymmetry that confirms this reading: the "Ruff lint" step uses stable
`ruff check --output-format=rdjson` **without** `--preview`, because the linter's rdjson output is
stable. Only the formatter step needed `--preview`, purely as a side effect of wanting rdjson.

## Decision

Switch the format step to the **stable** formatter and feed reviewdog a **unified diff** instead of
rdjson:

```yaml
uv run ruff format --diff -- ${{ steps.filter.outputs.py_files }} | \
  reviewdog -f=diff -f.diff.strip=0 -name="ruff-format" -reporter="${REVIEWDOG_REPORTER}" -filter-mode=nofilter -fail-level=any
```

Rationale:

- `ruff format --diff` runs in stable mode → CI formatting now matches local pre-commit and
  `CLAUDE.md`. The bug is gone.
- `--diff` emits a standard unified diff, which reviewdog parses via `-f=diff` — the canonical
  reviewdog pattern for formatters (`gofmt -s -d . | reviewdog -f=diff -f.diff.strip=0`).
- Inline PR comments are preserved. reviewdog turns diff input into **suggested changes**
  ("Apply suggestion") on `github-pr-review` — a small UX improvement over the previous rdjson output,
  which only flagged "would reformat" with no ready fix.
- `-f.diff.strip=0` because ruff's diff headers carry no `a/`/`b/` prefixes; paths are already
  repo-relative.
- Drop the trailing `2>&1`: the `N file would be reformatted` summary goes to stderr, so only the
  clean diff reaches reviewdog's stdin (matching the canonical `gofmt -d | reviewdog` form).

The step id (`format`), `continue-on-error: true`, and the non-zero-exit-on-findings semantics are
unchanged, so the downstream "Check results" gate (`steps.format.outcome == "failure"`) keeps working.

## Alternatives considered

- **Upgrade ruff to drop `--preview` while keeping rdjson.** Rejected: the formatter's
  `--output-format` is still preview-gated on the latest `0.15.21` (verified empirically). The repo
  is already on a near-latest ruff; upgrading does not help.
- **Unify the lint step onto `--diff` too, for symmetry.** Rejected: `ruff check --diff` only emits
  the diff of *auto-fixable* violations and silently drops everything without a fix (undefined names,
  complexity, most `B` rules), plus rule codes and messages. The linter's rdjson is stable and richer,
  and the lint step has no bug — leave it on rdjson. The right consistency is "richest **stable**
  machine format per tool", not "one input format for all".
- **Switch the ty step to a native format.** Out of scope and not viable: ty (`0.0.52` pinned,
  `0.0.58` latest) offers only `full/concise/gitlab/github/junit`; none is a reviewdog input format
  (rdjson/rdjsonl/diff/checkstyle/sarif). The `ty_to_rdjsonl.py` converter stays.
- **Use `ty --output-format github` / native GitHub annotations for type errors.** Not applicable to
  this bug; also rejected as a general direction because native annotations are a different UI surface
  (not resolvable review-comment threads), are capped at ~10 per step, and have path-mapping friction.
  The pipeline deliberately unifies on the reviewdog review-comment surface.

## Verification evidence

Gathered during design (ruff `0.15.19`/`0.15.21`, reviewdog built from `go install`):

- `ruff format --diff` on a misformatted file emits a valid unified diff and exits non-zero.
- reviewdog `-f=diff -f.diff.strip=0 -reporter=local` parses that diff and maps each change to the
  correct repo-relative `path:line`.
- With `-fail-level=any`: a file needing reformatting → reviewdog exits `1`
  (`found at least one issue ... >= any`); an already-formatted file → empty diff → exit `0`.
  This matches the current rdjson step's gate semantics exactly.

## Out of scope

- The "Ruff lint" step (`ruff check`) — unchanged.
- The "Type check" step (`ty` + `ty_to_rdjsonl.py`) — unchanged.
- Any ruff/ty version bump.

## Acceptance criteria

- The "Ruff format check" step no longer passes `--preview` (nor `--output-format=rdjson`).
- Format findings still appear as inline PR review comments via reviewdog.
- A formatting violation still fails the job through the existing "Check results" gate.
- Code formatted by the stable local `ruff format` passes the CI format check (the PR #107 failure
  no longer reproduces).
- `actionlint` passes on the workflow.
