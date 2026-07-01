# Agent Instructions — statuskit

Python package (`statuskit`) in the claude-tools monorepo. See the root `AGENTS.md` for
repo-wide agent and review guidance.

## Architecture & principles

`statuskit` renders Claude Code's statusline: it reads the hook JSON from **stdin**, runs
it through pluggable **modules**, and prints the formatted line(s). Entry point: `main()` →
`_render_statusline()` (`src/statuskit/__init__.py`).

- **`core/`** — I/O-light plumbing. `models.py` holds frozen `StatusInput` /
  `RenderContext` dataclasses (`StatusInput.from_dict()` deserializes the hook JSON with
  safe fallbacks). `config.py` returns the first config file that exists, in priority order
  `.claude/statuskit.local.toml` > project `.claude/statuskit.toml` > user
  `~/.claude/statuskit.toml` (first found wins; files are not merged). `schema.py` is a
  declarative, side-effect-free
  param system (`param()` / `parse_params()` → values + warnings). `loader.py` maps config
  module names to classes via the `BUILTIN_MODULES` registry.
- **`modules/`** — each module subclasses `BaseModule[P]` (P = a params dataclass, validated
  at class-creation time), declares `name`/`description`, and implements
  `render(...) -> str | None` (text, or `None` to skip). Built-ins: `model`, `git`,
  `usage_limits` (`beads` is planned — commented out in `BUILTIN_MODULES`). The user picks
  and orders them via `modules = [...]` in config.

**Principles:** modular plugin pattern (add a module = register in `BUILTIN_MODULES`, no
core changes); **error isolation** — the render loop wraps each module in try/except so one
failure never cascades; **degrade, don't crash** — bad config drops to defaults with
warnings; external calls (git, usage API) are timeout-guarded and fall back to cache.

## Review guidelines

These apply on top of the root `AGENTS.md` review guidelines, for changes under
`packages/statuskit/`. Focus on judgment issues CI doesn't catch (CI already runs `ruff`
and `ty`).

**Module contract (P1).** A module's `render()` must return `str | None` and must not raise
on valid-but-sparse input — `StatusInput` fields are frequently `None`, so guard before
access. A new module must be registered in `BUILTIN_MODULES` and declare its config via a
`param()` schema.

**Degrade, don't crash (P1).** Config/schema parsing must stay best-effort: invalid values
fall back to defaults with warnings, never an exception. Flag changes that make config
parsing — or a single module's failure — fatal to the whole statusline.
