"""Path resolution for setup command."""

from enum import Enum
from pathlib import Path


class Scope(Enum):
    """Installation scope for statuskit."""

    USER = "user"
    PROJECT = "project"
    LOCAL = "local"


def get_settings_path(scope: Scope) -> Path:
    """Get settings.json path for the given scope."""
    if scope == Scope.USER:
        return Path.home() / ".claude" / "settings.json"
    if scope == Scope.PROJECT:
        return Path(".claude") / "settings.json"
    # LOCAL
    return Path(".claude") / "settings.local.json"


def get_config_path(scope: Scope) -> Path:
    """Get statuskit.toml path for the given scope."""
    if scope == Scope.USER:
        return Path.home() / ".claude" / "statuskit.toml"
    if scope == Scope.PROJECT:
        return Path(".claude") / "statuskit.toml"
    # LOCAL
    return Path(".claude") / "statuskit.local.toml"
