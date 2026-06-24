"""Model module for statuskit."""

from termcolor import colored

from statuskit.core.schema import param, params_schema
from statuskit.modules.base import BaseModule

# Time constants
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600

# Number formatting thresholds
_THOUSAND = 1_000
_MILLION = 1_000_000


@params_schema
class ModelParams:
    show_duration: bool = param(True, "Show session duration")
    show_context: bool = param(True, "Show context window usage")
    context_format: str = param(
        "free",
        "Context display format",
        choices={
            "free": "free tokens remaining — e.g. `150,000 free (75.0%)`",
            "used": "tokens consumed — e.g. `50,000 used (25.0%)`",
            "ratio": "used / total — e.g. `50,000/200,000 (25.0%)`",
            "bar": "progress bar — e.g. `[███████░░░] 75%`",
        },
    )
    context_compact: bool = param(False, "Compact number format (150k instead of 150,000)")
    context_threshold_green: int = param(50, "Percentage free above which colour is green")
    context_threshold_yellow: int = param(25, "Percentage free above which colour is yellow")


class ModelModule(BaseModule[ModelParams]):
    """Display model name, session duration, and context window usage."""

    name = "model"
    description = "Model name, session duration, context window usage"

    def render(self) -> str | None:
        parts = []

        # [Model name]
        if self.data.model:
            parts.append(f"[{self.data.model.display_name}]")

        # Duration: 2h 15m
        if self.params.show_duration:
            duration = self._format_duration()
            if duration:
                parts.append(duration)

        # Context: 150,000 free (75.0%)
        if self.params.show_context:
            ctx_str = self._format_context()
            if ctx_str:
                parts.append(f"Context: {ctx_str}")

        return " | ".join(parts) if parts else None

    def _format_duration(self) -> str | None:
        if not self.data.cost or not self.data.cost.total_duration_ms:
            return None

        ms = self.data.cost.total_duration_ms
        if ms == 0:
            return None

        total_sec = ms // _THOUSAND
        if total_sec < _SECONDS_PER_MINUTE:
            return f"{total_sec}s"

        hours, remainder = divmod(total_sec, _SECONDS_PER_HOUR)
        minutes = remainder // _SECONDS_PER_MINUTE
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def _format_context(self) -> str | None:
        ctx = self.data.context_window
        if not ctx or not ctx.current_usage or not ctx.context_window_size:
            return None

        usage = ctx.current_usage
        total = ctx.context_window_size
        used = usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens
        free = total - used
        pct_free = (free / total) * 100
        pct_used = (used / total) * 100

        color = self._determine_color(pct_free)
        text = self._format_context_text(free, used, total, pct_free, pct_used)
        return colored(text, color)

    def _determine_color(self, pct_free: float) -> str:
        if pct_free > self.params.context_threshold_green:
            return "green"
        if pct_free > self.params.context_threshold_yellow:
            return "yellow"
        return "red"

    def _format_context_text(self, free: int, used: int, total: int, pct_free: float, pct_used: float) -> str:
        fmt = self._get_number_formatter()
        free_fmt, used_fmt, total_fmt = fmt(free), fmt(used), fmt(total)
        pct_precision = 0 if self.params.context_compact else 1

        if self.params.context_format == "used":
            return f"{used_fmt} used ({pct_used:.{pct_precision}f}%)"
        if self.params.context_format == "ratio":
            return f"{used_fmt}/{total_fmt} ({pct_used:.{pct_precision}f}%)"
        if self.params.context_format == "bar":
            bar = self._make_bar(pct_free)
            return f"{bar} {pct_free:.0f}%"
        # "free" or default
        return f"{free_fmt} free ({pct_free:.{pct_precision}f}%)"

    def _get_number_formatter(self):
        if self.params.context_compact:
            return self._compact_number
        return lambda n: f"{n:,}"

    def _compact_number(self, n: int) -> str:
        if n >= _MILLION:
            return f"{n / _MILLION:.1f}M"
        if n >= _THOUSAND:
            return f"{n / _THOUSAND:.0f}k"
        return str(n)

    def _make_bar(self, pct_free: float, width: int = 10) -> str:
        filled = int(pct_free / 100 * width)
        empty = width - filled
        return f"[{'█' * filled}{'░' * empty}]"
