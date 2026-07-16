# Flow Codex support — design

**Date:** 2026-07-17
**Status:** approved, pending implementation plan

## Context

The Flow plugin was authored for Claude Code. Codex already discovers its skills, but two
Claude-specific assumptions prevent reliable execution:

1. skill bodies name Claude Code tools and subagent parameters directly (`TodoWrite`, `Skill`,
   `Agent`, `subagent_type`, `haiku`, and `sonnet`);
2. skills invoke `flow-*` helpers as bare commands, relying on Claude Code adding the plugin's
   `bin/` directory to `PATH`, while Codex preserves the directory but does not add it to `PATH`.

The goal is behavioral parity between Claude Code and Codex. Harnesses may use different native
tools, but they must preserve the same workflow order, confirmation gates, role boundaries,
safety constraints, outputs, and completion conditions.

## Goals

- Keep one canonical set of Flow skills for both harnesses.
- Express workflows in harness-neutral, semantic language.
- Localize harness-specific tool and model choices in runtime adapters.
- Keep existing bare `flow-*` invocations and the established extensionless Python helpers under
  `plugins/flow/bin/`.
- Preserve current Claude Code behavior while making the same supported workflows executable in
  Codex.
- Make model cost/ability selection explicit where the harness supports it, without making model
  selection a correctness dependency.

## Non-goals

- Duplicating skills into Claude-specific and Codex-specific trees.
- Adding recurring `if Codex` / `if Claude Code` branches to skill bodies.
- Repackaging `bin/` as an importable Python package or restoring `.py` suffixes.
- Adding skill-local wrappers, symlinks, or relative `../../bin/flow-*` paths.
- Adding Flow's `bin/` directory to Codex's process-wide `PATH`.
- Precreating Claude Code custom agents.
- Implementing `flow:create-codex-agents` in this change.
- Porting or otherwise changing `flow:sonar-sync`. It receives no Codex-specific warning, guard,
  documentation marker, or adapter branch.

## Design principles

### One workflow, two mechanisms

A skill specifies what must happen. A runtime adapter specifies how the active harness performs
it. An adapter may change only the mechanism; it may not change:

- step ordering;
- user confirmation gates;
- read/write authority of a role;
- safety and untrusted-data boundaries;
- required output shape;
- success and completion criteria.

### Semantic instructions in skills

Canonical skill bodies use semantic actions instead of harness API names. For example:

| Claude-specific wording | Canonical wording |
|---|---|
| Create a `TodoWrite` checklist | Track these workflow steps with the harness progress mechanism |
| Use the `Skill` tool | Invoke the named skill through the harness skill mechanism |
| Launch an `Agent` with `model="sonnet"` | Dispatch a read-only reviewer at the balanced capability tier |
| Use `Read` / `Grep` / `Write` | Read, search, or write with the mapped native file tool |

The adapters own the exact tool names. Claude-specific `allowed-tools` frontmatter remains
Claude Code metadata; workflow behavior must not depend on Codex interpreting it.

### User choices are always plain text

Every harness asks for a user decision with a plain-text prompt and waits for an explicit reply.
Flow does not use structured choice dialogs or timeout-driven defaults in either harness.

## Architecture

### Plugin layout

Flow adds one Codex manifest and one shared hook bundle while retaining the existing Claude
manifest and skill tree:

```text
plugins/flow/
├── .claude-plugin/plugin.json
├── .codex-plugin/plugin.json
├── hooks/
│   ├── hooks.json
│   ├── session-start
│   └── runtime/
│       ├── common.md
│       ├── claude-code.md
│       └── codex.md
├── skills/
└── bin/
```

Both harnesses register the same `SessionStart` hook. The hook composes `common.md` with exactly
one harness adapter and emits the result as session context. It runs for startup, resume, and
context-resetting lifecycle events supported by the harness, including clear and compact.

The hook chooses the adapter in one centralized boundary. Codex exposes the Codex-specific
`PLUGIN_ROOT` and also exposes `CLAUDE_PLUGIN_ROOT` for compatibility; Claude Code exposes
`CLAUDE_PLUGIN_ROOT`. Therefore `PLUGIN_ROOT` selects the Codex adapter and its absence selects
the Claude Code adapter. No skill performs environment detection.

Codex requires users to review and trust a newly installed or changed plugin hook. Installation
documentation must mention this one-time step and the `/hooks` command. The design does not add a
second implicit-activation skill such as `using-flow`; the hook is the runtime instruction
delivery mechanism.

### Common runtime contract

`common.md` contains rules shared by both harnesses:

1. Treat skill steps, gates, role access, safety boundaries, output requirements, and completion
   conditions as invariant across harnesses.
2. Ask all user choices as plain text and wait for an explicit response.
3. For an action, prefer the native tool named by the active harness adapter.
4. If that tool is unavailable, use this fallback order:
   - an equivalent native tool;
   - a generic safe mechanism that preserves the skill contract;
   - stop and report the missing capability when parity cannot be preserved.
5. Do not turn data into shell or program source, weaken a required non-shell operation, or relax
   a security/data boundary defined by the active skill.
6. Dispatch subagents with an explicit role, capability tier, access boundary, execution mode,
   and output contract.

The common rule is intentionally general. Concrete rules for untrusted reviewer bodies, paths,
snippets, and reply text remain in `review-comments`, where that data boundary exists.

### Harness adapters

Each adapter is a concise translation table, not an alternate workflow. It maps semantic actions
to the current harness mechanisms for:

- reading, searching, editing, and writing files;
- running shell commands;
- invoking another skill;
- tracking progress;
- dispatching a subagent;
- selecting a model/capability tier where supported;
- resolving bare Flow helpers.

The skill requests an action in generic terms and directs the agent to prefer the tool named in
the active adapter. Tool renames or harness API changes therefore require an adapter edit, not a
rewrite of every skill.

## Flow helper resolution

Skills continue to invoke helpers by their stable bare names:

```sh
bd graph --all --json | flow-task-tree
flow-sync pull
```

Claude Code continues to resolve those names through the plugin `bin/` path it provides.

For Codex, the SessionStart hook renders the installed plugin's actual absolute `bin/` path into
the adapter context. The adapter instructs Codex that every bare command matching Flow's shipped
`flow-*` helpers must be executed from that directory, preserving its arguments, stdin/stdout,
pipes, and exit status. Conceptually:

```text
flow-task-tree ...  ->  <resolved-plugin-root>/bin/flow-task-tree ...
```

This is an invocation rule, not a `PATH` mutation. It avoids wrappers, symlinks, skill-relative
paths, assumptions about the current working directory, and assumptions about the plugin cache
location.

## Subagent capability routing

### Shared capability reference

Skills select a capability tier from the nature of the task, not the amount of output or the
number of files:

| Tier | Task references |
|---|---|
| `fast` | Bounded, repeatable work; summarizing test or log output; locating a targeted fact; applying an already approved mechanical edit |
| `balanced` | Code-grounded review; tracing related definitions or sibling sites; triaging an ambiguous defect; assessing or challenging a review comment |
| `strongest` | Open-ended architecture; subtle authorization, concurrency, state, or security reasoning; escalation after a balanced agent is genuinely blocked or inconclusive |

Do not select `strongest` merely because a task is important, verbose, or spans many files.

Every dispatch also declares:

- **role:** researcher, reviewer, implementer, skeptic, or another narrow responsibility;
- **access:** read-only or workspace-write;
- **execution:** foreground/background and parallel/sequential requirements;
- **output contract:** exact expected structure and completion signal.

### Claude Code adapter

Claude Code supports selecting a model at dispatch time, so no custom agents are needed for cost
routing:

| Capability tier | Claude model family |
|---|---|
| `fast` | `haiku` |
| `balanced` | `sonnet` |
| `strongest` | `opus` |

The adapter invokes Claude's native subagent mechanism with the selected model and the role
contract from the skill. Precreated plugin agents are deferred unless Flow later needs hard native
tool restrictions or begins reusing the same role definitions across several skills.

### Codex adapter

Prompt text cannot reliably select a Codex model or prove which model handled a subagent. Flow
therefore treats model routing as an optimization, not a correctness requirement.

The Codex adapter dispatches a native subagent with the role, capability tier, access boundary,
and output contract in its prompt. Without project custom agents, Codex uses its available native
or default routing and the workflow continues. Flow does not name an unverified profile, require a
profile to exist, or stop when cost routing is unavailable.

### Optional future Codex agent setup

A future `flow:create-codex-agents` skill may install Flow-owned templates into the current
project's `.codex/agents/` directory. It is explicitly optional:

- Flow remains functional without it;
- its purpose is to avoid spending expensive models on cheap tasks and make routing more
  predictable;
- it creates only missing profiles and never overwrites user-owned files;
- project files remain editable so users can change models and reasoning effort;
- after creating profiles, it asks the user to restart Codex;
- SessionStart never creates or modifies agent profiles automatically;
- installation documentation may recommend invoking it after plugin installation for users who
  want cost-aware routing.

The concrete profile set and TOML templates are deferred to that skill's own design and
implementation. This Codex-only convenience does not justify precreating Claude agents: Claude
already supports explicit per-dispatch model selection.

## `review-comments` migration

`review-comments` is the only supported Flow workflow that currently depends heavily on explicit
subagent model selection. Its workflow and dispatch points remain unchanged, but the dispatch
descriptions become semantic:

| Phase | Role | Tier | Access | Purpose |
|---|---|---|---|---|
| 3 | reviewer | `balanced` | read-only | Read code and return a code-backed verdict for each review comment |
| 5.1 | researcher | `balanced` | read-only | Find and verify sibling sites sharing the accepted defect class |
| 5.2 | implementer | `fast` | workspace-write | Apply the already approved, bounded fixes |
| 5.3 | skeptic | `balanced` | read-only | Adversarially review the applied diff before push |

`strongest` is reserved for explicit escalation when balanced analysis is blocked or the issue is
genuinely architecture-, security-, concurrency-, or state-heavy. Existing parallel/sequential
requirements, verdict JSON, untrusted-data handling, fix-the-class behavior, user gates, formatter
and linter handling, commit/push gate, and reply semantics remain unchanged.

## Other skill migrations

The remaining supported skills need only mechanical vocabulary changes:

- `start` and `continue`: replace `TodoWrite` and `Skill tool` wording with semantic progress and
  skill-invocation instructions;
- `review-loop`: invoke `flow:review-comments` through the semantic skill mechanism;
- other skills: replace any body-level Claude tool names with the corresponding semantic action;
- retain Claude `allowed-tools` frontmatter, updating grants only when the canonical workflow's
  actual command set changes.

`sonar-sync` is left exactly as it is. Its current subagent behavior is neither migrated nor
annotated by this work.

## Alternatives considered

### Separate skill sets or harness branches

Rejected because two workflow copies would drift, while scattered environment branches would
make every future skill edit a cross-harness maintenance task.

### Skill-local wrappers or symlinks

Rejected because wrappers duplicate trivial plumbing across skills, and symlinks introduce
packaging and platform assumptions. Both obscure that helpers are shared plugin-level utilities.

### Relative paths such as `../../bin/flow-*`

Rejected because they expose plugin layout in every workflow and depend on how the harness
resolves a skill's working directory.

### Repackage helpers as a Python package

Rejected because Flow already has a tested extensionless executable convention and callers need
commands, not importable library APIs. Repackaging is unrelated to harness parity.

### Add a broad `using-flow` skill

Rejected because implicit skill activation is less direct than session runtime context and still
does not solve helper resolution for every Flow skill. SessionStart is the single adapter entry
point.

### Precreate custom agents in both harnesses

Rejected for the current scope. Claude can select its model directly. Codex project agents can be
an optional cost optimization later, but making them mandatory would add installation state to
workflow correctness.

## Verification

### Hook and adapter tests

- Simulate Claude Code with `CLAUDE_PLUGIN_ROOT` only and verify the hook emits `common.md` plus
  `claude-code.md` exactly once.
- Simulate Codex with both `PLUGIN_ROOT` and `CLAUDE_PLUGIN_ROOT` and verify it selects `codex.md`.
- Verify the Codex output contains the resolved absolute `bin/` path and never a cache-relative or
  working-directory-relative path.
- Verify startup, resume, clear, and compact lifecycle matchers inject the runtime contract.
- Validate both Claude and Codex hook output formats.

### Static skill checks

For migrated skills, scan bodies for direct harness vocabulary such as `TodoWrite`, `Skill tool`,
`subagent_type`, and concrete model names. Claude-only frontmatter and the deliberately untouched
`sonar-sync` skill are excluded from this check.

### Behavioral smoke tests

- Install the plugin in Codex, trust its hook, and verify skill discovery.
- Run representative helper pipelines from `start` / `continue` and a direct helper call from an
  `after-*` skill; confirm Codex resolves the installed helper without a `PATH` change.
- Exercise the four `review-comments` dispatch roles and verify their role, tier, access, and output
  contracts survive adapter translation.
- Run the same representative flows in Claude Code and verify existing tool selection and helper
  resolution remain unchanged.

### Parity acceptance criteria

For every migrated workflow:

- step order and confirmation gates match between harnesses;
- subagent roles and read/write boundaries match;
- output and completion semantics match;
- bare `flow-*` commands execute correctly;
- common skill bodies contain no harness branches;
- no wrappers, symlinks, duplicated skills, or process-wide `PATH` mutations are introduced.

## Documentation impact

Flow's README and installation guidance must explain:

- Claude Code and Codex are supported by the same skill set;
- Codex users must trust the plugin SessionStart hook;
- helpers remain bare commands in skill prose but are resolved through the runtime adapter;
- custom Codex agents are not required;
- if `flow:create-codex-agents` is implemented later, it is an optional per-project cost-routing
  setup followed by a Codex restart.
