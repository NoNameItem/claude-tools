# statuskit

[![PyPI version](https://img.shields.io/pypi/v/claude-statuskit)](https://pypi.org/project/claude-statuskit/)
[![Python versions](https://img.shields.io/pypi/pyversions/claude-statuskit)](https://pypi.org/project/claude-statuskit/)
[![License](https://img.shields.io/pypi/l/claude-statuskit)](https://github.com/NoNameItem/claude-tools/blob/master/LICENSE)

Modular statusline for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

Statuskit displays contextual information below Claude's responses: current model, git status, API usage limits, and more. It reads JSON from Claude Code's statusline hook and renders formatted, colored output.

## Features

- **Modular architecture** — enable only the modules you need
- **Configurable** — customize each module's behavior via TOML config
- **Built-in modules:**
  - `model` — current Claude model name
  - `git` — branch, remote status, changes, last commit, project/worktree location
  - `usage_limits` — API quota tracking (5h session, 7d weekly) with color-coded warnings
- **Coming soon:**
  - `beads` — display active beads tasks
  - External modules support — load custom modules from separate packages

## Installation

```bash
# Using uv (recommended)
uv tool install claude-statuskit

# Using pipx
pipx install claude-statuskit

# Using pip
pip install claude-statuskit
```

## Quick Start

Run the setup command to configure Claude Code:

```bash
# User-level setup (recommended for personal use)
statuskit setup

# Project-level setup (shared config for team)
statuskit setup --scope project

# Local setup (personal overrides, gitignored)
statuskit setup --scope local
```

Setup will:
1. Add the statusline hook to Claude Code settings
2. Create configuration file at the appropriate level
3. Update gitignore for local configs (if applicable)

After setup, restart Claude Code to see the statusline.

## Configuration

Configuration files are loaded in priority order (first found wins):

| Level | Path | Use case |
|-------|------|----------|
| Local | `.claude/statuskit.local.toml` | Personal overrides, gitignored |
| Project | `.claude/statuskit.toml` | Shared team configuration |
| User | `~/.claude/statuskit.toml` | Global personal defaults |

### Basic Configuration

```toml
# Modules to display (in order)
modules = ["model", "git", "usage_limits"]

# Enable debug output
debug = false
```

### Module Configuration

Each module can be configured in its own section:

```toml
[git]
show_branch = true
commit_age_format = "compact"

[usage_limits]
show_session = true
show_weekly = true
multiline = false
```

## Module Reference

### `model` Module

Displays model name, session duration, and context window usage.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `show_duration` | bool | `true` | Show session duration |
| `show_context` | bool | `true` | Show context window usage |
| `context_format` | string | `"free"` | Context display format (see below) |
| `context_compact` | bool | `false` | Use compact numbers (e.g., `150k` instead of `150,000`) |
| `context_threshold_green` | int | `50` | Percentage of free context to show green |
| `context_threshold_yellow` | int | `25` | Percentage of free context to show yellow (below = red) |

**`context_format` values:**

| Value | Output example |
|-------|----------------|
| `"free"` | `150,000 free (75.0%)` |
| `"used"` | `50,000 used (25.0%)` |
| `"ratio"` | `50,000/200,000 (25.0%)` |
| `"bar"` | `[███████░░░] 70%` |

### `git` Module

Displays git branch, remote status, changes, last commit, and project/worktree location.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `show_project` | bool | `true` | Show project (repository) name |
| `show_worktree` | bool | `true` | Show worktree name with 🌲 indicator |
| `show_folder` | bool | `true` | Show current subfolder relative to repo root |
| `show_branch` | bool | `true` | Show current branch name |
| `show_remote_status` | bool | `true` | Show ahead/behind/diverged status |
| `show_changes` | bool | `true` | Show staged/modified/untracked counts |
| `show_commit` | bool | `true` | Show last commit hash and age |
| `commit_age_format` | string | `"relative"` | Commit age format (see below) |

**`commit_age_format` values:**

| Value | Output example |
|-------|----------------|
| `"relative"` | `2 hours ago` |
| `"compact"` | `2h` |

### `usage_limits` Module

Displays API usage limits with color-coded warnings based on consumption rate.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `show_session` | bool | `true` | Show 5-hour session limit |
| `show_weekly` | bool | `true` | Show 7-day weekly limit |
| `show_sonnet` | bool | `false` | Show Sonnet-only weekly limit |
| `show_reset_time` | bool | `true` | Show time until reset |
| `multiline` | bool | `true` | Display each limit on separate line |
| `show_progress_bar` | bool | `false` | Show visual progress bar |
| `bar_width` | int | `10` | Progress bar width in characters |
| `session_time_format` | string | `"remaining"` | Time format for session limit |
| `weekly_time_format` | string | `"reset_at"` | Time format for weekly limit |
| `sonnet_time_format` | string | `"reset_at"` | Time format for Sonnet limit |
| `cache_ttl` | int | `60` | Cache lifetime in seconds |

**Time format values:**

| Value | Output example |
|-------|----------------|
| `"remaining"` | `2h 30m` |
| `"reset_at"` | `Thu 17:00` |

**Color coding:** Usage is colored based on consumption rate vs elapsed time:
- 🟢 Green — on track or under
- 🟡 Yellow — approaching the limit trajectory
- 🔴 Red — ahead of pace, may hit limit

## License

MIT — see [LICENSE](https://github.com/NoNameItem/claude-tools/blob/master/LICENSE) for details.
