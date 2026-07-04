# Fix: Show Current Directory Outside a Git Repo

**Task:** claude-tools-5dl.17
**Date:** 2026-07-03

## Problem

The current directory is surfaced **only** as Line 1 (location) of the git module,
built by `_get_location()` → `_render_location_line()`. But `GitModule.render()`
short-circuits early (`modules/git.py:78-80`):

```python
branch = self._get_branch()
if branch is None:
    return None
```

When there is no resolvable branch, the whole module returns `None`, so the location
line is never built and the user loses all location context. There is no standalone
directory module — the path is only a side-effect of the git module.

Two distinct trigger cases:

- **(a) Not a git repo at all** (e.g. `/tmp/scratch`): `_get_branch()` and
  `_get_location()` both fail (git commands return non-zero).
- **(b) In a repo but no resolvable branch** (fresh repo with no commits): `git branch
  --show-current` is empty and `rev-parse --short HEAD` fails, so `_get_branch()` is
  `None` — yet `_get_location()` *would* succeed. The location line is dropped anyway
  because `render()` bails before building it.

## Solution

**Approach A — fix entirely within `GitModule`.** Line 1 is already a "location"
concern (project / worktree / subfolder), not a git-status concern, so the fallback
belongs here. No new module, no config schema changes, no loader changes.

Restructure `render()` so the **location line is always attempted** and the **status
line renders only when a branch resolves**:

```python
def render(self) -> str | None:
    location = self._get_location()   # git-based; None  ⟺  current_dir NOT in a repo
    branch = self._get_branch()       # None even inside a repo (fresh, no commits)

    # Line 1: location — always attempted
    if location is not None:
        line1 = self._render_location_line(location)   # project → worktree → subfolder
    else:
        line1 = self._render_cwd_fallback()            # Case 1 / Case 2 (see below)

    # Line 2: git status — only when a branch resolves
    line2 = None
    if branch is not None:
        # (existing remote/changes/commit assembly)
        line2 = self._render_status_line(branch, remote_status, changes, commit)

    lines = [line for line in (line1, line2) if line]
    return "\n".join(lines) if lines else None
```

This fixes **both** trigger cases:

| Situation | `location` | `branch` | Result |
|---|---|---|---|
| Normal repo | present | present | location line + status line (unchanged) |
| **(b)** Fresh repo, no commits | present | `None` | location line only (previously vanished) |
| **(a)** Not a repo | `None` | `None` | cwd-fallback line only, no status line |

Because `location is None ⟹ branch is None` (git can't resolve a branch outside a
repo), the fallback path never produces a status line.

## Case detection for the fallback

Reached only when `current_dir` is not a repo. We distinguish two states using the two
independent path fields Claude Code provides in the statusline JSON:

- `workspace.current_dir` — the current working directory (tracks `cd`).
- `workspace.project_dir` — the **session-start project root** (stable; same value as
  `$CLAUDE_PROJECT_DIR`, documented as "Project root path").

| State | `git -C project_dir` | `git -C current_dir` | Meaning |
|---|:---:|:---:|---|
| **Case 1** | repo | not repo | Started inside a repo, then `cd`'d out of it |
| **Case 2** | not repo | not repo | Outside a repo from the start |

Detection cost is one extra `git rev-parse` and only on the fallback path. Skip it
entirely when `project_dir == current_dir` (or `project_dir` is missing) → **Case 2** by
definition. This requires threading a working directory into `_run_git`:

```python
def _run_git(self, *args: str, cwd: str | None = None) -> str | None:
    ...
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, ...)
```

Existing callers are unaffected (`cwd` defaults to `None` = process cwd, which tracks
`current_dir`, as the module already relies on).

## Color scheme

The **folder leaf** (the current folder you're standing in) is `light_magenta` whenever
you are legitimately inside a folder, and `red` only for the abnormal "you stepped out of
your project" state.

| Element | Color | Change? |
|---|---|---|
| project / repo name | cyan | unchanged |
| 🌲 worktree | yellow | unchanged |
| `→` separator | dark_grey | unchanged |
| **folder leaf** — in-repo subfolder **and** Case-2 plain dir | **light_magenta** | subfolder was `white` |
| **Case-1 leaf** — path after leaving the repo | **red** | new |

Rendered examples (path shortened, `$HOME` → `~`):

- In repo, subfolder: `claude-tools`[cyan] → `packages/statuskit`[light_magenta]
- In repo, **at root**: `claude-tools`[cyan] (+ `🌲 <worktree>`[yellow] if a worktree) —
  the repo name still shows; only the subfolder segment is absent. **Unchanged.**
- Case 1 (left repo): `claude-tools`[cyan] → `~/tmp/scratch`[red]
- Case 2 (never in repo): `~/tmp/scratch`[light_magenta]

## Rendering details

New helpers on `GitModule`:

- `_shorten_path(path: str) -> str` — replace a leading `$HOME` with `~`
  (`str(Path.home())` prefix); returns `~` when `path == $HOME`. Reused by both cases.
- `_render_cwd_fallback() -> str | None` — reads `self.data.workspace.current_dir`;
  returns `None` if there is no workspace or the dir is empty. Otherwise resolves Case 1
  vs Case 2 and renders accordingly.

Case-1 project name is derived the **same way** as the in-repo project name
(`git -C project_dir rev-parse --git-common-dir`, resolve, basename — `.git` →
parent name), so the repo label is consistent whether you are in it or just left it.

The existing subfolder color line changes from `white` to `light_magenta`
(`modules/git.py:388-389`).

## Params — reuse existing, no new config

- The **path leaf** is gated by the existing `show_folder` — this covers the in-repo
  subfolder, the Case-2 plain-dir path, **and** the Case-1 red path.
- The **Case-1 repo prefix** is gated by the existing `show_project`.
- Each segment is gated independently; if both toggles are off, or
  `workspace.current_dir` is missing, the fallback yields nothing and the module
  returns `None`.
- **YAGNI:** no new "enable fallback" flag — the whole point of the bug is that users
  want the directory shown.

## Edge cases

- No `workspace` / empty `current_dir` → no fallback line.
- `current_dir == $HOME` → renders `~`.
- Detached HEAD **with** commits → unchanged (`_get_branch()` already returns the short
  hash, so `branch` is not `None`).
- In-repo **root** (no subfolder) → location line still shows the project (and worktree),
  as today.
- Case 1 where `project_dir` is itself a worktree → `--git-common-dir` resolves to the
  main repo, matching in-repo behavior.

## Testing

**Unit** (`tests/test_git_module.py`, mocking `_run_git`):

- Case 2: `_get_location()`/`_get_branch()` mocked to `None`, `project_dir == current_dir`
  outside `$HOME` → single `light_magenta` shortened-path line, no status line.
- Case 1: `current_dir` git fails, `project_dir` git succeeds → `project`[cyan] →
  `path`[red].
- Fresh-repo-no-commits (case b): `_get_location()` returns a dict, `_get_branch()` is
  `None` → location line only, no status line.
- `~` shortening for a path under `$HOME`; `current_dir == $HOME` → `~`.
- Gating: `show_folder=False` and `show_project=False` suppress the respective segments.
- Missing `workspace` / empty `current_dir` → module returns `None`.

**Integration** (`tests/test_git_integration.py`, `@pytest.mark.integration`):

- `monkeypatch.chdir(tmp_path)` into a real non-git temp dir with `project_dir` also set
  to a non-repo path → renders the Case-2 fallback line.

## Files touched

- `packages/statuskit/src/statuskit/modules/git.py` — `render()` restructure,
  `_run_git(cwd=...)`, `_render_cwd_fallback()`, `_shorten_path()`, subfolder color.
- `packages/statuskit/tests/test_git_module.py` — unit tests above.
- `packages/statuskit/tests/test_git_integration.py` — non-git-dir integration test.

## Erratum (post-implementation, 2026-07-03, verified against git 2.47)

Case **(b)** above — "fresh repo with no commits → `_get_branch()` is `None` → location
line dropped" — does **not** actually occur on modern git. `git branch --show-current`
in a fresh `git init` repo returns the **unborn branch name** (e.g. `master`/`main`),
not an empty string, so `_get_branch()` resolves and a fresh repo renders **both** lines
normally (location + `master ☁✗`). A live check and the smoke tests confirm this.

The genuine `_get_branch() is None` **inside** a repo therefore requires the rare
degenerate state where `git branch --show-current` is empty *and* `rev-parse --short HEAD`
also fails (an unborn/detached HEAD with no resolvable ref) — practically never hit.

This does not change the fix: the `render()` restructure still robustly handles the real
trigger — case **(a)**, not a git repo at all — and correctly covers the rare branch-`None`
case by always attempting Line 1. Only the case-(b) *motivation* was inaccurate; the
implemented behavior and tests are unaffected. The corresponding unit test was named
`test_render_branch_unresolved_location_only` (not "fresh_repo") to reflect this.
