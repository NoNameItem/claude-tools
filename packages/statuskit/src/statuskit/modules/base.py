"""Base module class for statuskit."""

from abc import ABC, abstractmethod

from statuskit.core.models import RenderContext


class BaseModule(ABC):
    """Base class for statuskit modules.

    Subclasses must define:
    - name: str - module identifier
    - description: str - human-readable description
    - render() -> str | None - output to display
    """

    name: str
    description: str

    def __init__(self, ctx: RenderContext, config: dict):
        """Initialize module with context and config.

        Args:
            ctx: Render context with debug flag and status data
            config: Module-specific configuration from TOML
        """
        self.debug = ctx.debug
        self.data = ctx.data
        self.config = config

    @abstractmethod
    def render(self) -> str | None:
        """Render module output.

        Returns:
            String to display (can be multiline) or None to skip.
        """
        ...
