"""Model module for statuskit."""

from termcolor import colored

from statuskit.modules.base import BaseModule

# Time constants
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600

# Number formatting thresholds
_THOUSAND = 1_000
_MILLION = 1_000_000


class ModelModule(BaseModule):
    """Display model name, session duration, and context window usage."""

    name = "model"
    description = "Model name, session duration, context window usage"

    def __init__(self, ctx, config: dict):
        super().__init__(ctx, config)
        self.show_duration = config.get("show_duration", True)
        self.show_context = config.get("show_context", True)
        self.context_format = config.get("context_format", "free")
        self.context_compact = config.get("context_compact", False)
        self.threshold_green = config.get("context_threshold_green", 50)
        self.threshold_yellow = config.get("context_threshold_yellow", 25)

    def render(self) -> str | None:
        parts = []

        # [Model name]
        if self.data.model:
            parts.append(f"[{self.data.model.display_name}]")

        # Duration: 2h 15m
        if self.show_duration:
            duration = self._format_duration()
            if duration:
                parts.append(duration)

        # Context: 150,000 free (75.0%)
        if self.show_context:
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
        if pct_free > self.threshold_green:
            return "green"
        if pct_free > self.threshold_yellow:
            return "yellow"
        return "red"

    def _format_context_text(self, free: int, used: int, total: int, pct_free: float, pct_used: float) -> str:
        fmt = self._get_number_formatter()
        free_fmt, used_fmt, total_fmt = fmt(free), fmt(used), fmt(total)
        pct_precision = 0 if self.context_compact else 1

        if self.context_format == "used":
            return f"{used_fmt} used ({pct_used:.{pct_precision}f}%)"
        if self.context_format == "ratio":
            return f"{used_fmt}/{total_fmt} ({pct_used:.{pct_precision}f}%)"
        if self.context_format == "bar":
            bar = self._make_bar(pct_free)
            return f"{bar} {pct_free:.0f}%"
        # "free" or default
        return f"{free_fmt} free ({pct_free:.{pct_precision}f}%)"

    def _get_number_formatter(self):
        if self.context_compact:
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
