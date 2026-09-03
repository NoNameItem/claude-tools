# Design: Beadboard package skeleton and repository wiring

**Task:** claude-tools-144.1
**Date:** 2026-09-03
**Parent design:** `docs/superpowers/specs/2026-09-02-beadboard-design.md`

## Problem

The beadboard epic is decomposed into fourteen issues, and every one of them lands in a package
that does not exist yet. Issue `.1` creates it — and it is deliberately not only a package. A
skeleton that lint, tests, type-checking, Sonar and the release machinery do not see is not a
foundation; it is a directory. The wiring has to arrive with the skeleton, because a green CI run
is the only evidence that the next thirteen issues can start.

Two things make this more than a `mkdir`. The repository's CI derives most of its behaviour from
configuration rather than from hardcoded project lists, so the exact set of files that must change
is not obvious from the outside; and the layering the epic specifies is worth nothing unless
something fails when it is violated.

## Scope

**In.** The workspace member `packages/beadboard`; package metadata and the `beadboard` entry
point; an empty Textual application that starts and quits; the five layer packages as empty
modules; the test directory; the import-boundary test; `sonar-project.properties`; `AGENTS.md`; a
minimal `README.md`; the release-please entry and manifest line; the `beadboard` PR label; the
commit-scope rule in `CLAUDE.md` and `CONTRIBUTING.md`; two external registrations (the SonarCloud
project, the PyPI pending publisher).

**Out.** Domain types, projections, the repository port, adapters, the source registry, screens —
issues `.2` to `.7`. Nothing in this issue talks to `bd` or to Dolt.

## Mockups

None. This issue produces no screen: the application shows a placeholder and a footer. Layout,
artboards and their visual review begin with the board screen (`.5`). The empty application exists
so that `beadboard` is a runnable command from day one, not as a design artefact.

## Decisions

**D1. All five layer packages exist from the start; the boundary test is a rule, not a list.**
`model`, `sources`, `repository`, `service` and `ui` are created as packages with nothing but a
docstring. The alternative — adding each package in the issue that fills it — postpones the
boundary check until after the first import that violates it. The test is written against a table
of layer rules rather than a list of modules, so filling the packages never requires editing it.

**D2. The distribution is named `beadboard`.** Checked free on PyPI (`/pypi/beadboard/json` and
`/simple/beadboard/` both 404). Distribution, import package and console script therefore carry one
name, unlike `claude-statuskit` / `statuskit` / `statuskit` next door. The `claude-` prefix on the
sibling reflects what it is — a Claude Code statusline; beadboard is a beads client and has nothing
to do with Claude Code.

**D3. Textual is pinned `>=8.2,<9`.** Textual makes breaking API changes across majors, and
beadboard is an application rather than a library, so an upper bound constrains nobody downstream.
This departs from `statuskit`, whose `termcolor` dependency is unpinned — a far more stable
dependency.

**D4. The SonarCloud gate is `NoNameItem way` from the first analysis.** The organisation default
is `Sonar way no coverage`, and `statuskit` is on `NoNameItem way`, which adds overall conditions:
`coverage >= 80`, `violations = 0`, `duplicated_lines_density <= 3`. Adopting it later — say at the
first release — means meeting it against accumulated code instead of against three files. The cost
is that this issue must ship tests that cover the skeleton, which is exactly what makes the cost
small now.

**D5. No `pytest-asyncio` yet.** Textual's `App.run_test()` needs an event loop and an async test
plugin. What it would prove here — that an application with one placeholder starts — does not
justify a dev dependency and a pytest configuration change in a skeleton issue. `compose()` is a
generator and is testable synchronously. The real UI harness arrives with the board screen (`.5`),
where there are scenarios worth driving. Accepted cost: until then, nothing verifies that the
application starts under a terminal, only that its parts are assembled correctly.

**D6. A minimal `README.md` ships now.** `pyproject.toml` declares `readme = "README.md"`, so the
wheel does not build without it. The epic places the README in `.8`; what `.8` writes is the
user-facing one — installation, usage, screenshots. This one says what the package is, that it is
under development, and points at the epic design.

**D7. Issue templates are deferred to `.8`.** `statuskit` and `flow` each have a bug and a feature
template. They serve users filing issues, and beadboard has no users before its first release.

**D8. The PyPI pending publisher is registered now, not in `.8`.** Choosing a short unprefixed name
buys a risk: nothing reserves `beadboard` until a publisher is registered, and the whole MVP would
pass with the name unclaimed. Registration is the same web form the SonarCloud step already sends
the maintainer to, and `.8` keeps verifying that the publisher matches the workflow.

**D9. The release-please entry is added now, with a known consequence.** From the moment the entry
exists, `feat:` commits in issues `.2` to `.7` make release-please open release pull requests for
beadboard. Nothing is published until such a pull request is merged, so the handling is to leave
them open until `.8`. The alternative — adding the entry in `.8` — would leave the changelog for
the whole MVP to be reconstructed retroactively.

## Package layout

```
packages/beadboard/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── sonar-project.properties
├── src/beadboard/
│   ├── __init__.py
│   ├── cli.py
│   ├── model/__init__.py
│   ├── sources/__init__.py
│   ├── repository/__init__.py
│   ├── service/__init__.py
│   └── ui/
│       ├── __init__.py
│       └── app.py
└── tests/
    ├── __init__.py
    ├── test_app.py
    ├── test_cli.py
    └── test_import_boundaries.py
```

`BeadboardApp` lives in `ui/app.py` rather than in a top-level `app.py`, and the orchestration layer
is `service` — see the parent design, *Modules*, for why neither is called `app`.

`cli.py` is the composition root: it is the one module allowed to reach into any layer, because
its job is to assemble them.

### Package metadata

`pyproject.toml` follows `packages/statuskit/pyproject.toml`: hatchling, `src` layout,
`requires-python = ">=3.11"`, MIT, the same author and URL shape.

| Field | Value | Why it matters |
|---|---|---|
| `name` | `beadboard` | D2 |
| `version` | `0.1.0` | release-please owns it from here on |
| `dependencies` | `textual>=8.2,<9` | D3 |
| `[project.scripts]` | `beadboard = "beadboard.cli:main"` | the console script |
| `classifiers` | Python 3.11 – 3.14 | **not decoration**: `detect_changes.py` reads the classifiers to build the test matrix |
| `[tool.hatch.build.targets.wheel]` | `packages = ["src/beadboard"]` | src layout |

## The empty application

`BeadboardApp` is a Textual `App` with a `Header`, a `Footer`, a placeholder `Static`, and a
binding on `q` to quit. `main()` constructs it, calls `run()`, and returns `0`.

The point is a command that starts and exits cleanly. A skeleton whose entry point was never
executed hides exactly the failures — a broken console script, a missing dependency, an import
cycle — that a skeleton exists to rule out.

## Import-boundary test

The test parses every file under `src/beadboard/` with `ast`, collects the modules each file
imports, and checks them against a table:

| Layer | May not import |
|---|---|
| `model` | `textual`, `beadboard.{sources,repository,service,ui}` |
| `sources` | `textual`, `beadboard.{repository,service,ui}` |
| `repository` | `textual`, `beadboard.{sources,service,ui}` |
| `service` | `textual`, `beadboard.ui` |
| `ui` | — |
| root (`__init__.py`, `cli.py`) | — composition root, exempt |

`repository` may not import `sources` — the parent design's module table says the layer knows
nothing about the registry, while its dependency diagram drew an edge to it. The table is right: a
repository is handed the project it reads, and discovering projects belongs to `service`. The
diagram has been corrected in the parent design.

**Static parsing rather than importing.** An import-time check would have to import each layer in
isolation and inspect `sys.modules`, which is brittle and needs the packages to be non-empty. AST
parsing works on empty packages, needs neither Textual nor bd, and catches a violation inside a
branch that never executes.

## Tests and coverage

`NoNameItem way` requires >= 80% coverage over all code, so the skeleton is covered as it is
written, not afterwards.

| File | Covers |
|---|---|
| `test_cli.py` | `main()` with `BeadboardApp.run` patched: returns `0`, `run` called once |
| `test_app.py` | `compose()` yields the expected widget types; `BINDINGS` contains the quit binding |
| `test_import_boundaries.py` | the rule table above |

Empty layer packages hold nothing but a docstring, so they contribute no uncovered statements
and cannot drag the ratio down while they wait to be filled.

## Repository wiring

| File | Change |
|---|---|
| `pyproject.toml` (root) | `[tool.uv.sources] beadboard = { workspace = true }` and `beadboard` in the dev group — without it `uv sync` does not install the package and the tests cannot import it |
| `uv.lock` | regenerated |
| `release-please-config.json` | a `packages/beadboard` entry: `release-type: python`, `package-name: beadboard`, `bump-minor-pre-major`, `prerelease`, `extra-label: "ci:full,beadboard"` |
| `.release-please-manifest.json` | `"packages/beadboard": "0.1.0"` |
| `packages/beadboard/sonar-project.properties` | scanner properties; the file must sit in the package because CI sets `projectBaseDir: packages/beadboard`. Starts with no rule mutes — statuskit's exist for reasons beadboard has not met yet |
| `packages/beadboard/AGENTS.md` | architecture summary and review rules for the subtree; the layering rule is the P1 item |
| `CLAUDE.md`, `CONTRIBUTING.md` | `beadboard` in the commit-scope and PR-label tables |
| GitHub | the `beadboard` label, colour `#ff7f0e` — the next free colour in the palette `statuskit`/`flow`/`repo` already use |

**What needs no change**, because it is derived from `[tool.repo]` and from paths: the CI matrices
in `detect_changes.py`; lint, test and Sonar jobs in `_reusable-python-ci.yml`; `sonar.projectKey`,
which is templated as `NoNameItem_${{ matrix.project }}`; `ty` (`[tool.ty.src] include =
["packages"]`); pytest `testpaths`; and commit-scope validation in `validate.py`, which discovers
projects through `projects.py`.

`CONTRIBUTING.md`'s "Adding a New Package" section is also corrected while we are in it: it tells
the reader to set the quality gate to `Sonar way`, which no project in this organisation uses, and
it does not mention the PyPI pending publisher at all.

## Manual external steps

Both must be done before this issue's pull request reaches CI — the `sonarcloud` job fails with
"Project not found" otherwise.

1. **SonarCloud.** ✚ → *Analyze new project* → *Setup a monorepo* → `NoNameItem/claude-tools`, key
   `NoNameItem_beadboard`. The GitHub binding has no public API endpoint on SonarCloud
   (`alm_settings/*` does not exist there), so this step cannot be scripted. Assigning the quality
   gate afterwards can be: `api/qualitygates/select`.
2. **PyPI.** Pending publisher for project `beadboard`: owner `NoNameItem`, repository
   `claude-tools`, workflow `publish.yml`, environment `pypi`.

## Deviations from the epic design

| Epic design | Here | Why |
|---|---|---|
| "plus the SonarCloud project itself and its `projectKey` in the `sonarcloud` job's `args:`" | no workflow change | the key is already templated from `matrix.project` |
| `README.md` in `.8` | a minimal one here | `pyproject` declares `readme`; the wheel does not build without it (D6) |
| PyPI publisher in `.8` | here | reserves the unprefixed name (D8) |
| — | issue templates deferred to `.8` | not mentioned in the epic; they serve users that do not exist yet (D7) |
| — | no `App.run_test()` smoke test yet | avoids `pytest-asyncio` in a skeleton (D5) |
| `data` / `app` module names | `repository` / `service` | corrected in the epic design itself, not carried as a deviation |

## Acceptance

- `uv run pytest` — all three suites green (`packages/*/tests`, `plugins/*/bin/tests`,
  `.github/scripts/tests`).
- `uv run ruff format --diff` and `uv run ruff check` clean on the changed files.
- `uv run ty check` clean, run without a path argument.
- `uv run beadboard` starts and exits on `q`.
- A deliberate violation — an import of `beadboard.ui` added to `model/__init__.py` — fails
  `test_import_boundaries.py`. Verified locally and reverted; this is what distinguishes a boundary
  test from a boundary comment.
- In CI: `Lint (beadboard)`, `Test (beadboard, py3.11 … py3.14)` and `SonarCloud (beadboard)` green,
  with the project on the `NoNameItem way` gate.
