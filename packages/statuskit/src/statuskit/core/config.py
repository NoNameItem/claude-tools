"""Configuration loading for statuskit."""

import tomllib
from dataclasses import field
from pathlib import Path

from termcolor import colored

from statuskit.core.constants import CLAUDE_DIR, CONFIG_FILENAME
from statuskit.core.schema import param, parse_params, schema

CONFIG_LOCAL_FILENAME = CONFIG_FILENAME.replace(".toml", ".local.toml")


def _get_config_paths() -> list[Path]:
    """Get config paths in priority order (highest first)."""
    return [
        Path(CLAUDE_DIR) / CONFIG_LOCAL_FILENAME,  # Local (highest)
        Path(CLAUDE_DIR) / CONFIG_FILENAME,  # Project
        Path.home() / CLAUDE_DIR / CONFIG_FILENAME,  # User (lowest)
    ]


@schema
class Config:
    """Statuskit configuration."""

    modules: list[str] = param(
        ["model", "git", "usage_limits"],
        "Modules to display (in order)",
        type_=list[str],
    )
    debug: bool = param(False, "Enable debug output")
    colors: bool = param(True, "Colored output")
    cache_dir: str = param("~/.cache/statuskit", "Cache directory")
    module_configs: dict[str, dict] = field(default_factory=dict)  # internal, not a schema field

    def get_module_config(self, name: str) -> dict:
        """Get configuration for a specific module."""
        return self.module_configs.get(name, {})

    @property
    def cache_path(self) -> Path:
        """Expanded cache directory path."""
        return Path(self.cache_dir).expanduser()


def load_config() -> Config:
    """Load configuration from TOML files.

    Searches in priority order:
    1. .claude/statuskit.local.toml (Local)
    2. .claude/statuskit.toml (Project)
    3. ~/.claude/statuskit.toml (User)

    Returns defaults if no config file exists. Top-level keys are validated against the
    Config schema (per-field fallback); invalid values are dropped (the default applies)
    and unknown top-level keys are flagged; both are reported as warnings when the raw
    ``debug`` flag is True.
    """
    for config_path in _get_config_paths():
        if config_path.exists():
            try:
                with config_path.open("rb") as f:
                    data = tomllib.load(f)
            except (tomllib.TOMLDecodeError, OSError) as e:
                print(colored(f"[!] Config error in {config_path}: {e}", "red"))
                return Config()

            sections = {k: v for k, v in data.items() if isinstance(v, dict)}
            non_section = {k: v for k, v in data.items() if not isinstance(v, dict)}

            globals_, warnings = parse_params(Config, non_section)
            # Gate on the RAW debug flag (chicken-and-egg: debug must be known before it is
            # parsed). `is True` is deliberate — only a real TOML boolean enables warnings; a
            # mistyped `debug = 1` / "yes" is itself rejected by parse_params and stays off.
            if data.get("debug") is True:
                for w in warnings:
                    print(colored(f"[!] config.{w.field}: {w.message}", "yellow"))

            return Config(**globals_, module_configs=sections)

    return Config()
