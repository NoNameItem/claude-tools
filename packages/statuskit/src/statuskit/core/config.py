"""Configuration loading for statuskit."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from termcolor import colored

CONFIG_PATH = Path.home() / ".claude" / "statuskit.toml"


@dataclass
class Config:
    """Statuskit configuration."""

    debug: bool = False
    modules: list[str] = field(default_factory=lambda: ["model", "git", "beads", "quota"])
    module_configs: dict[str, dict] = field(default_factory=dict)

    def get_module_config(self, name: str) -> dict:
        """Get configuration for a specific module."""
        return self.module_configs.get(name, {})


def load_config() -> Config:
    """Load configuration from TOML file.

    Returns defaults if file doesn't exist.
    Shows error and returns defaults if file is invalid.
    """
    if not CONFIG_PATH.exists():
        return Config()

    try:
        with CONFIG_PATH.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        # Always show config errors
        print(colored(f"[!] Config error: {e}", "red"))
        return Config()

    # Extract module configs (any dict that's not a top-level setting)
    module_configs = {k: v for k, v in data.items() if isinstance(v, dict) and k not in ("debug", "modules")}

    return Config(
        debug=data.get("debug", False),
        modules=data.get("modules", Config().modules),
        module_configs=module_configs,
    )
