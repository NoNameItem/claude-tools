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
unverified detail (owner/repo shorthand inside a marketplace-file `url`) is sidestepped for the new
Codex marketplace by writing the full HTTPS `url` (Item 3).

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
- Keep the confirmed dual-manifest version bump guarded by the runtime name/version parity assertion
  (no config-file regression test — see Item 2).
- Establish a **dedicated Codex marketplace** at Codex's native path
  (`.agents/plugins/marketplace.json`), validate its registration symmetrically, pin its refs on
  release, and document the Codex install path; correct the README, which currently misdocuments it.

## Non-goals

- Targeting Codex's **strict directory-ingestion** contract (the `plugin-creator` allowlist that
  rejects `hooks`/`commands` and requires a full `interface` block). Flow uses hooks and is not
  publishing to OpenAI's official directory; we target the **permissive runtime loader** contract.
- Creating a `.codex-plugin/marketplace.json` — no such path exists in Codex. Codex's native
  marketplace path is `.agents/plugins/marketplace.json` (Item 3 creates that).
- Deep-validating inline hook/mcpServer object structure. We validate shape (path vs inline), not
  the internal hook schema.
- Wiring `.github/scripts/tests/` into CI. Those tests stay author-time only (see Item 2); this task
  does not change that.

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

## Item 2 — release parity (no new test)

No rework and **no new test** — the dual bump is confirmed working, and its guard is the runtime
name/version parity assertion in `validate_codex_manifest` (Item 1).

- The parity assertion runs in **plugin CI** whenever the plugin changes. If
  `release-please-config.json` ever stops bumping both manifests, the two versions drift and the
  assertion fails on the release PR (which touches `plugin.json`). Drift is caught — at release
  time, not at config-edit time, which is acceptable here.
- **No `test_release_please_config.py`.** It would be a regression test over a *configuration file*
  (`release-please-config.json`), not over a script — and config-file regression tests are not a
  convention in this repo. It also would not run: the `.github/scripts/tests/` suite is deliberately
  **not** wired into CI (workflow scripts change rarely and are tested at author/edit time, not
  guarded by CI-over-CI), so such a test would provide zero protection.

## Item 3 — dedicated Codex marketplace

### Decision: create a Codex marketplace at Codex's native path

Create a new artifact `.agents/plugins/marketplace.json` — Codex's **native** marketplace path
(`marketplace.rs`). This replaces the earlier "reuse `.claude-plugin/marketplace.json`" plan.
Ground-truth from `marketplace.rs`: Codex recognises `.agents/plugins/marketplace.json` (native) and
also `.claude-plugin/marketplace.json`; **`.codex-plugin/marketplace.json` does not exist**; and
`git-subdir` (with `url` + required `path` + optional `ref`/`sha`) is a first-class source type.

**Why a dedicated file, not reuse:** plugins in this repo are written Claude-first, then gain Codex
support once they settle; some future plugins may be harness-specific. Two marketplace files let the
per-harness plugin sets diverge, and make each harness's distribution an explicit, validated
contract rather than an implicit "Codex happens to read the Claude file."

### File contents

`.agents/plugins/marketplace.json` mirrors the Claude marketplace schema (`name`, `owner`,
`metadata.pluginRoot`, `plugins[].source` as a tag-pinned `git-subdir`). Codex ignores unknown keys,
so the shared schema is safe. Differences from the Claude file:

- **Plugin set is its own** — lists only Codex-enabled plugins (currently just `flow`).
- **`source.url` is the full HTTPS form** `https://github.com/NoNameItem/claude-tools` (not the
  `owner/repo` shorthand). The file is new, so there is no working install to risk; writing the
  verified-safe full URL sidesteps the unproven "shorthand inside a marketplace file" assumption.

### Known risk: Codex recognises both marketplace files

Codex reads both `.agents/plugins/marketplace.json` (native) and `.claude-plugin/marketplace.json`,
and both list `flow`. Whether Codex, for a single added repo source, merges the two (listing `flow`
twice) or dedupes is not confirmed from source. The smoke test (Verification, step 1) checks `flow`
appears **exactly once**. If it double-lists, that is a one-line follow-up whose fix depends on the
observed Codex merge behaviour (e.g. a distinct marketplace `name` for the Codex file). Deferred to
the smoke test rather than guessed, consistent with the `source.url` decision above.

### Symmetric marketplace-registration validation (`validate_plugin.py`)

`validate_marketplace_registration` becomes symmetric, driven by an explicit manifest→marketplace
mapping:

| Manifest present | Must be registered in |
|---|---|
| `.claude-plugin/plugin.json` (always) | `.claude-plugin/marketplace.json` |
| `.codex-plugin/plugin.json` (if present) | `.agents/plugins/marketplace.json` |

The Claude check is today's behaviour, unchanged. The Codex check fires only when the plugin ships a
Codex manifest (aligns with `--require-codex-manifest`, which flow already passes). Registration is
matched as today: by plugin name, or by a `source` whose path points at the plugin's location. New
`test_validate_plugin.py` cases: Codex manifest present but plugin missing from
`.agents/plugins/marketplace.json` → error; present in both → ok; name mismatch in the Codex
marketplace → error.

### Ref pinning generalised to all marketplace files (`pin_marketplace_refs.py`)

Today the script hardcodes `MARKETPLACE = Path(".claude-plugin/marketplace.json")`. Generalise it to
iterate over a list of marketplace files — `[".claude-plugin/marketplace.json",
".agents/plugins/marketplace.json"]` — pinning, in each file that exists, every plugin whose
`source.path` maps to a release-please package. Without this, a release pins the Claude file but
leaves the Codex file's `source.ref` stale/unpinned, so Codex users resolve the wrong subdir.
`test_pin_marketplace_refs.py` gains a two-file case (both files pinned in one run; an absent file is
skipped without error).

### README — document the Codex install path

Codex does **not** use Claude Code's `/plugin marketplace add` + `/plugin install` slash commands.
The current README Codex section wrongly implies it does. Correct it to the real Codex flow, sourced
from `.agents/plugins/marketplace.json`:

1. `codex plugin marketplace add NoNameItem/claude-tools` — add the repo's marketplace source (Codex
   reads `.agents/plugins/marketplace.json` from the repo).
2. In the `codex` TUI, run `/plugins` and install **flow** (Codex resolves the `git-subdir` source,
   tag-pinned to `flow-<version>`).
3. Trust the plugin's `SessionStart` / `PreToolUse` hooks via `/hooks` (one-time).
4. Start a new Codex session so hooks load.

Keep the existing Claude Code install instructions unchanged; present Codex as a parallel path.

## Verification

- **CI (real execution, not unit tests):** `validate_plugin.py` runs against the real `flow` plugin
  in **plugin CI** every run (`_reusable-claude-code-plugin-ci.yml`, with `--require-codex-manifest`).
  This exercises Item 1's Codex field-schema validation, Item 2's name/version parity assertion, and
  Item 3's symmetric marketplace-registration check against flow's actual manifests and marketplace
  files. A schema violation, a version drift, or a missing/late-added Codex registration fails CI.
- **Author-time unit tests (not in CI, by repo convention):** the new `test_validate_plugin.py` and
  `test_pin_marketplace_refs.py` cases are run locally with
  `uv run pytest .github/scripts/tests/...` when the scripts are edited. `.github/scripts/tests/`
  is intentionally not wired into CI.
- **Manual smoke test (Item 3), on a real Codex CLI (≥ 0.144.6):**
  1. `codex plugin marketplace add NoNameItem/claude-tools` succeeds and lists `flow` **exactly
     once**, resolved from `.agents/plugins/marketplace.json`.
  2. Installing `flow` via `/plugins` resolves the `git-subdir` source (full HTTPS `url`) and fetches
     the tagged subdir.
  3. After trusting hooks and restarting, `$flow:start` discovers and runs.

## Acceptance

- Codex manifests are validated against a Codex field schema (Item 1), not Claude's `PATH_FIELDS`:
  `apps` is validated as a single path, inline `hooks`/`mcpServers` are accepted, real Codex fields
  are modelled.
- A release bumps both manifests coherently; the runtime name/version parity assertion guards
  against drift (Item 2). No config-file regression test is added.
- A dedicated Codex marketplace exists at `.agents/plugins/marketplace.json` (full-HTTPS
  `git-subdir` source), marketplace registration is validated symmetrically (Claude manifest →
  Claude marketplace, Codex manifest → Codex marketplace), a release pins refs in **both**
  marketplace files, and the README documents the Codex install path (Item 3).

## Alternatives considered

- **Minimal patch to `validate_codex_manifest`** (just add `apps`, allow inline hooks) — rejected:
  keeps `PATH_FIELDS` shared with Claude and leaves the Codex/Claude schema conflation that caused
  the original review comment.
- **Full Codex loader mirror** (validate `interface`, `keywords` types; flag non-Codex fields) —
  rejected as overengineering for a single hand-maintained manifest; the field-schema table covers
  the real gaps.
- **New `.codex-plugin/marketplace.json`** — rejected: that path does not exist in Codex. The native
  Codex path is `.agents/plugins/marketplace.json` (Item 3 uses that).
- **Reuse `.claude-plugin/marketplace.json` for Codex (no new file)** — rejected: it works today
  only because Codex happens to read the Claude path, an implicit contract. A dedicated
  `.agents/plugins/marketplace.json` lets per-harness plugin sets diverge and makes registration a
  validated contract per harness.
- **Shorthand `source.url` in the Codex file, verified by smoke test** — rejected: the Codex file is
  new, so the full HTTPS `url` (known-safe) is written from the start rather than carrying an
  unproven shorthand-in-file assumption. The Claude file keeps its existing shorthand (works for
  Claude Code); Codex no longer depends on it.
