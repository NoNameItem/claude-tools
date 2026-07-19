FLOW RUNTIME ACTIVE

Treat every Flow skill's step order, user gates, role access, safety
boundaries, output requirements, and completion conditions as invariant.
Ask every user choice in plain text and wait for an explicit response.
Perform semantic actions with the native mechanism named by the active
harness adapter. If it is unavailable, use an equivalent native mechanism,
then a generic safe mechanism preserving the same contract; otherwise stop
and report the missing capability.
Never turn data into shell or program source, replace a required non-shell
operation with shell interpolation, or relax a skill's security boundary.
Every subagent dispatch must state role, capability tier, access boundary,
foreground/background and parallel/sequential mode, and exact output contract.
