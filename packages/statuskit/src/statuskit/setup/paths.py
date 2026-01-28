"""Path resolution for setup command."""

from enum import Enum
from pathlib import Path

from statuskit.core.constants import CLAUDE_DIR, CONFIG_FILENAME


class Scope(Enum):
    """Installation scope for statuskit."""

    USER = "user"
    PROJECT = "project"
    LOCAL = "local"


SETTINGS_FILENAME = "settings.json"
SETTINGS_LOCAL_FILENAME = "settings.local.json"
CONFIG_LOCAL_FILENAME = CONFIG_FILENAME.replace(".toml", ".local.toml")


def get_settings_path(scope: Scope) -> Path:
    """Get settings.json path for the given scope."""
    if scope == Scope.USER:
        return Path.home() / CLAUDE_DIR / SETTINGS_FILENAME
    if scope == Scope.PROJECT:
        return Path(CLAUDE_DIR) / SETTINGS_FILENAME
    # LOCAL
    return Path(CLAUDE_DIR) / SETTINGS_LOCAL_FILENAME


def get_config_path(scope: Scope) -> Path:
    """Get statuskit.toml path for the given scope."""
    if scope == Scope.USER:
        return Path.home() / CLAUDE_DIR / CONFIG_FILENAME
    if scope == Scope.PROJECT:
        return Path(CLAUDE_DIR) / CONFIG_FILENAME
    # LOCAL
    return Path(CLAUDE_DIR) / CONFIG_LOCAL_FILENAME
