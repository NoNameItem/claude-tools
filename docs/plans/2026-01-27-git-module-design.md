# Git Module Design

Statuskit module for displaying git repository information in Claude Code statusline.

## Output Format

Two-line output:

```
[cyan]project[/] [dim]→[/] [green]🌲[/] [yellow]worktree[/] [dim]→[/] [white]subfolder[/]
[magenta]branch[/] [yellow]↑2[/] [[green]+3[/] [yellow]~2[/] [cyan]?1[/]] [dim]fc49b3d 2h ago[/]
```

### Line 1: Location

Shows project name, worktree (if applicable), and current subfolder.

| Case | Output |
|------|--------|
| worktree, root | `project → 🌲 worktree` |
| worktree, subfolder | `project → 🌲 worktree → src/utils` |
| not worktree, root | `project` |
| not worktree, subfolder | `project → src/utils` |

**Colors:**
- project: cyan
- `→` separator: dim
- `🌲` icon: green
- worktree name: yellow
- subfolder: white

### Line 2: Git Status

Shows branch, remote sync status, working directory changes, and last commit.

**Branch:** Current branch name in magenta. For detached HEAD, shows short commit hash.

**Remote status:**

| State | Output |
|-------|--------|
| ahead | `[yellow]↑N[/]` |
| behind | `[red]↓N[/]` |
| diverged | `[red]⇅N[/]` (N = total) |
| synced | `[green]✓[/]` |
| no upstream | `[blue]☁✗[/]` |

**Changes:** In square brackets, only non-zero counts shown.

| Type | Symbol | Color |
|------|--------|-------|
| staged | `+N` | green |
| modified | `~N` | yellow |
| untracked | `?N` | cyan |

**Commit:** Short hash (7 chars) + age in dim color.

## Data Sources

All data from git commands (not Claude Code JSON):

```bash
# Location detection
git rev-parse --git-common-dir    # main repo .git path
git rev-parse --show-toplevel     # current worktree root
test -f .git                      # worktree detection

# Branch and remote
git branch --show-current
git rev-parse --abbrev-ref @{upstream}
git rev-list --left-right --count HEAD...@{upstream}

# Changes
git status --porcelain

# Last commit
git log -1 --format='%h %ar'
```

All commands use `--no-optional-locks` for performance.

## Configuration

```toml
[git]
# Line 1 — location
show_project = true        # project name
show_worktree = true       # 🌲 worktree name
show_folder = true         # subfolder path

# Line 2 — git status
show_branch = true         # branch name
show_remote_status = true  # ↑↓✓☁✗
show_changes = true        # [+N ~N ?N]
show_commit = true         # hash + age

# Format
commit_age_format = "relative"  # relative | compact | absolute
```

**commit_age_format values:**
- `relative`: `2 hours ago` (default)
- `compact`: `2h`
- `absolute`: `Jan 26`

**Behavior:**
- If all line 1 options disabled → line 1 not rendered
- If all line 2 options disabled → line 2 not rendered
- If both lines empty → module returns `None`

## Implementation

**File:** `packages/statuskit/src/statuskit/modules/git.py`

**Class structure:**

```python
class GitModule(BaseModule):
    name = "git"
    description = "Git branch, status, and location"

    def __init__(self, ctx, config): ...
    def render(self) -> str | None: ...

    def _run_git(self, *args) -> str | None: ...
    def _get_location_line(self) -> str | None: ...
    def _get_status_line(self) -> str | None: ...
    def _get_remote_status(self) -> str: ...
    def _get_changes(self) -> str: ...
    def _format_commit_age(self, age_str: str) -> str: ...
```

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Not a git repo | Return `None` |
| Git not installed | Return `None` |
| Detached HEAD | Show short hash instead of branch |
| Empty repo (no commits) | Skip commit block |
| Command timeout (2s) | Skip that block |

## Files

```
packages/statuskit/src/statuskit/modules/git.py   # module
packages/statuskit/tests/test_git_module.py       # tests
```

Module registered in `modules/__init__.py`, auto-discovered by loader.
