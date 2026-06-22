# Declarative module config — declaration and parsing (subtask)

**Task:** claude-tools-5dl.9.1
**Parent:** claude-tools-5dl.9 — see `2026-06-18-declarative-module-config-design.md` for the
whole-feature context (problem, goal, rejected libraries). This spec covers only the first
subtask and supersedes the parent's component details where they differ.
**Date:** 2026-06-22
**Status:** Design approved

## Scope

Declarative param declaration, framework-side parsing and validation, `Config` as a typed
schema, the generic `BaseModule`, and migration of the three built-in modules — ending with the
raw `config: dict` removed from the module constructor.

**Out of scope** (subtask 5dl.9.2): the TOML template generator and the `config init` / `config
sync` CLI. This subtask only produces the declarations those features will later introspect.

## Approach

A module declares its options once as a plain `@dataclass` of `param()` fields. The framework —
not module code — parses the module's raw TOML section against that contract, validates and
coerces each value, and hands the module a typed `self.params`. `Config` uses the same `param()`
mechanism for global settings, so validation is uniform and the template generator (9.2) has a
single source of truth.

### Typed params without asserts: generic `BaseModule`

`BaseModule` is generic over its params type. The concrete params class is reflected from the
generic argument once per subclass (in `__init_subclass__`) and stored as a private
`_params_class`. The subclass declares its params type in exactly one place — the generic
argument — and reads `self.params.x` with full static typing.

```python
P = TypeVar("P")

class BaseModule(ABC, Generic[P]):
    _params_class: type[P]          # resolved from BaseModule[X]; private to the base
    params: P

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if isinstance(origin, type) and issubclass(origin, BaseModule):
                cls._params_class = get_args(base)[0]
                return

    def __init__(self, ctx: RenderContext, raw_section: dict) -> None:
        self.debug = ctx.debug
        self.data = ctx.data
        parsed = parse_params(self._params_class, raw_section, debug=ctx.debug, label=self.name)
        self.params = self._params_class(**parsed)

    @abstractmethod
    def render(self) -> str | None: ...
```

```python
class ModelModule(BaseModule[ModelParams]):     # the single declaration
    name = "model"
    description = "Model name, session duration, context window usage"

    def render(self) -> str | None:
        if self.params.show_context:             # typed; ty checks it, no assert
            fmt = self.params.context_format
```

#### Why this shape (decisions verified against `ty` during design)

- **The type binding flows through the generic argument, not through an assignment.** Typing
  `_params_class: type[P]` with the same `TypeVar` as `params: P` ties them together: calling
  `self._params_class(**parsed)` returns `P`, assignable straight to `params` with **no `cast`**.
  Verified: `self.params.<bad-attr>` is flagged by `ty`, so access is genuinely typed.
- **An assignment alone would not type the field.** A subclass that wrote only
  `_params_class = ModelParams` and skipped the generic argument leaves `P` unbound, and `ty`
  silently degrades `params` to `Unknown` (no attribute checking at all). The generic argument is
  mandatory.
- **`ty` does not cross-check the two, so we keep only one.** `ty` does not verify a
  `_params_class = X` assignment against `BaseModule[X]`. Reflecting the class from the generic
  argument means the params type is named exactly once, with nothing to drift.
- **No asserts.** This eliminates the ~16 `assert isinstance(self.params, …)` narrowing calls the
  earlier (discarded) plan required across the three modules — each of which was runtime noise and
  a silent footgun (forgotten in a new method → `ty` break; stripped under `-O`).
- **Trade-off accepted:** ~8 lines of `__orig_bases__` reflection live in the base. This is the
  one piece of "machinery" the parent spec's ethos otherwise avoids; it is localized to
  `BaseModule` and never seen by module authors.

#### No `PARAMS_CLASS = None` path

The parent spec allowed `PARAMS_CLASS = None` for modules with no config. There are zero such
modules today (all three built-ins are configurable; `beads` is deferred). Requiring every module
to name a params type removes the `… | None` union entirely. A shared empty `NoParams` dataclass
covers the rare future paramless module and the test stub:

```python
@dataclass
class NoParams:
    """Marker params class for modules with no configurable options."""

class SomeModule(BaseModule[NoParams]):
    ...
```

### Files

```
core/schema.py          [NEW]    param() + parse_params() + _coerce() + NoParams
modules/base.py         [edit]   generic BaseModule[P]; reflects _params_class; drops raw config
modules/model.py        [edit]   ModelParams; BaseModule[ModelParams]; remove __init__
modules/git.py          [edit]   GitParams; BaseModule[GitParams]; remove __init__
modules/usage_limits.py [edit]   UsageLimitsParams; BaseModule[UsageLimitsParams]; keep __init__ for cache
core/config.py          [edit]   Config as param() schema; cache_dir -> str; cache_path; load_config coerces
__init__.py             [edit]   RenderContext(cache_dir=config.cache_path)  (one line)
core/loader.py          [none]   still passes (ctx, raw_section)
```

### Data flow

`load_config()` reads TOML → coerces top-level keys against `Config`'s schema fields (per-field
fallback) and keeps module sections raw in `module_configs` → `loader.load_modules` passes a
module's raw section into `BaseModule.__init__` → **`BaseModule` (framework) parses it against the
module's `_params_class`** and stores the result in `self.params` → `render()` reads
`self.params.x`.

## Components

### `core/schema.py` — `param()`, `_coerce()`, `parse_params()`, `NoParams`

```python
from dataclasses import field
from typing import Any, TypeVar

T = TypeVar("T")


def param(default: T, description: str, *, choices: tuple[T, ...] | None = None,
          type_: Any = None) -> T:
    """Declare a config field: a dataclasses.field() carrying description/choices/type.

    Annotated `-> T` so `x: bool = param(False, ...)` type-checks as bool (dataclasses.field
    is typed `-> _T` in typeshed, so no `# type: ignore` is needed). The runtime type used for
    coercion is captured from `type(default)` (or `type_` when the default is None or a generic
    alias such as `list[str]` that has no runtime class).

    When `choices` is given, the allowed values are appended to the stored description
    (e.g. "Context display format (choices: free, used, ratio, bar)"), so the single
    `choices=(...)` tuple is the only source — no hand-written, drift-prone list.
    """
    if choices is not None:
        description = f"{description} (choices: {', '.join(map(str, choices))})"
    meta = {"description": description, "choices": choices, "type": type_ or type(default)}
    if isinstance(default, (list, dict, set)):
        return field(default_factory=lambda: type(default)(default), metadata=meta)
    return field(default=default, metadata=meta)
```

- `choices` / `type_` are keyword-only so call sites stay self-documenting.
- A field with `choices` gets the allowed values appended to its stored description
  automatically. The template generator (9.2) therefore emits the description verbatim and never
  re-appends choices — the `choices` tuple remains the single source of truth.
- `type_: Any` accepts both plain types (`int`) and generic aliases (`list[str]`).
- Mutable defaults use `default_factory` (a fresh copy per instance).
- "Schema field" = a dataclass field whose `metadata` has a `"type"` key. Internal fields (e.g.
  `Config.module_configs`) have no metadata and are skipped by parsing and template generation.

```python
def parse_params(params_cls: Any, raw: dict, *, debug: bool = False, label: str = "") -> dict:
    """Return validated {field_name: value} for the schema fields of params_cls.

    Per-field fallback: a value of the wrong type or outside `choices` is dropped (the dataclass
    default applies on construction) with a debug-only warning. Absent keys are omitted (default
    applies). Unknown keys are ignored with a debug-only warning.
    """
    result: dict = {}
    schema = [f for f in fields(params_cls) if "type" in f.metadata]
    known = {f.name for f in schema}
    for f in schema:
        if f.name in raw:
            value, err = _coerce(raw[f.name], f.metadata["type"], f.metadata["choices"])
            if err is None:
                result[f.name] = value
            elif debug:
                print(colored(f"[!] {label}.{f.name}: {err}, using default", "yellow"))
    if debug:
        for k in raw.keys() - known:
            print(colored(f"[!] {label}: unknown key '{k}'", "yellow"))
    return result
```

`_coerce(raw, expected_type, choices)` returns `(value, None)` or `(None, "error text")`.
Dispatch order:

1. **Generic alias** (`get_origin(expected_type) is not None`, e.g. `list[str]`): check
   `isinstance(raw, origin)` for the container, then `isinstance(e, elem_type)` for every element
   via `get_args`. `modules = ["model", 42]` fails because `42` is not `str`.
2. **`bool`** before `int` (since `bool` is an `int` subclass): `expected_type is bool` → require
   `isinstance(raw, bool)` strictly; `expected_type is int` → reject `bool` values so
   `bar_width = true` does not silently become `True`.
3. **All other plain types**: `isinstance(raw, expected_type)`.

After the type check, validate `choices` if provided.

**Known limitation (documented, no current field hits it):** only single-argument containers are
element-validated. A future `dict[str, int]` would check keys but ignore value types, and
`list[int]` would admit `bool` elements (`bool ⊂ int`). Revisit if such a field is added.

```python
@dataclass
class NoParams:
    """Params class for modules with no configurable options."""
```

### `modules/base.py` — generic `BaseModule`

As shown in *Approach*. Notes:

- `_params_class` is resolved in `__init_subclass__` once at class-creation, not per instance.
- The raw `config: dict` is no longer stored on the instance — modules read `self.params`.
- Module migration per module: declare the `*Params` dataclass, change the base to
  `BaseModule[XParams]`, delete the `config.get()` block, and rewrite `render()` reads from
  `self.x` to `self.params.x`. No `assert isinstance` anywhere.

### Module declarations

```python
# modules/model.py
@dataclass
class ModelParams:
    show_duration: bool = param(True, "Show session duration")
    show_context: bool = param(True, "Show context window usage")
    context_format: str = param("free", "Context display format",
                                choices=("free", "used", "ratio", "bar"))
    context_compact: bool = param(False, "Compact number format (150k instead of 150,000)")
    context_threshold_green: int = param(50, "Percentage free above which colour is green")
    context_threshold_yellow: int = param(25, "Percentage free above which colour is yellow")
```

```python
# modules/git.py
@dataclass
class GitParams:
    commit_age_format: str = param("relative", "Commit age display format",
                                   choices=("relative", "compact", "raw"))
    show_project: bool = param(True, "Show project name")
    show_worktree: bool = param(True, "Show worktree name")
    show_folder: bool = param(True, "Show current subfolder")
    show_branch: bool = param(True, "Show branch name")
    show_remote_status: bool = param(True, "Show remote tracking status")
    show_changes: bool = param(True, "Show working tree change counts")
    show_commit: bool = param(True, "Show last commit hash and age")
```

```python
# modules/usage_limits.py
@dataclass
class UsageLimitsParams:
    show_session: bool = param(True, "Show 5-hour session limit")
    show_weekly: bool = param(True, "Show 7-day weekly limit")
    show_sonnet: bool = param(False, "Show Sonnet-only 7-day limit")
    show_reset_time: bool = param(True, "Show time until / when reset occurs")
    multiline: bool = param(True, "Multi-line output (one limit per line)")
    show_progress_bar: bool = param(False, "Show ASCII progress bar")
    bar_width: int = param(10, "Progress bar character width")
    session_time_format: str = param("remaining", "Session time display",
                                     choices=("remaining", "reset_at"))
    weekly_time_format: str = param("reset_at", "Weekly time display",
                                    choices=("remaining", "reset_at"))
    sonnet_time_format: str = param("reset_at", "Sonnet time display",
                                    choices=("remaining", "reset_at"))
    cache_ttl: int = param(60, "Minimum seconds between usage-API refetches")
```

`ModelModule` and `GitModule` drop their `__init__` entirely. `UsageLimitsModule` keeps an
`__init__` that calls `super().__init__(ctx, raw_section)` (which sets `self.params`) and then
initialises the cache, feeding the new `cache_ttl` param into `UsageCache`'s `rate_limit`:

```python
self.cache = (
    UsageCache(cache_dir=ctx.cache_dir, rate_limit=self.params.cache_ttl)
    if ctx.cache_dir else None
)
```

This finally wires up `cache_ttl`: the old hardcoded template advertised `cache_ttl = 60`, but the
module never read it and `UsageCache` used its built-in `rate_limit=30`. The param default is `60`
to match the documented value (and to halve API calls for a line that renders on every prompt), so
the effective refetch gap changes from the previously hardcoded `30s` to `60s`.

The current `ModelModule` stores `context_threshold_green` under the attribute name
`threshold_green`; after migration it reads `self.params.context_threshold_green` (the internal
rename is invisible to config).

### `core/config.py` — `Config` is the global schema

```python
@dataclass
class Config:
    modules: list[str] = param(["model", "git", "usage_limits"],
                               "Modules to display (in order)", type_=list[str])
    debug: bool = param(False, "Enable debug output")
    colors: bool = param(True, "Colored output")
    cache_dir: str = param("~/.cache/statuskit", "Cache directory")
    module_configs: dict[str, dict] = field(default_factory=dict)   # internal, not a schema field

    def get_module_config(self, name: str) -> dict:
        return self.module_configs.get(name, {})

    @property
    def cache_path(self) -> Path:
        return Path(self.cache_dir).expanduser()
```

`Config` is not generic and is not a `BaseModule`; `load_config` parses it directly with
`parse_params(Config, …)`.

**`cache_dir` must be `str`, not `Path` — a correctness requirement, not cosmetics.** `_coerce`
checks `isinstance(raw, declared_type)`, and TOML values arrive as strings. A `Path`-typed field
would reject every real config value and always fall back to its default. Consumers that need a
path use `config.cache_path`.

`load_config()`:

1. Read TOML (unchanged error handling: bad file → message + `Config()`).
2. Split the top-level table into non-section keys (any non-dict value: `modules`, `debug`,
   `colors`, `cache_dir`) and module sections (dict values).
3. `globals_ = parse_params(Config, non_section, debug=(data.get("debug") is True), label="config")`.
   The raw `debug` flag bootstraps parse warnings (chicken-and-egg: we need `debug` before it is
   parsed).
4. `return Config(**globals_, module_configs=sections)`.

The one current `config.cache_dir` consumer (`__init__.py`, `RenderContext(cache_dir=…)`) changes
to `config.cache_path`. `RenderContext.cache_dir` stays `Path | None`, so `UsageCache` is
unaffected.

Remove the now-dead `DEFAULT_CACHE_DIR` constant (its only consumers are the lines this redesign
replaces). Remove `CONFIG_PATH` as well — it is already unreferenced anywhere in `src/` or
`tests/`.

## Error handling

Per-field fallback: an invalid or unknown value never breaks the statusline. The offending field
uses its default, every other field is unaffected, the line always renders, and a warning is
printed only in debug mode. Unknown keys are ignored (debug warning). Unknown whole sections (a
`[typo]` table for no registered module) are silently dropped — module sections are validated
lazily, only when that module is instantiated. This matches the statusline's robustness
requirement.

## Testing

| Area | Cases |
|------|-------|
| `core/schema` | `param()` builds field + metadata (incl. mutable-default isolation); `param()` appends `choices` to the stored description (and leaves it untouched when no choices); `parse_params` valid / wrong-type / not-in-choices / missing / unknown-key (+ debug warnings); `_coerce` incl. bool-vs-int, generic `list[str]` (rejects non-list and list with a non-str element) |
| `modules/base` | `_params_class` resolved from the generic argument; section parsed into `self.params`; per-field fallback; debug warning; a `NoParams` module constructs with `self.params` an empty instance |
| `core/config` | `Config` schema defaults; `load_config` coercion (incl. invalid `cache_dir` falls back); `cache_path`; module sections extracted |
| `core/loader` | **`test_load_modules_with_config` rewritten** from `modules[0].config == {…}` to `modules[0].params.show_duration is False` — the raw `config` attribute no longer exists |
| modules | existing `render()` tests are the regression harness; all pass valid values, so coercion does not change their behaviour; plus a test that `cache_ttl` flows into `UsageCache.rate_limit` (default `60`, and a custom value is honoured) |
| quality | `uv run ty check` green; `ruff format` + `ruff check` clean |

**`cache_path` tests must monkeypatch the `HOME` environment variable, not `Path.home`.**
`Path.expanduser()` resolves `~` from `$HOME` (via `os.path.expanduser`), not from `Path.home()`.
A test that does `monkeypatch.setattr(Path, "home", lambda: tmp)` and asserts
`cfg.cache_path == Path.home() / …` fails, because the left side expands the real `$HOME` while
the right side reads the patched `Path.home()`. Use `monkeypatch.setenv("HOME", str(tmp_home))`
(the existing config-path tests can keep patching `Path.home`, which `_get_config_paths` does
use).

## Carried-over issues for 5dl.9.2

- The template generator will introspect each module's params class. With reflection, that class
  is available as `ModuleClass._params_class` (a class attribute, accessible within the package);
  9.2 can read it directly or add a small accessor.

## Decomposition

This subtask is 5dl.9.1. Subtask 5dl.9.2 (the template generator + `config init` / `config sync`
CLI) depends on it: the generator needs the modules' params classes and `Config`'s schema, both
delivered here.
