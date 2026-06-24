"""Declarative config schema: param declaration, validation, and parsing.

This module has NO presentation dependency (no termcolor, no print). It returns
data; callers (BaseModule, load_config, the future `config validate`) decide how
to surface warnings.
"""

from dataclasses import Field, dataclass, field, fields
from typing import Any, TypeVar, dataclass_transform, get_args, get_origin, overload

T = TypeVar("T")


@overload
def param(
    default: None,
    description: str,
    *,
    choices: tuple | dict | None = ...,
    type_: type[T],
) -> Field[T]: ...


@overload
def param(
    default: T,
    description: str,
    *,
    choices: tuple[T, ...] | dict[T, str] | None = ...,
    type_: Any = ...,
) -> T: ...


def param(
    default: T,
    description: str,
    *,
    choices: tuple[T, ...] | dict[T, str] | None = None,
    type_: Any = None,
) -> T:
    """Declare a config field: a dataclasses.field() carrying description/choices/type.

    Annotated `-> T` so `x: bool = param(False, ...)` type-checks as bool. The runtime
    type used for validation is captured from `type(default)`, or from `type_` when the
    default is None or a generic alias (e.g. list[str]) with no runtime class.

    `choices` is either a plain tuple of allowed values or a dict mapping each value to a
    short help string. Both forms are stored verbatim in metadata; the 9.2 template
    generator renders them. `description` is left untouched.

    Raises ValueError if `default is None` and `type_` is not given.
    """
    if default is None and type_ is None:
        msg = f"param({description!r}): default is None, an explicit type_ is required"
        raise ValueError(msg)
    meta = {"description": description, "choices": choices, "type": type_ or type(default)}
    if isinstance(default, list | dict | set):
        return field(default_factory=lambda: type(default)(default), metadata=meta)
    return field(default=default, metadata=meta)


@dataclass_transform(frozen_default=True, field_specifiers=(field, param))
def params_schema(cls: type[T]) -> type[T]:
    """Frozen schema decorator for module ``*Params`` classes (and param-based test helpers).

    ``dataclass_transform(field_specifiers=(field, param))`` tells PEP 681-aware tools (ruff, ty)
    that ``param()`` is a legitimate field specifier: no RUF009 false positive, and each field is
    typed from its annotation. ``frozen_default=True`` makes ty enforce read-only access. The body
    returns a real frozen dataclass, so ``is_dataclass()``/``fields()``/runtime ``frozen`` hold.
    """
    return dataclass(frozen=True)(cls)


@dataclass_transform(field_specifiers=(field, param))
def config_schema(cls: type[T]) -> type[T]:
    """Non-frozen schema decorator for ``Config`` (it carries the mutable ``module_configs``)."""
    return dataclass(cls)


@dataclass(frozen=True)
class ParamWarning:
    """A single, section-attributable config problem. Callers format/print it."""

    field: str  # the offending key
    message: str  # e.g. "expected int, got str", "unknown key"
    kind: str  # "invalid" | "unknown"


def _type_msg(raw: Any, expected_type: Any) -> str | None:
    """Return an error message if `raw` fails the type check, else None.

    Handles generics (list[str]), bool-vs-int strictness, and plain types.
    """
    origin = get_origin(expected_type)
    msg: str | None = None
    if origin is not None:
        # Generic alias, e.g. list[str].
        if not isinstance(raw, origin):
            msg = f"expected {origin.__name__}, got {type(raw).__name__}"
        else:
            args = get_args(expected_type)
            if args:
                elem_type = args[0]
                bad = [e for e in raw if not isinstance(e, elem_type)]
                if bad:
                    msg = f"expected {origin.__name__}[{elem_type.__name__}], got element {type(bad[0]).__name__}"
    elif expected_type is bool and not isinstance(raw, bool):
        msg = f"expected bool, got {type(raw).__name__}"
    elif expected_type is int and (isinstance(raw, bool) or not isinstance(raw, int)):
        # bool is an int subclass; reject it so bar_width = true does not become True.
        msg = f"expected int, got {type(raw).__name__}"
    elif expected_type not in (bool, int) and not isinstance(raw, expected_type):
        msg = f"expected {expected_type.__name__}, got {type(raw).__name__}"
    return msg


def _coerce(raw: Any, expected_type: Any, choices: tuple | dict | None) -> tuple[None, str] | tuple[Any, None]:
    """Validate `raw` against `expected_type` (and `choices`). Never converts across types.

    Returns (value, None) on success or (None, "error text") on failure. TOML values are
    already typed, so this is effectively a validator: e.g. a float given to an int field
    is rejected, not truncated.
    """
    msg = _type_msg(raw, expected_type)
    if msg is not None:
        return None, msg
    if choices is not None and raw not in choices:
        allowed = ", ".join(str(c) for c in tuple(choices))
        return None, f"not in choices: {allowed}"
    return raw, None


def parse_params(params_cls: Any, raw: dict) -> tuple[dict, list[ParamWarning]]:
    """Return (validated {field_name: value}, warnings) for the schema fields of params_cls.

    Per-field fallback: a value of the wrong type or outside `choices` is dropped (the
    dataclass default applies on construction) and a ParamWarning(kind="invalid") is
    recorded. Absent keys are omitted. Unknown keys are recorded as kind="unknown".

    Pure: never prints. The caller decides whether to print, collect, or fail loudly.
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
    warnings.extend(ParamWarning(key, "unknown key", "unknown") for key in raw.keys() - known)
    return result, warnings


@dataclass(frozen=True)
class NoParams:
    """Params class for modules with no configurable options."""
