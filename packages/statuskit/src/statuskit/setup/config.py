"""Config file creation, reset and sync for setup command."""

import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from statuskit.setup.config_gen import Removal, build_config
from statuskit.setup.hooks import create_backup


class InitStatus(Enum):
    """Outcome of init_config."""

    CREATED = "created"
    EXISTS = "exists"
    RESET = "reset"
    ERROR = "error"


@dataclass(frozen=True)
class InitResult:
    """Result of init_config (data only, nothing is printed)."""

    status: InitStatus
    backup: Path | None = None
    error: str = ""


class SyncStatus(Enum):
    """Outcome of sync_config."""

    CREATED = "created"
    UNCHANGED = "unchanged"
    UPDATED = "updated"
    ERROR = "error"


@dataclass(frozen=True)
class SyncResult:
    """Result of sync_config (data only, nothing is printed)."""

    status: SyncStatus
    removals: tuple[Removal, ...] = ()
    backup: Path | None = None
    error: str = ""


def _write_atomic(path: Path, text: str) -> None:
    """Write text to path atomically, following symlinks.

    A dotfiles-managed config is often a symlink; replacing the link itself would
    silently detach it, so the resolved target is written instead.
    """
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        tmp.replace(target)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def create_config(path: Path) -> bool:
    """Create statuskit.toml with the generated template.

    Does not overwrite existing file.
    Returns True if file was created, False if it already existed.
    """
    if path.exists():
        return False

    _write_atomic(path, build_config()[0])
    return True


def init_config(path: Path, *, force: bool) -> InitResult:
    """Write the default template; with force, reset an existing file (backed up)."""
    exists = path.exists()
    if exists and not force:
        return InitResult(InitStatus.EXISTS)
    try:
        backup = create_backup(path) if exists else None
        _write_atomic(path, build_config()[0])
    except OSError as exc:
        return InitResult(InitStatus.ERROR, error=f"Cannot write {path}: {exc}. Nothing was changed.")
    return InitResult(InitStatus.RESET if exists else InitStatus.CREATED, backup=backup)


def sync_config(path: Path, *, dry_run: bool) -> SyncResult:
    """Rebuild the config from the current schema, keeping the user's values."""
    if not path.exists():
        text, _ = build_config()
        status = SyncStatus.CREATED
        removals: tuple[Removal, ...] = ()
        raw = None
    else:
        try:
            raw = path.read_bytes()
            data = tomllib.loads(raw.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            return SyncResult(SyncStatus.ERROR, error=f"Cannot read {path}: {exc}. Nothing was changed.")
        text, found = build_config(data)
        removals = tuple(found)
        if text.encode("utf-8") == raw:
            return SyncResult(SyncStatus.UNCHANGED)
        status = SyncStatus.UPDATED

    if dry_run:
        return SyncResult(status, removals)
    try:
        backup = create_backup(path) if raw is not None else None
        _write_atomic(path, text)
    except OSError as exc:
        return SyncResult(SyncStatus.ERROR, error=f"Cannot write {path}: {exc}. Nothing was changed.")
    return SyncResult(status, removals, backup)
