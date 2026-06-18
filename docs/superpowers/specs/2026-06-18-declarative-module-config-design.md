# Declarative module configuration

**Task:** claude-tools-5dl.9
**Date:** 2026-06-18
**Status:** Design approved

## Problem

Module configuration defaults live in **two places that must be kept in sync by hand**:

1. Each module reads its options with scattered `config.get("key", default)` calls in its
   `__init__` (`modules/model.py:22-29`, `modules/git.py:50-59`,
   `modules/usage_limits.py:336-348`). The defaults are hardcoded there.
2. `setup/config.py` holds a ~60-line hardcoded `DEFAULT_CONFIG` TOML string that
   duplicates every option, written out by `statuskit setup`.

Adding an option to a module means remembering to also edit the template string; the two
drift. There is also **no validation**: `BaseModule.__init__` stores the raw `config: dict`
as-is (`modules/base.py:20-29`), so `context_format = "nonsense"` silently falls back at
render time and `bar_width = "huge"` blows up mid-render instead of at load.

This task was spun off on 2026-01-27 from the
`2026-01-27-update-default-config-design.md` work (which patched that hardcoded string by
hand) as its "do it properly" follow-up.

## Goal

A module declares its config options **once**, as a typed contract. The framework — not
module code — parses the module's TOML section against that contract, validates and coerces
values, and hands the module its typed parameters. The same contracts are introspected to
**auto-generate** the commented TOML config template. Raw `config: dict` is removed from the
module constructor.

Global settings (`modules`, `debug`, `colors`, `cache_dir`) use the same mechanism so the
template and validation are uniform and the drift is killed completely.

### Non-goals

- No third-party config library (pydantic / msgspec / goodconf). See *Rejected alternatives*.
- No per-module generation mode (`config init --module git`) in this iteration — deferred.
- No external-module loading work (tasks `claude-tools-u5w` / `claude-tools-w6j`); the
  mechanism just happens to work for them for free because it lives on `BaseModule`.

## Approach

Plain `@dataclass` "params" classes whose fields are declared with a thin `param()` helper
that wraps `dataclasses.field()` and stashes `{description, choices, type}` in field
metadata. The dataclass annotation (`show_context: bool`) gives native `ty` typing with no
descriptor machinery and no `# type: ignore`; introspection is `dataclasses.fields()`.

### Why this shape (decisions taken during design)

- **Hand-rolled, not a library.** Research showed no library does all three of
  declare + validate-per-section + generate-commented-TOML without binding to pydantic and
  still missing the per-section commenting we want. The template generator is ours
  regardless (~25 lines). Cold-start import matters (statusline runs every render):
  stdlib `dataclasses` adds ~0 ms over the ~6 ms already paid, vs msgspec ~11 ms /
  pydantic ~36 ms. So a library would only buy validation we can hand-roll for these
  bool/int/str fields.
- **`dataclass` + `param()` over a `Generic` descriptor.** A descriptor allowed `self.x`
  access but required a cluttered `x: ConfigField[bool] = ConfigField(...)` declaration and,
  per spike, only type-checked under `ty` with an explicit annotation (a silent footgun if
  forgotten). The dataclass form declares as `x: bool = param(...)`, type-checks natively
  (`ty` even flags a wrong-typed default), and the annotation is mandatory for dataclass
  anyway, so it cannot be silently forgotten. Trade-off accepted: module access is
  `self.params.x` instead of `self.x`.
- **No `# type: ignore`.** `dataclasses.field()` is typed `-> _T` in typeshed, so
  `param() -> T` returning `field(default=default)` type-checks cleanly (verified with `ty`).
- **`param()` captures the runtime type from `type(default)`** into metadata, so coercion
  never needs `typing.get_type_hints()` / annotation resolution.

### Files

```
core/schema.py        [NEW]    param() helper + parse_params() + coercion
modules/base.py       [edit]   __init__ parses section via PARAMS_CLASS; drops raw config dict
modules/model.py      [edit]   ModelParams dataclass + PARAMS_CLASS; remove config.get block
modules/git.py        [edit]   GitParams + PARAMS_CLASS
modules/usage_limits.py [edit] UsageLimitsParams + PARAMS_CLASS
core/config.py        [edit]   Config becomes the global params dataclass; load_config coerces; cache_path
core/loader.py        [none]   still passes (ctx, raw_section)
setup/config_gen.py   [NEW]    template generator (string builder)
setup/config.py       [edit]   create_config delegates to config_gen; hardcoded DEFAULT_CONFIG removed
cli.py                [edit]   `config` subcommand (init / sync)
__init__.py           [edit]   _handle_config dispatch
```

### Data flow

`load_config()` reads TOML → coerces top-level keys against `Config`'s schema fields
(per-field fallback) and extracts module sections raw into `module_configs` →
`loader.load_modules` passes a module's raw section into `BaseModule.__init__` →
**`BaseModule` (framework) parses it against the module's `PARAMS_CLASS`** and stores the
result in `self.params` → module `render()` reads `self.params.x`.

## Components

### `core/schema.py` — `param()` and `parse_params()`

```python
from dataclasses import field
from typing import TypeVar

T = TypeVar("T")


def param(default: T, description: str, *, choices: tuple[T, ...] | None = None,
          type_: type | None = None) -> T:
    """Declare a config field: a dataclasses.field() carrying description/choices/type.

    Annotated `-> T` so `x: bool = param(False, ...)` type-checks as bool (dataclasses.field
    is typed `-> _T` in typeshed, so no `# type: ignore` is needed). The runtime type used
    for coercion is captured from `type(default)` (or `type_` when the default is None).
    """
    meta = {"description": description, "choices": choices, "type": type_ or type(default)}
    if isinstance(default, (list, dict, set)):
        return field(default_factory=lambda: type(default)(default), metadata=meta)
    return field(default=default, metadata=meta)
```

- `choices` / `type_` are keyword-only (the `*`) so call sites stay self-documenting.
- Mutable defaults use `default_factory` (a fresh copy per instance — verified isolated).
- "Schema field" = a dataclass field whose `metadata` has a `"type"` key. Internal fields
  (e.g. `Config.module_configs`) have no metadata and are skipped by validation and
  generation.

```python
def parse_params(params_cls, raw: dict, *, debug: bool = False, label: str = "") -> dict:
    """Return validated {field_name: value} for the schema fields of params_cls.

    Per-field fallback: a value of the wrong type or outside `choices` is dropped (the
    dataclass default applies on construction) with a debug-only warning. Absent keys are
    omitted (default applies). Unknown keys are ignored with a debug-only warning.
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

`_coerce(raw, expected_type, choices)` returns `(value, None)` or `(None, "error text")`:
mismatched type → error; `choices` set and value not in it → error; otherwise the value.
`bool` is checked before `int` (since `bool` is an `int` subclass) to reject
`show_context = 1`.

### Module declaration and `BaseModule`

```python
# modules/model.py
@dataclass
class ModelParams:
    show_duration:  bool = param(True, "Показывать длительность сессии")
    show_context:   bool = param(True, "Показывать использование контекста")
    context_format: str  = param("free", "Формат контекста",
                                  choices=("free", "used", "ratio", "bar"))
    context_compact: bool = param(False, "Компактный режим")
    context_threshold_green:  int = param(50, "Порог зелёного, %")
    context_threshold_yellow: int = param(25, "Порог жёлтого, %")


class ModelModule(BaseModule):
    name = "model"
    description = "Claude model, session duration, context usage"
    PARAMS_CLASS: ClassVar[type] = ModelParams

    def render(self) -> str | None:
        if self.params.show_context:          # typed access; ty checks it
            fmt = self.params.context_format
```

```python
# modules/base.py
class BaseModule(ABC):
    name: str
    description: str
    PARAMS_CLASS: ClassVar[type]

    def __init__(self, ctx: RenderContext, raw_section: dict):
        self.debug = ctx.debug
        self.data = ctx.data
        parsed = parse_params(self.PARAMS_CLASS, raw_section, debug=ctx.debug, label=self.name)
        self.params = self.PARAMS_CLASS(**parsed)
        # raw `config: dict` is no longer stored
```

Each module migration: add the `*Params` dataclass, set `PARAMS_CLASS`, delete the
`config.get()` block from `__init__`, and rewrite `render()` reads from `self.x` to
`self.params.x`. `usage_limits` keeps its `ctx.cache_dir` handling unchanged.

### `core/config.py` — `Config` is the global schema

```python
@dataclass
class Config:
    modules: list = param(["model", "git", "usage_limits"], "Модули для отображения (по порядку)")
    debug:   bool = param(False, "Включить debug-вывод")
    colors:  bool = param(True,  "Цветной вывод")
    cache_dir: str = param("~/.cache/statuskit", "Каталог кэша")
    module_configs: dict[str, dict] = field(default_factory=dict)   # internal, not a template option

    def get_module_config(self, name: str) -> dict:
        return self.module_configs.get(name, {})

    @property
    def cache_path(self) -> Path:
        return Path(self.cache_dir).expanduser()
```

`load_config()`:
1. Read TOML (unchanged error handling: bad file → message + `Config()`).
2. Split the top-level table into non-section keys (any value that is **not** a dict —
   `modules`, `debug`, `colors`, `cache_dir`) and module sections (dict values).
3. `globals_ = parse_params(Config, non_section_keys, debug=..., label="config")`.
4. Extract module sections into `module_configs` (the existing dict-comprehension).
5. `return Config(**globals_, module_configs=module_configs)`.

`cache_dir` stays a `str` in the schema (so the template shows a string); consumers that
need a path use `config.cache_path`. The one current consumer
(`__init__.py:93 RenderContext(cache_dir=config.cache_dir)`) changes to `config.cache_path`.
Existing `Config(...)` keyword construction in tests and `load_config` keeps working because
`param()` fields are ordinary dataclass fields with defaults.

### `setup/config_gen.py` — template generator

A dependency-free string builder (no tomlkit — every line is a comment, so a structured TOML
writer buys nothing). Walks `Config`'s schema fields for the global block, then each
`BUILTIN_MODULES` entry's `PARAMS_CLASS` for its section:

```python
def render_template() -> str:
    # global block from schema fields of Config
    # per module: "# ─── {name} module: {description} ───", "# [{name}]",
    #   then per field: "# {key} = {toml_repr(default)}  # {description}[ (choices: a, b)]"
```

`toml_repr`: `True→true`, `False→false`, `str→"..."`, `list→["a", "b"]`, numbers as-is.
Output matches the current `DEFAULT_CONFIG` shape; the hardcoded string is deleted and
`create_config()` calls `render_template()`.

### CLI: `config` subcommand

```
statuskit config init           # write full template; refuse if file exists
statuskit config init --force   # overwrite
statuskit config sync           # append only options absent from the existing file
```

- A `config` subparser in `cli.py`; `_handle_config` in `__init__.py` dispatches `init`/`sync`.
- `init` reuses the `create_config` path (now backed by `render_template`); `--force`
  overwrites.
- `sync`: for each schema option key, text-scan the existing file for that key (whether a
  real `key =` line or a commented `# key =` line). Append commented stubs for keys found
  nowhere, grouped under their section header, without modifying any existing line.

## Error handling

Per-field fallback (decided during design): an invalid/unknown value never breaks the
statusline. The offending field uses its default, every other field is unaffected, the line
always renders, and a warning is printed only in debug mode. Unknown keys are ignored
(debug warning). This matches the statusline's robustness requirement.

## Testing

| Area | Cases |
|------|-------|
| `core/schema` | `param()` builds field + metadata (incl. mutable default isolation); `parse_params` valid / wrong-type / not-in-choices / missing / unknown-key; `_coerce` incl. bool-vs-int |
| `modules/base` | section parsed into `self.params`; per-field fallback; debug warnings; no raw `config` attr |
| `core/config` | `Config` schema defaults; `load_config` coercion; `cache_path`; module sections extracted |
| `setup/config_gen` | full-template snapshot; `sync` appends only missing options and leaves existing lines intact |
| CLI | `config init` create / refuse-existing / `--force`; `config sync` append |
| quality | `uv run ty check` green; `ruff format` + `ruff check` clean |

## Decomposition

The task adds two features: declarative config declaration, and template generation from
those declarations. Split accordingly (the by-component pieces — `core/schema.py`, `Config`,
`BaseModule`, module migration — are folded into the first):

1. **Декларативное объявление и парсинг конфигов модулей** (claude-tools-5dl.9.1) —
   `core/schema.py` (`param()` + `parse_params` + coercion), `Config` as the dataclass schema
   + `load_config` integration + `cache_path`, section parsing in `BaseModule`, migrate
   `model` / `git` / `usage_limits` to `*Params`, drop the raw `config: dict` from the
   constructor.
2. **Генерация конфиг-шаблона из объявлений + CLI** (claude-tools-5dl.9.2) —
   `setup/config_gen.py` template builder from `Config` + module `PARAMS_CLASS` schemas,
   remove the hardcoded `DEFAULT_CONFIG`, `config init [--force]` / `config sync` CLI
   subcommand. **Depends on 5dl.9.1** (the generator needs the modules' `PARAMS_CLASS` and
   `Config`'s schema).

## Rejected alternatives

- **pydantic / pydantic-settings / goodconf** — heaviest cold-start (~36 ms + compiled
  `pydantic-core` wheel) on a per-render tool; pydantic-settings solves multi-source env
  layering we do not have; goodconf is the only one generating commented TOML but does not
  comment per-section sub-fields (exactly our need) and still drags in pydantic.
- **msgspec** — fastest library (~11 ms, C backend, native choices introspection), but adds
  a compiled dependency to a currently zero-runtime-dep tool, needs `Annotated[..., Meta(...)]`
  ceremony for descriptions, and we still hand-write the template generator. Reasonable
  fallback if validation needs ever outgrow hand-rolled coercion.
- **`Generic` descriptor (`ConfigField[T]`)** — enables `self.x` access but cluttered
  declaration and type-safe under `ty` only with an explicit annotation (silent footgun if
  omitted). Superseded by `dataclass` + `param()`.
- **Converting `Config` to descriptors** — loses dataclass's free keyword constructor, breaks
  every `Config(...)` call site, no benefit over `Config`-as-params-dataclass.
