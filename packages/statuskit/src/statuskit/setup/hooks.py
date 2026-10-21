"""Hook detection for setup command."""

import json
import os
import secrets
import shlex
import shutil
from datetime import datetime
from pathlib import Path

# O_EXCL never follows a symlink and fails if anything already exists at the name.
_NEW_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)


def is_our_hook(hook: dict) -> bool:
    """Check if the hook points to statuskit.

    Recognizes:
    - statuskit
    - /usr/local/bin/statuskit
    - ~/.local/bin/statuskit --debug
    """
    cmd = hook.get("command", "")
    if not cmd:
        return False
    try:
        first_word = shlex.split(cmd)[0]
        return Path(first_word).name == "statuskit"
    except ValueError:
        return False


def read_settings(path: Path) -> dict:
    """Read settings.json file.

    Returns empty dict if file doesn't exist.
    Raises ValueError if file contains invalid JSON.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        msg = f"Invalid JSON in {path}: {e}"
        raise ValueError(msg) from e


def write_settings(path: Path, data: dict) -> None:
    """Write settings.json file.

    Creates parent directories if needed.
    Uses 2-space indent for readability.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def open_temp_sibling(path: Path) -> tuple[Path, int]:
    """Create a new, randomly named temp file next to path and return it with an open fd."""
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    return tmp, os.open(tmp, _NEW_FILE_FLAGS, 0o666)


def _open_new_backup(path: Path, stamp: str) -> tuple[Path, int]:
    """Create the first free `<name>.<stamp>[-N].bak` next to path and return it with an open fd."""
    n = 0
    while True:
        suffix = f"{stamp}-{n}" if n else stamp
        candidate = path.with_name(f"{path.name}.{suffix}.bak")
        try:
            return candidate, os.open(candidate, _NEW_FILE_FLAGS, 0o666)
        except FileExistsError:
            n += 1


def create_backup(path: Path, *, now: datetime | None = None) -> Path:
    """Copy path to a new `<name>.<YYYYMMDD-HHMMSS>.bak` next to it and return the backup path.

    The name comes from the local time (`now`, the current time by default). An existing
    file is never touched: the backup is created exclusively, so a name that is already
    taken (a backup made in the same second, or a planted file or symlink) moves on to
    `-1`, `-2`, ... A failed copy removes the partial backup.
    """
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    backup_path, fd = _open_new_backup(path, stamp)
    try:
        try:
            dst = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            raise
        with dst, path.open("rb") as src:
            shutil.copyfileobj(src, dst)
        shutil.copystat(path, backup_path)
    except BaseException:
        backup_path.unlink(missing_ok=True)
        raise
    return backup_path
