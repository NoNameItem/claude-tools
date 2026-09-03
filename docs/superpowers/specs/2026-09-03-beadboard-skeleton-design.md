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
CodeRabbit path instructions; the commit-scope rule in `CLAUDE.md` and `CONTRIBUTING.md`; two
external registrations (the SonarCloud project with Automatic Analysis off, the PyPI pending
publisher).

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
dependency. Checked 2026-09-03: the current release is 8.2.8, `requires-python >=3.9,<4`, with a
3.14 classifier — the whole 3.11 – 3.14 test matrix is supported.

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
under development, and points at the epic design. It opens with the CI badge
(`badges-data/beadboard.json`), which `publish_badges.py` fills in automatically from the job
names and which therefore works from the first push to master; the PyPI badges only resolve after
the first release and belong to `.8`.

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

**D10. beadboard inherits statuskit's two Sonar rule mutes.** `python:S1192` (duplicated string
literals, MAINTAINABILITY/HIGH — it blocks the merge under `NoNameItem way`) and `python:S107` (too
many parameters, MEDIUM) are copied into beadboard's `sonar-project.properties` with the same
written rationales. Neither argument is about statuskit: S1192 asks for a constant where the
literal itself reads better, and S107 is the Sonar half of `PLR0913`, which the root
`pyproject.toml` disables repository-wide. Muting them before the first violation costs nothing and
keeps the tracker honest; a *third* mute still has to arrive with its own reason next to it.

Checked on the statuskit project so that beadboard is not configured against a half-picture
(2026-09-03): its Python quality profile is the built-in `Sonar way` (481 rules — the custom
`python` profile in the organisation belongs to `read-comics`), and the only project-level setting
that is not inherited is `sonar.autoscan.enabled = false`. That setting is the one manual step this
design nearly missed — see *Manual external steps*.

**D11. The manifest starts at `0.0.0`, so the MVP is released as `0.1.0`.** release-please reads
the manifest as the version *already released* and computes the next one from the commits on top of
it. statuskit was bootstrapped at `0.1.0` — a version that predated the tool, with a hand-written
changelog — and its first automatic release was consequently `0.2.0`. Writing `0.1.0` here would
ship the MVP as `0.2.0`. With `0.0.0` in the manifest and in `pyproject.toml`, `bump-minor-pre-major`
on and `bump-patch-for-minor-pre-major` off, the first `feat:` bumps the minor: `0.0.0` → `0.1.0`,
tag `beadboard-0.1.0`, GitHub release flagged pre-release, `publish.yml` to PyPI. Nothing seeds
`CHANGELOG.md`; release-please writes it with that first release. Rejected: a `Release-As:` commit
footer or a `release-as` config key, both of which need removing afterwards, and `initial-version`,
which this repository has never exercised. Accepted cost: until the first release
`sonar.projectVersion` reads `0.0.0` — cosmetic.

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
| `version` | `0.0.0` | nothing released yet; release-please owns it from here on (D11) |
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
| `uv.lock` | regenerated locally, **not committed** — the lock is listed in `.gitignore` and is untracked; CI resolves from scratch on every `uv sync` |
| `release-please-config.json` | a `packages/beadboard` entry: `release-type: python`, `package-name: beadboard`, `bump-minor-pre-major`, `prerelease`, `extra-label: "ci:full,beadboard"` |
| `.release-please-manifest.json` | `"packages/beadboard": "0.0.0"` (D11) |
| `packages/beadboard/sonar-project.properties` | scanner properties; the file must sit in the package because CI sets `projectBaseDir: packages/beadboard`. Carries statuskit's two rule mutes from the first analysis (D10) |
| `packages/beadboard/AGENTS.md` | architecture summary and review rules for the subtree; the layering rule is the P1 item |
| `CLAUDE.md` | `beadboard` in the commit-scope and PR-label tables — and in the three places that table does not cover: the Overview ("two types of tools"), the terminology examples, and the Project Structure tree |
| `CONTRIBUTING.md` | the same two tables, plus the "Adding a New Python Package" corrections below |
| `AGENTS.md` (root) | `packages/beadboard/` added where it enumerates the nested `AGENTS.md` files |
| `.coderabbit.yaml` | a `packages/beadboard/**` entry under `path_instructions`; statuskit has one, and without it the subtree is reviewed with no architectural context |
| GitHub | the `beadboard` label, colour `#ff7f0e` — the next free colour in the palette `statuskit`/`flow`/`repo` already use |

**What needs no change**, because it is derived from `[tool.repo]` and from paths: the CI matrices
in `detect_changes.py`; lint, test and Sonar jobs in `_reusable-python-ci.yml`; `sonar.projectKey`,
which is templated as `NoNameItem_${{ matrix.project }}`; `ty` (`[tool.ty.src] include =
["packages"]`); pytest `testpaths`; and commit-scope validation in `validate.py`, which discovers
projects through `projects.py`.

Five more were checked against the live repository and organisation rather than assumed, so the
next project need not check them again: the master ruleset's required status checks (the required
contexts are the aggregate `Python CI Gate` / `Claude Code Plugin CI Gate` jobs, never per-project
ones); the Python quality profile (built-in `Sonar way`, no custom profile to attach); the new-code
definition (statuskit carries no project-level override either, so beadboard inherits the same
default); ruff `per-file-ignores` (the `**/tests/**` pattern already covers the new tests); and
dependabot / CODEOWNERS, neither of which exists in this repository.

`CONTRIBUTING.md`'s "Adding a New Python Package" section is also corrected while we are in it —
followed literally today, it does not produce a working project:

- it sets the quality gate to `Sonar way`, which no project in this organisation uses (D4);
- it never mentions turning Automatic Analysis off — the one setting that actually breaks CI;
- it stops at the package directory and SonarCloud: the root `pyproject.toml` wiring, the
  release-please entry and its manifest line, the GitHub label and the CodeRabbit path
  instructions are all absent;
- it says nothing about the PyPI pending publisher;
- its `uv run ty check packages/statuskit` contradicts `CLAUDE.md`, which requires `ty` to be run
  without a path argument.

Its step 3 stays as it is and is load-bearing for `.8`: master must carry a successful analysis
before the first release is cut, or the release notification ships with no Sonar blocks at all.

## Manual external steps

Both must be done before this issue's pull request reaches CI — the `sonarcloud` job fails with
"Project not found" otherwise.

1. **SonarCloud.** ✚ → *Analyze new project* → *Setup a monorepo* → `NoNameItem/claude-tools`, key
   `NoNameItem_beadboard`. The GitHub binding has no public API endpoint on SonarCloud
   (`alm_settings/*` does not exist there), so this step cannot be scripted. Two settings on the
   new project then have to be changed, and both are scriptable:

   - **Automatic Analysis off.** It is on for every new project and collides with the CI analysis.
     The setting is per-project and is not inherited — statuskit carries
     `sonar.autoscan.enabled = false`, which is its only non-inherited setting (D10).
     `POST api/settings/set?component=NoNameItem_beadboard&key=sonar.autoscan.enabled&value=false`.
   - **Quality gate `NoNameItem way`** (D4): `POST api/qualitygates/select`.
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
  with the project on the `NoNameItem way` gate and the analysis arriving from the CI scanner —
  SonarCloud shows no "Automatic Analysis" run for the project (D10, *Manual external steps*).
