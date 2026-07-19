FLOW HARNESS: Codex

Use Codex's native local file/search/edit, shell, skill, progress, and
spawn_agent mechanisms for the corresponding semantic actions. Preserve
non-shell handling wherever a Flow skill marks data as untrusted; if the
active Codex surface cannot provide that boundary, stop and report the
missing capability.

Map capability tiers to agent_type as follows:
- fast -> flow-fast
- balanced -> flow-balanced
- strongest -> flow-strongest

Call spawn_agent with a unique task_name, the mapped hidden agent_type,
fork_turns: "none", and a message containing the requested role, task,
access boundary, execution mode, and output contract.

If the profile is missing, the hidden field is rejected, or its model is
unavailable, warn that cost routing degraded and retry exactly once with
the default native agent. Preserve the same message and access boundary.

For every shell call made while executing a Flow skill, prepend this exact
statement in the same shell source before the original command:

{{FLOW_PATH_EXPORT}}

Do not run the export separately and do not retry a helper only after
command-not-found; an outer command may already have mutated state.

A profile selects cost/reasoning only. It never grants authorization or
relaxes the parent sandbox, approval, MCP, credential, or file-access policy.
