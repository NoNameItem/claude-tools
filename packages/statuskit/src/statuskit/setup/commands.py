"""Setup command implementations."""

from dataclasses import dataclass
from typing import Protocol

from .config import create_config
from .gitignore import ensure_local_files_ignored
from .hooks import create_backup, is_our_hook, read_settings, write_settings
from .paths import Scope, get_config_path, get_settings_path


class UI(Protocol):
    """Protocol for user interaction."""

    def confirm(self, message: str) -> bool:
        """Ask user for yes/no confirmation."""
        ...

    def choose(self, message: str, options: list[str]) -> int:
        """Ask user to choose from options. Returns 0-based index."""
        ...


@dataclass
class InstallResult:
    """Result of install_hook operation."""

    success: bool = False
    already_installed: bool = False
    backup_created: bool = False
    config_created: bool = False
    gitignore_updated: bool = False
    higher_scope_installed: bool = False
    higher_scope: Scope | None = None
    message: str = ""


def install_hook(scope: Scope, force: bool, ui: UI | None) -> InstallResult:
    """Install statuskit hook to settings.json.

    Args:
        scope: Installation scope (user/project/local)
        force: Skip confirmations, create backup
        ui: User interaction handler (None for non-interactive)

    Returns:
        InstallResult with operation details
    """
    settings_path = get_settings_path(scope)
    config_path = get_config_path(scope)

    # Read current settings
    try:
        settings = read_settings(settings_path)
    except ValueError as e:
        return InstallResult(success=False, message=str(e))

    current_hook = settings.get("statusLine", {})

    # Check if already installed
    if is_our_hook(current_hook):
        # Still create config if missing
        config_created = create_config(config_path)
        return InstallResult(
            success=True,
            already_installed=True,
            config_created=config_created,
            message="Already installed",
        )

    # Handle foreign hook
    backup_created = False
    if current_hook.get("command"):
        if force:
            create_backup(settings_path)
            backup_created = True
        elif ui:
            foreign_cmd = current_hook.get("command", "")
            if not ui.confirm(f"statusLine points to: {foreign_cmd}\nOverwrite? (backup will be created)"):
                return InstallResult(success=False, message="Cancelled by user")
            create_backup(settings_path)
            backup_created = True
        else:
            return InstallResult(
                success=False,
                message=f"Foreign hook exists: {current_hook.get('command')}. Use --force to overwrite.",
            )

    # Install hook
    settings["statusLine"] = {"type": "command", "command": "statuskit"}
    write_settings(settings_path, settings)

    # Handle gitignore for local scope
    gitignore_updated = False
    if scope == Scope.LOCAL:
        gitignore_updated = ensure_local_files_ignored()

    # Create config
    config_created = create_config(config_path)

    return InstallResult(
        success=True,
        backup_created=backup_created,
        config_created=config_created,
        gitignore_updated=gitignore_updated,
        message="Installed successfully",
    )


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
