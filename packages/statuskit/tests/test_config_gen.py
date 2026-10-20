"""Tests for config template generation."""

import math
import tomllib

import pytest
from statuskit.setup.config_gen import toml_value

ROUND_TRIP = [
    True,
    False,
    0,
    -7,
    10**12,
    1.5,
    -0.25,
    1e300,
    "",
    "plain",
    'quote " inside',
    "back\\slash",
    "C:\\Users\\me",
    "tab\there",
    "new\nline",
    "bell\x07",
    "nul\x00",
    "del\x7f",
    "ünïcödé ✓ ███",
    "~/.cache/statuskit",
    [],
    ["model", "git"],
    [1, 2],
    [True, False],
    ("a", "b"),
]


@pytest.mark.parametrize("value", ROUND_TRIP)
def test_toml_value_round_trips(value):
    parsed = tomllib.loads(f"k = {toml_value(value)}")["k"]
    assert parsed == (list(value) if isinstance(value, tuple) else value)
    assert type(parsed) is (list if isinstance(value, tuple) else type(value))


def test_toml_value_literal_forms():
    assert toml_value(True) == "true"
    assert toml_value(False) == "false"
    assert toml_value(10) == "10"
    assert toml_value("free") == '"free"'
    assert toml_value(["model", "git"]) == '["model", "git"]'
    assert toml_value([]) == "[]"
    assert toml_value("ü") == '"ü"'  # non-ASCII written as-is


def test_toml_value_special_floats():
    assert toml_value(math.inf) == "inf"
    assert toml_value(-math.inf) == "-inf"
    assert math.isnan(tomllib.loads(f"k = {toml_value(math.nan)}")["k"])


@pytest.mark.parametrize("value", [None, {"a": 1}, {1, 2}, object()])
def test_toml_value_rejects_unsupported(value):
    with pytest.raises(TypeError):
        toml_value(value)
