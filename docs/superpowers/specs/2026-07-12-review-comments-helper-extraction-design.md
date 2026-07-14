# Review-comments helper extraction — design

**Task:** claude-tools-elf.26 (review-comments rework — PR #109)
**Date:** 2026-07-12
**Status:** approved, pending implementation plan

## Context

The `flow:review-comments` skill (elf.26) went through **7 waves** of Codex `review-gate`
feedback on PR #109. Almost every finding lived in **hand-written shell-recipe prose** that an
LLM/subagent re-derives on each run:

- untrusted reviewer data (file paths, titles, applied paths) inlined into shell source →
  command-substitution / word-split injection;
- hard-coded ` ``` ` fences around content that can itself contain a fence → early close;
- Read-tool `offset/limit` confused with an absolute end line → over-read;
- diff-position range arithmetic without a `max(1, …)` clamp;
- `allowed-tools` grants missing for commands the recipes invoke.

These are **not** logic bugs in the workflow — they are defects of expressing deterministic
mechanism as prose. The same mechanism, written once as tested code, cannot regress this way.
The skill has also grown to **1510 lines / ~12.9k words** (≈26× the writing-skills concision
bar), most of it that mechanism.

This design extracts the deterministic mechanism into tested helper scripts, shrinking SKILL.md
and eliminating the recurring bug classes at the source.

## Goal

Move the **algorithmizable** parts of the skill (comment collection, GitLab snippet
reconstruction, card-JSON assembly) out of SKILL.md prose into tested `plugins/flow/bin/flow-*`
helpers, leaving the LLM only **judgment** (analysis verdicts, triage, reply-text authoring,
generalize-the-class, self-review).

### Guiding principle — and its limit

Extract into a script only when the logic is deterministic **and** the script is clearly
simpler / more reliable than the equivalent short LLM instruction. Do **not** script something
whose algorithm would be complex/branchy while a one-sentence instruction covers it just as
well.

- Script it: parsing `gh`/`glab` API JSON into threads; reconstructing a snippet from a diff
  position; assembling/rendering a card.
- Keep as instruction: "before committing, run the project's tests and its configured linting
  and confirm they pass" — scripting that needs language + per-project toolchain detection,
  while the instruction is one sentence (see commit `7af35d5`, which deliberately de-scripted
  the linter call).

The broad, whole-plugin version of this audit is tracked separately as **claude-tools-elf.35**;
this design is the first worked example, scoped to review-comments.

## Scope

**In scope:** Phase 2 (collection + snippet reconstruction) and Phase 4.2 (card assembly).
That is where all 7 waves of bugs lived and where the prose bloats most.

**Out of scope (YAGNI):**
- Phase 5 finalizers (reply posting, commit, summary) — thin, already hardened `gh`/`git`
  calls; low bug-yield. Deferred to elf.35.
- Making `flow` a pip-installed package.
- Any change to analysis / triage / reply **behavior** — same verdicts, same decisions, same
  reply formats. This is a mechanism extraction, not a behavior change.

## Architecture

Two helpers plus one shared module, all in `plugins/flow/bin/` (Python, stdlib-only,
py3.9-compatible, pytest fixtures — the established `flow-comment-card` pattern):

1. **`_git.py`** (new shared module) — the CLI-interaction foundation for git/gh/glab, written
   and tested **once**. Home for future git helpers too.
2. **`flow-review-collect`** (new executable) — owns IO; does all of Phase 2 deterministically
   and emits one structured JSON.
3. **`flow-comment-card`** (extend the existing executable) — gains a merge mode that assembles
   a card from collector metadata + an LLM verdict, then renders (the old full-card-on-stdin
   path stays for backward compatibility).

The bin/ scripts are extensionless executables with no package; an executable imports a sibling
module via `sys.path[0]` (its own directory). Tests already run helpers as subprocesses
(`run_helper`) with fake `gh`/`glab`/`bd` on PATH (`fake_gh` / `fake_glab` fixtures) — the same
mechanism covers the new helper and the shared module.

### Data flow — files, not shell literals

```
flow-review-collect [n] > metadata.json          # deterministic: all of Phase 2
        │
        ▼   main LLM: render TOC, filter already_replied, (>~20) select a subset
Phase 3: per ref, a sonnet subagent reads its slice of metadata.json,
         writes verdict-{ref}.json   (JSON, NOT a fenced block)                    # judgment
        │
        ▼
flow-comment-card --meta metadata.json --ref C1 --verdict verdict-C1.json          # deterministic
        │
        ▼   user: fix / won't-fix / follow-up / skip                               # choice
Phase 5 …
```

The main LLM orchestrates only **file paths** — the last quoting/heredoc surface disappears.

## `_git.py`

A shared module wrapping the git/gh/glab CLIs:

- `run(argv, *, timeout, check)` — subprocess wrapper (argv list, timeout, error handling).
  Injection-safe by construction: an argv list is never parsed by a shell.
- `detect_platform()` → `"github" | "gitlab"` — remote host → `gh`/`glab auth` match → fallback
  heuristic (the Phase-0 algorithm, now code).
- `resolve_repo()` → `owner/repo` (GitHub); `resolve_project()` → URL-encoded `group%2Frepo`
  (GitLab).
- `gh_api(path, *, paginate=False)` / `glab_api(path, *, paginate=False)` — thin API callers.

Unit-tested directly, and exercised through the subprocess tests of its consumers.

## `flow-review-collect`

**Interface** — minimal args; it detects and resolves via `_git.py`. The skill must sync the
branch (`git pull`) **before** calling it, because the collector reconstructs snippets from the
**current** working tree:

```
flow-review-collect [<pr_or_mr_number>]
```

**Output** — one JSON object on stdout (the skill stores it as `metadata.json`):

```json
{ "platform": "github",
  "unit": { "number": 109, "branch": "…", "url": "…" },
  "me": "NoNameItem",
  "counts": { "total": N, "already_replied": M, "actionable": K },
  "comments": [
    { "ref": "C1", "user": "…", "is_bot": true,
      "path": "…", "start_line": null, "line": 665,
      "outdated": false, "already_replied": false,
      "comment_id": 123, "discussion_id": null, "summary_id": null,
      "body": "full text", "thread": [ { "user": "…", "body": "…" } ],
      "diff_hunk": "…|null", "position": {…}|null,
      "snippet": { "lang": "python", "text": "…" }|null } ] }
```

The script deterministically absorbs the whole of the current STEP 1–4: fetch (comments +
reviews / discussions, with pagination), thread parsing, outdated detection with
`original_line`/`original_start_line` fallback, source classification, resolved-thread skipping
(GitLab), bot-summary extraction with `summary_id` (GitHub reviews), `already_replied`, ref
assignment (humans `U…` first, bots `C…` second), and snippet reconstruction (range math +
`max(1, …)` clamp + `open(path)` file read + language-from-extension).

**Snippet threshold (deterministic — replaces an LLM judgment).** A `snippet` is attached when
the note is not outdated **and** either the platform is GitLab (no `diff_hunk` exists) **or** the
GitHub `diff_hunk` is absent or shorter than a fixed threshold of context lines (a single small
constant — the exact number is pinned in the implementation plan). This turns the
former Phase-3 "is the hunk too thin?" judgment (after which the LLM hand-built a snippet) into a
tested line-count threshold, removing snippet mechanics from Phase 3 entirely. If the file read
yields nothing usable (deleted/moved file) → `snippet = null` (degrade, do not fail).

## `flow-comment-card` (merge mode)

New invocation (the existing full-card-on-stdin path is retained):

```
flow-comment-card --meta metadata.json --ref C1 --verdict verdict-C1.json
```

- Reads the `metadata.json` item for `ref` and the verdict file.
- Merges: `card = meta_item + { author, category, thought, suggested }`.
- Applies the `diff_hunk ↔ snippet` override (was the Phase-4.2 jq prose): a non-empty `snippet`
  — attached by the collector precisely when the hunk is thin/absent — wins over `diff_hunk`;
  otherwise `diff_hunk` is shown.
- Renders. The whole 4.2 assembly (jq + quoted-heredoc) moves into tested Python.

**Phase-3 verdict is JSON, not a text block.** The analysis sonnet subagent reads its comment
slice from `metadata.json` and writes `verdict-{ref}.json`:

```json
{ "verdict": "disagree", "category": "correctness",
  "thought": "…", "suggested": "won't-fix",
  "claim": "…", "evidence": "…" }
```

`claim`/`evidence` are present only for `disagree` / `outdated_fixed`; there is **no** snippet
field — the collector owns snippets. This removes three bug classes from Phase 3 at once:
fence-collision (no fenced snippet output), quoting/heredoc injection (the main LLM no longer
hand-builds jq; `flow-comment-card` reads `--meta`/`--verdict` by path), and offset/limit (no
file read in Phase 3). The Phase-3 prompt shrinks to pure judgment.

## `flow-wait-ci` migration

`flow-wait-ci` is currently the only helper that talks to gh/glab, with its own inline `_run`,
platform detection, and repo/project resolution. Migrate those onto `_git.py` so the CLI
foundation is not duplicated. Its CI-specific queries (GraphQL check-runs, pipelines/jobs) stay
in `flow-wait-ci`. The existing `test_flow_wait_ci.py` guards the refactor.

## SKILL.md impact

| Block | Now | After | Moves into code |
|-------|-----|-------|-----------------|
| Phase 2.1+2.2+2.3 | ~290 lines (two large subagent prompts + cap + untrusted-data rule + snippet math) | ~15–25 lines: run collector, filter already_replied, render TOC, select subset if >~20 | all fetch/parse/snippet/summary_id/stable-id/offset-limit |
| Phase 3 | ~145 lines | ~40% shorter: read slice → reason → write verdict JSON | SNIPPET rules, offset/limit, fence |
| Phase 4.2 | ~130 lines (jq + heredoc) | ~5 lines: one `flow-comment-card` invocation per ref | quoted-heredoc / fence / delimiter / override |
| Platform table, Red Flags, Rationalizations, Edge Cases, Examples | heavy mechanism (sed / fence / stable-id / clamp) | markedly thinner | references to the scripts' mechanism |

Estimate: **1510 → ~700–850 lines**, roughly halved. What remains is genuinely prose-worthy:
judgment (analysis criteria, the disagree-evidence discipline, generalize-the-class,
self-review), triage, reply-text authoring, platform/scope boundaries, and examples.

## Bug class → resolution

| Recurring class (waves 1–7) | Resolved by |
|-----------------------------|-------------|
| untrusted path → shell injection | `_git.py run(argv)` + collector `open(path)`; no shell parses a path |
| fenced snippet collision | verdict is JSON; collector owns snippets; no fenced LLM output |
| Read `offset`/`limit` vs end line | snippet reconstruction is tested Python in the collector |
| range clamp (lines 1–4) | `max(1, …)` clamp in the collector, unit-tested |
| card-assembly quoting / heredoc | `flow-comment-card` reads `--meta`/`--verdict` by path |
| `allowed-tools` grant gaps | fewer commands invoked from prose; the collector is one grant |

## Testing

- `_git.py`: unit tests + reuse `fake_gh` / `fake_glab`.
- `flow-review-collect`: subprocess tests via `run_helper` + `fake_gh`/`fake_glab` (queue
  comments/reviews/discussions JSON) + `git_repo`/tmp files for snippet reconstruction. Cases:
  outdated→`original_line`, `summary_id`, resolved-skip, `already_replied`, ref ordering, GitLab
  range (multiline / single / clamp at lines 1–4 / outdated → null), thin-hunk threshold,
  deleted/moved file → `snippet = null`.
- `flow-comment-card` merge: extend `test_flow_comment_card.py` — merge meta+verdict, the
  override, and the retained stdin path.
- SKILL.md edits: the writing-skills documentation-test discipline, the `check_md.py`
  heading-parity check, and a dogfood-skeptic pass.

## Non-goals

- No Phase-5 finalizer extraction (→ elf.35).
- No pip packaging of `flow`.
- No behavior change to analysis / triage / reply.
- The GitHub thin-hunk threshold reuses one fixed value; no per-language tuning.
