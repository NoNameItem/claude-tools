"""Tests for statuskit.core.schema."""

from dataclasses import field, fields

import pytest
from statuskit.core.schema import (
    NoParams,
    _coerce,
    param,
    params_schema,
    parse_params,
)

# --- param() ---


def test_param_builds_field_with_metadata():
    @params_schema
    class S:
        x: int = param(5, "an int")

    f = next(fld for fld in fields(S) if fld.name == "x")
    assert f.metadata["description"] == "an int"
    assert f.metadata["type"] is int
    assert f.metadata["choices"] is None
    assert S().x == 5


def test_param_mutable_default_isolated():
    @params_schema
    class S:
        items: list = param([], "a list", type_=list)

    a, b = S(), S()
    a.items.append(1)
    assert b.items == []


def test_param_none_without_type_raises():
    with pytest.raises(ValueError, match="explicit type_"):
        param(None, "bad")


def test_param_none_with_type_allowed():
    fld = param(None, "ok", type_=str)
    assert fld.metadata["type"] is str


def test_param_stores_tuple_choices_verbatim():
    @params_schema
    class S:
        c: str = param("a", "choice", choices=("a", "b"))

    f = next(fld for fld in fields(S) if fld.name == "c")
    assert f.metadata["choices"] == ("a", "b")
    assert f.metadata["description"] == "choice"


def test_param_stores_dict_choices_verbatim():
    choices = {"a": "help a", "b": "help b"}

    @params_schema
    class S:
        c: str = param("a", "choice", choices=choices)

    f = next(fld for fld in fields(S) if fld.name == "c")
    assert f.metadata["choices"] == choices
    assert f.metadata["description"] == "choice"  # description left untouched


# --- _coerce() ---


def test_coerce_valid_passthrough():
    assert _coerce(5, int, None) == (5, None)


def test_coerce_wrong_type():
    value, err = _coerce("x", int, None)
    assert value is None
    assert err is not None
    assert "expected int" in err


def test_coerce_bool_rejected_for_int():
    value, err = _coerce(True, int, None)
    assert value is None
    assert err is not None
    assert "expected int, got bool" in err


def test_coerce_bool_field_accepts_bool():
    assert _coerce(True, bool, None) == (True, None)


def test_coerce_bool_field_rejects_int():
    value, err = _coerce(1, bool, None)
    assert value is None
    assert err is not None
    assert "expected bool" in err


def test_coerce_int_rejects_float():
    value, err = _coerce(10.0, int, None)
    assert value is None
    assert err is not None
    assert "expected int, got float" in err


def test_coerce_choices_tuple_membership():
    assert _coerce("a", str, ("a", "b")) == ("a", None)
    value, err = _coerce("c", str, ("a", "b"))
    assert value is None
    assert err is not None
    assert "not in choices: a, b" in err


def test_coerce_choices_dict_membership_lists_keys_only():
    choices = {"a": "help a", "b": "help b"}
    assert _coerce("a", str, choices) == ("a", None)
    value, err = _coerce("c", str, choices)
    assert value is None
    assert err is not None
    assert "not in choices: a, b" in err  # help strings never leak


def test_coerce_generic_list_str_valid():
    assert _coerce(["a", "b"], list[str], None) == (["a", "b"], None)


def test_coerce_generic_rejects_non_list():
    value, err = _coerce("x", list[str], None)
    assert value is None
    assert err is not None
    assert "expected list" in err


def test_coerce_generic_rejects_bad_element():
    value, err = _coerce(["a", 42], list[str], None)
    assert value is None
    assert err is not None
    assert "str" in err


# --- parse_params() ---


@params_schema
class SampleParams:
    flag: bool = param(True, "a flag")
    count: int = param(3, "a count")
    mode: str = param("x", "a mode", choices=("x", "y"))


def test_parse_params_valid():
    values, warnings = parse_params(SampleParams, {"flag": False, "count": 7, "mode": "y"})
    assert values == {"flag": False, "count": 7, "mode": "y"}
    assert warnings == []


def test_parse_params_missing_keys_omitted():
    values, warnings = parse_params(SampleParams, {})
    assert values == {}
    assert warnings == []


def test_parse_params_wrong_type_warns_and_drops():
    values, warnings = parse_params(SampleParams, {"count": "nope"})
    assert "count" not in values
    assert len(warnings) == 1
    assert warnings[0].field == "count"
    assert warnings[0].kind == "invalid"


def test_parse_params_not_in_choices_warns():
    values, warnings = parse_params(SampleParams, {"mode": "z"})
    assert "mode" not in values
    assert warnings[0].field == "mode"
    assert warnings[0].kind == "invalid"


def test_parse_params_unknown_key_warns():
    values, warnings = parse_params(SampleParams, {"bogus": 1})
    assert values == {}
    assert len(warnings) == 1
    assert warnings[0].field == "bogus"
    assert warnings[0].kind == "unknown"


def test_parse_params_skips_non_schema_field():
    @params_schema
    class WithInternal:
        a: int = param(1, "a")
        internal: dict = field(default_factory=dict)  # no metadata -> not a schema field

    values, _ = parse_params(WithInternal, {"a": 2})
    assert values == {"a": 2}  # 'internal' never coerced or added


# --- NoParams ---


def test_noparams_is_empty_dataclass():
    assert fields(NoParams) == ()
    assert NoParams() is not None
