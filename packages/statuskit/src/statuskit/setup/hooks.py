"""Hook detection for setup command."""

import json
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


def create_backup(path: Path) -> Path:
    """Create backup of file as .bak.

    Overwrites existing .bak file.
    Returns path to backup file.
    """
    backup_path = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup_path)
    return backup_path
