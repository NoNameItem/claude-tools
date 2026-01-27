"""Module loader for statuskit."""

from statuskit.core.config import Config
from statuskit.core.models import RenderContext
from statuskit.modules import git, model
from statuskit.modules.base import BaseModule

BUILTIN_MODULES: dict[str, type[BaseModule]] = {
    "model": model.ModelModule,
    "git": git.GitModule,
    # "beads": ...,  # v0.3
    # "quota": ...,  # v0.4
}


def load_modules(config: Config, ctx: RenderContext) -> list[BaseModule]:
    """Load modules based on configuration.

    Args:
        config: Statuskit configuration
        ctx: Render context for modules

    Returns:
        List of instantiated modules
    """
    modules = []
    for name in config.modules:
        if name in BUILTIN_MODULES:
            module_config = config.get_module_config(name)
            modules.append(BUILTIN_MODULES[name](ctx, module_config))
        elif ctx.debug:
            print(f"[!] Unknown module: {name}")
    return modules
