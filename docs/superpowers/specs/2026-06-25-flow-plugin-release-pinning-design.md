# Pin Marketplace Plugins to Release Tags (Stop the master-leak)

**Task:** — (repo-level: marketplace release process)
**Date:** 2026-06-25
**Status:** Design

## Problem

The `flow` plugin is distributed through this repo's marketplace
(`.claude-plugin/marketplace.json`, marketplace name `nonameitem-toolkit`). The plugin
entry currently sources content from a **live path**:

```json
{ "name": "flow", "source": "./plugins/flow" }
```

So consumers receive whatever is on the **working tree / `master` HEAD**, while the version
label in `plugins/flow/.claude-plugin/plugin.json` only advances when a release-please PR
merges. Between releases, post-release `master` commits ride under the **previous** version
number — unreleased code wearing a released label.

Observed in practice: a flow change appeared in an unrelated project before the version was
bumped. Confirmed on disk — the marketplace is registered as a **live directory source**,
and the plugin is **enabled globally**:

- `~/.claude/plugins/known_marketplaces.json` → `nonameitem-toolkit.source =
  { "source": "directory", "path": "/Users/artem.vasin/Coding/claude-tools" }`,
  `installLocation` = the repo itself.
- `~/.claude/settings.json` → `"flow@nonameitem-toolkit": true` (user-level → every project).

Net: **globally enabled + content sourced from the live repo directory** ⇒ every project on
the machine reflects `master`. The version label is decorative; there is no way to pin a
project (including `claude-tools` itself) to a vetted release.

### Why the label doesn't gate this

Claude Code resolves a plugin's version from the first of: (1) `plugin.json` `version`;
(2) the marketplace entry `version`; (3) the git commit SHA, for git-hosted sources; (4)
`unknown`, for local dirs not in git. The leak is structural — the **source points at live
content**, so "what is served" is decoupled from "what the version says". The fix is to make
the source resolve to an immutable **release tag**, not the working tree.

## Goal

Every consumer of the marketplace — external users **and** this machine's other projects,
including `claude-tools` itself — runs the **last released tag** of each plugin. `master`
moves freely with zero leakage. Local development of unreleased changes is done
deliberately, per session, via `--plugin-dir`.

## Solution

Pin each plugin's marketplace `source` to its release-please tag (`<component>-<version>`,
e.g. `flow-2.1.0`), and **advance that pin inside the release-please PR itself** so the bump
is atomic and reviewed. A single generic CI step handles **all** marketplace plugins, so
future plugins need no workflow changes.

Three confirmed facts from Claude Code docs underpin this (see Constraints):
`git-subdir` sources accept a `ref`; version then resolves from the tag's `plugin.json`
(each tag = a distinct version → `/plugin update` picks it up); and `--plugin-dir` takes
precedence over a same-named marketplace plugin for that session.

### 1. `marketplace.json` — source becomes a tag-pinned `git-subdir`

Replace the live path with a `git-subdir` object (exact schema per docs — fields
`source`/`url`/`path`/`ref`, optional `sha`):

```json
{
  "name": "flow",
  "source": {
    "source": "git-subdir",
    "url": "NoNameItem/claude-tools",
    "path": "plugins/flow",
    "ref": "flow-2.1.0"
  }
}
```

The **marketplace file itself** is still read live from `master` HEAD; only the plugin
**content** is now frozen to the tag. Because `marketplace.json` lives at the repo root
(not inside `plugins/flow`), what the tag's tree says about `marketplace.json` is
irrelevant — consumers always read the pointer from `master` HEAD. This removes any
chicken-and-egg between "pin commit" and "tag content".

**One-time migration:** set `ref` to the current latest tag, `flow-2.1.0`.

### 2. Universal pin step — `.github/scripts/pin-marketplace-refs.sh`

A data-driven script: it iterates **every plugin in `marketplace.json`** and, for each one
that has an open release-please PR this run, writes that plugin's release tag into its
`source.ref` **on the plugin's own release PR branch**. No plugin name is hardcoded.

How each value is derived per plugin:

| Value | Source |
|---|---|
| marketplace entry name | `marketplace.json` → `.plugins[].name` |
| subdirectory path | `marketplace.json` → `.plugins[].source.path` |
| component (= tag prefix = branch suffix) | `release-please-config.json` → `.packages[<path>]."package-name"` |
| new version | `<path>/.claude-plugin/plugin.json` on the release PR branch (release-please already bumped it there) |
| release PR branch | `release-please--branches--master--components--<component>` (verified format — such branches already exist in the repo) |

The plugin↔component bridge is the **path**: `source.path` in `marketplace.json` equals the
package key in `release-please-config.json`. Non-plugin packages (e.g. `statuskit`, absent
from `marketplace.json`) are naturally excluded.

```bash
#!/usr/bin/env bash
# Pin each marketplace plugin's source.ref to its release tag, inside that
# plugin's own release-please PR branch. Generic over all marketplace plugins.
set -euo pipefail

MARKETPLACE=.claude-plugin/marketplace.json
RP_CONFIG=release-please-config.json
BRANCH_PREFIX="release-please--branches--master--components--"

git config user.name  "release-please[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

# Snapshot (name, subdir, component) for every plugin whose source is already a
# git-subdir object. Computed on the trigger ref (master) BEFORE we switch branches,
# so the release-please-config.json lookup never reads a checked-out release branch.
mapfile -t PLUGINS < <(
  jq -r '.plugins[]
         | select(.source | type == "object" and has("path"))
         | [.name, .source.path] | @tsv' "$MARKETPLACE" \
  | while IFS=$'\t' read -r name path; do
      comp=$(jq -r --arg p "$path" '.packages[$p]."package-name" // empty' "$RP_CONFIG")
      [ -n "$comp" ] && printf '%s\t%s\t%s\n' "$name" "$path" "$comp"
    done
)

for row in "${PLUGINS[@]}"; do
  IFS=$'\t' read -r NAME PATHX COMPONENT <<<"$row"

  BRANCH="${BRANCH_PREFIX}${COMPONENT}"
  git fetch origin "$BRANCH" 2>/dev/null || { echo "skip '$NAME': no open release PR"; continue; }
  git checkout -B "$BRANCH" "origin/$BRANCH"

  VERSION=$(jq -r '.version' "$PATHX/.claude-plugin/plugin.json")   # bumped by release-please here
  TAG="${COMPONENT}-${VERSION}"

  jq --arg n "$NAME" --arg ref "$TAG" \
    '(.plugins[] | select(.name == $n).source.ref) = $ref' \
    "$MARKETPLACE" > "$MARKETPLACE.tmp" && mv "$MARKETPLACE.tmp" "$MARKETPLACE"

  git diff --quiet -- "$MARKETPLACE" && { echo "'$NAME' already at $TAG"; continue; }
  git add "$MARKETPLACE"
  git commit -m "chore: pin $NAME marketplace ref to $TAG"
  git push origin "$BRANCH"
  echo "pinned '$NAME' -> $TAG"
done
```

### 3. Wiring in `.github/workflows/release-please.yml`

```yaml
    steps:
      - uses: actions/checkout@v4               # release-please-action leaves no working tree
        with: { fetch-depth: 0, token: "${{ secrets.RELEASE_PLEASE_TOKEN }}" }
      - uses: googleapis/release-please-action@v4
        id: release
        with:
          token: "${{ secrets.RELEASE_PLEASE_TOKEN }}"
          config-file: release-please-config.json
          manifest-file: .release-please-manifest.json
      - name: Pin marketplace refs in release PRs
        if: ${{ steps.release.outputs.prs_created == 'true' }}
        run: bash .github/scripts/pin-marketplace-refs.sh
```

At PR merge, the version bump, the `marketplace.json` pin, and the new tag all land
together — fully atomic. No direct push to `master`, no dependence on admin bypass.

### 4. Local development of unreleased flow changes

The marketplace copy is now tag-pinned, so the working tree is not what loads by default.
To test unreleased changes inside `claude-tools`:

```bash
claude --plugin-dir /Users/artem.vasin/Coding/claude-tools/plugins/flow
```

`--plugin-dir` **takes precedence** over the same-named marketplace plugin for that session
(no duplicate skills / name clash); `/reload-plugins` picks up edits. Exiting the session
returns to the tag-pinned version. (Documented behavior — see Constraints.)

### 5. Consumer migration (one-time)

Because `flow` is enabled globally, after the source change each project that has it active
runs `/plugin update flow` once to move from the live-directory copy to the tag copy.
Note: third-party / local marketplaces have **auto-update off by default**, so post-release
updates are explicit (`/plugin update`) — desirable (no surprise updates). Auto-update can be
opted into per marketplace if "only releases, automatically" is wanted.

## Key properties / invariants

- **Idempotent.** `git diff --quiet` ⇒ no commit/push when already pinned. Re-runs are safe.
- **Self-healing.** release-please owns and force-pushes its release branch; the step runs
  after the action in the same job, so the pin is re-applied on top of the regenerated
  branch every run. With two plugins releasing at once, each is pinned on its **own** branch;
  after one merges, the other is regenerated atop the new `master` and re-pinned — no
  `marketplace.json` conflict.
- **Atomic & reviewable.** The pin is a commit in the release PR; it merges with the bump and
  is visible in "files changed".
- **Migration filter.** `select(.source | type=="object")` skips legacy string sources
  (`"./plugins/x"`); a new plugin is only auto-pinned once its `source` is a git-subdir
  object — the deliberate one-time step when adding a plugin.

## Constraints / confirmed facts

From Claude Code docs (verified during brainstorming):

- **`git-subdir` schema** — `source: "git-subdir"`, `url` (accepts `owner/repo`
  shorthand), `path` (subdir), `ref` (branch/tag), optional `sha`.
  `plugin-marketplaces.md#git-subdirectories`.
- **Version resolution** — `plugin.json` `version` wins; for git-hosted sources each
  distinct tag (distinct `plugin.json` version) is a new version and triggers update on
  `/plugin update`. `plugins-reference.md#version-management`.
- **`--plugin-dir` precedence** — a local plugin dir overrides a same-named marketplace
  plugin for that session, no coexistence/clash. `plugins.md#test-your-plugins-locally`.

From release-please-action v4 (`/googleapis/release-please-action`):

- Manifest mode exposes per-path outputs `<path>--release_created` / `--tag_name` /
  `--version` / `--sha`, and top-level `prs_created` / `releases_created`. Paths with `/`
  are read via `steps.release.outputs['plugins/flow--tag_name']`.

From this repo:

- `master` protection: required PR + required checks + linear history, **`enforce_admins:
  false`**. (Relevant only as the fallback rationale; the chosen fold-in-PR design merges
  through the normal PR and does **not** rely on this.)

## Open implementation details (resolve in the plan — not blockers)

1. **Commit scope vs the "Validate PR" check.** `.claude-plugin/marketplace.json` is a
   root config → per CONTRIBUTING/CLAUDE.md that is **no scope** (`chore:`, label `repo`).
   The script already uses `chore: pin …`. Verify against `pr.yml` / the PR-validation rule
   so the pin commit on the release branch doesn't fail required checks.
2. **PAT push re-triggers `pr.yml`.** Pushing to the release branch under
   `RELEASE_PLEASE_TOKEN` re-runs PR checks (keeps required checks green — good). Confirm no
   unexpected loop. `release-please.yml` triggers only on `master`, so it does not re-run.
3. **`actions/checkout` before the action.** Confirm release-please-action@v4 leaves no
   usable working tree (it uses the API); the explicit checkout above is included so the
   git/jq step works.
4. **`RELEASE_PLEASE_TOKEN` permissions.** Pushing to the (unprotected) release branch needs
   only write access — already held. Admin/bypass is **not** required by this design.

## Scope

**In:**
- `.claude-plugin/marketplace.json` — `flow` source → tag-pinned `git-subdir` (`flow-2.1.0`).
- `.github/scripts/pin-marketplace-refs.sh` — new generic pin script.
- `.github/workflows/release-please.yml` — explicit checkout + pin step.
- One-time consumer migration note (`/plugin update flow`).

**Out of scope (decided during brainstorming):**
- **Branch-pointer approach (`ref: "stable"` + CI moving a `stable` branch)** — rejected: an
  extra long-lived mutable branch; the user prefers immutable per-version tags.
- **Post-merge push to `master`** — rejected in favor of fold-in-PR: it adds an extra commit
  to `master` and leans on `enforce_admins: false`. Fold-in-PR is atomic and merges normally.
- **Letting release-please write the ref via `extra-files`** — not possible: its updaters
  write the **bare** version (`2.2.0`), but `ref` needs the prefixed tag (`flow-2.2.0`).
- **Convention-based simplification** (component == marketplace name == subdir basename ⇒
  drop the `release-please-config.json` lookup, `COMPONENT="$NAME"`) — noted as an option;
  the robust config-driven form is the default.

## Testing / validation

- **Script (local, before wiring):** run `pin-marketplace-refs.sh` against a fixture
  checkout with a fake open release branch; assert the right `source.ref` is written, that a
  second run is a no-op (idempotent), and that a string-source plugin is skipped.
- **`marketplace.json` validity:** the existing "Claude Code Plugin CI" must still pass with
  the `git-subdir` object source.
- **Dry-run the flow:** open a trivial `feat(flow)` PR, let release-please raise its release
  PR, confirm the pin commit appears on the release branch with the correct
  `flow-<next>` tag and that required checks go green.
- **Post-merge:** confirm `master` `marketplace.json` points at the new tag and the
  `flow-<next>` tag exists at the merge commit.
- Pre-commit hygiene on any Python touched (none expected here; the script is bash —
  `shellcheck` it if available).

## Rollout sequence

1. Migrate `marketplace.json` `flow` source → `git-subdir` @ `flow-2.1.0`; verify Plugin CI.
2. Add `.github/scripts/pin-marketplace-refs.sh` + wire `release-please.yml`.
3. Resolve open details 1–3 against `pr.yml` during implementation.
4. Exercise via the next real flow release; confirm the atomic pin.
5. `/plugin update flow` in active projects to leave the live-directory copy behind.
