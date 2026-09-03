# Design: Beadboard — a TUI for beads

**Task:** claude-tools-144
**Date:** 2026-09-02

## Problem

Three gaps that neither `bd` nor `/flow:start` closes.

**Watching several projects means walking between folders.** `bd` resolves its database from the
current directory, so a cross-project picture costs a `cd` per project. `/flow:start` is worse for
this purpose: it only reads one project, it only fits the start of a session, and it spends Claude
tokens to render what is essentially a list.

**Assembling the picture takes many commands.** `bd list`, `bd show`, `bd blocked`, `bd ready` each
answer one question; the state of a project is the union of several invocations plus the flags to
remember.

**Both existing views mix statuses together.** Issues of every status arrive in one stream, while
the shape that answers "what is going on" is a kanban board.

Beadboard is a standalone terminal application: it costs no Claude tokens, it holds several
projects at once, and it renders them as a board.

## Scope

### MVP — read only

- **Source registry.** A source is either a project folder or a Dolt server; a server expands into
  every database it hosts. Sources are managed from the app and from the config file. Projects
  arriving from two sources are deduplicated.
- **Project board.** Columns by status, trees inside the columns, clickable ghost ancestors.
- **Project switching** without restarting or changing directory.
- **Issue card** with the full description and relations; details are fetched on demand.
- **Refresh on request** (`r`). Auto-refresh is the next iteration; the architecture reserves the
  place for it.
- **Navigation, filters and search** within the loaded snapshot.

### Editing — after MVP

Increment order, fixed: **C + A**, then **B + D**.

- **C — creation.** A new issue, including as a child of the selected epic.
- **A — state.** Status change (moving a card between columns), claim/assignee, close with a
  reason, reopen, priority, `defer`.
- **B — fields.** Title, description, notes/design/acceptance, labels.
- **D — relations.** Dependencies and re-parenting, with a picker for the second issue and cycle
  protection.

### Out of scope

- **Comments.** Neither read nor written; the card keeps the `comment_count` badge only.
- The issue picker for `/flow:start`.
- Anything touching git, PRs or branches.
- bd administration: `init`, migrations, remote setup, compaction.
- Web and GUI frontends. Terminal only.

## Decisions

**D1. The registry holds sources, not projects.** A source is a project folder or a Dolt server.
The folder form works with any backend and carries a filesystem path; the server form registers
five projects at once with no per-project setup. Both are needed: the shared server on
`127.0.0.1:3308` already hosts `claude_tools`, `ordm`, `read_comics`, `scripts` and `beads_global`,
while `tkbeads` exists only on disk. Projects that arrive from both forms are deduplicated by the
bd `project id`, not by name.

**D2. Trees inside columns.** A column is a status; inside it, cards keep the parent-child nesting
rather than forming a flat list. A flat board loses the only context that makes a card like
"Reduce Cognitive Complexity (git.py:236)" mean anything.

**D3. Ancestors outside the column render as clickable ghosts.** A parent and its child are usually
in different columns — an epic is `open` while its child is `in_progress` — so a column that showed
only its own issues would strand every card. Ghost ancestors are drawn dim and unboxed, above the
real cards. An epic therefore appears in every column that holds its descendants; that duplication
is the point, the same way `git log --graph` repeats a branch line. Pressing Enter on a ghost
navigates to that issue's real card.

Rejected: rendering a parent only when its own status matches (strands cards in the common case);
aggregating a parent's status from its children (a column would stop meaning status — a closed
subtask would sit under `in_progress`); a single level of grouping (collapses a three-level tree).

**D4. Columns are statuses, from a fixed set.** bd ships seven statuses (`open`, `in_progress`,
`blocked`, `deferred`, `closed`, `pinned`, `hooked`) in four categories, and a project may add its
own. Seven columns do not fit a terminal. MVP fixes the column set; the exact list and the mapping
of statuses onto it are settled when the board screen is designed. Configurable columns are a
later feature, worth building only once custom statuses are actually in use.

`closed` is never loaded in full: the done column shows recently closed issues within a configurable
window.

**D5. MVP refreshes on request only.** `r` reloads the focused project's snapshot. Auto-refresh —
polling a cheap per-project fingerprint on a timer and reloading only what changed — is the next
iteration. Both are the same operation at the architecture level ("re-read the source"), so the
second does not rewrite the first. An event subscription is not available: neither the Dolt
sql-server nor the bd CLI offers a change channel.

A refresh preserves the cursor position and the expanded nodes. The screen must not jump.

**D6. A light snapshot plus details on demand.** The snapshot carries what the board draws; the
expensive and rarely read fields — description, notes/design/acceptance, version history — are
fetched when a card is opened. At 217 issues the loading cost is indistinguishable from a full
snapshot, but the boundary is what later makes auto-refresh cheap (only the light projection is
re-read) and keeps every project's descriptions out of memory on a multi-project screen.

**D7. Every write goes through `bd`, never straight to SQL.** ID generation, the audit trail,
dependency validation, auto-commit and remote sync all live in bd; writing around them drifts the
database silently. Reads may take a fast path; writes may not. This makes the deferred data-layer
choice a question about reading only.

**D8. Ports and adapters with a pure core.** The repository layer is isolated from the UI by an explicit
port, and the board's logic lives in pure functions rather than in widgets. See *Architecture*.

**D9. The entry point is the project board.** A summary page across all projects is an open
question — whether it is needed at all, what belongs on it, and whether it is the entry point — and
is decided by its own task, possibly outside MVP. Multi-project work in MVP is served by the project
switcher, one keystroke away.

## Architecture

### Modules

Dependencies point one way. There are no back edges.

```
ui  ──►  service  ──►  repository  ──►  model
             │                            ▲
             └────►  sources  ────────────┘
```

`ui`, `service`, `repository` and `sources` may all import `model`; nothing points the other way.
`repository` does not import `sources`: a repository is handed the project it reads, and knowing
how projects are discovered is `service`'s job.

Two names earn their oddity. The orchestration layer is `service`, not `app`, because
`beadboard.app` next to Textual's `App` reads as the same thing in every import. The storage layer
is `repository`, not `data`, because `data` and `sources` sound like the same concern while holding
different ones — `sources` knows which projects exist and where, `repository` knows how to read the
issues of one of them.

| Module | Owns | Knows nothing about |
|---|---|---|
| `model` | Domain types and **pure functions**: the tree, the column projection, ghost ancestors, filters, search | Everything else. No I/O, no `textual`, no `bd` |
| `sources` | The source registry, resolving a source into projects, deduplication | Issues, the board, the UI |
| `repository` | The `IssueRepository` port and its adapters; translating raw data into `model` types | The board, the screens, the registry |
| `service` | Orchestration: snapshots and their cache, `refresh`, lazy detail fetch, per-source failure isolation, keeping work off the render thread | Widgets and keybindings |
| `ui` | Screens, widgets, input, layout | How storage works or where the data came from |

What this buys: the trickiest logic — which ghosts belong in the `in_progress` column for a given
tree — is table-testable without a terminal and without a running Dolt; swapping the adapter
touches no file above `repository`; and the write increments (C+A → B+D) land in `repository` and
`service` as port methods rather than accreting onto widgets.

### Process model

One Textual application, one process. Every call into a source blocks — a `bd` subprocess or a SQL
query — so it runs on a worker off the render thread while the screen shows a loading state. No
background daemons: closing the app ends the process.

### Keeping the boundary

"`model` and `repository` do not import `textual`; `model` does not import `repository`" is
enforced by an import test, not by convention. A violation fails CI.

## Domain model and projections

### Types

**`Source`** — a registry entry: a project folder or a Dolt server. Resolves to zero or more
projects.

**`Project`** — name, issue prefix, bd `project id`, the source it came from, and the repository
path when one is known. The `project id` is the deduplication key: prefixes differ between projects
today, but nothing guarantees it.

**`Issue`** — the light projection the board draws: `id`, title, status, priority, type, labels,
assignee, parent, dependencies, dates, `comment_count`. Identity is globally the pair (project, id).

**`IssueDetail`** — loaded only when a card is opened: description, notes/design/acceptance, version
history. A separate type rather than optional fields on `Issue`, so that "the board does not have
this data" is visible in the type system.

**`ProjectSnapshot`** — a consistent slice of one project at a point in time: its issues plus the
load timestamp. Everything the board renders is computed from the snapshot and from nothing else; a
screen never reaches into a source itself.

### What the snapshot contains

Open issues, recently closed ones within the configured window, **and the full ancestry of every
included issue regardless of that ancestor's status**. Without this, a closed epic above an open
subtask has no ghost to draw, and the card is stranded again. Pulling ancestors one at a time during
rendering is exactly the N+1 the snapshot exists to avoid.

### Two structures, not one

`parent-child` links form a **forest** — the tree and the ghosts are built from it. All other
dependencies form a **DAG**, which takes no part in layout: it feeds the issue card and the
"blocked" markers. Merging them would leave the layout undefined, because the tree has to be a tree.

### The column projection

For each column (a column is a set of statuses):

1. Select the issues whose own status belongs to the column — these are the **cards**.
2. Take the union of those cards' ancestor chains; ancestors that are not themselves cards become
   **ghosts**.
3. Render the resulting sub-forest in traversal order.

A ghost is a role, not an entity: the same issue shown as context. Its clickability follows from
that — Enter navigates to the issue's real card.

The function is pure: a snapshot and a column set in, a layout out. This is what the table tests
cover.

## Screens and navigation

**Project board** — the main and entry screen, showing one focused project. On start it opens the
project used last (remembered in application state); failing that, the first in the registry;
with an empty registry, the sources screen.

**Project switcher** — an overlay rather than a screen: the registry's projects, search by name,
Enter to change focus. Each row shows the project's state — loaded, loading, unavailable. This is
what answers "watch several projects without walking between folders" in MVP.

**Issue card** — description, labels, assignee, priority, dates, ancestry, dependencies in both
directions, the comment count. Opened with Enter from the board; this is where the lazy
`IssueDetail` fetch happens. Every relation is a link out, and there is always a way back.

**Sources screen** — list, add a folder or a Dolt server, remove, check availability. Outside the
main working loop: needed on first run and rarely afterwards. Opens by itself when the registry is
empty.

**Navigation is one principle.** Every step inward — into a card, along a relation, into a subtree —
pushes onto a history stack; `Esc`/`Backspace` pops it. That is what makes ghosts and relations safe
to click: there is always a way back out of the graph.

Screens do not reach into sources, do not compute projections, and do not know about adapters. A
screen receives a finished layout and emits intents ("open issue", "switch project", "refresh").

## Design artefacts for screens

Screens are designed in two stages, and the artefact differs by stage.

**Structure first, in text or on a canvas.** Before any widget exists the questions are how many
columns fit, where ghosts sit, how dense a card is, and what a narrow terminal drops. ASCII
wireframes in the issue's own design doc answer them; when several variants need comparing side by
side, a Claude Design canvas does. An artboard imitating a terminal is bound by explicit
constraints, because HTML affords what a terminal cannot: a fixed cell grid, a monospace face,
colours only from Textual's theme tokens, borders only from Textual's border types, no radii,
shadows or gradients, and text only at integer cell positions. Without them a canvas produces a
layout nobody can build — and unlike a web mockup, the mismatch is not a wrong token but an
impossible one.

**Acceptance runs against real renders.** `App.save_screenshot()` writes an SVG of the actual
Textual render. Those SVGs, committed next to the spec, are what a finished screen is checked
against, in both themes. For a terminal UI the real renderer is cheaper to run than to imitate, and
the artefact is code, which cannot quietly drift from the implementation.

A screen issue's design therefore links its SVGs (or its canvas) from its *Mockups* section, and
its translation contract names Textual widgets — `Header`, `Footer`, `Tree`, `DataTable`, `Static`,
`Rule` — saying which widget renders each block, and for each hand-built block why no widget fit.

## Repository layer

### The port

`IssueRepository` is everything `service` knows about storage. Reads:

- **`resolve()`** — project identity and availability (id, prefix, name).
- **`list_issues(scope)`** — the light projection for the snapshot, including the ancestry of
  included issues.
- **`get_detail(issue_id)`** — description, notes/design/acceptance, history.
- **`fingerprint()`** — a cheap change indicator. Unused in MVP; present so that auto-refresh does
  not rewrite the port.

The write increments add methods to this same port. That is the only place writes will appear.

### Adapters

**`BdCliRepository`** — `bd -C <path> … --json` subprocesses. Behaves exactly like bd does by hand,
survives schema changes, needs no driver. Costs a process per query and requires the project to
exist on disk.

**`DoltSqlRepository`** — one connection to the shared sql-server, one database per project. Fast,
cross-project, needs no repository path. Depends on bd's internal schema, which nobody promises to
keep stable.

**`FakeRepository`** — fixture data, for testing `service` and the UI without bd or Dolt.

**Choosing the adapter is deferred to its own task**, as the epic records. The architecture only
guarantees the choice costs one config key and no edits above `repository`.

### Risk: server-only projects may be read-only

Writes go through `bd` (D7), and `bd` addresses a database via `-C <path>` or `--db`. A project
registered only through a Dolt server may have no folder on this machine. If bd cannot address a
database on the shared server without a project directory, such projects are **read-only**, which
must either be shown honestly in the UI or be prevented by requiring a path when a server is
registered. Cheap to check, and worth checking inside the data-layer task — before increment C
starts.

## Errors and states

State belongs to a project, not to the application: `not loaded` / `loading` / `loaded (with
snapshot time)` / `error (with text)`. An unreachable server, a missing folder, an incompatible bd
version — each is one project's error. The switcher shows it on that project's row and the others
keep working. No source-side failure crashes the application.

## Testing

- **`model` — table tests.** Column projection, ghosts, the tree, filters: a snapshot in, a layout
  out. No terminal, no bd.
- **Port contract tests.** One suite runs against every adapter, so `DoltSqlRepository` and
  `BdCliRepository` cannot drift apart. Those needing a live bd are marked `integration`.
- **UI over `FakeRepository`.** Textual runs the app under test; navigation scenarios need no
  external dependencies.
- **An import-boundary test**, per *Keeping the boundary*.

## Package and repository wiring

`packages/beadboard` joins the same uv workspace as `statuskit` and follows its conventions:
`src/` layout, hatchling, `requires-python >= 3.11`, a `beadboard` entry point in
`[project.scripts]`. Dependencies: `textual`, plus whatever the chosen adapter needs (a MySQL
driver for the SQL adapter; nothing external for the bd CLI one). Tests live in
`packages/beadboard/tests` and are picked up by the repo-wide `testpaths`.

Configuration lives at `~/.config/beadboard/config.toml` (honouring `$XDG_CONFIG_HOME`): the source
registry, the repository adapter, the column set, the auto-refresh interval.

**CI picks the package up on its own.** `detect_changes.py` builds its matrix from
`[tool.repo.project-types.python].paths = ["packages"]`, so lint and tests need no workflow change.
What does not come for free:

- `packages/beadboard/sonar-project.properties` — the scanner resolves it under `projectBaseDir`;
  plus the SonarCloud project itself and its `projectKey` in the `sonarcloud` job's `args:`.
- `packages/beadboard/AGENTS.md`, after `packages/statuskit/AGENTS.md`, for the Codex review.
- A `release-please-config.json` entry (`release-type: python`) and the manifest.
- The `beadboard` PR label and the commit-scope rule in `CLAUDE.md` / `CONTRIBUTING.md`.

**Publishing is generic.** `publish.yml` resolves the project, reads the name from
`pyproject.toml`, and publishes through a Trusted Publisher into the `pypi` environment. The only
manual step is registering the pending publisher on PyPI for the new package name.

## Decomposition

Each child issue runs the usual cycle: brainstorm → design doc → plan → implementation. Issues are
`claude-tools-144.1` … `claude-tools-144.14`; the blocking edges below are recorded in beads.

**MVP** — labelled `mvp`, priority P2.

1. **Package skeleton and repository wiring** (`.1`, chore). The workspace member, the entry point,
   an empty Textual application, the test directory and the import-boundary test — plus
   `sonar-project.properties` and the SonarCloud project, `AGENTS.md`, the release-please entry, the
   label and the commit-scope rule. Kept as one issue: a skeleton without green CI proves nothing,
   and the wiring has nothing to attach to without the skeleton. Blocks everything.
2. **Domain model and projections** (`.2`). Types, the `parent-child` forest, the dependency DAG,
   the column projection, ghost ancestors, filters and search. Settles the concrete column list.
   Blocked by 1.
3. **Repository layer** (`.3`). The port, the adapter choice (bd CLI / SQL / hybrid — the epic's deferred
   decision), the first working adapter, `FakeRepository`, contract tests. Includes checking the
   read-only risk above. Blocked by 1; takes its types from 2.
4. **Source registry** (`.4`). The source model, source-to-project resolution, deduplication, the
   config file, the sources screen. Blocked by 1 and 3.
5. **Board screen** (`.5`). Columns, trees, clickable ghosts, the navigation stack, `refresh`
   preserving position. The largest MVP issue. Blocked by 2, 3 and 4.
6. **Project switcher** (`.6`). The overlay, search, per-project load state, remembering the last
   focused project. Blocked by 5.
7. **Issue card** (`.7`). The full view, the lazy `IssueDetail`, navigation along relations. Blocked
   by 3 and 5.
8. **First release and publication** (`.8`, chore). `README.md`, registering the pending publisher
   on PyPI, the first release-please and `publish.yml` run, and verifying that `beadboard`
   installed from PyPI works on a clean machine. Blocked by 6 and 7 — the release waits for the
   whole MVP, not only for the issue card.

Order: 1 → (2, 3) → 4 → 5 → (6, 7) → 8.

**After MVP** — every issue below is blocked by 8.

9. **Summary page** (`.9`, P3). Decide whether a cross-project summary is needed, what belongs on
    it, and whether it is the entry point. The outcome is either the page itself — built within
    this issue — or a recorded decision not to build it.
10. **Auto-refresh** (`.10`, P4). Fingerprint polling, reloading only changed snapshots, preserving
    cursor position and expanded nodes.
11. **Increment C — creating issues** (`.11`, P2).
12. **Increment A — state operations** (`.12`, P2).
13. **Increment B — field editing** (`.13`, P4).
14. **Increment D — relations and re-parenting** (`.14`, P4).

## Open questions

- The summary page: needed, contents, entry point (issue 9).
- The concrete column list and the mapping of statuses onto columns (issue 2 / issue 5).
- The read path: bd CLI, SQL, or a hybrid (issue 3).
- Whether server-only projects can be written to at all (issue 3).
- Board and card layout in a narrow terminal (issue 5).
