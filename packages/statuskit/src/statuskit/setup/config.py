"""Config file creation, reset and sync for setup command."""

import errno
import os
import shutil
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


def _write_atomic(path: Path, text: str, *, backup: bool = False) -> Path | None:
    """Write text to path atomically, following symlinks.

    A dotfiles-managed config is often a symlink; replacing the link itself would
    silently detach it, so the resolved target is written instead.

    The temp file is written first, then (with backup=True) the previous content is
    backed up, and only then is the target replaced, so a failed write never costs
    the previous backup. The original permission bits are carried over.
    Returns the backup path, if one was made.
    """
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    existed = target.exists()
    try:
        if existed and not os.access(target, os.W_OK):
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(target))
        tmp.write_text(text, encoding="utf-8", newline="\n")
        made = create_backup(path) if backup and existed else None
        if existed:
            shutil.copymode(target, tmp)
        tmp.replace(target)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return made


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
    try:
        path.stat()
        exists = True
    except FileNotFoundError:
        exists = False
    except OSError as exc:
        return InitResult(InitStatus.ERROR, error=f"Cannot read {path}: {exc}. Nothing was changed.")
    if exists and not force:
        return InitResult(InitStatus.EXISTS)
    try:
        backup = _write_atomic(path, build_config()[0], backup=exists)
    except OSError as exc:
        return InitResult(InitStatus.ERROR, error=f"Cannot write {path}: {exc}. Nothing was changed.")
    return InitResult(InitStatus.RESET if exists else InitStatus.CREATED, backup=backup)


def sync_config(path: Path, *, dry_run: bool) -> SyncResult:
    """Rebuild the config from the current schema, keeping the user's values."""
    raw: bytes | None
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raw = None
    except OSError as exc:
        return SyncResult(SyncStatus.ERROR, error=f"Cannot read {path}: {exc}. Nothing was changed.")

    if raw is None:
        text, _ = build_config()
        status = SyncStatus.CREATED
        removals: tuple[Removal, ...] = ()
    else:
        try:
            data = tomllib.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            return SyncResult(SyncStatus.ERROR, error=f"Cannot read {path}: {exc}. Nothing was changed.")
        text, found = build_config(data)
        removals = tuple(found)
        if text.encode("utf-8") == raw:
            return SyncResult(SyncStatus.UNCHANGED)
        status = SyncStatus.UPDATED

    if dry_run:
        return SyncResult(status, removals)
    try:
        backup = _write_atomic(path, text, backup=raw is not None)
    except OSError as exc:
        return SyncResult(SyncStatus.ERROR, error=f"Cannot write {path}: {exc}. Nothing was changed.")
    return SyncResult(status, removals, backup)
