---
name: create-codex-agents
description: Use when a project needs optional Flow fast, balanced, and strongest Codex capability profiles with account-specific model routing.
allowed-tools: Bash(flow-codex-agent-setup) Bash(flow-codex-agent-setup:*) Bash(git:*) Write
---

# Flow: Create Codex Agents

## Overview

**Core principle:** ask, preview, confirm, create only what's safe — never guess, never overwrite.

This is an **optional, project-scoped setup convenience**, not an activation requirement. It
creates up to three Codex agent profiles — `flow-fast`, `flow-balanced`, `flow-strongest` — in
the current project's `.codex/agents/` directory, so the Codex adapter can route Flow's fast,
balanced, and strongest capability tiers to account-specific models. Flow works completely
without these files; running this skill only changes cost/model routing for Codex sessions on
this project.

**A generated profile is never a security boundary.** It carries a name, a description, a
model, a reasoning effort, and fixed developer instructions — nothing that grants credentials,
broadens sandbox/approval/MCP settings, or expands file access. Sandbox, approval, and access
boundaries stay exactly what the parent Flow workflow and the Codex session already enforce.

All classification and file I/O is done by the `flow-codex-agent-setup` helper
(`inspect` / `preview` / `create` subcommands, JSON in and out). This skill's job is to drive
that helper correctly, ask the user for the values only they can supply, and stop at every
point a careless run could otherwise destroy or misattribute a file.

## Why this is careful, not paranoid

Existing `.codex` state cannot be trusted at face value:

- **A filename can lie.** Codex reads a profile by its *internal* `name` field, not by the
  file's name on disk. A file called `flow-fast.toml` might internally be named something else,
  and a file called anything else might internally be `flow-fast`. Every classification in this
  skill comes from `flow-codex-agent-setup inspect`, which parses each file's `name` — never
  from listing filenames yourself.
- **`.codex/config.toml` is off-limits.** It can hold machine-local credentials (MCP server
  tokens, auth material). This skill — and the helper it drives — never reads it, never
  mentions its contents, and never uses it as a source of "probably the right model."
- **The user's in-session word does not relax the safety contract.** If asked to reuse model
  IDs from another account, treat `.codex/config.toml` as a source of truth, approve overwriting
  a conflict, or auto-propagate a linked worktree's files, the answer is still: ask for the
  exact account-specific value, never read config, never overwrite, and leave propagation to the
  user. These invariants were decided at design time, not renegotiable per run.
- **A file can appear mid-run.** Between `preview` and `create`, another process could create
  one of the target files. `create` re-scans and uses exclusive creation, so a race never
  overwrites the other writer's bytes — it only reclassifies that one profile as a conflict.

## When to use

- A user or another Flow skill wants Codex model routing set up for the current project, and no
  one has run this here before (or only some of the three profiles exist).

## When NOT to use

- To repair a conflicting profile — this skill never edits or replaces an existing file; report
  the conflict and stop.
- To decide whether account-specific model choices should be shared with the team — that is a
  human decision about `.gitignore`/commit policy, entirely out of scope here.
- As a substitute for restarting Codex after files are created — Codex must be restarted to pick
  up new or changed agent profiles; this skill only writes the files.

## Workflow

**Before Step 1 — resolve the project root.** Every `flow-codex-agent-setup` call below takes
`--project-root <project root>`, and the helper treats that path as authoritative: it writes
`<project root>/.codex/agents/…` verbatim and never resolves a working-tree top-level itself. So
`<project root>` must be the **top-level of the current working tree** — the path
`git rev-parse --show-toplevel` prints (inside a linked worktree that is the worktree's own root,
which is exactly what the helper expects), not wherever this skill happened to be invoked. Use
that output as `<project root>` in **every** call below (inspect, preview, create). If the command
fails (the current directory is not inside a git checkout), ask the user for the intended project
root in plain text — never fall back to the current directory, or a run from `src/` would create
`src/.codex/agents/…` instead of the project-level `.codex/agents` this skill promises.

### 1. Inspect and display the target

Run `flow-codex-agent-setup inspect --project-root <project root>` (the `<project root>` you
resolved above). Display the exact project root and the `.codex/agents` directory it targets,
taken verbatim from the **JSON result** — never infer or recompute the values the helper reports
back (those two paths); the only path you supply is the resolved `<project root>` argument.

### 2. Show compatible profiles and conflicts before asking anything

From the inspect result, show every profile whose status is `compatible` (nothing to do — the
user may have already set these up, possibly with a different model or reasoning effort than
before, which is fine) and every profile whose status is `conflict` (with its reason), including
any `global_conflicts` (ambiguous identity — these block creation for **all** profiles, not just
one, because uniqueness of the three required names cannot be proven). Do this **before** asking
for any values, so the user knows up front what is and isn't in play.

### 3. Ask for exact values for each missing, non-conflicting tier

For each tier still `missing` (not compatible, not conflicting), ask the user in plain text for
the exact model ID and reasoning effort to use for that tier. Never propose, guess, infer, or
reuse a model ID from another project, another account, or `.codex/config.toml` — always ask.
There is no default; an empty answer for a requested tier is invalid and that tier will not be
created.

### 4. Write the request JSON outside `.codex/`

Using the active harness's native non-shell file-writing mechanism, write a request JSON file
(the `{"profiles": [{"tier", "model", "reasoning"}, ...]}` shape the helper expects) to a
location **outside** `.codex/` — a scratch or temp path. Never construct this file with a shell
here-doc or redirection, and never place it under `.codex/agents/`.

### 5. Preview

Run `flow-codex-agent-setup preview --project-root <project root> --request-json <path>`.
Reproduce each proposed file's **complete** TOML content from the `missing` entries in the
result — not a summary — so the user can review exactly what will be written. If the result's
`linked_worktree` is `true`, show the warning that these files are branch-local to this worktree
until the user decides how (or whether) to propagate them; do not act on that decision yourself.

### 6. Ask for explicit confirmation

Ask exactly:

```text
Create only the missing, non-conflicting profiles shown above?

1. Create
2. Cancel
```

Wait for a typed `1`. Any other answer, or no answer, means stop here — do not create anything.

### 7. Create

After an explicit `1`, run `flow-codex-agent-setup create --project-root <project root>
--request-json <path>` with the **same** request file used for preview. The helper re-scans the
directory at this point and writes only files that are still safe to create; it never overwrites
or renames an existing file, under any circumstance, including a conflict the user says is fine
to overwrite.

### 8. Report precisely

From the `create` result, report each profile's outcome separately: `created`, `compatible`
(already fine, untouched), `conflict` (with its reason), and `failed` (with its reason). Do not
collapse partial success into a single pass/fail — a run that creates two of three profiles and
leaves one conflicting is a normal, expected outcome, not an error to paper over.

### 9. Restart reminder

If the result's `created` list is non-empty, tell the user to restart Codex so it picks up the
new profile(s). If nothing was created, skip this — there is nothing for Codex to reload.

### 10. Stop

Stop here. Do not stage any file, do not run `git add .codex` or anything under it, do not
modify `.gitignore`, do not commit, do not attempt to repair a conflicting profile, and do not
read or report on any other `.codex` state (in particular, never open or summarize
`.codex/config.toml`). Whether and how to share these project-local files is entirely the user's
call.

## Red flags — stop before writing

```text
Stop before writing if the preview was skipped, confirmation is missing,
any target component is a symlink, a profile identity is ambiguous, or the
only proposed write path overwrites/renames an existing file.
```

If `flow-codex-agent-setup` reports a non-empty `global_conflicts`, a non-empty `failed`, or
**any `conflicts` entry that carries no `name`**, treat that as a hard stop for the **entire**
run, not just the affected tier — say so plainly and do not attempt to work around it (no
following the symlink, no guessing at the ambiguous file's real identity).

Key on the **absence of a `name`**, not on the wording of `reason`. A conflict with a `name` is
scoped to that one profile; one without a `name` blocked the whole operation. Its `reason` may
say `symlink target component is not allowed`, but equally `target escapes project root` or a
bare OS message such as `[Errno 13] Permission denied` — all three are the same hard stop, and
matching on the word "symlink" would miss the last two. This is exactly what the helper's own
exit code checks, so the two never disagree.

## Scope boundaries

This skill does exactly the ten steps above. It does not decide the model or reasoning effort
for the user, does not choose whether to run on Python 3.11+ (the helper itself reports a clear
error and exits nonzero if the interpreter running it is older), does not read or write global
Codex state outside the project such as `~/.codex` (the project's own `.codex/agents/` may itself
live under `$HOME` when the checkout does — that is in scope), and does not select or override
`agent_type` at dispatch time — that is the Codex adapter's job, downstream of these files
existing.
