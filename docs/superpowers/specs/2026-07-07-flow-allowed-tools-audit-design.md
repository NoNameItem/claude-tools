# Flow skills: audit `allowed-tools` for bin/ helper commands

- **Task:** claude-tools-elf.22
- **Date:** 2026-07-07
- **Status:** design approved

## Problem

The `flow-*` helper scripts in `plugins/flow/bin/` (e.g. `flow-require-bd`, `flow-sync`,
`flow-task-card`) are invoked by the flow skills, but no skill's `allowed-tools` frontmatter
lists them. In environments where a skill's `allowed-tools` is strictly enforced as an
allowlist — notably Codex — every helper call triggers a permission prompt or is rejected.
The result is that `/flow:*` skills stutter on their own internal plumbing.

The originating Codex review (PR #85) proposed covering the helpers with a single
`Bash(flow-*:*)` wildcard. That exact syntax is wrong (see Findings), and the underlying
question — enumerate vs. wildcard, and how wide to grant — needed deciding.

## Goals

- Every flow skill pre-approves the internal `flow-*` helper scripts it invokes, so they
  never prompt.
- Clearly-safe, read-only shell utilities (the `cd`/`ls`/`tail` class) are pre-approved too,
  so incidental plumbing the agent improvises does not prompt.
- Dangerous or destructive tools are **not** rubber-stamped; they continue to prompt so the
  user decides each time.

## Non-goals

- **No `disallowed-tools`.** Nothing is hard-blocked. Dangerous tools are simply left
  unlisted so the user's normal permission flow governs them.
- **No drift-guard test.** The skills are prose instructions to an LLM; their true runtime
  command set is under-specified by design, so an automated "did you list every command"
  check would produce false positives. Rejected during design.
- **No removal of existing safe pre-approvals** ("add-only"), with one deliberate exception:
  `python3` (see Design → The one removal).
- Not refactoring the skills' logic, helpers, or behavior. Frontmatter only.

## Findings (verified during design)

1. **`Bash(flow-*:*)` is invalid.** The `:*` form means "a space then anything" (a word
   boundary), so `Bash(flow-:*)` = `Bash(flow- *)` and does **not** match `flow-sync`. The
   correct single wildcard for the helper family is **`Bash(flow-*)`** (no colon, no space) —
   it matches `flow-sync`, `flow-require-bd`, all 14 helpers, plus their arguments.
2. **Pipelines are matched per segment.** `bd show x --json | flow-task-card` needs *both*
   `Bash(bd:*)` and coverage for `flow-task-card`. This is why the current skills prompt even
   though `bd` is allowed.
3. **In Claude Code, `allowed-tools` is additive, not restrictive.** It pre-approves listed
   tools; it does not deny unlisted ones (session settings still govern, and unlisted tools
   may prompt). Restriction would require the separate `disallowed-tools` field — which this
   design does not use. In strictly-enforcing environments (Codex), `allowed-tools` *is* the
   gate, so omission there denies. The design's restriction intent therefore holds in Codex
   and is a no-op in Claude Code, which matches the "let the user decide dangerous" goal.
4. **No skill body instructs `python3` or `jq` directly.** JSON parsing is improvised by the
   agent, so the capability can be moved from `python3` (arbitrary code execution) to `jq`
   (constrained data extraction) with no body edits.
5. **Frontmatter format:** a single space-separated line is valid and matches the existing
   convention; a YAML list is also accepted.

## Design

### Capability principle

Tools are sorted by capability, not by "is it used today":

- **Pre-approve — internal + clearly-safe read-only.** `Bash(flow-*)` (only in skills that call
  helpers) plus a fixed baseline of read-only/inspection utilities. None of these write files,
  exec code, or reach the network **through their own arguments** — the property that
  command-allowlisting can actually enforce (it is why `sort -o` / `uniq OUTPUT` are excluded).
  This is deliberately *not* a capability sandbox: shell redirection (`echo x > f`) can write on
  **any** allowed command, and any read tool (`cat`, `tail`, `jq`) can read any file — the
  permission system plus the human remain the real boundary. Within that bound these tools are
  benign, so pre-approving them cuts prompts.
- **Pre-approve — domain/service tools per skill.** `bd`, `git`, `gh`, `glab`,
  `mcp__sonarqube__*`. These can mutate, but that is the skill's declared job, and listing
  them documents which services the skill touches. Kept as already present (add-only).
- **Leave unlisted — dangerous / destructive.** `python3`/`python`, `curl`, `wget`, `eval`,
  `bash -c`, `sh -c`, `awk` (arbitrary exec / network) and `rm`, `mv`, `mkdir`, `sed`
  (destructive / in-place edit). Not rubber-stamped; they prompt; the user decides.

### The safe baseline

Every flow skill except `init-worktree` gets this baseline:

```
Bash(flow-*) Bash(cat:*) Bash(grep:*) Bash(head:*) Bash(tail:*) Bash(cut:*) Bash(tr:*) Bash(wc:*) Bash(echo:*) Bash(test:*) Bash(ls:*) Bash(cd:*) Bash(jq:*)
```

`Bash(flow-*)` is included only in skills that actually invoke helpers — and blanket `flow-*` only
where those helpers include `flow-sync` (which pushes beads state). Two skills are narrowed so the
push-capable `flow-sync` is not pre-approved where it isn't used (limiting the prompt-injection
blast radius):

- `review-comments` calls no `flow-*` helper → it gets **none**.
- `sonar-sync` uses only `flow-require-bd` and `flow-current-task`; its body defers `flow-sync push`
  to the user ("separate concern; user runs after if needed"), so it enumerates
  `Bash(flow-require-bd:*) Bash(flow-current-task:*)` instead of blanket `flow-*`.

(The `:*` form matches the bare command as a complete token *and* the command-with-args, so
`flow-require-bd` with no args is covered.)

`sort` and `uniq` are deliberately **excluded**: both write files through their own arguments
(`sort -o FILE`, `uniq [INPUT [OUTPUT]]`), so a `Bash(sort:*)` / `Bash(uniq:*)` rule would
pre-approve file writes. No skill uses them. `echo` and `test` **are** included — `start`'s
worktree auto-resolve runs `test -n "$WT" && echo …` (the `[ … ]` form was normalized to `test`
so a plain command name can be allow-listed), and per-segment matching means each needs its own
rule; both are safe builtins (stdout / condition-eval only).

### The one removal: `python3` → `jq`

`start` and `continue` currently pre-approve `Bash(python3:*)`, so arbitrary `python3 -c "…"`
never prompts. That contradicts "let the user decide dangerous." Remove both entries. The
baseline's `Bash(jq:*)` gives a pre-approved, constrained path for the only real need (JSON
parsing); if the agent still reaches for `python3`, it prompts and the user decides. This is
the design's only removal.

### The `init-worktree` exception

`init-worktree` keeps its bare `Bash Read`. It runs *unknowable* project-setup commands
(`uv sync`, `npm install`, `cargo build`, possibly `python3 setup.py`), so its command set
cannot be enumerated. The real safety control there is the explicit user confirmation the
skill body already requires before running anything.

### Per-skill target `allowed-tools`

Non-Bash tools (`Skill`, `Agent`, `Read`, `Edit`, `TodoWrite`, `mcp__sonarqube__*`) are
carried over unchanged. `BASELINE` = the safe baseline string above.

| Skill | Target `allowed-tools` |
|---|---|
| after-design | `Bash(bd:*) BASELINE` |
| after-plan | `Bash(bd:*) BASELINE` |
| continue | `Bash(bd:*) Bash(git:*) BASELINE Skill TodoWrite` (−`python3`) |
| decompose | `Bash(bd:*) Bash(git:*) BASELINE Read Edit` |
| done | `Bash(bd:*) Bash(git:*) Bash(gh:*) BASELINE` |
| init-worktree | `Bash Read` (unchanged) |
| review-comments | `Bash(git:*) Bash(gh:*) Bash(glab:*) BASELINE Agent Read` (BASELINE **minus** `Bash(flow-*)` — no helper calls) |
| sonar-sync | `Bash(bd:*) Bash(gh:*) BASELINE Agent mcp__sonarqube__search_my_sonarqube_projects mcp__sonarqube__search_sonar_issues_in_projects` (BASELINE's `Bash(flow-*)` **replaced by** `Bash(flow-require-bd:*) Bash(flow-current-task:*)` — no `flow-sync`) |
| start | `Bash(bd:*) Bash(git:*) BASELINE Skill TodoWrite` (−`python3`) |

Consequences worth noting:
- `done` still prompts on `rm`/`mv`/`mkdir`/`sed` (plan-file cleanup, branch inspection) — by
  design.
- `review-comments` still prompts on `sed` (reading code ranges) — by design.
- `after-design`/`after-plan`'s current `Bash(ls:*) Bash(head:*)` are absorbed into the
  baseline (kept, not removed).

## Known limitations

- **Command-substitution captures still prompt.** `Bash(flow-*)` matches a command whose *first
  token* is `flow-…`. Helpers whose stdout is captured — `WORKTREE_DIR=$(flow-worktree-dir …)`,
  `BRANCH=$(flow-branch-for …)`, `WT=$(flow-find-worktree … | head -1)`, `"$(flow-actor)"` in
  `start`/`continue` — are matched as commands starting with `VAR=$(…)` (Claude Code does not
  split on `$(…)` — only `&&`/`||`/`;`/`|`/`|&`/`&`/newlines — nor recurse into substitutions),
  so `Bash(flow-*)` does not cover them and they still prompt in enforcing sessions. Capturing
  output inherently needs `$(…)`, so this can't be fixed by "making helpers standalone." Affected:
  `flow-branch-for`, `flow-find-worktree`, `flow-worktree-dir`, `flow-actor`. Tracked as a
  follow-up (a PreToolUse hook or restructured capture) — out of scope for a frontmatter audit.
- **Not a capability sandbox.** As noted above, shell redirection (`echo x > f`) can write on any
  allowed command and any read tool can read any file; command-allowlisting only bounds a
  command's own arguments. The permission system + human are the real boundary.

## Verification

- For each edited skill, confirm the frontmatter parses and that `flow-*` helpers plus the
  safe baseline are covered.
- Spot-check that no dangerous tool (`python3`, `curl`, `rm`, …) was accidentally added.
- Where feasible, run a `/flow:*` skill in a strictly-enforcing environment (Codex) and
  confirm no permission prompt fires on `flow-*` helpers.

## Definition of done

- Every bd/flow skill's `allowed-tools` covers (via `Bash(flow-*)`) all `flow-*` helpers it
  invokes.
- The safe read-only baseline is present in every skill except `init-worktree`.
- `Bash(python3:*)` removed from `start` and `continue`; `Bash(jq:*)` present via baseline.
- No `disallowed-tools` added; no drift-guard added.
