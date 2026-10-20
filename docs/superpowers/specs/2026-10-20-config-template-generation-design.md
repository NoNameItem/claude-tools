# Config template generation and `config init` / `config sync` (subtask)

**Task:** claude-tools-5dl.9.2
**Parent:** claude-tools-5dl.9 — `2026-06-18-declarative-module-config-design.md` (whole-feature
context). Sibling: claude-tools-5dl.9.1 — `2026-06-22-declarative-module-config-parsing-design.md`
(the `param()` / `parse_params()` / `BaseModule[P]` machinery this subtask consumes).
**Date:** 2026-10-20
**Status:** Design approved

This spec covers only 5dl.9.2. Where it differs from the parent or from the 9.1 "carried-over
issues" section, **this spec wins**. Write the code against the current source, not against the
two earlier specs: the code has moved on since (one frozen `@schema` decorator instead of
`params_schema`/`config_schema`, `cache_ttl` defaults to `120`, `model_time_format` instead of
`sonnet_time_format`, new `models_always_show` / `models_never_show` / `show_pr` / `pr_*` fields).

### Changes from the parent design

| Parent / 9.1 said | This spec |
|---|---|
| `config sync` appends commented stubs for missing keys, never touching existing lines | `config sync` **rebuilds the whole file** from the schema, carrying the user's valid values over |
| `config validate` command (9.1 carry-over) | dropped; `config sync --dry-run` reports the same problems and exits non-zero |
| no file selection for `config *` | `--scope user\|project\|local`, same as `setup` |
| output "matches the current `DEFAULT_CONFIG` shape" | new layout (below): description above each option, choices as a block, section headers always active |

## Why

Two audiences, two reasons:

- **The developer** (the repo owner) keeps defaults convenient for themselves and rarely edits
  their own `statuskit.toml`. For them the value is that the template is **generated from the
  `param()` declarations** and can no longer drift from the code. Today it has drifted:
  the hardcoded `DEFAULT_CONFIG` in `setup/config.py` omits `colors`, shows
  `models_always_show = ["Fable"]` while the real default is `[]`, lists only `relative`/`compact`
  for `commit_age_format` (the code also has `raw`), and carries no per-option descriptions.
- **PyPI users** who tune statuskit by hand. For them the value is a config file that **lists
  every existing option** with its default and description, **without losing what they already
  set**. After an upgrade they run `config sync` and get the new options in their file.

## Goals

1. One generator builds the config text from `Config`'s schema fields and every built-in module's
   params class. Nothing about options is hand-written anywhere else.
2. `statuskit config init` writes the full default template.
3. `statuskit config sync` rebuilds an existing file into the canonical template, keeping every
   valid user value (the one exception is the `modules` cleaning of decision 16), removing
   everything the schema does not know, and saying what it removed.
4. `statuskit setup` writes the same generated template (it already creates a config when missing).

### Non-goals

- Per-module generation (`config init --module git`). Deferred by the parent; the rebuild model
  makes it unnecessary.
- Preserving the user's own comments, blank lines, or key order. Explicitly accepted: the file is
  rebuilt every time. The file header says so.
- A separate `config validate` command (see `--dry-run`).
- Showing value constraints (min/max) in the template — that belongs to claude-tools-5dl.9.3, which
  may extend the generator later.
- Fixing the stale `MODULES_HELP` epilog in `cli.py` (still lists `beads`/`quota`) — that is
  claude-tools-5dl.11.5.

### Anti-goals (would be a failure even if it "works")

- A valid value the user set is lost or changed by `sync` — except the reported `modules`
  cleaning of decision 16.
- Uncommenting a single option line in the generated file does not produce a working setting
  (wrong section, duplicate table, TOML error).
- A key, section or `modules` entry is removed without appearing in the report. (The user's own
  comments are dropped without a report by design; the file header says so.)
- Any option text (key, default, description, choices) is written by hand outside `param()`.

## Mockups

No mockups — CLI only. The template excerpt in *Template format* is the layout reference; the
exact bytes are pinned by the golden-file test.

## Decisions

Marked **(user)** where the repo owner decided it in the design conversation, **(builder call)**
where the spec author settled it; the builder may revisit builder calls if the code argues
otherwise, but must not revisit user decisions.

1. **(user)** `sync` = rebuild, not append: build the canonical template, merge in the user's
   values, replace the file.
2. **(user)** Everything in the user's file that the canonical config does not contain is removed:
   unknown top-level keys, unknown keys inside a module section, renamed/removed options, sections
   of unknown modules. The output contains only options that really exist.
3. **(user)** The template contains **all built-in modules**, not only those listed in `modules`.
   (Reason: `sync` removes what the template lacks, so a "listed modules only" template would
   delete the settings of a module the user temporarily disabled.)
4. **(user)** `--scope user|project|local` on both commands, default `user`, resolved with the
   existing `setup.paths.get_config_path(scope)`.
5. **(user)** No `config validate`; `config sync --dry-run` instead.
6. **(user)** Layout as in *Template format*: description on its own line above the option, choices
   as a block, section headers always active, module order model → git → usage_limits.
7. **(builder call)** A user value that equals the default stays **active** — the user pinned it
   explicitly.
8. **(builder call)** A known key with an invalid value (`bar_width = "huge"`,
   `context_format = "freee"`) is treated like an unknown key: dropped (the option goes back to its
   commented default) and reported with the validation message. This matches how `load_config`
   already ignores such values at render time.
9. **(builder call)** Before overwriting an existing file, back it up with the existing
   `setup.hooks.create_backup` (single `<file>.bak`, overwritten each time). No backup and no write
   when the rebuilt text is byte-identical to the current file.
10. **(builder call)** `sync` on a missing file creates it (same result as `init`).
11. **(builder call)** A file that cannot be read or parsed (`OSError`, `UnicodeDecodeError`,
    `tomllib.TOMLDecodeError`) is never touched; the command prints the error and exits 1.
12. **(builder call)** Values are written in canonical form (`modules = [ 'git' ]` →
    `modules = ["git"]`).
13. **(builder call)** A module that is not in the effective `modules` list (the user's valid value,
    else the default) gets a one-line note in its section banner telling how to enable it.
14. **(builder call)** `BUILTIN_MODULES` in `core/loader.py` is reordered to model, git,
    usage_limits so the generator can iterate it directly. Render order is unaffected (it follows
    `config.modules`).
15. **(user)** The README stops documenting options. The per-module parameter tables and the
    per-option value tables are removed; the README instead says that `statuskit config init`
    writes a config listing every option with its default and description. See *README*.
16. **(user)** The `modules` list is cleaned: names that are not built-in modules and repeated
    names (second and later occurrences) are struck out, the order of the rest is kept, and each
    struck name is reported (`modules: "beads" — unknown module`, `modules: "git" — duplicate`).
    `parse_params` accepts any `list[str]`, so this is an extra check in `build_config`; without
    it `sync --dry-run` would return 0 on a file statuskit partly ignores (the loader skips
    unknown names silently outside debug). Resetting the whole list to the default was rejected:
    it would re-enable modules the user deliberately left out.

## Template format

Reference excerpt — the user has set `modules = ["model", "git"]` and `context_format = "bar"`,
everything else is default:

```toml
# Statuskit configuration — https://pypi.org/project/claude-statuskit/
#
# Every option is listed with its default value, commented out.
# Uncomment a line and change the value to override it.
# `statuskit config sync` rebuilds this file: your values are kept,
# unknown keys are removed, your own comments are not preserved.

# Modules to display (in order)
modules = ["model", "git"]

# Enable debug output
# debug = false

# Colored output
# colors = true

# Cache directory
# cache_dir = "~/.cache/statuskit"

# ─────────────────────────────────────────────────────────────
# model: Model name, session duration, context window usage
# ─────────────────────────────────────────────────────────────
[model]

# Show session duration
# show_duration = true

# Context display format:
#   "free"  — free tokens remaining — e.g. `150,000 free (75.0%)`
#   "used"  — tokens consumed — e.g. `50,000 used (25.0%)`
#   "ratio" — used / total — e.g. `50,000/200,000 (25.0%)`
#   "bar"   — progress bar — e.g. `[███████░░░] 75%`
context_format = "bar"

# Compact number format (150k instead of 150,000)
# context_compact = false

# ... remaining model options ...

# ─────────────────────────────────────────────────────────────
# usage_limits: API usage limits (5h session, 7d weekly, per-model)
# Not enabled — add "usage_limits" to `modules` to show it.
# ─────────────────────────────────────────────────────────────
[usage_limits]

# ...
```

(The `Not enabled` line appears only when that module is missing from the effective `modules`;
with the default `modules` no module carries the note.)

Rules:

- **Header**: the fixed comment block shown above.
- **Global block**: `Config`'s schema fields (dataclass fields whose metadata has `"type"`), in
  declaration order: `modules`, `debug`, `colors`, `cache_dir`. `module_configs` is internal and
  never emitted. Global options come before the first table, so uncommenting one keeps it
  top-level.
- **Module sections**: one per `BUILTIN_MODULES` entry, in registry order. A banner (rule line,
  `# {name}: {description}` using the module class's `name` / `description`, optional
  `Not enabled` line, rule line), then an **always active** `[name]` header — an empty TOML table
  is valid, so uncommenting one option line inside it is enough. Fields come from the module
  class's `_params_class` (resolved by `BaseModule.__init_subclass__`), in declaration order.
- **Per option**: blank line, `# {description}` line, choices (if any), then the option line:
  - not set by the user → `# key = <default>`;
  - set by the user with a valid value → `key = <value>`.
- **Choices, dict form** (`{value: help}`): the description line gets a trailing `:`; then one line
  per value, `#   <value> — <help>`, values rendered as TOML, left-aligned and padded with spaces
  on the right to the widest value in that block (as in the excerpt). All current choices use the
  dict form.
- **Choices, tuple form**: one line `# Choices: <v1>, <v2>, ...` after the description (no field
  uses it today; it must still render).
- The file ends with exactly one newline. Exact blank-line placement follows the excerpt and is
  pinned by the golden file.

### Value serialization

A `toml_value(v)` helper renders a Python value as a TOML literal. Allowed inputs are exactly what
`schema._check_declared_type` admits: `bool`, `int`, `float`, `str`, and `list`/`tuple` of those.

- `bool` before `int` (`True` → `true`), `int` → decimal.
- `float` → `repr()`, except `inf`/`-inf`/`nan` → `inf`/`-inf`/`nan`.
- `str` → TOML basic string `"..."`, escaping `\` and `"`, the control characters (`\b \t \n \f \r`,
  others as `\uXXXX`) and DEL (U+007F). Other characters, including non-ASCII, are written as-is
  (the file is UTF-8).
- `list` / `tuple` → `[a, b]` (`[]` when empty).
- Contract: for every allowed value, `tomllib.loads(f"k = {toml_value(v)}")["k"]` equals `v`
  (a tuple comes back as a list).

## Rebuild algorithm

`build_config(data: dict | None) -> tuple[str, list[Removal]]` in `setup/config_gen.py`:

1. `data` is the parsed TOML of the user's file (`None` / `{}` for a fresh template).
2. Split it into top-level non-table keys and tables — the same split `load_config` does. Extract
   that split into a small shared helper in `core/config.py` and use it in both places.
3. Globals: `values, warnings = parse_params(Config, non_section)`. Every warning becomes a
   `Removal` (`location` = the bare key, e.g. `colors`; `reason` = the warning message).
   If `modules` survived validation, clean it (decision 16): walk the list, keep the first
   occurrence of each name that is a `BUILTIN_MODULES` key, and record
   `Removal(location='modules: "<name>"', reason="unknown module" | "duplicate")` for every
   other element. The cleaned list stays active even if it ends up empty or equal to the default
   (decision 7); an empty list renders nothing, exactly as the uncleaned list did, since the
   loader skips unknown names. The `Not enabled` notes are computed from the cleaned list.
4. For each table: if its name is a `BUILTIN_MODULES` key, `parse_params(module._params_class,
   table)`; each warning becomes a `Removal` with `location` `"{section}.{key}"`. A nested table
   inside a module section (`[git.extra]`) arrives as an unknown key and is removed the same way.
   A table whose name is not a built-in module becomes `Removal(location="[name]", reason="unknown
   section")`.
5. Render the template (previous section) with the validated values: every key in `values`
   renders active, every other schema field renders as its commented default.
6. Return the text and the removals in file-walk order (globals first, then sections in the user
   file's order; within a section, in the order the keys appear in the file). `parse_params`
   emits `unknown` warnings from a set difference, so `build_config` reorders them by the raw
   dict's key order — the report must be deterministic.

`Removal` is a small frozen dataclass `(location: str, reason: str)`. `build_config` is pure: no
I/O, no printing.

Invariant (tested): re-parsing the produced text and running `build_config` on it again yields the
same text and no removals — `sync` is idempotent.

## File operations

In `setup/config.py`, next to the existing `create_config` and following the `InstallResult`
pattern of `setup/commands.py` (a result dataclass, no printing):

- `create_config(path) -> bool` — unchanged contract (create if missing, never overwrite), now
  writes `build_config(None)` text. `DEFAULT_CONFIG` is deleted. `setup` keeps calling it.
- `init_config(path, *, force) -> InitResult` — missing file → write template; existing file and
  not `force` → refuse; existing file and `force` → `create_backup`, write template.
- `sync_config(path, *, dry_run) -> SyncResult` — missing file → create (or, in dry-run, report
  that it would be created); unreadable/unparsable → error result, nothing written; otherwise
  `build_config(parsed)`, compare with the current text, and if different (and not dry-run)
  back up and write. The result carries the outcome (created / unchanged / updated / error), the
  backup path if any, and the removals.

Write with `path.write_text(text, encoding="utf-8", newline="\n")` — always LF, so the
byte-for-byte "unchanged" comparison holds on every platform — creating parent directories as
`create_config` does today. Read the current bytes once, and parse them with `tomllib.loads` after
a strict UTF-8 decode; compare the rebuilt text against the same decoded content.

The `config` commands touch only the config file. `--scope local` does **not** update
`.gitignore` — that stays `setup`'s job.

## CLI

```
statuskit config init [--scope user|project|local] [--force]
statuskit config sync [--scope user|project|local] [--dry-run]
```

- `cli.py`: a `config` subparser with required `init` / `sync` sub-subparsers. `statuskit config`
  with no action is an argparse usage error (exit 2).
- `__init__.py`: `main()` dispatches `args.command == "config"` to a `_handle_config(args)` that
  calls the file operations and prints, mirroring `_handle_setup`.
- Paths: `get_config_path(Scope(args.scope))`. Project/local scopes are relative to the current
  directory, exactly as in `setup`.

Messages (wording may be polished; the content and exit codes are the contract):

| Situation | Output | Exit |
|---|---|---|
| `init`, file missing | `✓ Created <path>` | 0 |
| `init`, file exists | `<path> already exists. Run 'statuskit config sync' to update it, or 'config init --force' to reset it to defaults.` | 1 |
| `init --force`, file exists | `✓ Reset <path> to defaults (backup: <path>.bak)` | 0 |
| `sync`, file missing | `✓ Created <path>` | 0 |
| `sync`, nothing to change | `<path> is up to date.` | 0 |
| `sync`, rebuilt | `✓ Updated <path> (backup: <path>.bak)` + removal list | 0 |
| `sync`, unreadable/unparsable | `Cannot read <path>: <error>. Nothing was changed.` | 1 |
| `sync --dry-run`, file missing | `<path> does not exist; sync would create it.` | 0 |
| `sync --dry-run`, nothing to change | `<path> is up to date.` | 0 |
| `sync --dry-run`, would rebuild | `Would update <path>` + removal list | 1 if any removals, else 0 |
| `sync --dry-run`, unreadable/unparsable | same as `sync` | 1 |

Removal list format, one line per removal:

```
Removed:
  modules: "beads" — unknown module
  git.show_prr — unknown key
  usage_limits.bar_width — expected int, got str
  [typo] — unknown section
```

(`Would remove:` in dry-run.) The exit code of `--dry-run` makes it usable as the validator the
9.1 spec wanted: non-zero means the file contains something statuskit ignores.

## Files

```
setup/config_gen.py  [NEW]   toml_value(), Removal, build_config(), template rendering
setup/config.py      [edit]  DEFAULT_CONFIG removed; create_config via build_config; init_config, sync_config + result types
core/config.py       [edit]  shared top-level/table split helper, used by load_config
core/loader.py       [edit]  BUILTIN_MODULES order: model, git, usage_limits
cli.py               [edit]  `config` subparser (init / sync, --scope, --force, --dry-run)
__init__.py          [edit]  _handle_config dispatch + printing
README.md            [edit]  option tables removed; `config init` / `config sync` documented (see *README*)
```

`setup/commands.py` needs no change (it already calls `create_config`).

## README

`packages/statuskit/README.md` (the PyPI page) has hand-written option tables that have already
drifted from the code (`commit_age_format` lacks `raw`, the `bar` example says 70% instead of
75%, descriptions differ). With the generated template as the single source, they go:

- **Remove** from *Module Reference*: the three `| Parameter | Type | Default | Description |`
  tables and the value tables (`context_format` values, `commit_age_format` values, time format
  values).
- **Keep** the behavioural prose, which documents what modules do rather than listing options:
  each module's one-line summary, *PR / MR display* (incl. the state/glyph/colour table),
  *Optional dependencies*, the `usage_limits` data-source paragraphs, *Color coding*. Where that
  prose states an option's default (`pr_cache_ttl`, "default 300s"), drop the value and keep the
  option name, so no default is written by hand.
- **Add** to *Configuration*: `statuskit config init [--scope …]` writes a config listing every
  option with its default and description (this is now the option reference); after upgrading,
  `statuskit config sync` adds new options and removes unknown ones while keeping the user's
  values, with a `.bak` backup and `--dry-run` to check a file without changing it. The short
  *Basic* / *Module Configuration* examples stay.
- **Add** one sentence next to the priority table (builder call): a project or local file
  replaces the user file entirely — files are not merged — so `config init --scope local` in a
  project shadows every user-level setting there. This only documents current behaviour
  (claude-tools-ck3 owns any change to it).

## Known limitation

`schema._check_declared_type` admits `tuple[X, ...]` params, but TOML arrays parse to `list`, so
`_coerce` rejects every user value for a tuple-typed field. Before this task that meant "ignored
at render"; under `sync` it means the user's value is **removed** (reported as invalid). No field
is tuple-typed today, so this spec does not fix it; the fix belongs in `core/schema.py` (accept a
`list` for a `tuple` field and convert), tracked separately if wanted. The generator itself must
still render tuple defaults (see *Value serialization*).

## Testing

| Area | Cases |
|---|---|
| `toml_value` | round-trip contract over bool, int (incl. negative), float (incl. `inf`/`nan` via `math.isnan`), str with `"`, `\`, tab, newline, other control chars, DEL, non-ASCII, empty; list/tuple of each, empty list |
| template structure | golden file of `build_config(None)` text (intentional changes update it); every schema field of `Config` and every built-in module appears exactly once as `# key = <default>`; the default text parses to `{"model": {}, "git": {}, "usage_limits": {}}`; **for every option line, uncommenting just that line yields a file that `load_config`-style parsing turns into exactly that option at its default, in the right section** |
| choices | dict form renders the padded block with TOML-quoted values; tuple form renders the `Choices:` line (use a test-only params class) |
| merge | valid value kept active; value equal to default kept active; unknown global key, unknown module key, invalid type, value outside choices, nested table, unknown section — each removed and reported with the right location/reason; `modules` cleaning: unknown name struck + reported, duplicate struck + reported, order of the rest kept, all-unknown list becomes an active `modules = []`; `Not enabled` note follows the cleaned `modules`; idempotence (second build: same text, no removals) |
| file ops | `init`: create / refuse existing / `--force` resets + backup; `sync`: missing → created; unchanged → no write, no `.bak`; rebuilt → `.bak` holds the old bytes; unparsable and non-UTF-8 → untouched + error; dry-run never writes; dry-run result reports would-create / unchanged / removals |
| CLI | parser: `config init`/`config sync` flags, `--scope` default `user`, bare `config` is a usage error; `main()` dispatch and exit codes per the table (patch `get_config_path` or `HOME` + `chdir(tmp_path)`) |
| setup | existing `test_setup_config.py` keeps passing (`'# modules = ["model", "git", "usage_limits"]'` is still in the output) |
| quality | `uv run ty check` (pathless) green; `ruff format` + `ruff check` clean, no suppressions |

## Left to the builder

- Exact wording of messages and of the `Not enabled` note; exact blank-line layout beyond the
  excerpt (the golden file then pins it).
- Whether template rendering and `build_config` share one function or two.
- Whether to read `_params_class` directly or add a small public accessor on `BaseModule`.
- Location of the golden file (e.g. `tests/data/default_config.toml`).
- No line wrapping of long descriptions is required.
