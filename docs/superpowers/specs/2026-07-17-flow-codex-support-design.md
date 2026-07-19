# Flow Codex support — design

**Date:** 2026-07-17
**Updated:** 2026-07-19
**Status:** revised, awaiting user review

## Context

The Flow plugin was authored for Claude Code. Codex already discovers its skills, but two
Claude-specific assumptions prevent reliable execution:

1. skill bodies name Claude Code tools and subagent parameters directly (`TodoWrite`, `Skill`,
   `Agent`, `subagent_type`, `haiku`, and `sonnet`);
2. skills invoke `flow-*` helpers as bare commands, relying on Claude Code adding the plugin's
   `bin/` directory to `PATH`, while Codex preserves the directory but does not add it to the
   environment of model-generated shell calls.

Codex custom-agent files can select a model, but reliable routing requires the native
`spawn_agent` runtime's `agent_type` field. In Codex CLI 0.144.6 that field is accepted by the
runtime even though it is omitted from the model-visible tool schema. Flow must therefore provide
an exact dispatch contract and retain a default-agent fallback for other Codex surfaces.

The goal is behavioral parity between Claude Code and Codex. Harnesses may use different native
tools, but they must preserve the same workflow order, confirmation gates, role boundaries,
safety constraints, outputs, and completion conditions.

## Goals

- Keep one canonical set of Flow skills for both harnesses.
- Keep exactly one physical `SKILL.md` for every Flow skill; do not add harness wrappers.
- Express workflows in harness-neutral, semantic language.
- Localize harness-specific tool and model choices in runtime adapters.
- Treat the native local Codex CLI as the primary Codex acceptance surface; admit IDE/Desktop
  support only when they expose the same local hook and subagent contracts.
- Keep existing bare `flow-*` invocations and the established extensionless Python helpers under
  `plugins/flow/bin/`.
- Preserve current Claude Code behavior while making the same supported workflows executable in
  Codex.
- Make model cost/ability selection explicit where the harness supports it, without making model
  selection a correctness dependency.
- Add `flow:create-codex-agents` as an optional, project-scoped setup skill in this change.

## Non-goals

- Duplicating skills into Claude-specific and Codex-specific trees.
- Adding recurring `if Codex` / `if Claude Code` branches to skill bodies.
- Repackaging `bin/` as an importable Python package or restoring `.py` suffixes.
- Adding skill-local wrappers, symlinks, or relative `../../bin/flow-*` paths.
- Adding Flow's `bin/` directory to Codex's process-wide `PATH`.
- Precreating Claude Code custom agents.
- Installing or modifying Codex custom agents automatically from `SessionStart`.
- Making Codex custom agents a prerequisite for any Flow workflow.
- Hard-coding model IDs that may not be available to the user's Codex account.
- Supporting hosted Work mode, which does not load project-local shell hooks and agents through
  the same native runtime.
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

The adapters own the exact tool names. Claude-specific `allowed-tools` frontmatter remains in the
single shared file as Claude Code metadata. Codex CLI currently ignores it rather than treating
omitted tools as denied, but Flow does not rely on that remaining true: a Codex compatibility
canary must verify that a shared skill with `allowed-tools` still discovers and can use its mapped
Codex tools.

For every migrated skill, static checks cross-reference real command recipes against Claude Code
frontmatter: any no-argument invocation requires the bare grant, and any argument-bearing
invocation requires the `:*` grant. Inline quick references and examples are checked as
model-visible command sources, not dismissed as prose.

The deliberately untouched `sonar-sync` remains an explicit exception: it currently has bare
helper recipes but only `:*` grants. This design neither fixes nor claims frontmatter accuracy for
that skill.

### User choices are always plain text

Every harness asks for a user decision with a plain-text prompt and waits for an explicit reply.
Flow does not use structured choice dialogs or timeout-driven defaults in either harness.

## Architecture

### Plugin layout

Flow adds one Codex manifest and harness-specific hook wiring while retaining the existing Claude
manifest and the single shared skill tree:

```text
plugins/flow/
├── .claude-plugin/plugin.json
├── .codex-plugin/plugin.json
├── hooks/
│   ├── claude-hooks.json
│   ├── codex-hooks.json
│   ├── session-start
│   ├── codex-pre-tool-use
│   └── runtime/
│       ├── common.md
│       ├── claude-code.md
│       └── codex.md
├── skills/
│   └── create-codex-agents/
│       └── SKILL.md
└── bin/
```

Both harnesses register the same `SessionStart` handler. The Codex manifest explicitly selects
`codex-hooks.json`; the Claude manifest selects `claude-hooks.json`. Both files register
`SessionStart`, while only the Codex file registers `PreToolUse`. This is harness wiring, not a
second workflow or skill implementation.

`SessionStart` composes `common.md` with exactly one harness adapter and emits the result as
session context. It runs for startup, resume, and context-resetting lifecycle events supported by
the harness, including clear and compact.

The hook chooses the adapter in one centralized boundary. Codex exposes the Codex-specific
`PLUGIN_ROOT` and also exposes `CLAUDE_PLUGIN_ROOT` for compatibility; Claude Code exposes
`CLAUDE_PLUGIN_ROOT`. Therefore `PLUGIN_ROOT` selects the Codex adapter and its absence selects
the Claude Code adapter. No skill performs environment detection.

Codex requires users to review and trust newly installed or changed plugin hooks. Installation
documentation must mention this one-time step, the `/hooks` command, and the degraded behavior
when hooks are disabled or filtered by `allow_managed_hooks_only`. The design does not add a
second implicit-activation skill such as `using-flow`; the hooks are the runtime adapter
mechanism.

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

An audit of canonical fenced recipes found 52 real helper calls in four shell shapes:

| Shape | Count | Example |
|---|---:|---|
| Standalone helper command | 30 | `flow-sync pull` |
| Helper is the top-level command in a compound command, redirect, or with a nested argument command | 7 | `flow-review-collect ... > metadata.json` |
| Another command pipes into the helper | 7 | `bd graph --json | flow-task-tree` |
| Helper is nested in substitution or assignment | 8 | `bd update ... "$(flow-actor)"` |

The second row includes the two `flow-link-doc ... "$(git ...)"` calls: the helper is top-level,
but the shell evaluates a nested command while preparing its arguments. With a narrower category
that excludes those two hybrids, the same inventory is `32 / 5 / 7 / 8`.

There are also model-visible inline quick references and examples. Rewriting individual
invocations in prompt text is therefore too fragile, and moving `bd`, `git`, or `head` calls into
helpers solely for path resolution would mix workflow orchestration into otherwise focused
utilities.

### Primary resolver: Codex-only `PreToolUse`

The Codex `PreToolUse` handler matches shell calls as `Bash` and checks their command source for
an exact literal name from the plugin's generated list of shipped `flow-*` executables. It does
not build or execute a shell parser: a conservative false positive only adds a PATH entry, while
static checks forbid canonical skills from constructing helper names dynamically. Calls with no
known literal Flow helper remain untouched.

For a matching call, the handler obtains the installed plugin root from the hook environment,
shell-quotes `<PLUGIN_ROOT>/bin`, and prepends this statement to the same shell source:

```sh
export PATH='<resolved-plugin-root>/bin':"$PATH"
```

It then executes the original tool input unchanged. The export and the command must remain in the
same shell call; a separate export does not persist into later Codex shell calls, and a
single-command assignment before the left side of a pipeline does not affect the right side.
This mechanically covers pipelines, substitutions, redirects, and compound commands without
parsing or rewriting their individual helper invocations.

The handler must:

- preserve the original command byte-for-byte after the generated prologue;
- update the command field used by the active Codex shell tool without changing unrelated input;
- define one canonical prologue string and be idempotent only when the tool input already starts
  with that exact prologue; do not inspect the hook process's `$PATH` or use a path substring test;
- shell-quote the resolved path rather than interpolate it as source;
- return Codex's required `updatedInput` and hook allow decision;
- fail open on handler failure by preserving the original tool input and reporting the failure;
- never claim to replace the normal sandbox or user-approval boundary.

The current Codex manual documents `PreToolUse` rewriting but does not document the
`updatedInput`/allow wire shape in the stable common-output section. Implementation therefore has
a conservative minimum version of Codex CLI 0.144.6, where this shape was verified, plus an
integration test proving that a rewrite does not bypass a command that the sandbox or approval
policy would otherwise reject. If that test fails, the mechanical resolver is not shippable and
the prompt mechanism becomes the only supported resolver.

The prologue temporarily gives this plugin version's `bin` directory PATH priority only for a
shell call containing a known Flow helper. That deliberately selects the plugin-owned helper over
a user executable with the same reserved name. It does not mutate Codex's process-wide PATH or
persist across calls.

Codex launches multiple matching hooks concurrently and does not provide a safe precedence
contract for competing `updatedInput` rewrites. Flow therefore supports exactly one active Flow
plugin version per Codex session. Installation and upgrade smoke tests verify that the plugin
manager deactivates the old version; documentation treats simultaneous Flow installations as a
configuration error instead of guessing which helper version wins.

Flow's existing command recipes are POSIX shell workflows. Native Windows command rewriting is
outside this change; documentation must not imply Windows support until the skills and helper
entrypoints themselves have a Windows execution contract.

### Fallback resolver: `SessionStart` instruction

The Codex adapter also receives the resolved, shell-quoted `bin` path and this redundant safety
rule:

```text
While executing a Flow skill, prepend the generated Flow PATH export to every
shell tool call in the same shell source. Do not rewrite individual flow-*
invocations and do not run the export as a separate tool call.
```

When `PreToolUse` is active, its idempotence check leaves the already-prefixed command unchanged.
When rewrite support is unavailable but `SessionStart` still runs, the prompt rule preserves
helper resolution. This is safer than retrying after `command not found`: a missing helper inside
`$(...)` can otherwise leave an outer mutating command running with an empty argument.

If all plugin hooks are disabled, untrusted, or excluded by `allow_managed_hooks_only`, neither
the mechanical resolver nor the adapter prompt is available. Flow must report that its Codex hook
setup is inactive; it cannot claim transparent bare-helper support in that state.

Current Flow subagents do not invoke any `flow-*` helper: all helper calls remain in the parent
workflow. No `SubagentStart` PATH injection is required in this change. If a future Flow subagent
is explicitly assigned helper execution, its dispatch prompt or `SubagentStart` context must
receive the same fallback contract.

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

Codex CLI 0.144.6's native runtime accepts `agent_type`, `model`, and `reasoning_effort` on
`spawn_agent`, although the model-visible schema in that release omits those fields. A live probe
selected a temporary custom agent and failed on that profile's deliberately invalid model,
proving that `agent_type` applies the profile's `model`.

Flow defines mappings for three optional project-scoped capability profiles:

| Capability tier | Codex `agent_type` |
|---|---|
| `fast` | `flow-fast` |
| `balanced` | `flow-balanced` |
| `strongest` | `flow-strongest` |

The Codex adapter gives the agent an exact dispatch contract rather than merely mentioning the
profile name:

```text
Call spawn_agent with:
- task_name: a unique narrow task name;
- agent_type: the mapped Flow profile, even when this field is omitted from
  the advertised schema;
- message: the role, task, access boundary, execution mode, and output
  contract requested by the Flow skill;
- fork_turns: "none".
```

`task_name` remains mandatory alongside `agent_type`. `fork_turns: "none"` avoids the current
full-history-fork restriction on agent/model overrides. The profile selects the model and
reasoning effort; it does not replace the role-specific dispatch prompt.

Profiles are not a security boundary. Flow templates do not grant credentials or broaden tools,
and the workflow continues to express read-only/workspace-write access in the dispatch contract.
Parent runtime sandbox, approval, MCP, and `-m` overrides may be inherited by the child and take
precedence over profile defaults.

Model routing remains an optimization:

- if the profile is missing, the surface rejects hidden fields, or the profile's model is
  unavailable to the account, retry once with a native/default agent and the same message;
- tell the user that cost routing degraded, but do not fail the Flow workflow;
- never weaken the role's access boundary during fallback;
- do not infer successful model selection from the child response; integration tests inspect the
  child turn metadata or deliberately exercise an invalid model.

An explicit parent `codex -m ...` runtime override can replace the model from the selected child
profile. Documentation must warn that users who want profile-based model routing should select
their normal parent model through config rather than a per-run `-m` override. Model IDs are also
account-specific: a syntactically valid ID may still be rejected for the current ChatGPT account.

### `flow:create-codex-agents`

This change adds one shared physical skill at
`skills/create-codex-agents/SKILL.md`. It is a Codex setup convenience, not an activation
requirement. Any harness capable of safely editing project files may run it; the generated files
affect only Codex.

The skill targets the current Git project's `.codex/agents/` directory and:

1. resolves and displays the exact project root and target directory;
2. scans every existing `.toml` file and parses its `name` field, because `name`, not the
   filename, is the profile identity;
3. classifies each required profile as missing, already Flow-compatible, or conflicting;
4. asks for the exact model ID and reasoning effort for each missing profile instead of
   hard-coding account-dependent model IDs;
5. previews all files and asks for explicit confirmation before writing;
6. creates only missing, non-conflicting files with an exclusive-create operation;
7. refuses symlinks in any target path component or candidate file and verifies every candidate
   remains beneath the displayed project root;
8. never reads unrelated `.codex` state, overwrites, renames, or edits an existing profile;
9. reports partial success precisely and asks the user to restart Codex after any creation.

An existing required `name` is Flow-compatible only when its non-model contract matches the
generated tier description and developer instructions; users may freely change its `model` and
`model_reasoning_effort`. A duplicate required name, a required filename containing a different
name, an unreadable/ambiguous TOML file, or a matching name with a different behavioral contract
is a conflict. Conflicts block only that profile, but all conflicts are shown before the user
decides whether to create independently safe missing profiles.

The three templates share minimal capability-neutral instructions:

```toml
developer_instructions = """
Follow the role, task, access boundary, execution mode, and output contract
supplied by the parent Flow workflow. Do not broaden the task or perform
unrelated work. Return only the requested result.
"""
```

Each file also contains its matching `name`, a tier-specific `description`, the user-selected
`model`, and `model_reasoning_effort`. The skill validates TOML syntax and non-empty required
fields before writing. It does not edit `.gitignore`, stage files, commit them, or decide whether
the project should share account-specific model choices. In a linked worktree it writes to that
worktree's project root and warns that the files are branch-local until the user chooses how to
propagate them. It never runs `git add .codex` or scans `.codex/config.toml`, which can contain
machine-local credentials.

Flow remains fully functional when the skill has never run, when only some profiles exist, after
the user edits generated files, or when the active Codex surface cannot select `agent_type`.
Session hooks never create or repair profiles automatically.

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
- `create-codex-agents`: add the optional project-profile setup described above as one shared
  physical skill;
- other skills: replace any body-level Claude tool names with the corresponding semantic action;
- retain Claude `allowed-tools` frontmatter, audit bare and argument-bearing command forms, and
  update grants only when the canonical workflow's actual command set changes.

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

### Prompt-only helper path rewriting

Rejected as the primary resolver because the 52 canonical calls include pipelines,
substitutions, redirects, and compound commands, while inline examples can teach the model stale
forms. A SessionStart PATH prologue remains a redundant safety mechanism, not the main resolver.

### Move upstream commands inside helpers

Rejected as a path-resolution strategy. Making `flow-task-tree` or `flow-task-card` own `bd`
queries would couple presentation helpers to workflow policy, duplicate argument and error
handling, and still leave substitutions and other helpers unresolved. Such API changes require
their own behavior-driven reason.

### Repackage helpers as a Python package

Rejected because Flow already has a tested extensionless executable convention and callers need
commands, not importable library APIs. Repackaging is unrelated to harness parity.

### Add a broad `using-flow` skill

Rejected because implicit skill activation is less direct than session runtime context and still
does not solve helper resolution for every Flow skill. The harness-specific hook bundle is the
single runtime-adapter boundary.

### Precreate custom agents in both harnesses

Rejected. Claude can select its model directly. Codex receives three optional project profiles
through an explicit setup skill, but making either harness's generated agents mandatory would add
installation state to workflow correctness.

### Pass a model directly without named Codex profiles

Rejected as the canonical Codex mapping. The native runtime currently accepts a hidden `model`
field, but named profiles keep model IDs and reasoning effort in user-editable project
configuration and keep the shared skill vocabulary at the stable `fast` / `balanced` /
`strongest` tiers. Direct model dispatch remains runtime-specific and would duplicate profile
configuration in prompt context.

## Verification

### Hook and adapter tests

- Simulate Claude Code with `CLAUDE_PLUGIN_ROOT` only and verify the hook emits `common.md` plus
  `claude-code.md` exactly once.
- Simulate Codex with both `PLUGIN_ROOT` and `CLAUDE_PLUGIN_ROOT` and verify it selects `codex.md`.
- Verify only the Codex hook config registers `PreToolUse`.
- Validate both manifests and confirm the packaged plugin contains both hook configs, handlers,
  runtime fragments, the new skill, and executable helpers at the same release version.
- Verify the Codex context contains the resolved, shell-quoted absolute `bin/` path and never a
  cache-relative or working-directory-relative path.
- Keep each model-visible hook output below Codex's approximate 2,500-token per-message limit.
- Verify startup, resume, clear, and compact lifecycle matchers inject the runtime contract.
- Validate both Claude and Codex hook output formats.
- Feed the `PreToolUse` handler standalone, pipeline, redirect, substitution, and compound command
  shapes and verify that the original command remains unchanged after one idempotent PATH
  prologue.
- Verify a non-Flow shell call remains byte-for-byte untouched and every literal shipped helper
  name triggers the resolver in all four audited shapes.
- Cover plugin paths containing spaces, quotes, shell metacharacters, and non-ASCII characters.
- Verify handler timeout, malformed input, missing `PLUGIN_ROOT`, and unsupported rewrite output
  fail open with useful diagnostics.
- In a real minimum-version Codex CLI, verify the rewritten command still obeys sandbox denial and
  approval requirements. A hook allow decision must not become an authorization bypass.
- Verify a SessionStart-prefixed Flow command is not double-prefixed by `PreToolUse`.
- Verify sessions with rewrite support disabled but SessionStart enabled use the prompt prologue.
- Exercise masked failures from `|| echo`, `| head`, and `$(flow-actor)` and prove the prompt
  prologue is present before the first outer command; never rely on a post-failure retry.
- Verify fully untrusted/disabled and `allow_managed_hooks_only` sessions report inactive Flow
  hook setup rather than claiming transparent helper resolution.
- Verify upgrade leaves one active Flow hook set; treat simultaneous version rewrites as a
  configuration failure.

### Static skill checks

For migrated skills, scan bodies for direct harness vocabulary such as `TodoWrite`, `Skill tool`,
`subagent_type`, and concrete model names. Claude-only frontmatter and the deliberately untouched
`sonar-sync` skill are excluded from this check. The purpose-built `create-codex-agents` skill may
name Codex configuration concepts, but it still must not hard-code harness tool names or model IDs.

Validate that:

- every skill still has exactly one physical `SKILL.md`;
- `allowed-tools` does not prevent Codex discovery and use of mapped tools;
- in migrated skills, Claude grants cover every bare and argument-bearing helper form actually
  shown in recipes, quick references, and examples; `sonar-sync` remains the named exception;
- no helper command was rewritten to an absolute or skill-relative path;
- every executable shipped under `bin/` uses the reserved `flow-*` name prefix;
- canonical commands never construct a helper name dynamically, so the hook's literal-name
  detector remains complete.

### Custom-agent setup tests

- In an empty project, preview and create exactly `flow-fast`, `flow-balanced`, and
  `flow-strongest` with user-selected model and reasoning values.
- Parse existing agents by TOML `name`, including a matching name in an unrelated filename.
- Skip compatible profiles, stop on conflicts, and create only independently safe missing files.
- Simulate a concurrent file creation between preview and write and verify exclusive creation
  preserves the other writer's file.
- Reject malformed TOML, empty required values, duplicate profile names, and unsupported reasoning
  effort before writing.
- Reject symlinked `.codex`, `.codex/agents`, and candidate files, including links that escape the
  project root.
- Verify a linked worktree targets its own project root and emits the branch-local warning.
- Verify the skill does not read `.codex/config.toml` or alter `.gitignore`, staging, commits,
  user-level agents, or existing files.
- After restart, dispatch each tier with hidden `agent_type` and `fork_turns: "none"` and inspect
  child metadata to prove the selected model/reasoning effort.
- Verify unknown profiles, unsupported account models, hidden-field rejection, and parent `-m`
  overrides produce a clear warning and a single default-agent retry without changing the role or
  access contract.

### Behavioral smoke tests

- Install the plugin in Codex, trust its hook, and verify skill discovery.
- Run representative helper pipelines from `start` / `continue`, a nested substitution, and a
  direct helper call from an `after-*` skill; confirm Codex resolves the installed helper without
  a process-wide `PATH` change.
- Exercise the four `review-comments` dispatch roles and verify their role, tier, access, and output
  contracts survive adapter translation.
- Run `flow:create-codex-agents` in fresh, partial, conflicting, and linked-worktree setups.
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
- Codex cost routing selects the mapped profile when available and degrades to a default agent
  without changing workflow correctness when unavailable.

## Documentation impact

Flow's README and installation guidance must explain:

- Claude Code and Codex are supported by the same skill set;
- Codex examples use its native `$flow:start`-style invocation while Claude Code retains
  `/flow:start`;
- native Codex CLI is the primary supported Codex surface; hosted Work mode is out of scope;
- Codex users must trust the plugin SessionStart and PreToolUse hooks;
- helpers remain bare commands in skill prose but are resolved through the Codex hook, with a
  redundant SessionStart PATH rule;
- custom Codex agents are not required;
- `flow:create-codex-agents` is an optional per-project cost-routing setup followed by a Codex
  restart;
- profile model IDs depend on account availability, and a parent `codex -m ...` override can
  replace the profile model.

The older `2026-07-07-flow-allowed-tools-audit-design.md` remains historical documentation for
the Claude Code frontmatter audit, but its statements that Codex strictly enforces
`allowed-tools` are marked superseded by this design.
