"""Data types for statuskit."""

from dataclasses import dataclass


@dataclass
class Model:
    """Model information from Claude Code."""

    id: str | None
    display_name: str


@dataclass
class Workspace:
    """Workspace paths from Claude Code."""

    current_dir: str
    project_dir: str


@dataclass
class Cost:
    """Cost and timing information from Claude Code."""

    total_cost_usd: float | None
    total_duration_ms: int | None
    total_api_duration_ms: int | None
    total_lines_added: int | None
    total_lines_removed: int | None


@dataclass
class CurrentUsage:
    """Current context window usage."""

    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int


@dataclass
class ContextWindow:
    """Context window information from Claude Code."""

    context_window_size: int | None
    total_input_tokens: int | None
    total_output_tokens: int | None
    current_usage: CurrentUsage | None


@dataclass
class StatusInput:
    """Parsed input from Claude Code status hook."""

    session_id: str | None
    cwd: str | None
    model: Model | None
    workspace: Workspace | None
    cost: Cost | None
    context_window: ContextWindow | None

    @classmethod
    def from_dict(cls, data: dict) -> "StatusInput":
        """Parse JSON dict into StatusInput dataclass.

        Missing fields become None.
        """
        model_data = data.get("model")
        model = (
            Model(
                id=model_data.get("id"),
                display_name=model_data.get("display_name", "Unknown"),
            )
            if model_data
            else None
        )

        workspace_data = data.get("workspace")
        workspace = (
            Workspace(
                current_dir=workspace_data.get("current_dir", ""),
                project_dir=workspace_data.get("project_dir", ""),
            )
            if workspace_data
            else None
        )

        cost_data = data.get("cost")
        cost = (
            Cost(
                total_cost_usd=cost_data.get("total_cost_usd"),
                total_duration_ms=cost_data.get("total_duration_ms"),
                total_api_duration_ms=cost_data.get("total_api_duration_ms"),
                total_lines_added=cost_data.get("total_lines_added"),
                total_lines_removed=cost_data.get("total_lines_removed"),
            )
            if cost_data
            else None
        )

        ctx_data = data.get("context_window")
        context_window = None
        if ctx_data:
            usage_data = ctx_data.get("current_usage")
            current_usage = (
                CurrentUsage(
                    input_tokens=usage_data.get("input_tokens", 0),
                    output_tokens=usage_data.get("output_tokens", 0),
                    cache_creation_input_tokens=usage_data.get("cache_creation_input_tokens", 0),
                    cache_read_input_tokens=usage_data.get("cache_read_input_tokens", 0),
                )
                if usage_data
                else None
            )

            context_window = ContextWindow(
                context_window_size=ctx_data.get("context_window_size"),
                total_input_tokens=ctx_data.get("total_input_tokens"),
                total_output_tokens=ctx_data.get("total_output_tokens"),
                current_usage=current_usage,
            )

        return cls(
            session_id=data.get("session_id"),
            cwd=data.get("cwd"),
            model=model,
            workspace=workspace,
            cost=cost,
            context_window=context_window,
        )


@dataclass
class RenderContext:
    """Context passed to modules for rendering."""

    debug: bool
    data: StatusInput
