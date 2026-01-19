"""Hook detection for setup command."""

import shlex
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
