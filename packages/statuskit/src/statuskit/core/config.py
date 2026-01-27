"""Configuration loading for statuskit."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from termcolor import colored

# Kept for backward compatibility in tests
CONFIG_PATH = Path.home() / ".claude" / "statuskit.toml"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "statuskit"


def _get_config_paths() -> list[Path]:
    """Get config paths in priority order (highest first)."""
    return [
        Path(".claude") / "statuskit.local.toml",  # Local (highest)
        Path(".claude") / "statuskit.toml",  # Project
        Path.home() / ".claude" / "statuskit.toml",  # User (lowest)
    ]


@dataclass
class Config:
    """Statuskit configuration."""

    debug: bool = False
    colors: bool = True
    modules: list[str] = field(default_factory=lambda: ["model", "git", "beads", "quota"])
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
                modules=data.get("modules", Config().modules),
                module_configs=module_configs,
                cache_dir=cache_dir,
            )

    return Config()
