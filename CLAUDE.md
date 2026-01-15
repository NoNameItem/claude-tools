# CLAUDE.md

Custom tools for Claude Code. Monorepo with uv workspaces.

## Project Structure

```
claude-tools/
├── pyproject.toml              # Workspace root, shared dev deps
├── packages/
│   └── statuskit/
│       ├── pyproject.toml      # statuskit package
│       ├── src/statuskit/      # Source code
│       └── tests/              # Tests
└── docs/plans/                 # Design documents
```

## Development

```bash
uv sync              # Install all dependencies
uv run pytest        # Run tests
uv run ruff check .  # Lint
uv run ruff format . # Format
uv run ty check .    # Type check
uv run statuskit     # Run statuskit
```

## Statuskit

Modular statusline kit for Claude Code with plugin architecture.

**Testing locally:**
```bash
echo '{"model":{"display_name":"Test"},"workspace":{"current_dir":"/tmp","project_dir":"/tmp"},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":1000}}}' | uv run statuskit
```

**Key files:**
- `~/.claude/statuskit.toml` - user config
- `~/.cache/statuskit/` - quota cache, session state
