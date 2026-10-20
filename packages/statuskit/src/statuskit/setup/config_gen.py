"""Config template generation for setup command."""

import math
from collections.abc import Mapping
from dataclasses import MISSING, Field, dataclass, fields

from statuskit.core.config import Config
from statuskit.core.loader import BUILTIN_MODULES
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


def _option_block(f: Field) -> str:
    choices = f.metadata.get("choices")
    colon = ":" if isinstance(choices, dict) else ""
    lines = [f"# {f.metadata['description']}{colon}", *_choices_lines(choices)]
    lines.append(f"# {f.name} = {toml_value(_default_of(f))}")
    return "\n".join(lines)


def _banner_block(module: type[BaseModule]) -> str:
    return "\n".join([RULE, f"# {module.name}: {module.description}", RULE, f"[{module.name}]"])


def build_config(
    data: dict | None = None,
    modules: Mapping[str, type[BaseModule]] | None = None,
) -> tuple[str, list[Removal]]:
    """Render the config template from the declared schema; returns the text and removals."""
    del data  # merging the user's values is implemented in a later step
    registry = BUILTIN_MODULES if modules is None else modules
    blocks = [HEADER.rstrip("\n")]
    blocks.extend(_option_block(f) for f in _schema_fields(Config))
    for module in registry.values():
        blocks.append(_banner_block(module))
        blocks.extend(_option_block(f) for f in _schema_fields(module.params_class()))
    return "\n\n".join(blocks) + "\n", []
