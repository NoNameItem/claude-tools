# CLAUDE.md

Custom tools and plugins for Claude Code. Monorepo with uv workspaces.

## Overview

This repository contains two types of tools for Claude Code:

**Statuskit** - Python package for customizable statusline display. Modular architecture with plugins for model info, git status, beads tasks, and quota tracking. Reads JSON from Claude Code's statusline hook and renders formatted output.

**Flow Plugin** - Claude Code plugin for beads workflow automation. Provides slash commands (`/flow:start`, `/flow:after-design`, `/flow:after-plan`, `/flow:done`) that guide you through task selection, branch management, design linking, and completion workflow.

## Terminology

| Term | Meaning | Location | Example |
|------|---------|----------|---------|
| **Project** | Generic term for any releasable unit in the monorepo | `packages/` or `plugins/` | statuskit, flow |
| **Package** | Python package with pyproject.toml, published to PyPI | `packages/` | statuskit |
| **Plugin** | Claude Code plugin with plugin.json | `plugins/` | flow |

**In code and CI:**
- "project" = package OR plugin (generic)
- "package" = only Python packages
- "plugin" = only Claude Code plugins
- Scope in conventional commits = project name (e.g., `feat(statuskit):`, `fix(flow):`)

## Project Structure

```
claude-tools/
├── .claude-plugin/
│   └── marketplace.json        # Plugin marketplace definition
├── plugins/
│   └── flow/                   # Beads workflow plugin
│       ├── .claude-plugin/
│       │   └── plugin.json
│       └── skills/             # /flow:* commands
├── packages/
│   └── statuskit/              # Python statusline package
│       ├── pyproject.toml
│       ├── src/statuskit/
│       │   ├── core/           # Config, loading, models
│       │   └── modules/        # Statusline modules
│       └── tests/
└── docs/plans/                 # Design documents
```

## Statuskit

Modular statusline kit for Claude Code with plugin architecture.

### Installation

```bash
uv sync              # Install all dependencies
```

### Configuration

Create `~/.claude/statuskit.toml`:

```toml
debug = false
modules = ["model", "git", "beads", "quota"]  # Default modules

# Module-specific configuration
[quota]
# Add quota module config here if needed
```

**Available modules:**
- `model` - Display current Claude model name
- `git` - Show git branch and status
- `beads` - Display active beads tasks
- `quota` - Track token usage and limits

**Key files:**
- `~/.claude/statuskit.toml` - User configuration
- `~/.cache/statuskit/` - Quota cache, session state

### Testing Locally

```bash
echo '{"model":{"display_name":"Test"},"workspace":{"current_dir":"/tmp","project_dir":"/tmp"},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":1000}}}' | uv run statuskit
```

### Development

```bash
uv run pytest        # Run tests
uv run ruff check .  # Lint
uv run ruff format . # Format
```

## Pre-commit Workflow

**Before every commit**, run formatter and linter on changed files:

```bash
git diff --name-only '*.py' | xargs uv run ruff format
git diff --name-only '*.py' | xargs uv run ruff check --fix
```

This is required because:
- Pre-commit hooks only **check** code, they don't auto-fix
- `ruff --fix` can sometimes break code (e.g., moving imports to TYPE_CHECKING block, adding return to generators)
- Running checks manually allows reviewing and fixing issues before commit

The pre-commit hooks will then verify:
1. `ruff-format` — auto-formats code (safe)
2. `ruff` — checks for remaining lint errors
3. `single-package-commit` — validates commit scope
4. `beads` — syncs beads state

**Type checking** (only for packages, run manually or in CI):
```bash
uv run ty check
```

**If lint error is unclear:** `ruff rule <CODE>` (e.g., `ruff rule E711`)

## Writing Implementation Plans

When writing plans that modify Python files, each commit step MUST include:
1. `uv run ruff format <files>`
2. `uv run ruff check --fix <files>`
3. Then `git add` and `git commit`

This applies to ALL Python files in the repo, including `.github/scripts/`.

## Creating Pull Requests

```bash
git push -u origin HEAD
gh pr create \
  --title "feat(statuskit): add quota module" \
  --label "statuskit" \
  --body "$(cat <<'EOF'
## Summary
...
## How it works
...
EOF
)"
```

См. CONTRIBUTING.md для полного шаблона описания PR.

## Git Push Policy

**ALWAYS ask for explicit confirmation before running `git push`.**

Never push automatically after commits. Always show what will be pushed and ask:
- Branch name
- Number of commits
- Brief summary of changes

This prevents accidental pushes and gives the user control over when changes go to remote.

## Claude Code Plugins

This repository is also a Claude Code plugin marketplace containing workflow automation tools.

### Installation

**Local development:**
```bash
/plugin marketplace add /Users/artem.vasin/Coding/claude-tools
/plugin install flow@nonameitem-toolkit
```

**From GitHub:**
```bash
/plugin marketplace add NoNameItem/claude-tools
/plugin install flow@nonameitem-toolkit
```

### Flow Plugin

Automated beads workflow commands for task management.

**Available commands:**
- `/flow:start` - Start working on a beads task (task selection, branch management, context display)
- `/flow:after-design` - After brainstorming/design phase (links design doc, parses subtasks, previews before creating)
- `/flow:after-plan` - After planning phase (links implementation plan document to task)
- `/flow:done` - Complete and verify task (checks git branch, closes task, handles parent tasks, syncs)

**Usage example:**
```bash
/flow:start              # Begin work session
# ... do your work ...
/flow:after-design       # After design is complete
/flow:after-plan         # After creating implementation plan
/flow:done               # Mark task complete
```

### Development

**Adding a new skill to existing plugin:**

Use the `superpowers:writing-skills` skill for creating or editing skills:
```bash
/superpowers:writing-skills
```

This skill guides you through proper skill creation, testing, and validation.

**Adding a new plugin to marketplace:**

1. Create plugin directory: `plugins/your-plugin/`
2. Create `.claude-plugin/plugin.json`:
   ```json
   {
     "name": "your-plugin",
     "version": "1.0.0",
     "description": "Your plugin description",
     "repository": "https://github.com/NoNameItem/claude-tools",
     "keywords": ["keyword1", "keyword2"],
     "category": "productivity",
     "skills": []
   }
   ```
3. Add skills using `superpowers:writing-skills`
4. Register in `.claude-plugin/marketplace.json`:
   ```json
   {
     "name": "your-plugin",
     "source": "./plugins/your-plugin",
     "description": "Your plugin description",
     "version": "1.0.0"
   }
   ```
5. Test locally: `/plugin install your-plugin@nonameitem-toolkit`
