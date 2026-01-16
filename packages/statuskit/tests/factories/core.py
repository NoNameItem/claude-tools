"""Core data factories for statuskit tests.

Pure functions that create test data dicts.
No pytest dependency - can be imported directly.
"""


def make_model_data(
    display_name: str = "Opus",
    model_id: str | None = None,
) -> dict:
    """Create model data dict."""
    data = {"display_name": display_name}
    if model_id is not None:
        data["id"] = model_id
    return data


def make_cost_data(
    duration_ms: int | None = None,
    cost_usd: float | None = None,
    api_duration_ms: int | None = None,
    lines_added: int | None = None,
    lines_removed: int | None = None,
) -> dict:
    """Create cost data dict."""
    data = {}
    if duration_ms is not None:
        data["total_duration_ms"] = duration_ms
    if cost_usd is not None:
        data["total_cost_usd"] = cost_usd
    if api_duration_ms is not None:
        data["total_api_duration_ms"] = api_duration_ms
    if lines_added is not None:
        data["total_lines_added"] = lines_added
    if lines_removed is not None:
        data["total_lines_removed"] = lines_removed
    return data


def make_context_window_data(
    size: int = 200000,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation: int = 0,
    cache_read: int = 0,
) -> dict:
    """Create context window data dict."""
    return {
        "context_window_size": size,
        "current_usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read,
        },
    }


def make_input_data(  # noqa: PLR0913
    model: dict | None = None,
    cost: dict | None = None,
    context_window: dict | None = None,
    session_id: str | None = None,
    cwd: str | None = None,
    workspace: dict | None = None,
) -> dict:
    """Create full input data dict."""
    data = {}
    if model is not None:
        data["model"] = model
    if cost is not None:
        data["cost"] = cost
    if context_window is not None:
        data["context_window"] = context_window
    if session_id is not None:
        data["session_id"] = session_id
    if cwd is not None:
        data["cwd"] = cwd
    if workspace is not None:
        data["workspace"] = workspace
    return data
