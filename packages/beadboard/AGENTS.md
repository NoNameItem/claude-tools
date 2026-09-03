# Agent Instructions — beadboard

Python package (`beadboard`) in the claude-tools monorepo. See the root `AGENTS.md` for
repo-wide agent and review guidance.

## Architecture & principles

`beadboard` is a terminal client for [beads](https://github.com/steveyegge/beads): it reads
issues and renders them as a Textual application. Entry point: `beadboard.cli:main()` →
`BeadboardApp` (`src/beadboard/ui/app.py`).

Five layers, each a package, in dependency order:

- **`model/`** — domain types. Depends on nothing, not even Textual.
- **`sources/`** — the registry of beads projects: which projects exist and how they are addressed.
- **`repository/`** — read access to *one* project. It is handed the project it reads and knows
  nothing about the registry.
- **`service/`** — orchestration: turns registry and repository into what the screens display.
- **`ui/`** — the Textual application, screens and widgets. May import anything.

`cli.py` is the composition root and the only module allowed to reach into any layer.

The first working version is **read-only**; writing (claim/close/edit/create) belongs to later
iterations. See `docs/superpowers/specs/2026-09-02-beadboard-design.md`.

## Review guidelines

These apply on top of the root `AGENTS.md` review guidelines, for changes under
`packages/beadboard/`. CI already runs `ruff` and `ty`; focus on judgment.

**Layering (P1).** A layer may import only the layers below it: `model` imports nothing;
`sources` and `repository` are siblings on `model` and may not import each other; `service`
may import `model`, `sources`, `repository`; `ui` may import anything, and only `ui` may
import `textual`. The rule is enforced by `tests/test_import_boundaries.py` against the
`FORBIDDEN` table — a change that edits that table to make a new import legal is a design
change and needs a reason in the pull request, not a green test.

**No `bd` calls outside `repository/` and `sources/` (P1).** Everything that shells out to `bd`
or talks to Dolt lives behind the repository port; screens and services receive data, they do
not fetch it.

**Textual widgets over hand-rolled rendering (P2).** Prefer a Textual widget and its styling
hooks to manual string assembly; a hand-built block needs a comment saying which widget was
tried and why it did not fit.
