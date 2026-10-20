"""Tests for config template generation."""

import math
import re
import tomllib
from dataclasses import MISSING, fields
from pathlib import Path

import pytest
from statuskit.core.config import Config, split_sections
from statuskit.core.loader import BUILTIN_MODULES
from statuskit.core.schema import param, schema
from statuskit.modules.base import BaseModule
from statuskit.setup.config_gen import build_config, toml_value

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


HEADER = (
    "# Statuskit configuration — https://pypi.org/project/claude-statuskit/\n"
    "#\n"
    "# Every option is listed with its default value, commented out.\n"
    "# Uncomment a line and change the value to override it.\n"
    "# `statuskit config sync` rebuilds this file: your values are kept,\n"
    "# unknown keys are removed, your own comments are not preserved.\n"
)
RULE = "# " + "─" * 61
OPTION_LINE = re.compile(r"^# ([a-z_]+) = (.*)$")


def _schema_fields(cls):
    return [f for f in fields(cls) if "type" in f.metadata]


def _field_default(f):
    return f.default if f.default_factory is MISSING else f.default_factory()


def _sections_by_header(text):
    chunks = [[]]
    names = [None]
    for line in text.splitlines():
        m = re.fullmatch(r"\[([a-z_]+)\]", line)
        if m:
            names.append(m.group(1))
            chunks.append([])
        else:
            chunks[-1].append(line)
    return names, chunks


def test_template_starts_with_header_and_ends_with_one_newline():
    text, removals = build_config()
    assert text.startswith(HEADER + "\n")
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert removals == []


def test_template_parses_to_empty_module_tables():
    assert tomllib.loads(build_config()[0]) == {"model": {}, "git": {}, "usage_limits": {}}


def test_module_banner():
    banner = f"\n{RULE}\n# model: Model name, session duration, context window usage\n{RULE}\n[model]\n"
    assert banner in build_config()[0]


def test_every_option_appears_once_as_commented_default_in_its_section():
    names, chunks = _sections_by_header(build_config()[0])
    classes = {None: Config} | {n: m.params_class() for n, m in BUILTIN_MODULES.items()}
    assert names == [None, *BUILTIN_MODULES]
    for name, lines in zip(names, chunks, strict=True):
        for f in _schema_fields(classes[name]):
            expected = f"# {f.name} = {toml_value(_field_default(f))}"
            assert lines.count(expected) == 1, (name, f.name)


def test_uncommenting_any_single_option_line_sets_exactly_that_option():
    text = build_config()[0]
    lines = text.splitlines()
    total = len(_schema_fields(Config)) + sum(len(_schema_fields(m.params_class())) for m in BUILTIN_MODULES.values())
    option_idx = [i for i, line in enumerate(lines) if OPTION_LINE.match(line)]
    assert len(option_idx) == total
    for i in option_idx:
        match = OPTION_LINE.match(lines[i])
        assert match
        key = match.group(1)
        section = None
        for earlier in lines[:i]:
            m = re.fullmatch(r"\[([a-z_]+)\]", earlier)
            if m:
                section = m.group(1)
        edited = [*lines[:i], lines[i][2:], *lines[i + 1 :]]
        top, sections = split_sections(tomllib.loads("\n".join(edited)))
        if section is None:
            assert list(top) == [key]
            assert all(not body for body in sections.values())
        else:
            assert top == {}
            assert list(sections[section]) == [key]
            assert all(not body for n, body in sections.items() if n != section)


def test_dict_choices_render_as_padded_block():
    assert (
        "# Context display format:\n"
        '#   "free"  — free tokens remaining — e.g. `150,000 free (75.0%)`\n'
        '#   "used"  — tokens consumed — e.g. `50,000 used (25.0%)`\n'
        '#   "ratio" — used / total — e.g. `50,000/200,000 (25.0%)`\n'
        '#   "bar"   — progress bar — e.g. `[███████░░░] 75%`\n'
        '# context_format = "free"\n'
    ) in build_config()[0]


@schema
class _TupleParams:
    mode: str = param("a", "Mode", choices=("a", "b"))


class _FakeModule(BaseModule[_TupleParams]):
    name = "fake"
    description = "Fake module"


def test_tuple_choices_render_as_choices_line():
    text, _ = build_config(modules={"fake": _FakeModule})
    assert '\n# Mode\n# Choices: "a", "b"\n# mode = "a"\n' in text


def test_default_template_matches_golden_file():
    golden = (Path(__file__).parent / "data" / "default_config.toml").read_text(encoding="utf-8")
    assert build_config()[0] == golden
