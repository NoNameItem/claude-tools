# Flow Codex plugin tooling — design

**Date:** 2026-07-22
**Status:** approved
**Task:** claude-tools-5vg.7 — *Adapt the plugin CI/release workflow for Codex plugins*

## Context

PR #113 added native Codex support to the Flow plugin: a second manifest
(`plugins/flow/.codex-plugin/plugin.json`) alongside the Claude one, Codex runtime hooks, and Codex
agent profiles. The runtime behaviour was designed in
`2026-07-17-flow-codex-support-design.md`. This document covers the **repo tooling** that native
Codex support implies but that #113 deferred: manifest validation, release/versioning parity, and
marketplace/distribution.

The design is grounded in the Codex CLI source (`openai/codex`, `main`): the plugin manifest
loader (`codex-rs/core-plugins/src/manifest.rs`), the marketplace loader
(`codex-rs/core-plugins/src/marketplace.rs`), and the marketplace CLI
(`codex-rs/cli/src/marketplace_cmd.rs`). Confidence in the field/type facts below is high; the one
unverified detail (owner/repo shorthand inside a marketplace-file `url`) is called out explicitly
and handled by a smoke test rather than a guess.

### Current state after #113 merged to master

- **Validation:** `validate_codex_manifest` (`.github/scripts/validate_plugin.py`) exists and is
  wired into CI (`_reusable-claude-code-plugin-ci.yml` passes `--require-codex-manifest` for flow).
  It validates the Codex manifest by **reusing `PATH_FIELDS`** — the field list built for Claude's
  schema — so it does not model Codex's real fields.
- **Release:** `release-please-config.json` already bumps **both** manifests via `extra-files`
  (`$.version`) from a single `.release-please-manifest.json`. **This is confirmed working**:
  after #113 merged, release-please correctly bumped the version in `.codex-plugin/plugin.json`.
- **Distribution:** the only marketplace file is `.claude-plugin/marketplace.json`, a tag-pinned
  `git-subdir` source pinned by `pin_marketplace_refs.py`.

## Goals

- Validate the Codex manifest against a **Codex-specific field schema**, not Claude's `PATH_FIELDS`.
- Guard the confirmed dual-manifest version bump with a regression test so parity cannot silently
  drift.
- Establish and document the Codex distribution/install path; correct the README, which currently
  misdocuments it.

## Non-goals

- Targeting Codex's **strict directory-ingestion** contract (the `plugin-creator` allowlist that
  rejects `hooks`/`commands` and requires a full `interface` block). Flow uses hooks and is not
  publishing to OpenAI's official directory; we target the **permissive runtime loader** contract.
- Creating a `.codex-plugin/marketplace.json`. No such path exists in Codex.
- Deep-validating inline hook/mcpServer object structure. We validate shape (path vs inline), not
  the internal hook schema.
- Speculatively rewriting `marketplace.json` `source.url`. Left as-is (shorthand) pending the smoke
  test.

## Ground-truth: Codex vs Claude manifest schema

Codex runtime loader (`manifest.rs`, camelCase, **unknown keys ignored**):

| Field | Codex type | Claude type |
|---|---|---|
| `name`, `version`, `description`, `keywords` | same as Claude | same |
| `skills` | path **or** list of paths | path or list |
| `commands` | path **or** list of paths | path or list |
| `apps` | **single path string only** (→ `.app.json`) | — (absent) |
| `hooks` | path · list of paths · **inline object** · **inline object list** | path or list only |
| `mcpServers` | path **or inline object** | path or list only |
| `agents`, `outputStyles`, `lspServers` | **absent** | path or list |

Key consequences: `apps` is never validated today (absent from `PATH_FIELDS`); an inline
`hooks`/`mcpServers` object is wrongly rejected as "not a path"; and `agents`/`outputStyles`/
`lspServers` are not Codex fields.

## Item 1 — Codex-specific field-schema validation

Replace the `for path_field in PATH_FIELDS:` loop in `validate_codex_manifest` (currently
`validate_plugin.py:152-161`) with a validation driven by an explicit **Codex field spec** — a
mapping from field name to a *kind* that encodes what values are accepted.

### Field spec

| Field | Kind |
|---|---|
| `skills` | `PATHS` |
| `commands` | `PATHS` |
| `apps` | `PATH_SINGLE` |
| `hooks` | `HOOKS` |
| `mcpServers` | `MCP` |

### Kind semantics

- **`PATHS`** — value is a single path string or a list of path strings. Each path is validated by
  the existing `_codex_manifest_path_error` (`./` prefix, resolves inside the plugin, exists). A
  dict, or a list containing a non-string, is an error.
- **`PATH_SINGLE`** (`apps`) — value must be a **single string** path (Codex forbids a list/object
  here). A list or dict is an error (`"apps must be a single path string"`); a string is then
  validated as a path.
- **`HOOKS`** (`hooks`) — accepts four Codex shapes: string → path; list of strings → paths; dict →
  inline (accepted, no path check); list of dicts → inline (accepted). A mixed or otherwise-typed
  list is an error.
- **`MCP`** (`mcpServers`) — string → path; dict → inline (accepted). A list or other type is an
  error (Codex has no list form for `mcpServers`).

### Decisions carried

- **`./` prefix kept.** Codex normalises paths and does not strictly require `./`, but the repo
  convention (and the existing `_codex_manifest_path_error`) require it. Keeping it is a
  deliberately stricter, harness-consistent rule.
- **Name/version parity assertion kept.** The existing check that Codex `name`/`version` equal the
  Claude manifest's stays — it is also the runtime safety net for Item 2.
- **Non-Codex fields ignored.** `agents`/`outputStyles`/`lspServers` are simply absent from the
  Codex field spec and are not validated (Codex ignores unknown keys). This is the chosen
  field-schema approach, not a full loader mirror — we do not warn on their presence.
- **Inline shapes validated structurally only** — dict / list-of-dict is accepted without inspecting
  the hook/server internals.

### Tests (`.github/scripts/tests/test_validate_plugin.py`)

- `apps`: valid single existing path → ok; `apps` as a list → error; `apps` pointing at a missing
  file → error.
- `hooks`: inline object → ok; inline list of objects → ok; path string → validated as a path
  (existing behaviour preserved); missing path string → error.
- `mcpServers`: inline object → ok; path string → validated as a path; list form → error.
- A non-Codex field (`agents`) present in the Codex manifest produces no false path error.

## Item 2 — release parity regression test

No rework — the dual bump is confirmed working. Add a regression guard so it cannot silently
regress.

- New test file `.github/scripts/tests/test_release_please_config.py` asserting that in
  `release-please-config.json`, `packages["plugins/flow"]["extra-files"]` contains **both**
  `.claude-plugin/plugin.json` **and** `.codex-plugin/plugin.json`, each with `type: json` and
  `jsonpath: $.version`.
- The runtime parity assertion in `validate_codex_manifest` (Item 1) remains as the second line of
  defence at validation time.

## Item 3 — marketplace / distribution

### Decision: reuse the existing marketplace file

No Codex-specific marketplace artifact is created. Ground-truth from `marketplace.rs`:

- Codex's recognised marketplace paths include `.claude-plugin/marketplace.json` (its own native
  path is `.agents/plugins/marketplace.json`; **`.codex-plugin/marketplace.json` does not exist**).
- `git-subdir` (with `url` + required `path` + optional `ref`/`sha`) is a first-class Codex
  marketplace source type.

So the current `.claude-plugin/marketplace.json` — a tag-pinned `git-subdir` source — is consumed
by Codex as-is. Structurally it is Codex-compatible; the tooling (`validate_plugin.py`,
`pin_marketplace_refs.py`, release-please) needs **no change** for distribution.

### Install commands differ — fix the README

Codex does **not** use Claude Code's `/plugin marketplace add` + `/plugin install` slash commands.
The current README Codex section wrongly implies it does. Correct it to the real Codex flow:

1. `codex plugin marketplace add NoNameItem/claude-tools` — add the repo's marketplace source
   (reads `.claude-plugin/marketplace.json` at the repo root).
2. In the `codex` TUI, run `/plugins` and install **flow** from the browser (Codex resolves the
   `git-subdir` source, tag-pinned to `flow-<version>`).
3. Trust the plugin's `SessionStart` / `PreToolUse` hooks via `/hooks` (one-time).
4. Start a new Codex session so hooks load.

Keep the existing Claude Code install instructions unchanged; present Codex as a parallel path.

### `source.url` shorthand — kept, verified by smoke test

`marketplace.json` uses `"url": "NoNameItem/claude-tools"` (owner/repo shorthand). Codex's
`marketplace add` **CLI argument** accepts shorthand, but whether Codex accepts shorthand in the
`url` field **inside a marketplace file** is not confirmed from source. Decision: **do not change
it speculatively.** The design includes a manual smoke test on a real Codex CLI; if shorthand fails
there, a separate one-line follow-up switches `url` to the full HTTPS form. This avoids risking the
working Claude Code install on an unverified assumption.

## Verification

- **Unit (CI):** the Item 1 and Item 2 tests run in the existing plugin CI test job.
- **Manual smoke test (Item 3), on a real Codex CLI (≥ 0.144.6):**
  1. `codex plugin marketplace add NoNameItem/claude-tools` succeeds and lists the `flow` plugin.
  2. Installing `flow` via `/plugins` resolves the `git-subdir` source and fetches the tagged
     subdir.
  3. After trusting hooks and restarting, `$flow:start` discovers and runs.
  4. If step 1 fails on the shorthand `url`, file the one-line follow-up to use the full HTTPS URL.

## Acceptance

- Codex manifests are validated against a Codex field schema (Item 1), not Claude's `PATH_FIELDS`:
  `apps` is validated as a single path, inline `hooks`/`mcpServers` are accepted, real Codex fields
  are modelled.
- A release bumps both manifests coherently and a regression test guards it (Item 2); parity cannot
  silently drift.
- The Codex distribution/install path is documented with the correct Codex commands, and the reuse
  of `.claude-plugin/marketplace.json` (no new artifact) is recorded with its one smoke-tested
  assumption (Item 3).

## Alternatives considered

- **Minimal patch to `validate_codex_manifest`** (just add `apps`, allow inline hooks) — rejected:
  keeps `PATH_FIELDS` shared with Claude and leaves the Codex/Claude schema conflation that caused
  the original review comment.
- **Full Codex loader mirror** (validate `interface`, `keywords` types; flag non-Codex fields) —
  rejected as overengineering for a single hand-maintained manifest; the field-schema table covers
  the real gaps.
- **New `.codex-plugin/marketplace.json`** — rejected: that path does not exist in Codex; Codex
  already reads `.claude-plugin/marketplace.json`.
- **Proactively switch `source.url` to full HTTPS** — deferred: unverified whether Claude Code's
  git-subdir accepts the full URL form, so changing it risks the working Claude install; smoke test
  first.
