"""Data types for statuskit."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


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
class RateLimitWindow:
    """One subscription usage window reported by Claude Code in the statusline payload."""

    used_percentage: float
    resets_at: datetime | None


@dataclass
class RateLimits:
    """Subscription usage limits from the payload's `rate_limits` block.

    Claude Code fills these from the `anthropic-ratelimit-unified-*` response headers, so they
    cost no network call and refresh on every API response. `spend_limit` (gateway deployments)
    is deliberately not modelled — statuskit does not render it.
    """

    five_hour: RateLimitWindow | None = None
    seven_day: RateLimitWindow | None = None


def _parse_rate_limit_window(value: object) -> RateLimitWindow | None:
    """Build a RateLimitWindow from one payload window, or None when it is unusable.

    Payload values are untrusted: `used_percentage` must be a finite number (a bool would sail
    through `float()` as 1.0), and `resets_at` is epoch SECONDS, not an ISO string. A window with
    an unusable reset time is still worth showing, so only the percentage gates the window.
    """
    if not isinstance(value, dict):
        return None
    percent = value.get("used_percentage")
    if isinstance(percent, bool) or not isinstance(percent, int | float) or not math.isfinite(percent):
        return None
    resets_at = None
    epoch = value.get("resets_at")
    if not isinstance(epoch, bool) and isinstance(epoch, int | float) and math.isfinite(epoch):
        try:
            resets_at = datetime.fromtimestamp(epoch, UTC)
        except (OSError, OverflowError, ValueError):
            resets_at = None
    return RateLimitWindow(used_percentage=float(percent), resets_at=resets_at)


@dataclass
class StatusInput:
    """Parsed input from Claude Code status hook."""

    session_id: str | None
    cwd: str | None
    model: Model | None
    workspace: Workspace | None
    cost: Cost | None
    context_window: ContextWindow | None
    rate_limits: RateLimits | None = None

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

        rl_data = data.get("rate_limits")
        rate_limits = None
        if isinstance(rl_data, dict):
            five_hour = _parse_rate_limit_window(rl_data.get("five_hour"))
            seven_day = _parse_rate_limit_window(rl_data.get("seven_day"))
            if five_hour is not None or seven_day is not None:
                rate_limits = RateLimits(five_hour=five_hour, seven_day=seven_day)

        return cls(
            session_id=data.get("session_id"),
            cwd=data.get("cwd"),
            model=model,
            workspace=workspace,
            cost=cost,
            context_window=context_window,
            rate_limits=rate_limits,
        )


@dataclass
class RenderContext:
    """Context passed to modules for rendering."""

    debug: bool
    data: StatusInput
    cache_dir: Path | None = None
