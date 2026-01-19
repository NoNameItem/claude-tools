"""Config file creation for setup command."""

from pathlib import Path

DEFAULT_CONFIG = """\
# Statuskit configuration
# See: https://github.com/NoNameItem/claude-tools

# Modules to display (in order)
modules = ["model", "git", "beads", "quota"]

# Enable debug output
# debug = false
"""


def create_config(path: Path) -> bool:
    """Create statuskit.toml with default content.

    Does not overwrite existing file.
    Returns True if file was created, False if it already existed.
    """
    if path.exists():
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG)
    return True
