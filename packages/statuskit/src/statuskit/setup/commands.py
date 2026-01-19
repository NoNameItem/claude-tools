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


def _get_higher_scopes(scope: Scope) -> list[Scope]:
    """Get scopes higher than the given scope.

    Scope hierarchy (lower to higher): LOCAL -> PROJECT -> USER
    """
    order = [Scope.LOCAL, Scope.PROJECT, Scope.USER]
    idx = order.index(scope)
    return order[idx + 1 :]


def _check_higher_scope_installation(scope: Scope) -> Scope | None:
    """Check if statuskit is installed at a higher scope.

    Returns the higher scope if installed, None otherwise.
    """
    for higher_scope in _get_higher_scopes(scope):
        settings_path = get_settings_path(higher_scope)
        settings = read_settings(settings_path)
        if is_our_hook(settings.get("statusLine", {})):
            return higher_scope
    return None


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

    # Check for higher scope installation (don't duplicate hook)
    higher_scope = _check_higher_scope_installation(scope)
    if higher_scope and not force:
        # Just create config, don't install hook
        config_created = create_config(config_path)
        return InstallResult(
            success=True,
            higher_scope_installed=True,
            higher_scope=higher_scope,
            config_created=config_created,
            message=f"Already installed at {higher_scope.value} scope",
        )

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


@dataclass
class RemoveResult:
    """Result of remove_hook operation."""

    success: bool = False
    not_installed: bool = False
    message: str = ""


def remove_hook(scope: Scope, force: bool, ui: UI | None) -> RemoveResult:
    """Remove statuskit hook from settings.json.

    Args:
        scope: Installation scope to remove from
        force: Skip confirmation for foreign hooks
        ui: User interaction handler

    Returns:
        RemoveResult with operation details
    """
    settings_path = get_settings_path(scope)

    # Read current settings
    try:
        settings = read_settings(settings_path)
    except ValueError as e:
        return RemoveResult(success=False, message=str(e))

    current_hook = settings.get("statusLine", {})

    # Check if anything to remove
    if not current_hook.get("command"):
        return RemoveResult(
            success=True,
            not_installed=True,
            message="Not installed",
        )

    # Check if it's our hook
    if not is_our_hook(current_hook):
        foreign_cmd = current_hook.get("command", "")
        if force:
            pass  # proceed with removal
        elif ui:
            if not ui.confirm(f"statusLine points to: {foreign_cmd}\nRemove anyway?"):
                return RemoveResult(success=False, message="Cancelled by user")
        else:
            return RemoveResult(
                success=False,
                message=f"Foreign hook: {foreign_cmd}. Use --force to remove.",
            )

    # Remove hook
    del settings["statusLine"]
    write_settings(settings_path, settings)

    return RemoveResult(success=True, message="Removed successfully")


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
