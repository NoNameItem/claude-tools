"""Setup command implementations."""

from .hooks import is_our_hook, read_settings
from .paths import Scope, get_settings_path


def check_installation() -> str:
    """Check installation status for all scopes.

    Returns formatted string showing status for each scope.
    """
    lines = []
    for scope in Scope:
        settings_path = get_settings_path(scope)
        settings = read_settings(settings_path)
        hook = settings.get("statusLine", {})

        status = "\u2713 Installed" if is_our_hook(hook) else "\u2717 Not installed"

        # Capitalize scope name
        scope_name = scope.value.capitalize()
        lines.append(f"{scope_name}:    {status}")

    return "\n".join(lines)
