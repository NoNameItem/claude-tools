# Flow Dolt Modes & Shared-Server Strategy — Design

**Date:** 2026-06-26
**Status:** Approved — ships in the same effort as the bd 1.0.0+ migration
**Related:** `2026-06-25-flow-dolt-native-sync-design.md` (the Dolt-native sync redesign this extends).
Implemented on branch `feature/claude-tools-akt-redesign-flow-sync-for-dolt` / **PR #85** (treated as
one continuous "migrate to bd 1.0.0+" effort).

---

## 1. Context & goal

bd 1.0.x supports several Dolt storage modes; flow today implicitly assumes **embedded**. The user
views tasks through **Perles** (`https://github.com/zjrosen/perles`), which can only attach to a
**`dolt sql-server`** — i.e. a server-class mode. This raised two distinct questions:

1. **Plugin correctness:** make flow *mode-agnostic* so its skills work whether a project is in
   embedded or any server-class mode, without the user configuring flow per mode.
2. **Personal topology:** decide which mode the user's own machines should run.

Both are settled below. The plugin change (Part 1) is small, backward-compatible, and ships
regardless of mode. The topology decision is **shared-server** (Part 2), adopted operationally.

---

## 2. The mode landscape (analysis)

Grounded in bd **1.0.5** (Homebrew core) on this machine plus the upstream
`gastownhall/beads/docs/DOLT.md`.

| | Embedded (today) | Local server | **Shared-server** (chosen) | External / central (rejected) |
|---|---|---|---|---|
| Engine | in-process, no daemon | per-project `dolt sql-server` | one local server for **all** projects | remote `dolt sql-server` on another host |
| Data location | `.beads/embeddeddolt/` | `.beads/dolt/` | `~/.beads/shared-server/dolt/<prefix>/` | on the remote host |
| Default port | — | 3307 | **3308** | host-defined |
| Concurrency | single-writer (file lock) | multi-writer | multi-writer | multi-writer |
| Task sync to git | `bd dolt push/pull` → `refs/dolt/data` | same | **same (unchanged)** | ❌ none (server is the live truth) |
| Issues live in repo | ✅ (via `refs/dolt/data`) | ✅ | ✅ | ❌ |
| Works offline | ✅ | ✅ | ✅ (server is local) | ❌ (network round-trip per `bd` call) |
| Perles | ❌ | ✅ | ✅ (one endpoint, all projects) | ✅ |
| Ops overhead | none | a server per project | one local server per machine | provision + secure + back up a host |
| `auto-commit` default | **on** | **off** | **off** | off |

Key facts that shaped the decision:

- **Mode is fixed at `bd init`**, stored in `metadata.json` (`dolt_mode`). There is **no in-place
  switch** command. `bd dolt set` has no `mode` key; `bd migrate` covers schema/issues/hooks/sync,
  not mode. Switching = a **`bd backup` → re-init → `bd backup restore --force`** flow, which is
  **reversible** and **history-preserving** (preserves Dolt commits/branches, unlike a JSONL export).
- **Server-class modes default `auto-commit: off` by design.** Per upstream docs, firing
  `DOLT_COMMIT` after every write under concurrent load throws `"database is read only"`. The
  consequence for flow: a bare `bd dolt push` ships only *committed* commits, so an uncommitted
  working set never leaves the machine. flow must flush a commit before pushing (Part 1).
- **Store location is irrelevant to git-sync** (see §4): a database syncs to git only if it has a
  remote configured; that is per-database and independent of where the bytes sit on disk.

---

## 3. Decision

- **Recommended personal mode: shared-server.** It is the only option that adds Perles
  visibility *and local multi-writer* while **keeping everything embedded already gives us**:
  git-coupled sync via `refs/dolt/data`, offline operation, and issues-in-repo. One local server
  (`localhost:3308`) serves every project, and **sync policy is per-project**, so synced projects
  and local-only TODO projects coexist under one Perles view.
- **Rejected: external/central server.** It replaces git-coupled task sync with an always-online
  dependency, decouples issues from the repo, and turns the user into a database operator (security,
  backups, single point of failure). The wins (Perles-anywhere, zero-sync) do not justify losing
  offline + repo-coupled durability for a single-writer workflow.
- **flow itself stays mode-agnostic.** The plugin must work in embedded *and* any server-class mode,
  because not every project/machine (or other plugin users) will be shared-server. flow never
  inspects or manages the server — bd auto-starts it.

---

## 4. How beads data reaches git (clarified model)

This corrects a common misconception and underpins both the local-TODO use case and the
shared-server sync story.

The actual issue data is a **Dolt repository on disk**. It reaches git through a **special ref**,
not through `git add`:

```
Dolt store on disk ──(bd dolt push)──► refs/dolt/data on the configured git remote
  embedded:  .beads/embeddeddolt/                  (a special ref — NOT a branch,
  shared:    ~/.beads/shared-server/dolt/<prefix>/  NOT files in your worktree)
```

- The **only** beads files committed to your branches are tiny pointers:
  `.beads/{config.yaml,metadata.json,.gitignore,README.md}`. The store itself is never tracked.
- `bd dolt pull` / `bd bootstrap` reconstruct the local store *from* `refs/dolt/data`.
- Therefore the **physical store location does not affect sync** — only the remote configured on the
  database does. Shared-server changes *where the bytes sit locally*, not *how they reach git*.

**Repo finding:** the existing `beads-sync` branch (local + origin) is a **dead bd 0.47 daemon
artifact** — its tip is `bd daemon sync: 2026-06-25 02:12:36` (the daemon format; 1.0.x has no
daemon) and it snapshots the whole worktree (the 0.47 model). `sync.branch` is unset. It is cleaned
up in Part 2.

**Data-safety finding:** `refs/dolt/data` does **not** yet exist on origin — the post-cutover 1.0.5
store has **never been pushed**. The 122 issues currently live only in the local
`.beads/embeddeddolt` on this machine. Establishing the offsite copy is the first Part-2 step.

---

## 5. Part 1 — Flow plugin changes (mode-agnostic robustness)

Backward-compatible; embedded behavior is byte-identical. Scope: `plugins/flow/` → `feat(flow)`,
label **flow**. Not a breaking change.

### 5.1 Contract
flow is mode-agnostic. It issues the same `bd dolt` commands in every mode and never inspects or
manages the server. All cross-mode robustness lives in **one place — the `flow-sync` helper**.
Skills are unchanged except a factual doc fix in `sonar-sync`. No runtime mode-branching is added.

### 5.2 `flow-sync` — commit-flush before every remote op
Today `flow-sync push` runs bare `bd dolt push`. Under `auto-commit: off` (every server-class
mode's default) that ships nothing. Fix:

- Before the remote op, run `bd dolt commit` (verified: prints `Nothing to commit.`, exit 0 when
  clean — a true no-op under `auto-commit: on`; flushes pending under `off`/`batch`).
- Apply to **both `pull` and `push`** for symmetry (commit-before-pull turns a would-be dirty-tree
  merge failure into a clean merge; a no-op when clean).
- Keep it **best-effort**: if the commit errors (e.g. the `"database is read only"` class under
  concurrent load), warn on stderr and still attempt the op. The helper keeps its existing
  "never gate, always exit 0", no-remote, and op-failure messaging.
- Implementation: a `flush_commit()` helper called at the top of the pull and push paths, after the
  `has_remote()` gate.

### 5.3 `sonar-sync` — correct the stale backend rationale
Three places claim parallel `bd create` "conflicts with **SQLite**" (lines ~294, ~382, ~519). Under
Dolt that is wrong. Fix the *reason*, keep the *behavior*:

- Rationale → "embedded Dolt is single-writer (a file lock), so parallel `bd create` contends;
  sequential is the default that is safe in **all** modes."
- Add one informational line: server / shared-server modes accept concurrent writes, so parallel
  creation is safe there — but flow keeps sequential as the universal default.
- No logic change; the skill stays sequential.

### 5.4 README (`plugins/flow/README.md`)
Add a short **"Dolt modes (embedded / server / shared-server)"** subsection to the existing storage
section:
- All modes supported; flow is mode-agnostic.
- The §4 data-to-git model (special `refs/dolt/data`, not files).
- Shared-server is the recommended personal setup and why (Perles + keeps git sync/offline).
- The `auto-commit` caveat and that `flow-sync` neutralizes it (commit-flush).
- gitignore note: ignore server port files (`.beads/dolt-server.port`, `.beads/*.port`) if they
  appear in-repo; store dirs (`.beads/embeddeddolt/`, `.beads/dolt/`) stay ignored.

### 5.5 Tests (`plugins/flow/bin/tests/test_flow_sync.py`)
- Extend the fake-bd to record call order.
- Assert `dolt commit` runs **before** `dolt push`, and **before** `dolt pull`.
- Assert a failing `commit` still proceeds to the op (best-effort).
- Keep existing no-remote / op-failure / exit-0 cases green.
- Gates: `ruff format` + `ruff check --fix` on helper & tests; `pytest plugins/flow/bin/tests -q`.
  (No `ty` — flow bin is not type-checked.)

---

## 6. Part 2 — Operational adoption (shared-server) + cleanup

Procedure + one-time ops. Not part of the flow code PR; tracked separately. Several steps are
**outward-facing or destructive** and require explicit confirmation at execution time.

### 6.1 Data-safety
The post-cutover store has never been pushed (`refs/dolt/data` is absent on origin), so the 122 issues
live only on this machine. Rather than a separate pre-migration push, the **migration itself**
provides durability: the `bd backup` in 6.3 captures a full local copy, and the first post-migration
`flow-sync push` establishes `refs/dolt/data` offsite. Verify afterwards with
`git ls-remote origin 'refs/dolt/*'`. *(The first push is outward-facing — confirm before pushing.)*

### 6.2 Smoke test on a throwaway project (before touching the real store)
The upstream doc is `gastownhall/beads` `main`; the binary is Homebrew **1.0.5** — there may be
behavioral skew. On a scratch repo, validate:
1. `bd init --shared-server -p scratch …` → `bd dolt status --json` shows the shared-server mode and
   data under `~/.beads/shared-server/`.
2. `bd backup` → re-init → `bd backup restore --force` round-trips issues with history.
3. `flow-sync pull`/`push` work (issues reach `refs/dolt/data`).
4. Two git worktrees of the scratch repo resolve to the **same** database (the residual unknown).
5. `auto-commit: off` + write + `flow-sync push` → data lands on the remote (proves §5.2).
6. Perles attaches to `localhost:3308` and shows the project.
Record results in the implementation plan / PR.

### 6.3 Migrate claude-tools: embedded → shared-server
After 6.1–6.2 pass. Reversible, history-preserving (exact in-place steps to be confirmed by the
smoke test before running on the 122-issue store):
```
bd backup init <backup-dir> && bd backup sync          # full Dolt backup (commits + branches)
# re-init the project into shared-server mode (move-aside / fresh .beads as in the 0.47 cutover)
bd init --shared-server -p claude-tools --skip-agents --skip-hooks
bd backup restore --force <backup-dir>                 # overwrite fresh DB with full history
bd stats && bd list                                    # verify 122 issues
```
Reverse direction is the same flow with `bd init` (no `--shared-server`).

### 6.4 Local-only TODO project pattern
For a project whose tasks must never go to git: init it on the shared server with **no remote**
(`sync.remote` unset, never `bd dolt push`) — flow-sync sees no remote and no-ops. Benefits:
- Data lives entirely in `~/.beads/shared-server/` — nothing beads-related in the repo tree but the
  config pointer (zero risk of committing a store).
- Perles still shows it (it is a server) alongside synced projects.
- For a fully invisible footprint, `bd init --shared-server --stealth` uses `.git/info/exclude` so
  even the pointer files are not committed.
- ⚠️ A no-remote project has **no offsite backup** unless `bd backup` is configured.

### 6.5 Perles wiring
Point Perles at the local shared server (`localhost:3308`). flow needs no involvement.

### 6.6 `beads-sync` cleanup (the dead 0.47 artifact)
```
git worktree remove --force <repo>/.git/beads-worktrees/beads-sync   # registered stale worktree
git worktree prune
git branch -D beads-sync                                             # local
git push origin --delete beads-sync                                  # remote — OUTWARD-FACING, confirm
```

### 6.7 gitignore hygiene
Add server port files if they materialize in-repo (`.beads/dolt-server.port`, `.beads/*.port`).

### 6.8 Restructure the bd-0.47→1.0.5 migration runbook
Update `docs/bd-0.47-to-1.0.5-migration.md`:
- Remove the one-time machine setup (Part A) — already completed on this machine.
- Split the per-project procedure into two clearly separated variants: **with git sync** (configure a
  dolt remote, push/pull, issues reach `refs/dolt/data`) and **without sync** (local-only TODO: no
  remote, optionally `--stealth`).
- Reflect the mode choice (embedded vs shared-server) and point at this design for the shared-server
  rationale.

---

## 7. Verification / acceptance

**Flow code (Part 1):**
- flow-sync runs `bd dolt commit` before both push and pull; best-effort on commit failure.
- sonar-sync no longer references SQLite; sequential default retained with corrected rationale.
- README documents the modes and the data-to-git model.
- `pytest plugins/flow/bin/tests -q` green, including new call-order tests.

**Operational (Part 2):**
- `refs/dolt/data` exists on origin (offsite backup established).
- Smoke test results recorded.
- claude-tools runs in shared-server mode; `bd stats` = expected count; Perles attaches.
- `beads-sync` branch and worktree removed (local + origin).

---

## 8. Risks & open questions

- **Version skew** (gastownhall `main` vs Homebrew 1.0.5) — mitigated by the §6.2 smoke test.
- **Mode propagation across machines:** does shared-server mode travel via committed `config.yaml`
  (`dolt.mode`) or stay per-machine in `metadata.json` (`dolt_mode`)? In 1.0.5 mode currently reads
  from `metadata.json`, while the doc treats `config.yaml` as the committed source. Decide whether to
  commit the mode (uniform across machines) or keep it per-machine, and confirm `bd bootstrap` sets
  up a fresh clone in shared-server mode.
- **Persistent local server** consumes resources vs embedded's zero-process model.
- **Per-machine single point of failure** for all projects — acceptable because issues remain
  recoverable from `refs/dolt/data` in git.
- Local-only projects have no offsite backup unless `bd backup` is set up.

---

## 9. Out of scope

- External/central server (rejected in §3).
- flow managing server lifecycle (start/stop/convert) — bd auto-starts; conversion is a documented
  manual procedure.
- flow-sync external-server **no-op detection** — only relevant to the rejected central topology;
  revisit only if external mode is ever adopted. (Shared-server needs *no* no-op; sync is real.)
