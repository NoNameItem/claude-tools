# Flow bin/ Helpers: Python 3.9 Compatibility via Lazy Annotations

**Task:** claude-tools-dsc
**Date:** 2026-06-11
**Status:** Design

## Problem

The helper executables in `plugins/flow/bin/` use PEP 604 union syntax (`str | None`)
in **runtime-evaluated** annotation positions — function signatures and `@dataclass`
field bodies. Without `from __future__ import annotations`, Python evaluates those
annotations at import time. On Python < 3.10 the expression `str | None` raises
`TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`, so the script
dies during import, before it reads stdin.

Reproduced under the system interpreter on macOS (`/usr/bin/python3` = 3.9.6):

```
$ echo "" | /usr/bin/python3 plugins/flow/bin/flow-actor
  File ".../flow-actor", line 12, in <module>
    def get_actor() -> str | None:
TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'

$ echo "[]" | /usr/bin/python3 plugins/flow/bin/flow-task-tree
  File ".../flow-task-tree", line 29, in Task
    parent_id: str | None = None
TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
```

The helpers run via `#!/usr/bin/env python3`, which is a PATH lookup. This is a
**latent portability bug**, not a constant failure:

- In an interactive shell where a newer `python3` precedes the system one on PATH
  (e.g. Homebrew/pyenv/uv), the helpers run under that newer interpreter and work.
  In this repo's dev shell `python3` is 3.14.2, so the bug is invisible there.
- The crash surfaces wherever the first `python3` on PATH is < 3.10: stock macOS with
  no newer Python ahead of `/usr/bin/python3`; subprocesses or hooks launched with a
  sanitized `PATH` (`/usr/bin:/bin`); CI or a contributor's machine on an old `python3`.

The break was discovered during the claude-tools-g27 review. It affects every helper
that declares a PEP 604 union: today `flow-actor`, `flow-find-leaf`, and
`flow-task-tree`, but any helper is one annotation away from the same fault.

Why the existing test suite missed it: `tests/conftest.py:run_helper` invokes each
script through `sys.executable` — the same interpreter pytest runs under (3.11+ in this
workspace). The 3.9 path is never exercised.

### Context that shapes the fix

- All `|` unions in the helpers are in annotations only. There is no other 3.10+
  syntax: no `match` statements, no `isinstance(X | Y)`, no module-level runtime type
  aliases (`Foo = int | str`), no `typing.get_type_hints()`. Confirmed by grep across
  all 11 helpers. Therefore `from __future__ import annotations` is a complete fix.
- Both `pyproject.toml` files (root and `packages/statuskit`) set
  `requires-python = ">=3.11"`. The helpers are standalone scripts launched outside the
  uv build, so that constraint does not govern which interpreter runs them.
- The system `/usr/bin/python3` is Apple-managed (Command Line Tools). It is pinned at
  3.9.6 and must not be modified; the correct mitigation is code that does not care
  which interpreter runs it.

## Solution

**Approach A — make the helpers independent of the interpreter version.**

Add `from __future__ import annotations` to **all 11** helpers — not only the three
that break today, for uniformity and to keep any future annotation lazy. Under PEP 563
the annotations become unevaluated strings, so no union is computed on any version.
`@dataclass` still works: it reads `__annotations__` as strings for field detection and
never evaluates the types.

The shebang `#!/usr/bin/env python3` is **kept**. In a healthy PATH the helpers
continue to run under the newest available Python (as they already do under 3.14); in a
restricted PATH they no longer crash under 3.9.

Placement: as the first statement after the shebang and the module docstring (if
present), before all other imports — the position Python requires for a `__future__`
import.

### Files (11)

```
flow-actor          flow-find-doc       flow-link-doc
flow-branch-for     flow-find-leaf      flow-task-card
flow-current-task   flow-in-worktree    flow-task-tree
flow-find-branches  flow-worktree-dir
```

### Regression gate

A pytest test wrapping the already-verified command:

```
ruff check --select FA102 --target-version py39 plugins/flow/bin/flow-*
```

The test asserts exit code 0; it skips when `ruff` is not on PATH. Ruff already lints
these extensionless files via the root `extend-include = ["plugins/flow/bin/flow-*"]`.
Targeting `py39` makes rule `FA102` ("Missing `from __future__ import annotations`, but
uses PEP 604 union") fire on any helper that reintroduces a runtime union without the
future import.

The gate runs via `uv run pytest plugins/flow/bin/tests/`. Caveat discovered during
implementation: the flow plugin's `bin/` tests are **not** currently wired into CI or
pre-commit — the plugin CI job only lints, and `.pre-commit-config.yaml` has no pytest
hook — so until that gap is closed (tracked as **claude-tools-7sw**) the gate is enforced
by the per-commit test checklist and local/pre-push runs, not automatically in CI. The
repo's main `ruff check` cannot substitute, because it runs under the global `py311`
target where PEP 604 unions are legal and `FA102` stays silent.

The workspace's global ruff `target-version` stays `py311`; the `py39` floor is applied
only by this test's explicit `--target-version` flag, so normal linting of the rest of
the repo is unaffected.

No behavioral test under a real 3.9 interpreter is added. It would catch any 3.10+
syntax (including a future `match` statement), but there is no such syntax today, and it
would require provisioning a 3.9 interpreter in CI to actually gate rather than skip.
The lint gate covers the demonstrated failure class with no new infrastructure.

### Documentation

Add one line to the flow plugin's docs (README or its CLAUDE.md section): the helpers
**recommend Python 3.11+** (matching `requires-python = ">=3.11"`), with **3.9 kept as
fallback compatibility** for stock macOS. No third version baseline is introduced.

## Scope

`plugins/flow/bin/flow-*` (the 11 helpers), one new test under
`plugins/flow/bin/tests/`, and one documentation line for the flow plugin.

Out of scope:

- Shell wrappers, a `.py` rename, version-probing shims, or a version-guard with a
  friendly error — rejected in favor of version independence.
- Changing `requires-python` in either `pyproject.toml` — the helpers run outside the
  uv build.
- Modifying the system `/usr/bin/python3`.

## Testing

1. Run all 11 helpers under `/usr/bin/python3` (3.9.6) with minimal input and confirm
   none raise `TypeError` at import.
2. `uv run ruff format`, `uv run ruff check --fix`, and `uv run ty check` are clean.
3. The new FA gate test passes; the full existing test suite still passes under the
   workspace interpreter.
