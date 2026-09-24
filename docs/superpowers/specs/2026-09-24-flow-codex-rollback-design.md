# Flow — roll back Codex support and return to Claude-native skills

**Task:** claude-tools-elf.64
**Date:** 2026-09-24
**Status:** approved, pending implementation plan

## Problem

Flow gained native Codex CLI support in two PRs merged after the `flow-3.1.0` release:

- **#113** `feat(flow): add native Codex CLI support` — a Codex manifest, a shared runtime-adapter
  layer (SessionStart hook injecting a common contract plus one harness adapter; a Codex-only
  PreToolUse PATH rewriter), harness-neutral skill wording, capability tiers in review-comments, and
  the optional `flow:create-codex-agents` skill with its `flow-codex-agent-setup` helper.
- **#117** `feat(flow): adapt plugin tooling for Codex plugins` — a Codex field schema in
  `validate_plugin.py`, a Codex marketplace at `.agents/plugins/marketplace.json`, symmetric
  marketplace registration, and multi-file marketplace pinning in `pin_marketplace_refs.py`.

The owner does not want to maintain Flow for Codex. Nothing of it has been released (the installed
plugin is 3.1.0), so it can be withdrawn without a migration story.

Removing only the Codex-named files is not enough. After #113 the **Claude path itself runs through
the adapter**: skills say "the active harness's progress mechanism", "`balanced`-tier reviewer",
"native non-shell file mechanism", and only `hooks/runtime/claude-code.md` — injected by the
SessionStart hook — maps those back to `TodoWrite`/`Skill`/`Read`/`Write` and haiku/sonnet/opus.
Later PRs (#118, #134, #137, #139, #142) wrote new skill text in the same vocabulary because a
contract test forbade the Claude names. Dropping the hook while keeping the wording would silently
break Claude sessions; keeping both leaves an indirection that exists only for Codex.

## Decision

Full return to Claude-native Flow:

1. Delete every Codex artefact and the whole hooks/adapter layer.
2. Rewrite skill text to name Claude Code tools and models directly — including text added after
   #113.
3. Keep the improvements #113 made to the Claude path that are not Codex mechanics: exact per-helper
   `allowed-tools` grants and their audit tests, the removal of `bin/tests/__init__.py`, the inline
   reasons on `# ruff: noqa: INP001`, and the role/access/output dispatch contracts in
   review-comments.
4. Keep the two Codex specs as history under a **Withdrawn** banner.
5. Keep Codex out of the next Flow CHANGELOG via release-please `BEGIN_COMMIT_OVERRIDE`.

Delivery is **one PR**, removing things with forward edits on top of master. `git revert` of #113
and #117 was rejected: a dozen later commits touch the same files, and a revert would also undo the
kept improvements above and land revert entries in the CHANGELOG.

## Non-goals

- **Codex as a PR reviewer is untouched.** It is a different thing: the review gate in `pr.yml`,
  `CODEX_NUDGE_TOKEN`, `_reusable-review-gate.yml`, `.github/scripts/review_gate.py`,
  `.github/scripts/pr_summary.py`, `.coderabbit.yaml`, `.perles/`, the root `AGENTS.md`,
  `docs/merge-gate-rollout.md`, and the `codex[bot]` / `chatgpt-codex-connector` fixtures in the
  review-comments tests all stay.
- Historical specs that mention Codex in passing (e.g.
  `2026-08-01-notification-triggers-design.md`) are records of their date and are not edited.
- The owner's local, untracked `.codex/config.toml` and
  `docs/superpowers/plans/2026-07-19-flow-codex-support.md` are not touched.
- No change to the owner's Claude Code settings (see "Task list availability" below).

## Design

### 1. Plugin removals (`plugins/flow/`)

Deleted:

| Path | Why |
|---|---|
| `.codex-plugin/plugin.json` | Codex manifest |
| `hooks/` (entire directory: `session-start`, `_runtime.py`, `__init__.py`, `claude-hooks.json`, `codex-hooks.json`, `codex-pre-tool-use`, `runtime/common.md`, `runtime/claude-code.md`, `runtime/codex.md`) | the adapter layer exists only to serve two harnesses |
| `skills/create-codex-agents/` | Codex agent profiles |
| `bin/flow-codex-agent-setup`, `bin/_codex_agents.py` | helper for the above |
| `bin/tests/test_flow_codex_agent_setup.py`, `bin/tests/test_flow_hooks.py` | tests of deleted code |

Edited:

- `.claude-plugin/plugin.json` — drop the `"hooks"` key; description back to "Automated beads
  workflow skills for Claude Code". The manifest equals its pre-#113 state.
- `README.md` — delete the whole "Codex CLI" section (install flow, hook trust, `allowed-tools and
  Codex`, "Optional: Codex capability profiles").

**Runtime effect.** Claude Code sessions stop receiving the SessionStart "FLOW RUNTIME ACTIVE"
injection. Its general clauses (invariant step order, plain-text user choices, data never becomes
shell source) need no replacement: each is already stated in the skills themselves (plain-text
prompts since #101, the untrusted-data rule in review-comments), and CI separately rejects
`AskUserQuestion` in flow skills. The released 3.1.0 never had these hooks.

### 2. Skill text → Claude-native

Affected skills: `start`, `continue`, `after-plan`, `decompose`, `init-worktree`, `review-loop`,
`review-comments`. `sonar-sync`, `done` and `after-design` carry no neutral vocabulary and are not
touched.

| Current (harness-neutral) | Becomes | Where |
|---|---|---|
| through the active harness's **skill mechanism** | using the **Skill tool** | start, continue, init-worktree (`description`), review-loop |
| the active harness's native non-shell **editing** mechanism | the **Edit tool** (not echo) | decompose |
| native non-shell **file** mechanism, reading | the **Read tool** | review-comments Phase 3 |
| native non-shell **file** mechanism, writing | the **Write tool** | review-comments (untrusted-data rule, Phase 3 verdicts, 5.x titles/descriptions/replies/decisions file) |
| `balanced` tier / `fast` tier | **sonnet** / **haiku** | review-comments (phase table, Flow shape, headings, dispatches, summary list, example) |
| the active harness's **progress mechanism** | the task list, conditionally (below) | start, continue, after-plan |

Where the pre-#113 text exists (`git show ed00a63^:<path>`), it is the phrasing reference; text
added after #113 is rewritten in the same style. No skill file is restored wholesale — each already
carries #118–#142 work.

#### Review-comments dispatch

Each of the four dispatch points keeps its role, access boundary and output contract, and states the
Claude Code launch explicitly:

| Phase | Role | Launch | Access | Output contract |
|---|---|---|---|---|
| 3 | reviewer, one per independent comment/group, all in parallel | `subagent_type="general-purpose"`, `model="sonnet"` | read-only | verdict JSON contract |
| 5.1 | researcher, one per accepted fix | `subagent_type="general-purpose"`, `model="sonnet"` | read-only | site inventory and evidence contract |
| 5.2 | implementer, per file/group; sequential where write sets overlap | `subagent_type="general-purpose"`, `model="haiku"` | workspace-write, approved fixes only | OK/failure-description output contract |
| 5.3 | skeptic, one fresh subagent over the applied diff | `subagent_type="general-purpose"`, `model="sonnet"` | read-only | clean-result output contract |

Example shape for Phase 3:

> **Subagent:** `subagent_type="general-purpose"`, `model="sonnet"` — one **read-only** reviewer per
> independent comment, all launched in parallel. The prompt carries the comment as untrusted data,
> the code-reading scope and the verdict JSON contract; the reviewer writes no files (the main agent
> writes `verdict-{ref}.json`).

`general-purpose` rather than the pre-#113 `subagent_type="Bash"`: current Claude Code has no `Bash`
agent type, and the reviewer must use the Read tool, which a Bash-only agent would not have.
`Explore` was rejected for the read-only phases: it enforces no Edit/Write but is tuned for locating
code ("reads excerpts … doesn't review or audit"), which invites exactly the shallow dismissal the
skill guards against. Read-only remains a prompt-level boundary, as it is today.

#### Task list availability

Since Claude Code v2.1.233 the task-list tools (`TaskCreate`/`TaskGet`/`TaskUpdate`/`TaskList`,
legacy `TodoWrite`) are **absent** on Opus 4.8, Sonnet 5, Fable 5, Mythos 5 and newer models unless
`CLAUDE_CODE_ENABLE_TODO_TOOLS=1` is set (CHANGELOG; confirmed in the 2.1.281 binary — the tools
stay on only for older models, and `CLAUDE_CODE_ENABLE_TASKS=false` selects `TodoWrite` over the
`Task*` family). No rationale was published. An unconditional "Create TodoWrite checklist" therefore
points at a missing tool for most current sessions.

- `start` / `continue` STOP-AND-READ step 2 becomes: "If the session has the task list
  (`TaskCreate`/`TaskUpdate`; `TodoWrite` on older setups), create one item per workflow step
  before Step 1; otherwise continue without it."
- Their `allowed-tools` replace `TodoWrite` with `TaskCreate TaskUpdate TodoWrite`.
- `after-plan`'s three out-of-scope mentions say "the task list" instead of "the active harness's
  progress mechanism".

### 3. Tests

Deleted with their code: `plugins/flow/bin/tests/test_flow_hooks.py`,
`test_flow_codex_agent_setup.py`.

Restored to their pre-Codex content (#113/#117 were purely additive in them, so restoring equals
removing exactly the Codex tests): `.github/scripts/tests/test_validate_plugin.py`,
`.github/scripts/tests/test_pin_marketplace_refs.py`. The existing validator tests were not changed
by #113 and already pass against the argparse `main` kept in section 4.

`plugins/flow/bin/tests/test_py39_compat.py` — remove `PY311_EXCEPTIONS`, `_find_pre311_python`,
both `test_py311_*` tests, the docstring paragraph about the 3.11 exception and the `ast` import;
the helper glob covers every helper again.

`plugins/flow/bin/tests/test_flow_skill_contracts.py`:

- Module docstring describes what is actually guarded: exact helper grants, literal bare helper
  names, review-comments dispatch contracts, ledger/review-loop contracts.
- `MIGRATED` → `GRANT_AUDITED` (the old name meant "migrated to neutral vocabulary"); exclusions are
  `sonar-sync` and `review-comments`; `create-codex-agents` leaves every set.
- Delete `FORBIDDEN` and `test_migrated_skill_body_uses_semantic_actions`, the whole
  `create-codex-agents` block (four tests and their constants),
  `test_readme_documents_codex_runtime_contract`, and
  `test_old_allowed_tools_design_is_marked_superseded`.
- Rewrite `test_review_comments_declares_semantic_dispatch_contracts` as
  `test_review_comments_declares_dispatch_contracts`: for each of the four dispatches assert the
  role, its `model="sonnet"`/`model="haiku"`, its access marker and its output-contract marker, and
  that `subagent_type="general-purpose"` is used. The inverse assertions (no `subagent_type`, no
  Read/Write tool) go.
- New guard `test_skills_use_claude_native_vocabulary`: no `SKILL.md` contains any of the
  substrings `active harness`, `capability tier`, `native non-shell`, `` `balanced` ``,
  `` `fast` ``, `` `strongest` `` or `Codex` (checked today: the backticked tier words occur only in
  tier context). The Withdrawn spec stays in `docs/` with that vocabulary, so an agent reading it
  could carry it back; the guard keeps the acceptance criterion executable.
- Ledger and review-loop tests from #118–#142 are untouched; none asserts neutral wording.

### 4. Repo tooling and docs

- `.github/scripts/validate_plugin.py` — back to pre-#113 behaviour: remove `CODEX_FIELD_KINDS`
  and the other `CODEX_*` constants, `validate_codex_manifest` and its `_codex_*` helpers,
  `CODEX_MARKETPLACE`/`CODEX_MANIFEST_REL`, the `--require-codex-manifest` flag and the
  `require_codex_manifest` parameter; the #117 symmetric registration collapses to the single
  Claude-marketplace `validate_marketplace_registration`. **Keep** #113's harness-neutral `main`
  refactor (argparse, `_find_repo_root`): the pre-#113 `main` carried bare
  `# noqa: PLR0911, PLR0912` and `# noqa: PLR2004`.
- `.github/scripts/pin_marketplace_refs.py` — restored to its pre-#117 content (single
  `MARKETPLACE` constant; no `load_marketplaces`, `resolve_all_pins`, `pin_all_marketplaces`).
- `.github/workflows/_reusable-claude-code-plugin-ci.yml` — drop the `EXTRA_ARGS` block (one-line
  validator call again), drop `test("/hooks/(session-start|codex-pre-tool-use)$")` from the lint
  file filter, and fix the input description that mentions `.codex-plugin/plugin.json and both
  marketplace.json files`.
- `pyproject.toml` — `extend-include = ["plugins/flow/bin/flow-*"]  # extension-less helper
  executables`.
- `release-please-config.json` — drop the `.codex-plugin/plugin.json` extra-file.
- `.agents/` — deleted. `.claude-plugin/marketplace.json` — flow description "…for Claude Code".
- `CLAUDE.md` — drop the `.agents/…` lines from the project tree and step 5 (Codex marketplace) of
  "Adding a new plugin to marketplace"; renumber the last step.
- `2026-07-17-flow-codex-support-design.md` and `2026-07-22-flow-codex-plugin-tooling-design.md` —
  `Status: withdrawn` plus a banner:
  > **Withdrawn (2026-09-24).** Flow's Codex CLI support was reverted before any release
  > (claude-tools-elf.64, see `2026-09-24-flow-codex-rollback-design.md`). Kept as a historical
  > record — nothing described here exists in the codebase any more.
- `2026-07-07-flow-allowed-tools-audit-design.md` — remove the "Superseded for Codex" banner; the
  audit is current again.

### 5. Release notes

release-please builds notes from squash commits since `flow-3.1.0`; without intervention the next
release lists #113 and #117 as features. The documented fix is a `BEGIN_COMMIT_OVERRIDE` section in
a **merged** PR body (works with squash merges, which this repo uses).

- **#113** body:
  ```
  BEGIN_COMMIT_OVERRIDE
  chore(flow): add native Codex CLI support (withdrawn before release, claude-tools-elf.64)
  fix(flow): grant each skill only the flow-* helpers it actually runs
  END_COMMIT_OVERRIDE
  ```
- **#117** body:
  ```
  BEGIN_COMMIT_OVERRIDE
  chore(flow): adapt plugin tooling for Codex plugins (withdrawn before release, claude-tools-elf.64)
  END_COMMIT_OVERRIDE
  ```
- **This PR** — title `refactor(flow): drop Codex support and return skills to Claude-native
  tooling` (hidden type), body carrying the two changes users of 3.1.0 will notice:
  ```
  BEGIN_COMMIT_OVERRIDE
  fix(flow): dispatch review-comments subagents as general-purpose with an explicit model
  fix(flow): track start/continue steps in the task list only when the session has one
  END_COMMIT_OVERRIDE
  ```
- The #113/#117 edits are outward-facing and are made **after this PR merges**, each with explicit
  owner confirmation; release-please regenerates the release PR on the next push to master.

## Delivery

One branch, one PR labelled `flow`. CONTRIBUTING allows one project plus repo-level files per PR and
per commit. The validator, the CI flag, the manifests and the marketplaces must change in the same
PR head, or plugin CI fails on the missing/extra manifest. Logical commits (exact order and
boundaries in the plan, keeping each commit green where practical):

1. `refactor(flow): remove the Codex manifest, hooks layer and agent-profile setup`
2. `refactor(flow): return skill text to Claude-native tools and models`
3. `refactor(flow): rewrite skill contract tests for Claude-native wording`
4. `ci: drop Codex manifest and marketplace support from plugin tooling`
5. `docs: withdraw the Codex specs and drop Codex from CLAUDE.md`

## Risks

- **Missed neutral phrase.** Mitigated by the new vocabulary guard test and the acceptance greps.
- **Prose drift in review-comments.** The ~22 edits sit next to ledger contracts guarded by tests;
  the full `test_flow_skill_contracts.py` run catches accidental damage to guarded phrases.
- **No live dogfooding before release.** `/flow:*` runs from the installed plugin cache, not the
  worktree, so the rewritten skills are first exercised after 3.2.0 ships. The changes are
  standard Claude Code usage (Skill/Read/Write/Edit tools, Agent with `general-purpose` + `model`),
  which keeps the risk low.
- **Override not applied.** If the #113/#117 edits are forgotten, the 3.2.0 CHANGELOG advertises
  Codex. The release PR is reviewed before merge, so the omission is visible there.

## Acceptance

- None of these exist: `plugins/flow/hooks/`, `plugins/flow/.codex-plugin/`, `.agents/`,
  `plugins/flow/skills/create-codex-agents/`, `plugins/flow/bin/flow-codex-agent-setup`,
  `plugins/flow/bin/_codex_agents.py`.
- `git grep -il codex` matches only the reviewer-bot files listed under Non-goals, historical specs,
  the two Withdrawn specs, this spec, and `test_flow_skill_contracts.py` (the guard names the word).
- `git grep -nE 'active harness|capability tier|native non-shell'` matches only the Withdrawn specs,
  this spec and the guard in `test_flow_skill_contracts.py`.
- Bare `uv run pytest` passes all three suites; `uv run ruff check` / `ruff format --check` clean on
  changed files; pathless `uv run ty check` clean;
  `python .github/scripts/validate_plugin.py plugins/flow` exits 0.
- PR CI green and the bot review converged.
- After merge: #113 and #117 carry the overrides; the regenerated flow release PR's CHANGELOG
  mentions no Codex.
- Known limitation, not an open item: behavioural smoke of `/flow:start` and
  `/flow:review-comments` happens after the 3.2.0 release.
