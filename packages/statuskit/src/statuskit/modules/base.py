"""Base module class for statuskit."""

from abc import ABC, abstractmethod
from dataclasses import fields, is_dataclass
from typing import Any, Generic, TypeVar, get_args, get_origin

from termcolor import colored

from statuskit.core.models import RenderContext
from statuskit.core.schema import parse_params

P = TypeVar("P")


class BaseModule(ABC, Generic[P]):
    """Base class for statuskit modules, generic over its params type.

    Subclasses declare their params type once, as the generic argument::

        class ModelModule(BaseModule[ModelParams]):
            ...

    The concrete params class is reflected from that argument in __init_subclass__ and stored as
    ``_params_class``. __init_subclass__ is strict: a malformed declaration raises TypeError at
    class creation, never silently at render.

    Subclasses must define:
    - name: str - module identifier
    - description: str - human-readable description
    - render() -> str | None - output to display
    """

    name: str
    description: str
    _params_class: type[P]  # resolved from BaseModule[X]; NOT a ClassVar (keeps type[P] -> P linkage)
    params: P

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        concrete: list[type[P]] = []
        has_typevar = False
        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if isinstance(origin, type) and issubclass(origin, BaseModule):
                (arg,) = get_args(base)
                if isinstance(arg, TypeVar):
                    has_typevar = True  # generic intermediate, e.g. BaseModule[P]
                else:
                    concrete.append(arg)

        if not concrete:
            if has_typevar or hasattr(cls, "_params_class"):
                return  # intermediate (defer), or inherits a resolved class via the MRO
            msg = f"{cls.__name__} must subclass BaseModule[<Params>] with a concrete params class"
            raise TypeError(msg)
        # Reachable when two distinct generic intermediates bind different params
        # (e.g. class Bad(Mid1[A], Mid2[B])); plain BaseModule[A], BaseModule[B] is rejected
        # earlier by Python as a duplicate base class.
        if len(set(concrete)) > 1:
            msg = f"{cls.__name__}: ambiguous params classes {concrete}"
            raise TypeError(msg)

        params_cls = concrete[0]
        if not is_dataclass(params_cls):
            msg = f"{cls.__name__}: {params_cls.__name__} is not a @dataclass"
            raise TypeError(msg)
        not_declared = [f.name for f in fields(params_cls) if "type" not in f.metadata]
        if not_declared:
            msg = f"{params_cls.__name__}: fields not declared via param(): {not_declared}"
            raise TypeError(msg)
        cls._params_class = params_cls

    def __init__(self, ctx: RenderContext, raw_section: dict) -> None:
        """Initialize module: parse the raw TOML section into typed ``self.params``.

        Args:
            ctx: Render context with debug flag and status data.
            raw_section: Module-specific raw configuration from TOML.
        """
        if not hasattr(type(self), "_params_class"):
            msg = f"{type(self).__name__} was not specialized with a params class"
            raise TypeError(msg)
        self.debug = ctx.debug
        self.data = ctx.data
        parsed, warnings = parse_params(self._params_class, raw_section)
        if ctx.debug:
            for w in warnings:
                print(colored(f"[!] {self.name}.{w.field}: {w.message}", "yellow"))
        self.params = self._params_class(**parsed)

    @abstractmethod
    def render(self) -> str | None:
        """Render module output.

        Returns:
            String to display (can be multiline) or None to skip.
        """
        ...
