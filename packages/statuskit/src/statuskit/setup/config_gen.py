"""Config template generation for setup command."""

import math
from collections.abc import Mapping
from dataclasses import MISSING, Field, dataclass, fields
from typing import Any, get_args

from statuskit.core.config import Config, split_sections
from statuskit.core.loader import BUILTIN_MODULES
from statuskit.core.schema import ParamWarning, parse_params
from statuskit.modules.base import BaseModule

_FIRST_PRINTABLE = 0x20
_DEL = 0x7F

_SIMPLE_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}

_TOML_TYPES: dict[type, str] = {bool: "boolean", int: "integer", float: "float", str: "string"}


def _toml_string(value: str) -> str:
    parts = []
    for char in value:
        if char in _SIMPLE_ESCAPES:
            parts.append(_SIMPLE_ESCAPES[char])
        elif ord(char) < _FIRST_PRINTABLE or ord(char) == _DEL:
            parts.append(f"\\u{ord(char):04X}")
        else:
            parts.append(char)
    return '"' + "".join(parts) + '"'


def _toml_float(value: float) -> str:
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return repr(value)


def toml_value(value: object) -> str:
    """Serialize a bool, int, float, str or list/tuple of those as a TOML literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _toml_float(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    msg = f"Cannot serialize {type(value).__name__} as a TOML value"
    raise TypeError(msg)


HEADER = (
    "# Statuskit configuration — https://pypi.org/project/claude-statuskit/\n"
    "#\n"
    "# Every option is listed with its default value, commented out.\n"
    "# Uncomment a line and change the value to override it.\n"
    "# `statuskit config sync` rebuilds this file: your values are kept,\n"
    "# unknown keys are removed, your own comments are not preserved.\n"
)
RULE = "# " + "─" * 61


@dataclass(frozen=True)
class Removal:
    """A key or value dropped while rebuilding a config file."""

    location: str
    reason: str


def _schema_fields(cls: type) -> list[Field]:
    return [f for f in fields(cls) if "type" in f.metadata]


def _default_of(f: Field) -> object:
    return f.default if f.default_factory is MISSING else f.default_factory()


def _choices_lines(choices: tuple | dict | None) -> list[str]:
    if isinstance(choices, dict):
        width = max(len(toml_value(v)) for v in choices)
        return [f"#   {toml_value(v).ljust(width)} — {help_text}" for v, help_text in choices.items()]
    if choices:
        return ["# Choices: " + ", ".join(toml_value(v) for v in choices)]
    return []


def _toml_type(declared: Any) -> str:
    """TOML name of a declared param type: a primitive, or list/tuple over one."""
    args = get_args(declared)
    if args:
        return f"array of {_TOML_TYPES[args[0]]}s"
    return _TOML_TYPES[declared]


def _option_block(f: Field, active: Mapping[str, object]) -> str:
    choices = f.metadata.get("choices")
    colon = ":" if isinstance(choices, dict) else ""
    lines = [f"# {f.metadata['description']}{colon}", *_choices_lines(choices)]
    if f.name in active:
        lines.append(f"{f.name} = {toml_value(active[f.name])}")
    elif (default := _default_of(f)) is None:
        # TOML has no null, so an unset default has no value to show: the line is left
        # empty, and uncommenting it as is would make the file unparsable.
        note = f"you must give it a value ({_toml_type(f.metadata['type'])})."
        lines += [f"# Not set by default. If you uncomment this line, {note}", f"# {f.name} ="]
    else:
        lines.append(f"# {f.name} = {toml_value(default)}")
    return "\n".join(lines)


def _banner_block(module: type[BaseModule]) -> str:
    return "\n".join([RULE, f"# {module.name}: {module.description}", RULE, f"[{module.name}]"])


def _clean_modules(value: list[str], registry: Mapping[str, type[BaseModule]]) -> tuple[list[str], list[Removal]]:
    kept: list[str] = []
    removals: list[Removal] = []
    for name in value:
        if name not in registry:
            removals.append(Removal(f'modules: "{name}"', "unknown module"))
        elif name in kept:
            removals.append(Removal(f'modules: "{name}"', "duplicate"))
        else:
            kept.append(name)
    return kept, removals


def _warning_removals(raw: dict, warnings: list[ParamWarning], prefix: str) -> list[tuple[int, Removal]]:
    """Removals for one scope, keyed by the position of the key in the raw dict."""
    order = {key: i for i, key in enumerate(raw)}
    return [(order[w.field], Removal(f"{prefix}{w.field}", w.message)) for w in warnings]


def _merge_globals(raw: dict, registry: Mapping[str, type[BaseModule]]) -> tuple[dict, list[Removal]]:
    """Validate top-level keys; returns the active values and removals in file order."""
    values, warnings = parse_params(Config, raw)
    positioned = _warning_removals(raw, warnings, "")
    if "modules" in values:
        values["modules"], cleaned = _clean_modules(values["modules"], registry)
        position = list(raw).index("modules")
        positioned.extend((position, removal) for removal in cleaned)
    positioned.sort(key=lambda item: item[0])  # stable: modules removals keep their list order
    return values, [removal for _, removal in positioned]


def _merge_tables(
    tables: dict[str, dict], registry: Mapping[str, type[BaseModule]]
) -> tuple[dict[str, dict], list[Removal]]:
    """Validate each module table; returns active values per module and removals in file order."""
    values: dict[str, dict] = {}
    removals: list[Removal] = []
    for name, raw in tables.items():
        if name not in registry:
            removals.append(Removal(f"[{name}]", "unknown section"))
            continue
        values[name], warnings = parse_params(registry[name].params_class(), raw)
        positioned = sorted(_warning_removals(raw, warnings, f"{name}."), key=lambda item: item[0])
        removals.extend(removal for _, removal in positioned)
    return values, removals


def build_config(
    data: dict | None = None,
    modules: Mapping[str, type[BaseModule]] | None = None,
) -> tuple[str, list[Removal]]:
    """Render the config template from the declared schema; returns the text and removals."""
    registry = BUILTIN_MODULES if modules is None else modules
    top_raw, tables = split_sections(data or {})
    global_values, global_removals = _merge_globals(top_raw, registry)
    table_values, table_removals = _merge_tables(tables, registry)
    blocks = [HEADER.rstrip("\n")]
    blocks.extend(_option_block(f, global_values) for f in _schema_fields(Config))
    for name, module in registry.items():
        blocks.append(_banner_block(module))
        blocks.extend(_option_block(f, table_values.get(name, {})) for f in _schema_fields(module.params_class()))
    return "\n\n".join(blocks) + "\n", [*global_removals, *table_removals]
