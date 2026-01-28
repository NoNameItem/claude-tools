"""Configuration loading for statuskit."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from termcolor import colored

from statuskit.core.constants import CLAUDE_DIR, CONFIG_FILENAME

# Kept for backward compatibility in tests
CONFIG_PATH = Path.home() / CLAUDE_DIR / CONFIG_FILENAME
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "statuskit"

CONFIG_LOCAL_FILENAME = CONFIG_FILENAME.replace(".toml", ".local.toml")


def _get_config_paths() -> list[Path]:
    """Get config paths in priority order (highest first)."""
    return [
        Path(CLAUDE_DIR) / CONFIG_LOCAL_FILENAME,  # Local (highest)
        Path(CLAUDE_DIR) / CONFIG_FILENAME,  # Project
        Path.home() / CLAUDE_DIR / CONFIG_FILENAME,  # User (lowest)
    ]


@dataclass
class Config:
    """Statuskit configuration."""

    debug: bool = False
    modules: list[str] = field(default_factory=lambda: ["model", "git", "usage_limits"])
    colors: bool = True
    module_configs: dict[str, dict] = field(default_factory=dict)
    cache_dir: Path = field(default_factory=lambda: DEFAULT_CACHE_DIR)

    def get_module_config(self, name: str) -> dict:
        """Get configuration for a specific module."""
        return self.module_configs.get(name, {})


def load_config() -> Config:
    """Load configuration from TOML files.

    Searches in priority order:
    1. .claude/statuskit.local.toml (Local)
    2. .claude/statuskit.toml (Project)
    3. ~/.claude/statuskit.toml (User)

    Returns defaults if no config file exists.
    Shows error and returns defaults if file is invalid.
    """
    for config_path in _get_config_paths():
        if config_path.exists():
            try:
                with config_path.open("rb") as f:
                    data = tomllib.load(f)
            except (tomllib.TOMLDecodeError, OSError) as e:
                print(colored(f"[!] Config error in {config_path}: {e}", "red"))
                return Config()

            # Extract module configs
            module_configs = {
                k: v for k, v in data.items() if isinstance(v, dict) and k not in ("debug", "modules", "cache_dir")
            }

            # Parse cache_dir
            cache_dir_str = data.get("cache_dir")
            cache_dir = Path(cache_dir_str).expanduser() if cache_dir_str else DEFAULT_CACHE_DIR

            return Config(
                debug=data.get("debug", False),
                colors=data.get("colors", True),
                modules=data.get("modules", Config().modules),
                module_configs=module_configs,
                cache_dir=cache_dir,
            )

    return Config()
