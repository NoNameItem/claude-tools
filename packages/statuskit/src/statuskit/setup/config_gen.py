"""Config template generation for setup command."""

import math

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
