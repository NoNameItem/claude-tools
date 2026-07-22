FLOW HARNESS: Claude Code

Use Claude Code's native Read, Grep/Glob, Edit/Write, Bash, Skill, TodoWrite,
and Agent mechanisms for the corresponding semantic actions. Keep reviewer
data and generated reply/body content in non-shell Read/Write operations.

Map subagent tiers as fast -> haiku, balanced -> sonnet, strongest -> opus.
Pass the skill's role, access, execution, and output contract in the dispatch
prompt. A model tier is a routing preference, not an authorization boundary.

Claude Code resolves the plugin's bare flow-* helpers through its plugin bin
path. Do not rewrite helper names or paths.
