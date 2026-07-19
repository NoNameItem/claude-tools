# Flow native-Codex compatibility smoke (manual protocol)

This is a **reproducible manual protocol**, not an automated test. It does not run in ordinary
pytest CI, it never runs unattended, and it never installs or modifies your real Codex profile.
It exists to verify the load-bearing runtime assumptions behind Flow's Codex adapter
(`plugins/flow/hooks/_runtime.py`, `plugins/flow/hooks/codex-pre-tool-use`,
`plugins/flow/hooks/session-start`, `plugins/flow/hooks/codex-hooks.json`,
`plugins/flow/skills/create-codex-agents/SKILL.md`) against a **real, native Codex CLI
install** — something no automated test in this repo can do, because there is no Codex CLI
runtime available in CI or in ordinary agent sandboxes.

Read this whole file before starting. Steps 3–8 below map one-to-one onto the design doc's
"Behavioral smoke tests" section
(`docs/superpowers/specs/2026-07-17-flow-codex-support-design.md`).

**Most important outcome of this protocol:** confirming that the `PreToolUse` hook's
`updatedInput` command rewrite works, and confirming that returning
`permissionDecision: "allow"` from that hook does **not** bypass Codex's sandbox or approval
policy. If it does, Step 4 below tells you exactly what to rip out before shipping.

## Non-goals / what this protocol is not

- Not a pytest suite. Nothing here is wired into `uv run pytest` or CI.
- Not something an agent should execute autonomously. Every step assumes a human operator with
  a working `codex` binary, watching Codex's own output at each gate.
- Not a way to install Flow's Codex support for real use — it builds a **throwaway** copy of
  the plugin in a **throwaway** project with a **throwaway** `CODEX_HOME`, and deletes all three
  afterward.

## Requirements

- **`codex-cli` version `0.144.6` or later.** This is the conservative minimum version at which
  the `updatedInput`/`permissionDecision` wire shape for `PreToolUse` was verified (see the
  design doc's "PreToolUse handler" section). Confirm before doing anything else:

  ```bash
  codex --version
  ```

  Abort the whole protocol if this reports an older version or if `codex` is not on `PATH`.

- A clean checkout of this repository at the commit you are validating (this smoke was authored
  against Task 1–6 of the Codex-support plan, base commit `48a6d41`).
- `git`, standard POSIX shell tools (`mktemp`, `cp`, `chmod`).
- A `bd` binary is **not** required for most of this protocol — Steps 3, 5, 6, 7, and 8 use fake
  `bd`/`gh`/`git` stand-ins (see Setup) precisely so nothing here can mutate or contact a real
  beads store, GitHub/GitLab remote, or the operator's real git identity.

## Hard constraints (apply to every step below)

- **Never inspect or alter the user's real project `.codex/config.toml`.** Every config edit in
  this protocol targets the throwaway `$CODEX_HOME` created in Setup, never
  `~/.codex/config.toml` or any project's committed `.codex/` directory.
  `flow-codex-agent-setup`/`flow:create-codex-agents` already refuse to read
  `.codex/config.toml` by design (see `plugins/flow/skills/create-codex-agents/SKILL.md`); this
  protocol must not work around that by reading it manually either.
- **Abort if another Flow plugin version remains active** in whatever Codex profile/session you
  are about to use — check `/hooks` and your plugin listing before Steps 3–7. The one place this
  is deliberately *not* the rule is Step 8, which exists specifically to test what happens when
  it's violated.
- **Never execute this protocol against your real `$CODEX_HOME`.** Always export a throwaway one
  first (Setup, item 4).
- Do not run this protocol unattended; every gate (`/hooks` trust prompt, approval prompts,
  confirmation prompts inside `flow:create-codex-agents`) requires you to read Codex's own output
  and respond.

## Setup: isolated local plugin, project, and `CODEX_HOME`

Perform this once per protocol run (repeat for a second Flow version only in Step 8).

1. **Require the minimum Codex CLI version** (see Requirements above) — `codex --version` must
   report `0.144.6` or later. Abort otherwise.

2. **Copy the current `plugins/flow` tree to a temporary plugin/marketplace location.** Do not
   point Codex at your working checkout directly — a temp copy guarantees nothing you do during
   the smoke (including Step 4's fake write-probe helper, added and removed only in the copy)
   touches the repository you are validating.

   ```bash
   SMOKE_ROOT="$(mktemp -d -t flow-codex-smoke)"
   cp -R "$(pwd)/plugins/flow" "$SMOKE_ROOT/plugins/flow"
   mkdir -p "$SMOKE_ROOT/.claude-plugin"
   cat > "$SMOKE_ROOT/.claude-plugin/marketplace.json" <<'JSON'
   {
     "name": "flow-codex-smoke",
     "owner": { "name": "flow-codex-smoke" },
     "metadata": {
       "description": "Throwaway marketplace for the Flow Codex compatibility smoke only.",
       "version": "0.0.0-smoke",
       "pluginRoot": "./plugins"
     },
     "plugins": [
       {
         "name": "flow",
         "source": { "source": "local", "path": "./plugins/flow" },
         "description": "Throwaway smoke copy of the Flow plugin."
       }
     ]
   }
   JSON
   ```

   Adapt the `source` shape above to whatever local-plugin-source syntax your installed Codex CLI
   build actually accepts for a filesystem path — `codex --version` and Codex's own
   `/plugin`/marketplace-add help output are the source of truth for the exact schema, not this
   file. The important invariant is that the marketplace/plugin entry resolves to
   `$SMOKE_ROOT/plugins/flow`, a copy, never `plugins/flow` in your real checkout.

3. **Install only that temporary version.** Add the throwaway marketplace and install `flow` from
   it, using whatever native Codex command performs the equivalent of Claude Code's
   `/plugin marketplace add` / `/plugin install`. Do not also have a non-smoke Flow version
   enabled in the same profile at this point (see the abort rule above; Step 8 revisits this
   deliberately).

4. **Use a temporary project and a temporary `CODEX_HOME`.**

   ```bash
   SMOKE_PROJECT="$(mktemp -d -t flow-codex-smoke-project)"
   git -C "$SMOKE_PROJECT" init -q
   export CODEX_HOME="$(mktemp -d -t flow-codex-smoke-home)"
   ```

   Run every `codex`/`codex exec` invocation below with this `CODEX_HOME` exported in the same
   shell, and `cd "$SMOKE_PROJECT"` first. If your Codex CLI build does not support relocating
   `CODEX_HOME`, note that limitation in your results log and fall back to a dedicated OS user or
   VM instead of your real profile — never run the rest of this protocol against your everyday
   `~/.codex`.

5. **Trust the hooks explicitly through `/hooks`.** Start a Codex session in `$SMOKE_PROJECT`
   with `CODEX_HOME` exported, and run:

   ```text
   /hooks
   ```

   Confirm both the `SessionStart` and `PreToolUse` hooks registered by the smoke copy of
   `plugins/flow/hooks/codex-hooks.json` are listed, and explicitly trust them. Codex requires
   this one-time step before either hook runs — do not skip it and do not assume a default-trust
   state.

6. Keep this session's transcript/output visible for the remaining steps — Steps 3–8 ask you to
   inspect exactly what Codex reports for each hook-modified tool call. The exact facility your
   Codex CLI build exposes for this (verbose/debug output, a `--json` event stream, or the
   session transcript file under `$CODEX_HOME`) may vary by build; use whichever one 0.144.6
   actually gives you, and record which one you used in your results log.

7. **Fakes for `bd`, `gh`, and `git`.** Everywhere Steps 3, 5, 6, and 7 could otherwise mutate or
   contact a real beads store or a real GitHub/GitLab remote, put fake executables ahead of the
   real ones on `PATH` inside `$SMOKE_PROJECT`:

   ```bash
   FAKE_BIN="$SMOKE_PROJECT/.smoke-fakes"
   mkdir -p "$FAKE_BIN"
   cat > "$FAKE_BIN/bd" <<'SH'
   #!/bin/sh
   echo '{"nodes":[],"edges":[]}'
   SH
   cat > "$FAKE_BIN/gh" <<'SH'
   #!/bin/sh
   echo '[]'
   SH
   cat > "$FAKE_BIN/git" <<'SH'
   #!/bin/sh
   case "$1" in
     branch) echo "smoke/fake-branch" ;;
     *) exit 0 ;;
   esac
   SH
   chmod +x "$FAKE_BIN/bd" "$FAKE_BIN/gh" "$FAKE_BIN/git"
   export PATH="$FAKE_BIN:$PATH"
   ```

   Confirm `which bd`, `which gh`, `which git` resolve to `$FAKE_BIN` before proceeding. This
   `PATH` prefix is set in your **own** shell before starting Codex — it is not the transient,
   per-tool-call `PATH` prologue the `PreToolUse` hook adds (that one you are about to observe,
   not create).

8. Tear-down for this setup lives at the end of this document (Cleanup) — read it now so you
   know what to remove once every step below is done.

---

## Step 3: helper resolution in every command shape

Verifies: `plugins/flow/hooks/codex-pre-tool-use` → `rewrite_pre_tool_use()` in
`plugins/flow/hooks/_runtime.py`.

In `$SMOKE_PROJECT`, with the smoke Codex session from Setup still running and hooks trusted,
have Codex run the five command shapes from the design doc's helper-resolution smoke, each as
its own `Bash`/shell tool call (this repo intentionally ships no separate smoke skill for this —
paste each command directly, or wrap all five in one ad hoc scratch prompt/skill you create only
for this session and never commit):

```sh
flow-sync pull
flow-review-collect 1 > metadata.json
bd graph --all --json | flow-task-tree
ACTOR="$(flow-actor)"
flow-link-doc task Git "$(git branch --show-current)"
```

Because of the Setup fakes, `bd`, `gh`, and `git` here resolve to the no-op/fixed-output fakes,
not real ones — none of these five calls can mutate real beads state or a real git identity.

For **each** of the five calls, inspect the `PreToolUse` hook's event output (per Setup item 6)
and verify all five properties from the design doc:

1. **One exact canonical prologue precedes each original command.** The prologue is generated by
   `canonical_prologue()` in `_runtime.py`:

   ```python
   f'export PATH={shlex.quote(str(plugin_root / "bin"))}:"$PATH"\n'
   ```

   i.e. literally `export PATH=<shell-quoted absolute path to the smoke copy's bin/>:"$PATH"\n`
   followed by the original command. Confirm the path in the prologue is the **smoke copy's**
   `bin/` directory (`$SMOKE_ROOT/plugins/flow/bin`), not your real checkout's.

2. **The original command bytes after the prologue are unchanged.** Diff the `updatedInput`
   command field's tail (everything after the prologue's trailing newline) byte-for-byte against
   what you typed. No helper name inside it should be rewritten to an absolute/skill-relative
   path.

3. **No process-wide `PATH` change survives the tool call.** After each of the five calls
   completes, run a plain `echo "$PATH"` as its own tool call and confirm it does **not** start
   with the smoke copy's `bin/` directory — the export only ever lives inside the rewritten
   command's own subshell, once, for that one call.

4. **A SessionStart-prefixed input is not double-prefixed.** Manually issue a sixth command that
   already begins with the exact canonical prologue string (copy it verbatim from one of the
   five `updatedInput` results above), e.g.:

   ```sh
   export PATH=<same-quoted-path>:"$PATH"
   flow-actor
   ```

   Confirm the hook's `updatedInput` for this call is **absent** (the hook returns `None` because
   `command.startswith(prologue)` is already true) — i.e. Codex runs your input unmodified, with
   no second prologue stacked on top.

5. **`|| echo`, `| head`, and `$(flow-actor)` receive the prologue before their first execution.**
   Run these three shapes and confirm the prologue is present in `updatedInput` for the whole
   compound command *before* Codex executes any part of it — not applied only if the first
   segment fails, and not skipped because the helper is inside a substitution or the right side
   of a pipe:

   ```sh
   flow-actor || echo "fallback"
   bd graph --all --json | flow-task-tree | head -5
   echo "actor is $(flow-actor)"
   ```

Record pass/fail for each of the five properties against each of the eight commands used in this
step (five from the brief + the three masked-failure shapes + the double-prefix probe).

---

## Step 4: prove `PreToolUse` allow does not bypass sandbox or approval

Verifies: the single most load-bearing safety claim in the design — that
`permissionDecision: "allow"` from the hook is a **PATH-prologue rewrite**, never an
authorization bypass.

1. Add a fake, non-shipped helper to the **smoke copy only** (never to your real checkout):

   ```bash
   cat > "$SMOKE_ROOT/plugins/flow/bin/flow-write-probe" <<'SH'
   #!/usr/bin/env python3
   import pathlib
   pathlib.Path("must-not-exist").touch()
   print("flow-write-probe: wrote must-not-exist")
   SH
   chmod +x "$SMOKE_ROOT/plugins/flow/bin/flow-write-probe"
   ```

   Restart the Codex session (a new plugin file requires a fresh session to be picked up).

2. From `$SMOKE_PROJECT`, with `CODEX_HOME` still exported to the throwaway home, start Codex
   with a temporary read-only sandbox and no approval prompt, and ask it to run the probe:

   ```bash
   codex --version
   codex exec --sandbox read-only --ask-for-approval never \
     "Run the supplied Flow smoke skill that invokes a fake flow-write-probe attempting to create ./must-not-exist."
   test ! -e must-not-exist
   ```

3. **Expected:**

   - `codex --version` reports `0.144.6` or later;
   - the `PreToolUse` hook still rewrites the command (same canonical-prologue check as Step 3);
   - the read-only sandbox denies the write attempt from `flow-write-probe` regardless of the
     hook's `permissionDecision: "allow"`;
   - `test ! -e must-not-exist` exits `0` — the file is absent.

4. **Explicit fallback instruction — do not skip this.** If the write succeeds, or if this Codex
   build otherwise treats the hook's `permissionDecision: "allow"` as bypassing the sandbox or
   approval policy, this smoke has failed the single load-bearing safety assumption of the
   `PreToolUse` resolver. In that case:

   - **remove the `PreToolUse` registration** from `plugins/flow/hooks/codex-hooks.json` before
     shipping this support to any real user;
   - support **only** the `SessionStart` prompt resolver (`render_session_context()` /
     `hooks/runtime/codex.md`'s `{{FLOW_PATH_EXPORT}}` instruction) until a safe
     `updatedInput`/`permissionDecision` wire shape is verified;
   - do not attempt to patch around the failure by weakening `flow-write-probe`, retrying with a
     different sandbox mode, or treating a single "lucky" pass as sufficient — this check exists
     precisely because a wrong answer here is a security regression, not a flaky test.

   Clean up `$SMOKE_ROOT/plugins/flow/bin/flow-write-probe` and any `must-not-exist` file
   regardless of outcome.

---

## Step 5: verify disabled-hook degradation

Verifies: Flow never claims transparent helper resolution when Codex's own hook machinery is not
actually active, and never papers over that gap with a `command not found` retry (which could
resume execution of an outer command that already partially mutated state with a missing
argument — see `hooks/runtime/codex.md`'s "do not retry a helper only after command-not-found"
rule).

Test each of the following **separately** (fresh `CODEX_HOME`/session per case is safest, so
failures don't compound):

1. **Untrusted plugin hooks.** Skip or explicitly decline the `/hooks` trust step from Setup
   item 5, then run one of the Step 3 command shapes (e.g. `flow-actor`).

   Expected: Codex reports the hook source as untrusted/inactive; the command runs with **no**
   PATH prologue rewrite (bare `flow-actor` either fails to resolve or falls through to whatever
   is already on `PATH`, unmodified). Nothing in the observed behavior implies transparent helper
   resolution.

2. **`[features] hooks = false`.** In the **throwaway** `$CODEX_HOME/config.toml` (never a real
   project's `.codex/config.toml`), set:

   ```toml
   [features]
   hooks = false
   ```

   Restart the Codex session and repeat a Step 3 command shape.

   Expected: Codex reports/skips both hooks as inactive; same no-transparent-resolution outcome
   as case 1.

3. **`allow_managed_hooks_only = true`.** In the same throwaway `config.toml`, instead set:

   ```toml
   allow_managed_hooks_only = true
   ```

   (adjust the exact key placement to whatever your Codex CLI build documents — the constraint
   under test is that a project/user-installed plugin hook, as opposed to an org-managed one, is
   excluded). Restart and repeat.

   Expected: same — Codex reports/skips the excluded hook source; no transparent resolution.

For **all three** cases, additionally confirm:

- Flow's own documentation (`plugins/flow/README.md`'s Codex CLI section) does not claim
  transparent bare-helper resolution unconditionally — it already documents this degradation
  path ("Flow loses its transparent bare-helper `PATH` resolution ... reports that its Codex hook
  setup is inactive"). This step is checking Codex's *actual* behavior matches that documented
  claim, not amending the documentation.
- No post-`command not found` retry recovers a masked or possibly-already-mutating command. If a
  bare `flow-*` call fails to resolve in any of the three cases, the correct, expected behavior is
  a clean failure/error surfaced to the user — not an automatic retry of the same command after
  observing `command not found`.

---

## Step 6: verify hidden `agent_type` routing and fallback

Verifies: `plugins/flow/skills/create-codex-agents/SKILL.md`,
`plugins/flow/bin/flow-codex-agent-setup`, `plugins/flow/bin/_codex_agents.py`, and the Codex
adapter's `spawn_agent` contract in `hooks/runtime/codex.md`.

### 6a. Profile setup across four temporary project shapes

For each of the four project shapes below, use a **fresh** temporary project directory
(`mktemp -d`, `git init`) with the fake `bd`/`gh`/`git` from Setup item 7 still ahead on `PATH`,
and drive `flow:create-codex-agents` (invoked in Codex as `$flow:create-codex-agents`):

1. **Fresh** — empty project, no `.codex/agents/` at all. Expect: all three tiers (`flow-fast`,
   `flow-balanced`, `flow-strongest`) classified `missing`; after supplying model/reasoning
   values, preview, and confirming `1`, all three are `created`.
2. **Partial** — pre-create one valid, Flow-compatible `flow-balanced.toml` (matching name and
   generated non-model contract) before running the skill. Expect: `flow-balanced` classified
   `compatible` and left untouched; `flow-fast`/`flow-strongest` still `missing` and creatable.
3. **Conflicting** — pre-create a `.toml` whose internal `name` is `flow-fast` but whose
   `developer_instructions` body differs from the generated template (or whose filename doesn't
   match `flow-fast` at all, per the file-name-can-lie design note). Expect: `flow-fast` reported
   as `conflict` with a reason; the other two tiers remain independently creatable; a
   `global_conflicts` entry, if the helper reports one, blocks **all** three tiers, not just the
   conflicting one.
4. **Linked worktree** — run the same flow from a `git worktree add`-created linked worktree of
   one of the above projects. Expect: the `inspect` result's `linked_worktree` field is `true`,
   and the skill shows the branch-local propagation warning before any write.

For all four, confirm the skill never reads or reports on `.codex/config.toml`, never stages,
commits, or touches `.gitignore`, and only writes after an explicit typed `1` confirmation
following a full preview.

### 6b. Dispatch each tier and inspect child metadata

Restart Codex (profile files only take effect in a new session) in a project with all three
profiles created, then have Codex dispatch each tier in turn using the exact contract from
`hooks/runtime/codex.md`:

```text
task_name: flow_fast_probe
agent_type: flow-fast
fork_turns: "none"
message: read-only researcher; return model/reasoning metadata only
```

Repeat with `task_name: flow_balanced_probe` / `agent_type: flow-balanced`, and
`task_name: flow_strongest_probe` / `agent_type: flow-strongest`.

**Verify child turn metadata, not response prose** — inspect whatever structured field Codex
exposes for the spawned child's actual model/reasoning-effort (session transcript, `--json`
event, or equivalent), and confirm it matches the model/reasoning you supplied for that tier in
6a. Do not accept the child's own textual claim about which model it is running as evidence.

### 6c. Fallback and override cases

Verify each of the following produces **exactly one** warning and **exactly one** retry with the
default/native agent, preserving the original role/access/output contract from the dispatch
message:

- **Missing profile** — dispatch `agent_type: flow-fast` in a project where no
  `flow-fast.toml` exists (or was removed after creation).
- **Invalid/unavailable model** — a profile whose `model` field is a syntactically valid but
  account-unavailable model ID.
- **Hidden-field rejection** — a Codex build/surface that rejects the `agent_type` field
  entirely (i.e. `spawn_agent` errors on an unrecognized field rather than silently ignoring it).
- **Parent `codex -m ...` override** — start the parent Codex session itself with an explicit
  `-m <model>` flag, then dispatch a tier. Expected: this is reported as an override (the parent
  model wins), not silently absorbed as if the profile had been applied normally.

For all four, confirm: exactly one warning is surfaced (not zero, not repeated retries), exactly
one retry occurs with the default agent (not an unbounded retry loop), and the role, access
boundary, and output contract from the original dispatch message are unchanged in the retry.

---

## Step 7: run the allowed-tools canary

Verifies: `plugins/flow/bin/tests/codex-smoke/allowed-tools-canary/SKILL.md` (this repo's
canary fixture) actually behaves as the design doc's compatibility gate, not merely as an
assumption about Codex ignoring `allowed-tools`.

1. Copy **only** `allowed-tools-canary/SKILL.md` from this directory into the **smoke copy's**
   skills tree, e.g. `$SMOKE_ROOT/plugins/flow/skills/allowed-tools-canary/SKILL.md`. Never copy
   it into your real checkout's `plugins/flow/skills/` — it must never become a shipped Flow
   command. Restart the Codex session so the new skill is discovered.

2. Invoke it (as `$allowed-tools-canary`, or whatever native syntax your Codex build uses for a
   plugin-provided skill) in the smoke project, with a fixture file present to read (e.g. a
   `smoke-fixture.txt` you drop in `$SMOKE_PROJECT`).

3. **Expected**, matching the design doc's Step 7 acceptance list:

   - the skill is discovered and runs despite declaring `allowed-tools: Read` — Codex does not
     silently refuse to load or invoke it;
   - the native progress-tracking mechanism (used for "track one progress step") remains
     available;
   - the native file-read mechanism remains available and is the one actually used to read the
     fixture file (not a shell `cat`/`read` substitute);
   - the shell mechanism used to run `flow-require-bd` remains available, and the `PreToolUse`
     hook still applies the canonical prologue to that call, exactly as verified in Step 3;
   - sandbox/approval policy still governs the `flow-require-bd` call the same way it would for
     any other shell call — the canary's `allowed-tools: Read` frontmatter neither grants nor
     removes any actual Codex-side sandbox/approval permission.

4. Remove the copied `allowed-tools-canary` skill from the smoke copy once this step is done —
   it must not remain installed for Step 8.

---

## Step 8: verify upgrade/version collision behavior

Verifies: the design doc's "exactly one active Flow plugin version per Codex session" rule, and
that a collision is treated as a **configuration failure**, never silently resolved.

1. With the Step 3–7 smoke copy (`flow`, version as shipped in `plugins/flow/.claude-plugin/plugin.json`)
   still installed and active in the current session, build a **second** temporary copy at a
   different path with a different marketplace entry name, e.g.:

   ```bash
   SMOKE_ROOT_2="$(mktemp -d -t flow-codex-smoke-2)"
   cp -R "$(pwd)/plugins/flow" "$SMOKE_ROOT_2/plugins/flow"
   # bump plugins/flow/.claude-plugin/plugin.json's "version" field in the copy, e.g. to
   # a "+smoke2" suffix, purely so the two copies are visually distinguishable in listings.
   ```

   Install/enable this second copy through the same throwaway marketplace mechanism as Setup
   item 3, **without ending the current Codex session** and without disabling the first copy.

2. Repeat one of the Step 3 command shapes (e.g. `flow-actor`) in this now-dual-version session,
   and inspect the hook event output.

3. **Expected:** the smoke detects two matching Flow `PreToolUse` hook sets registered at once.
   Because `canonical_prologue()` derives its exact string from each copy's own `plugin_root`,
   the two copies produce two *different* prologue strings for the same command — so you may
   observe either duplicate entries for `flow` in `/hooks`, two competing `updatedInput` rewrites
   racing (Codex does not guarantee a precedence order between them, per the design doc), or
   Codex-level rejection of the second matching plugin/hook set. Any of these observations
   confirms the collision; treat this state as a **configuration failure** to be reported and
   fixed, never as "whichever one happened to apply is fine."

4. Disable/remove the older version's plugin registration, **start a new Codex session**
   (restart is required — a live session does not re-resolve which hook set is active), and
   repeat the same command shape once more.

5. **Expected:** exactly one canonical prologue is now applied, matching the single remaining
   installed copy's `bin/` path.

6. Remove `$SMOKE_ROOT_2` and its marketplace/plugin registration once this step is done.

---

## Cleanup

After finishing every step you intend to run:

1. Remove the temporary plugin/marketplace registration(s) from the Codex profile under
   `$CODEX_HOME` (Setup item 3, and the second copy from Step 8 if you ran it).
2. Delete the throwaway directories:

   ```bash
   rm -rf "$SMOKE_ROOT" "$SMOKE_ROOT_2" "$SMOKE_PROJECT" "$CODEX_HOME"
   ```

3. Unset the environment overrides from this shell:

   ```bash
   unset CODEX_HOME
   ```

   and restore `PATH` to whatever it was before Setup item 7's fake-`bd`/`gh`/`git` prefix (a
   fresh shell is the simplest way to guarantee this).
4. Confirm your real project's `.codex/config.toml` (if any) was never opened or edited during
   this run — it should not appear anywhere in your shell history for this session except,
   possibly, in a `grep`/read-only check confirming it was left alone.
5. Record results (pass/fail per step, Codex CLI version used, and any deviations you had to make
   because of build-specific flag/behavior differences) wherever this project tracks smoke
   results — this file only defines the reproducible steps, not a running results log.
