"""Declarative config schema: param declaration, validation, and parsing.

This module has NO presentation dependency (no termcolor, no print). It returns
data; callers (BaseModule, load_config, the future `config validate`) decide how
to surface warnings.
"""

from dataclasses import Field, dataclass, field, fields
from typing import Any, TypeVar, dataclass_transform, get_args, get_origin, overload

T = TypeVar("T")

_ALLOWED_PRIMITIVES = (bool, int, float, str)
_VARIADIC_TUPLE_ARGS = 2  # tuple[X, ...] -> get_args() returns (X, Ellipsis)


def _check_declared_type(declared: Any, description: str) -> None:
    """Raise ValueError unless `declared` is a supported param type.

    Allowed: the primitives bool/int/float/str, and ``list[X]``/``tuple[X]``/``tuple[X, ...]``
    where X is one of those primitives. Everything else is rejected at declaration time, so
    misuse fails on import rather than silently at parse time: dict, set, multi-arg or
    heterogeneous generics (``dict[K, V]``, ``tuple[int, str]``), nested generics
    (``list[list[str]]``), generics over non-primitives, and bare ``list``/``tuple`` with no
    element type.

    datetime/date/time are also valid TOML scalars but no param needs one; add them to
    ``_ALLOWED_PRIMITIVES`` if that ever changes.
    """
    if declared in _ALLOWED_PRIMITIVES:
        return
    origin = get_origin(declared)
    if origin in (list, tuple):
        args = get_args(declared)
        if origin is tuple and len(args) == _VARIADIC_TUPLE_ARGS and args[1] is Ellipsis:
            args = (args[0],)  # tuple[X, ...] is homogeneous: validate the single element type
        if len(args) == 1 and args[0] in _ALLOWED_PRIMITIVES:
            return
    allowed = ", ".join(t.__name__ for t in _ALLOWED_PRIMITIVES)
    msg = (
        f"param({description!r}): unsupported type {declared!r}; allowed are {allowed} "
        f"and list/tuple over one such primitive (e.g. list[str], tuple[int, ...])"
    )
    raise ValueError(msg)


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

    Mutable defaults (list/dict/set) get a fresh *shallow* copy per instance via
    default_factory; nested mutable objects would be shared (no current field nests).

    `choices` is either a plain tuple of allowed values or a dict mapping each value to a
    short help string. Both forms are stored verbatim in metadata; the 9.2 template
    generator renders them. `description` is left untouched.

    Raises ValueError if `default is None` and `type_` is not given.
    """
    if default is None and type_ is None:
        msg = f"param({description!r}): default is None, an explicit type_ is required"
        raise ValueError(msg)
    declared = type_ or type(default)
    _check_declared_type(declared, description)
    if default is not None:
        # `default` may diverge from `declared` when type_ is passed explicitly (e.g.
        # param({}, ..., type_=str)). Reject a default that violates its own type or choices so
        # it fails at declaration, not silently when the field is omitted from raw config.
        _, default_err = _coerce(default, declared, choices)
        if default_err is not None:
            msg = f"param({description!r}): invalid default: {default_err}"
            raise ValueError(msg)
    meta = {"description": description, "choices": choices, "type": declared}
    if isinstance(default, list):
        # Only list is both schema-allowed (_check_declared_type) and mutable, so it is the only
        # default needing a fresh per-instance copy. tuple is immutable; dict/set are rejected above.
        return field(default_factory=lambda: type(default)(default), metadata=meta)
    return field(default=default, metadata=meta)


@dataclass_transform(frozen_default=True, field_specifiers=(field, param))
def schema(cls: type[T]) -> type[T]:
    """Frozen dataclass schema decorator for param-based config classes.

    Used for both module ``*Params`` classes and the top-level ``Config`` — config is loaded
    once and never mutated during a render, so a single frozen decorator expresses both.

    ``dataclass_transform(field_specifiers=(field, param))`` tells PEP 681-aware tools (ruff, ty)
    that ``param()`` is a legitimate field specifier: no RUF009 false positive, and each field is
    typed from its annotation. ``frozen_default=True`` makes ty enforce read-only access. The body
    returns a real frozen dataclass, so ``is_dataclass()``/``fields()``/runtime ``frozen`` hold.

    ``Config`` holds a plain ``module_configs`` dict; freezing locks only the field binding, not
    the dict's contents — and nothing rebinds or mutates it after construction.
    """
    return dataclass(frozen=True)(cls)


@dataclass(frozen=True)
class ParamWarning:
    """A single, section-attributable config problem. Callers format/print it."""

    field: str  # the offending key
    message: str  # e.g. "expected int, got str", "unknown key"
    kind: str  # "invalid" | "unknown"


def _type_msg(raw: Any, expected_type: Any) -> str | None:
    """Return an error message if `raw` fails the type check, else None.

    Handles generics (list[str]), bool-vs-int strictness, and plain types. Declared types are
    restricted by `_check_declared_type` to primitives and list/tuple over a single primitive,
    so a generic always has exactly one primitive element type to validate.

    One residual laxity: ``list[int]`` admits ``bool`` elements, since ``bool`` subclasses
    ``int`` and element checks use ``isinstance``. No current field hits this.
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
