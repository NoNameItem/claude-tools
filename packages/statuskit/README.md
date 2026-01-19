# statuskit

Modular statusline for Claude Code.

## Installation

```bash
uv tool install statuskit
# or
pipx install statuskit
```

## Quick Start

```bash
statuskit setup
```

This adds the statusline hook to your Claude Code settings.

## Configuration

Configuration file locations (in priority order):
1. `.claude/statuskit.local.toml` (local, gitignored)
2. `.claude/statuskit.toml` (project)
3. `~/.claude/statuskit.toml` (user)

Example configuration:

```toml
# Modules to display (in order)
modules = ["model", "git", "beads", "quota"]

# Enable debug output
# debug = false
```

## Built-in Modules

- **model** — Display current Claude model name
- **git** — Show git branch and status
- **beads** — Display active beads tasks
- **quota** — Track token usage

## License

MIT
