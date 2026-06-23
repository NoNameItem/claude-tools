# Declarative module config — declaration and parsing (subtask)

**Task:** claude-tools-5dl.9.1
**Parent:** claude-tools-5dl.9 — see `2026-06-18-declarative-module-config-design.md` for the
whole-feature context (problem, goal, rejected libraries). This spec covers only the first
subtask and supersedes the parent's component details where they differ.
**Date:** 2026-06-22
**Status:** Design approved

## Revision 2026-06-23 — critical review pass

A critical re-read (against the actual code in `src/statuskit/`) reshaped four things; they are
folded into the sections below and listed here so the diff from the originally-approved design is
explicit:

1. **`parse_params` no longer prints.** It returns `(values, warnings)` where each warning is a
   structured `ParamWarning`. The *caller* (BaseModule / `load_config`) prints in debug mode. This
   removes the `termcolor` dependency from `core/schema.py` (the schema layer no longer touches a
   presentation library) and makes parsing a pure, testable function.
2. **Forward-compat for a future `config validate` (9.2).** Because warnings are now structured and
   attributable to a section, 9.2's validate/lint command is a thin loop over `parse_params`
   results — no re-architecture. 9.1 only has to make the `ParamWarning` rich enough; the command
   itself stays in 9.2.
3. **The generic resolution is hardened to fail at import time, not at render.** `__init_subclass__`
   now rejects (with a clear `TypeError`) a subclass that omits the generic argument, binds an
   ambiguous/duplicate params class, names a non-dataclass, or names a dataclass with a field not
   declared via `param()`. Generic *intermediate* bases (`BaseModule[P]`) are recognised and their
   resolution deferred. This was the main robustness gap: previously a mis-declared module raised a
   cryptic `AttributeError` at render time, swallowed by the per-module `try/except` and visible
   only in debug.
4. **`*Params` are `frozen=True`.** Config is read-only after construction; freezing prevents a
   module from accidentally mutating `self.params` during `render()`. Range validation (if ever
   added) lives in `param()` / `parse_params`, not in `__post_init__`, so frozen costs nothing.

Smaller corrections also folded in: the test-migration list was undercounted (it missed
`tests/test_base_module.py`); the `cache_ttl` change is a real runtime behavior change worth a
changelog note; `_coerce` validates rather than converts (now documented, and a rejected value is
no longer silent — it produces a `ParamWarning`); `param(None, ...)` without `type_` is rejected at
declaration; user-facing descriptions are English (matching the existing template).

## Scope

Declarative param declaration, framework-side parsing and validation, `Config` as a typed
schema, the generic `BaseModule`, and migration of the three built-in modules — ending with the
raw `config: dict` removed from the module constructor.

**Out of scope** (subtask 5dl.9.2): the TOML template generator and the `config init` / `config
sync` / `config validate` CLI. This subtask only produces the declarations and the structured
warnings those features will later introspect.

## Approach

A module declares its options once as a plain `@dataclass(frozen=True)` of `param()` fields. The
framework — not module code — parses the module's raw TOML section against that contract, validates
and coerces each value, and hands the module a typed `self.params`. `Config` uses the same
`param()` mechanism for global settings, so validation is uniform and the template generator (9.2)
has a single source of truth.

### Typed params without asserts: generic `BaseModule`

`BaseModule` is generic over its params type. The concrete params class is reflected from the
generic argument once per subclass (in `__init_subclass__`) and stored as a private
`_params_class`. The subclass declares its params type in exactly one place — the generic
argument — and reads `self.params.x` with full static typing.

`__init_subclass__` is **strict**: it validates the generic argument at class-creation time and
raises a clear `TypeError` for every malformed declaration, so a broken module fails at import,
never silently at render.

```python
from abc import ABC, abstractmethod
from dataclasses import fields, is_dataclass
from typing import Any, Generic, TypeVar, get_args, get_origin

P = TypeVar("P")


class BaseModule(ABC, Generic[P]):
    _params_class: type[P]          # resolved from BaseModule[X]; NOT ClassVar (see note)
    params: P

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        concrete: list[type] = []
        has_typevar = False
        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if isinstance(origin, type) and issubclass(origin, BaseModule):
                (arg,) = get_args(base)
                if isinstance(arg, TypeVar):
                    has_typevar = True          # generic intermediate, e.g. BaseModule[P]
                else:
                    concrete.append(arg)

        if not concrete:
            if has_typevar or hasattr(cls, "_params_class"):
                return                          # intermediate (defer), or inherits a resolved class
            raise TypeError(
                f"{cls.__name__} must subclass BaseModule[<Params>] with a concrete params class"
            )
        if len(set(concrete)) > 1:
            raise TypeError(f"{cls.__name__}: ambiguous params classes {concrete}")

        params_cls = concrete[0]
        if not is_dataclass(params_cls):
            raise TypeError(f"{cls.__name__}: {params_cls.__name__} is not a @dataclass")
        not_declared = [f.name for f in fields(params_cls) if "type" not in f.metadata]
        if not_declared:
            raise TypeError(
                f"{params_cls.__name__}: fields not declared via param(): {not_declared}"
            )
        cls._params_class = params_cls

    def __init__(self, ctx: RenderContext, raw_section: dict) -> None:
        if not hasattr(type(self), "_params_class"):
            raise TypeError(f"{type(self).__name__} was not specialized with a params class")
        self.debug = ctx.debug
        self.data = ctx.data
        parsed, warnings = parse_params(self._params_class, raw_section)
        if ctx.debug:
            for w in warnings:
                print(colored(f"[!] {self.name}.{w.field}: {w.message}", "yellow"))
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

#### Strictness rules (all enforced at class creation)

Each row is a concrete failure mode the hardened `__init_subclass__` catches at import time:

| Declaration | Without the rule | With the rule |
|---|---|---|
| `class Foo(BaseModule)` (no generic arg) | cryptic `AttributeError` at render, swallowed by per-module `try/except` | `TypeError` at import |
| `class Mid(BaseModule[P], Generic[P])` (intermediate) | `_params_class` = a `TypeVar`; `P(**parsed)` blows up at render | recognised as intermediate, resolution deferred; direct instantiation → clear `TypeError` via the `__init__` guard |
| `class Foo(Mid[FooParams])` (chained off an intermediate) | — | resolves `FooParams` correctly |
| params class is not a `@dataclass` | `fields()` raises at first parse | `TypeError` at import |
| field declared `x: int = 10` instead of `x: int = param(10, ...)` | field is **invisible** to parsing and to the 9.2 template generator — silent drift | `TypeError` at import |
| two different `BaseModule[A]` / `BaseModule[B]` bases | last-wins, silent | `TypeError` (ambiguous) |

The last rule is the most valuable for strictness: it makes a "half-param" — a field that exists on
the class but is invisible to both config parsing and the template generator — impossible.

Subclassing an already-resolved module (e.g. a test stub `class Foo(ModelModule)`, whose
`__orig_bases__` carries no generic argument) is allowed: when neither a concrete arg nor a
`TypeVar` is present but `_params_class` is already inherited via the MRO, resolution is simply
inherited and no error is raised.

#### Why this shape (decisions verified against `ty` during design)

- **The type binding flows through the generic argument, not through an assignment.** Typing
  `_params_class: type[P]` with the same `TypeVar` as `params: P` ties them together: calling
  `self._params_class(**parsed)` returns `P`, assignable straight to `params` with **no `cast`**.
  Verified: `self.params.<bad-attr>` is flagged by `ty`, so access is genuinely typed.
- **`_params_class` must NOT be `ClassVar`.** A `ClassVar` annotation cannot reference the class's
  own `TypeVar` (`P`), which would break the `type[P]` → `params: P` linkage that gives typing
  without `cast`. So the annotation stays "instance-shaped" by form even though the attribute is
  set on the class in `__init_subclass__`. The runtime strictness checks assign it the same way and
  do not disturb the typing. **This nuance must be re-confirmed with a quick `ty` spike** before
  implementation — it is the one subtle assumption the whole shape rests on.
- **An assignment alone would not type the field.** A subclass that wrote only
  `_params_class = ModelParams` and skipped the generic argument leaves `P` unbound, and `ty`
  silently degrades `params` to `Unknown` (no attribute checking at all). The generic argument is
  mandatory — and now also enforced at runtime.
- **`ty` does not cross-check the two, so we keep only one.** `ty` does not verify a
  `_params_class = X` assignment against `BaseModule[X]`. Reflecting the class from the generic
  argument means the params type is named exactly once, with nothing to drift.
- **No asserts.** This eliminates the ~16 `assert isinstance(self.params, …)` narrowing calls the
  earlier (discarded) plan required across the three modules — each of which was runtime noise and
  a silent footgun (forgotten in a new method → `ty` break; stripped under `-O`).
- **Trade-off accepted:** ~20 lines of strict `__orig_bases__` reflection live in the base. This is
  the one piece of "machinery" the parent spec's ethos otherwise avoids; it is localized to
  `BaseModule`, never seen by module authors, and it now buys import-time safety instead of just
  convenience. (This is an intentionally experimental, "exercise modern Python" choice for a
  personal project, made with eyes open.)

#### No `PARAMS_CLASS = None` path

The parent spec allowed `PARAMS_CLASS = None` for modules with no config. There are zero such
modules today (all three built-ins are configurable; `beads` is deferred). Requiring every module
to name a params type removes the `… | None` union entirely. A shared empty frozen `NoParams`
dataclass covers the rare future paramless module and the test stub:

```python
@dataclass(frozen=True)
class NoParams:
    """Marker params class for modules with no configurable options."""

class SomeModule(BaseModule[NoParams]):
    ...
```

`NoParams` has zero fields, so the strict checks pass trivially (it is a dataclass; it has no field
that skipped `param()`).

### Files

```
core/schema.py          [NEW]    param() + parse_params() + _coerce() + ParamWarning + NoParams
modules/base.py         [edit]   generic BaseModule[P]; strict _params_class resolution; prints warnings; drops raw config
modules/model.py        [edit]   frozen ModelParams; BaseModule[ModelParams]; remove __init__
modules/git.py          [edit]   frozen GitParams; BaseModule[GitParams]; remove __init__
modules/usage_limits.py [edit]   frozen UsageLimitsParams; BaseModule[UsageLimitsParams]; keep __init__ for cache
core/config.py          [edit]   Config as param() schema; cache_dir -> str; cache_path; load_config parses + prints warnings
__init__.py             [edit]   RenderContext(cache_dir=config.cache_path)  (one line)
core/loader.py          [none]   still passes (ctx, raw_section)
```

### Data flow

`load_config()` reads TOML → `parse_params(Config, non_section)` coerces top-level keys against
`Config`'s schema fields (per-field fallback) and returns `(globals, warnings)`; `load_config`
prints the warnings in debug mode and keeps module sections raw in `module_configs` →
`loader.load_modules` passes a module's raw section into `BaseModule.__init__` → **`BaseModule`
(framework) parses it against the module's `_params_class`**, prints its own warnings in debug, and
stores the result in `self.params` → `render()` reads `self.params.x`.

## Components

### `core/schema.py` — `param()`, `_coerce()`, `parse_params()`, `ParamWarning`, `NoParams`

`core/schema.py` has **no presentation dependency** (no `termcolor`, no `print`). It returns data;
callers decide how to surface it.

```python
from dataclasses import dataclass, field, fields
from typing import Any, TypeVar, get_args, get_origin

T = TypeVar("T")


def param(default: T, description: str, *,
          choices: tuple[T, ...] | dict[T, str] | None = None, type_: Any = None) -> T:
    """Declare a config field: a dataclasses.field() carrying description/choices/type.

    Annotated `-> T` so `x: bool = param(False, ...)` type-checks as bool (dataclasses.field
    is typed `-> _T` in typeshed, so no `# type: ignore` is needed). The runtime type used for
    coercion is captured from `type(default)` (or `type_` when the default is None or a generic
    alias such as `list[str]` that has no runtime class).

    `choices` accepts either a plain tuple of allowed values, or a dict mapping each value to a
    short help string for when the value name alone is not self-explanatory. Both forms are
    stored verbatim in metadata; the template generator (9.2) renders them — an inline list for
    the tuple form, a per-value annotated block for the dict form.

    Raises ValueError if `default is None` and `type_` is not given (the runtime type cannot be
    inferred from None, and a NoneType-typed field would reject every real value).
    """
    if default is None and type_ is None:
        raise ValueError(f"param({description!r}): default is None, an explicit type_ is required")
    meta = {"description": description, "choices": choices, "type": type_ or type(default)}
    if isinstance(default, (list, dict, set)):
        return field(default_factory=lambda: type(default)(default), metadata=meta)
    return field(default=default, metadata=meta)
```

- `choices` / `type_` are keyword-only so call sites stay self-documenting.
- `choices` is either a `tuple[T, ...]` of allowed values or a `dict[T, str]` mapping each value
  to a help string (for when the value name is not self-explanatory). It is stored verbatim and
  the `description` string is left untouched; the 9.2 generator owns all choices rendering. The
  `choices` structure is the single source — no hand-written, drift-prone list anywhere.
- **Convention for display-format choices:** when a choice *selects a rendering format*
  (`context_format`, `commit_age_format`, the `*_time_format` trio), use the dict form and make each
  help string carry a concrete **rendered example** of that format (e.g. `bar` →
  ``[███████░░░] 75%``). Because the help flows verbatim into the 9.2-generated template comments,
  the user sees exactly what each option produces without having to try it. Examples are kept
  consistent (the model ones share one scenario: total 200,000, used 50,000 → 150,000 free / 75%).
- `type_: Any` accepts both plain types (`int`) and generic aliases (`list[str]`).
- Mutable defaults use `default_factory` (a fresh copy per instance). This works under
  `frozen=True` too.
- "Schema field" = a dataclass field whose `metadata` has a `"type"` key. Internal fields (e.g.
  `Config.module_configs`) have no metadata and are skipped by parsing and template generation.
  Module `*Params` classes have **no** internal fields — the strict class check forbids a field
  that skipped `param()`.

```python
@dataclass(frozen=True)
class ParamWarning:
    """A single, section-attributable config problem. Callers format/print it."""
    field: str          # the offending key
    message: str        # e.g. "expected int, got str", "unknown key", "not in choices: a, b"
    kind: str           # "invalid" | "unknown"


def parse_params(params_cls: Any, raw: dict) -> tuple[dict, list[ParamWarning]]:
    """Return (validated {field_name: value}, warnings) for the schema fields of params_cls.

    Per-field fallback: a value of the wrong type or outside `choices` is dropped (the dataclass
    default applies on construction) and a ParamWarning(kind="invalid") is recorded. Absent keys
    are omitted (default applies). Unknown keys are ignored and recorded as kind="unknown".

    Pure: never prints. The caller (BaseModule, load_config, or 9.2's `config validate`) decides
    whether to print in debug, collect across sections, or fail loudly.
    """
    result: dict = {}
    warnings: list[ParamWarning] = []
    schema = [f for f in fields(params_cls) if "type" in f.metadata]
    known = {f.name for f in schema}
    for f in schema:
        if f.name in raw:
            value, err = _coerce(raw[f.name], f.metadata["type"], f.metadata["choices"])
            if err is None:
                result[f.name] = value
            else:
                warnings.append(ParamWarning(f.name, err, "invalid"))
    for k in raw.keys() - known:
        warnings.append(ParamWarning(k, "unknown key", "unknown"))
    return result, warnings
```

`_coerce(raw, expected_type, choices)` returns `(value, None)` or `(None, "error text")`. It
**validates and passes the value through unchanged — it never converts across types** (the name is
historical; it is effectively a validator). TOML values are already typed, so no `"5"` → `5`
conversion is wanted. Dispatch order:

1. **Generic alias** (`get_origin(expected_type) is not None`, e.g. `list[str]`): check
   `isinstance(raw, origin)` for the container, then `isinstance(e, elem_type)` for every element
   via `get_args`. `modules = ["model", 42]` fails because `42` is not `str`.
2. **`bool`** before `int` (since `bool` is an `int` subclass): `expected_type is bool` → require
   `isinstance(raw, bool)` strictly; `expected_type is int` → reject `bool` values so
   `bar_width = true` does not silently become `True`.
3. **All other plain types**: `isinstance(raw, expected_type)`.

After the type check, validate `choices` if provided. Membership works for both forms —
`raw not in choices` checks tuple elements or dict keys — and the error message lists the allowed
values via `tuple(choices)` (so a dict's help strings never leak into the message).

**Float vs int is a reject, not a convert.** A TOML float given to an `int` field (`bar_width =
10.0`) fails the `isinstance(raw, int)` check and falls back to the default — but the fallback is
**no longer silent**: it produces `ParamWarning("bar_width", "expected int, got float", "invalid")`,
visible in debug and to 9.2's validate command. This keeps the strict "don't convert across types"
philosophy while removing the original silent-fallback footgun.

**Known limitation (documented, no current field hits it):** only single-argument containers are
element-validated. A future `dict[str, int]` would check keys but ignore value types, and
`list[int]` would admit `bool` elements (`bool ⊂ int`). Revisit if such a field is added.

```python
@dataclass(frozen=True)
class NoParams:
    """Params class for modules with no configurable options."""
```

### `modules/base.py` — generic `BaseModule`

As shown in *Approach*. Notes:

- `_params_class` is resolved (and strictly validated) in `__init_subclass__` once at
  class-creation, not per instance. A malformed declaration fails at import.
- `BaseModule.__init__` guards against an unresolved `_params_class` (an intermediate instantiated
  directly), prints `parse_params` warnings in debug, and constructs `self.params`.
- `base.py` imports `termcolor.colored` (for the debug print) — this is the framework layer, not
  the schema layer; the schema layer stays presentation-free.
- The raw `config: dict` is no longer stored on the instance — modules read `self.params`.
- Module migration per module: declare the frozen `*Params` dataclass, change the base to
  `BaseModule[XParams]`, delete the `config.get()` block, and rewrite `render()` reads from
  `self.x` to `self.params.x`. No `assert isinstance` anywhere.

### Module declarations

All `*Params` classes are `frozen=True` (config is read-only after construction).

```python
# modules/model.py
@dataclass(frozen=True)
class ModelParams:
    show_duration: bool = param(True, "Show session duration")
    show_context: bool = param(True, "Show context window usage")
    context_format: str = param(             # dict form: each value annotated with a rendered example
        "free", "Context display format",
        choices={
            "free": "free tokens remaining — e.g. `150,000 free (75.0%)`",
            "used": "tokens consumed — e.g. `50,000 used (25.0%)`",
            "ratio": "used / total — e.g. `50,000/200,000 (25.0%)`",
            "bar": "progress bar — e.g. `[███████░░░] 75%`",
        },
    )
    context_compact: bool = param(False, "Compact number format (150k instead of 150,000)")
    context_threshold_green: int = param(50, "Percentage free above which colour is green")
    context_threshold_yellow: int = param(25, "Percentage free above which colour is yellow")
```

```python
# modules/git.py
@dataclass(frozen=True)
class GitParams:
    commit_age_format: str = param(
        "relative", "Commit age display format",
        choices={
            "relative": "full words — e.g. `1 day 2 hours 30 minutes ago`",
            "compact": "abbreviated — e.g. `1d 2h 30m`",
            "raw": "git's own string, unmodified — e.g. `2 hours ago`",
        },
    )
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
# Shared by the three *_time_format fields below (same choices, same examples).
_TIME_FORMAT_CHOICES = {
    "remaining": "time left until reset — e.g. `2h 30m`",
    "reset_at": "wall-clock reset time — e.g. `Thu 17:00`",
}


@dataclass(frozen=True)
class UsageLimitsParams:
    show_session: bool = param(True, "Show 5-hour session limit")
    show_weekly: bool = param(True, "Show 7-day weekly limit")
    show_sonnet: bool = param(False, "Show Sonnet-only 7-day limit")
    show_reset_time: bool = param(True, "Show time until / when reset occurs")
    multiline: bool = param(True, "Multi-line output (one limit per line)")
    show_progress_bar: bool = param(False, "Show ASCII progress bar")
    bar_width: int = param(10, "Progress bar character width")
    session_time_format: str = param("remaining", "Session time display",
                                     choices=_TIME_FORMAT_CHOICES)
    weekly_time_format: str = param("reset_at", "Weekly time display",
                                    choices=_TIME_FORMAT_CHOICES)
    sonnet_time_format: str = param("reset_at", "Sonnet time display",
                                    choices=_TIME_FORMAT_CHOICES)
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

**Runtime behavior change — call out in the changelog.** This finally wires up `cache_ttl`: the old
hardcoded template advertised `cache_ttl = 60`, but the module never read it and `UsageCache` used
its built-in `rate_limit=30`. The param default is `60` to match the documented value (and to halve
API calls for a line that renders on every prompt), so the effective refetch gap changes from the
previously hardcoded **30 s to 60 s for every existing user**. This is a behavior change (a
bugfix — the template was lying), not just a refactor, and should be noted explicitly in release
notes rather than buried.

The current `ModelModule` stores `context_threshold_green` under the attribute name
`threshold_green`; after migration it reads `self.params.context_threshold_green` (the internal
rename is invisible to config).

User-facing `description` strings are **English**, matching the existing `DEFAULT_CONFIG` template
and the strings the 9.2 generator will emit. (The parent spec's Russian examples are superseded.)

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
`parse_params(Config, …)`. It is **not** `frozen` — it carries the mutable internal
`module_configs` and keeps its free keyword constructor for the many `Config(...)` test call sites.
(The strict "all fields via `param()`" rule applies only to module `_params_class` resolution in
`BaseModule`, so `Config.module_configs` being a plain `field()` is fine.)

**`cache_dir` must be `str`, not `Path` — a correctness requirement, not cosmetics.** `_coerce`
checks `isinstance(raw, declared_type)`, and TOML values arrive as strings. A `Path`-typed field
would reject every real config value and always fall back to its default. Consumers that need a
path use `config.cache_path`.

`load_config()`:

1. Read TOML (unchanged error handling: bad file → message + `Config()`).
2. Split the top-level table into non-section keys (any non-dict value: `modules`, `debug`,
   `colors`, `cache_dir`) and module sections (dict values).
3. `globals_, warnings = parse_params(Config, non_section)`.
4. If the raw `debug` flag is `True`, print each warning as
   `colored(f"[!] config.{w.field}: {w.message}", "yellow")`. (The raw flag bootstraps parse
   warnings — chicken-and-egg: we need `debug` before it is parsed.)
5. `return Config(**globals_, module_configs=sections)`.

The one current `config.cache_dir` consumer (`__init__.py`, `RenderContext(cache_dir=…)`) changes
to `config.cache_path`. `RenderContext.cache_dir` stays `Path | None`, so `UsageCache` is
unaffected.

Remove the now-dead `DEFAULT_CACHE_DIR` constant (its only consumers are the lines this redesign
replaces). Remove `CONFIG_PATH` as well — it is already unreferenced anywhere in `src/` or
`tests/`.

## Error handling

Per-field fallback: an invalid or unknown value never breaks the statusline. The offending field
uses its default, every other field is unaffected, the line always renders, and a `ParamWarning` is
produced. Warnings are **printed only in debug mode** (by the caller), but they are now structured
data, so 9.2's `config validate` can print them all loudly and exit non-zero regardless of debug —
giving the user a way to discover a typo (`context_format = "freee"`) that the always-on path keeps
silent for robustness. Unknown keys are recorded (kind `"unknown"`). Unknown whole sections (a
`[typo]` table for no registered module) are silently dropped — module sections are validated
lazily, only when that module is instantiated. This matches the statusline's robustness
requirement.

**Schema evolution (acknowledged, not solved here):** renaming or removing a param leaves a stale
key in old user configs, which surfaces as an `"unknown"` warning and is ignored. There is no
automatic migration, and 9.2's `config sync` only *adds* missing keys, never removes renamed ones.
This is accepted as YAGNI for now; revisit if params start churning.

## Testing

| Area | Cases |
|------|-------|
| `core/schema` | `param()` builds field + metadata (incl. mutable-default isolation); `param(None)` without `type_` raises; `choices` stored verbatim for both the tuple and the dict-with-help forms, description left untouched; `parse_params` returns `(values, warnings)` — valid / wrong-type / not-in-choices / missing / unknown-key, each producing the right `ParamWarning` (field, kind); `_coerce` incl. bool-vs-int, `int` field rejects float (warning emitted), choices membership for tuple AND dict forms (+ error lists values only), generic `list[str]` (rejects non-list and list with a non-str element) |
| `modules/base` (strict resolution) | `_params_class` resolved from the generic argument; **missing generic arg raises `TypeError` at class creation**; **non-dataclass params raises**; **a `*Params` field not declared via `param()` raises**; **ambiguous duplicate params raises**; a generic intermediate (`BaseModule[P]`) resolves lazily and instantiating it directly raises via the `__init__` guard; a chained `Mid[FooParams]` resolves correctly |
| `modules/base` (behavior) | section parsed into `self.params`; per-field fallback; debug warning printed only when `ctx.debug`; a `NoParams` module constructs with `self.params` an empty instance; `self.params` is frozen — assigning to a field raises `FrozenInstanceError` |
| `core/config` | `Config` schema defaults; `load_config` coercion (incl. invalid `cache_dir` falls back) and warning printing in debug; `cache_path`; module sections extracted |
| `core/loader` | **`test_load_modules_with_config` rewritten** from `modules[0].config == {…}` to `modules[0].params.show_duration is False` — the raw `config` attribute no longer exists |
| `modules/base` test | **`tests/test_base_module.py` rewritten** — it currently asserts `mod.config == {"option": "value"}` (`test_base_module.py:25`), which the removed raw `config` attribute breaks. Audit *all* attribute-level access in tests, not only these two named files: any test reading `module.show_duration` (old attr) instead of `module.params.show_duration` must be updated. |
| modules | existing `render()` tests are the regression harness; the constructor still takes a `dict` positionally, so `ModelModule(ctx, {"show_duration": False})` still works (parsing now happens inside); all pass valid values, so coercion does not change their behaviour; plus a test that `cache_ttl` flows into `UsageCache.rate_limit` (default `60`, and a custom value is honoured) |
| quality | `uv run ty check` green (incl. the `_params_class: type[P]` ↔ `params: P` linkage — re-confirm the no-`ClassVar` nuance with a spike); `ruff format` + `ruff check` clean |

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
- Choices rendering is 9.2's responsibility: read each field's `choices` metadata and emit an
  inline `(choices: a, b)` list for the tuple form, or a per-value annotated block (value + help)
  for the dict form.
- **`config validate` (new, enabled by this revision):** because `parse_params` returns structured
  `ParamWarning`s attributable to a section, 9.2 can add a `config validate` command that runs
  `parse_params` over `Config` and every module section, prints all warnings loudly, and exits
  non-zero — the strict counterpart to the always-on silent-fallback path. No new parsing
  mechanism is needed; only the command wiring.

## Decomposition

This subtask is 5dl.9.1. Subtask 5dl.9.2 (the template generator + `config init` / `config sync` /
`config validate` CLI) depends on it: the generator needs the modules' params classes and
`Config`'s schema, and the validate command needs the structured warnings — all delivered here.
