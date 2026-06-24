"""Tests for statuskit.modules.base."""

from dataclasses import FrozenInstanceError, dataclass
from typing import Generic, TypeVar

import pytest
from statuskit.core.schema import NoParams, param, params_schema
from statuskit.modules.base import BaseModule


@params_schema
class StubParams:
    option: str = param("default", "An option")


class StubModule(BaseModule[StubParams]):
    name = "stub"
    description = "Stub module"

    def render(self) -> str | None:
        return f"stub output debug={self.debug}"


class NoParamsModule(BaseModule[NoParams]):
    name = "noparams"
    description = "No params module"

    def render(self) -> str | None:
        return "ok"


# --- behavior ---


def test_base_module_parses_section_into_params(make_render_context, minimal_input_data):
    ctx = make_render_context(minimal_input_data, debug=True)
    mod = StubModule(ctx, {"option": "value"})
    assert mod.debug is True
    assert mod.data is ctx.data
    assert mod.params.option == "value"


def test_base_module_uses_defaults_for_missing(make_render_context, minimal_input_data):
    ctx = make_render_context(minimal_input_data)
    mod = StubModule(ctx, {})
    assert mod.params.option == "default"


def test_base_module_per_field_fallback(make_render_context, minimal_input_data):
    ctx = make_render_context(minimal_input_data)
    mod = StubModule(ctx, {"option": 123})  # wrong type -> default applies
    assert mod.params.option == "default"


def test_base_module_render(make_render_context):
    ctx = make_render_context({}, debug=False)
    mod = StubModule(ctx, {})
    assert mod.render() == "stub output debug=False"


def test_base_module_debug_prints_warning(make_render_context, minimal_input_data, capsys):
    ctx = make_render_context(minimal_input_data, debug=True)
    StubModule(ctx, {"bogus": 1})
    captured = capsys.readouterr()
    assert "[!] stub.bogus" in captured.out


def test_base_module_no_warning_without_debug(make_render_context, minimal_input_data, capsys):
    ctx = make_render_context(minimal_input_data, debug=False)
    StubModule(ctx, {"bogus": 1})
    captured = capsys.readouterr()
    assert captured.out == ""


def test_noparams_module_constructs(make_render_context, minimal_input_data):
    ctx = make_render_context(minimal_input_data)
    mod = NoParamsModule(ctx, {})
    assert isinstance(mod.params, NoParams)


def test_params_are_frozen(make_render_context, minimal_input_data):
    ctx = make_render_context(minimal_input_data)
    mod = StubModule(ctx, {})
    attr = "option"  # variable name avoids ruff B010; setattr avoids ty's static read-only error
    with pytest.raises(FrozenInstanceError):
        setattr(mod.params, attr, "x")


# --- strict resolution (enforced at class creation) ---


def test_missing_generic_arg_raises():
    with pytest.raises(TypeError):

        class Bad(BaseModule):  # no generic argument
            name = "bad"
            description = "bad"

            def render(self) -> str | None:
                return None


def test_non_dataclass_params_raises():
    class NotADataclass:
        pass

    with pytest.raises(TypeError):

        class Bad(BaseModule[NotADataclass]):
            name = "bad"
            description = "bad"

            def render(self) -> str | None:
                return None


def test_field_without_param_raises():
    @dataclass(frozen=True)
    class BadParams:
        x: int = 10  # plain default, not param()

    with pytest.raises(TypeError):

        class Bad(BaseModule[BadParams]):
            name = "bad"
            description = "bad"

            def render(self) -> str | None:
                return None


def test_ambiguous_params_raises():
    @params_schema
    class A:
        a: int = param(1, "a")

    @params_schema
    class B:
        b: int = param(1, "b")

    with pytest.raises(TypeError):

        class Bad(BaseModule[A], BaseModule[B]):
            name = "bad"
            description = "bad"

            def render(self) -> str | None:
                return None


def test_generic_intermediate_resolves_lazily(make_render_context, minimal_input_data):
    Q = TypeVar("Q")

    class Mid(BaseModule[Q], Generic[Q]):
        def render(self) -> str | None:
            return None

    ctx = make_render_context(minimal_input_data)
    with pytest.raises(TypeError):
        Mid(ctx, {})

    @params_schema
    class FooParams:
        v: int = param(1, "v")

    class Concrete(Mid[FooParams]):
        name = "concrete"
        description = "concrete"

    assert Concrete._params_class is FooParams
