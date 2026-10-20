"""Hook detection for setup command."""

import json
import os
import secrets
import shlex
import shutil
from pathlib import Path


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
    """Create a new, randomly named temp file next to path and return it with an open fd.

    O_EXCL never follows a symlink and fails if anything already exists at the name.
    """
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    return tmp, os.open(tmp, flags, 0o666)


def create_backup(path: Path) -> Path:
    """Create backup of file as .bak.

    Overwrites existing .bak file: a symlink there is replaced, not followed, and a
    failed copy leaves the previous backup intact.
    Returns path to backup file.
    """
    backup_path = path.with_suffix(path.suffix + ".bak")
    tmp, fd = open_temp_sibling(backup_path)
    try:
        try:
            dst = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            raise
        with dst, path.open("rb") as src:
            shutil.copyfileobj(src, dst)
        shutil.copystat(path, tmp)
        tmp.replace(backup_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return backup_path
