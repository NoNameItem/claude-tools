"""CLI argument parsing for statuskit."""

import argparse
from importlib.metadata import PackageNotFoundError, version

MODULES_HELP = """
Built-in modules:
  model                  Display current Claude model name
  git                    Show git branch and status
  beads                  Display active beads tasks
  quota                  Track token usage
"""


def get_version() -> str:
    """Get statuskit version from installed package metadata.

    The distribution name (``claude-statuskit``) differs from the import
    package name (``statuskit``); metadata is keyed by the distribution name.
    """
    try:
        return version("claude-statuskit")
    except PackageNotFoundError:
        return "0.0.0+unknown"  # package not installed (e.g. running from source)


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for statuskit CLI."""
    parser = argparse.ArgumentParser(
        prog="statuskit",
        description="Modular statusline for Claude Code",
        epilog=MODULES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"statuskit {get_version()}",
    )

    subparsers = parser.add_subparsers(dest="command")

    # setup subcommand
    setup_parser = subparsers.add_parser(
        "setup",
        help="Configure Claude Code integration",
    )
    setup_parser.add_argument(
        "-s",
        "--scope",
        choices=["user", "project", "local"],
        default="user",
        help="Installation scope (default: user)",
    )
    setup_parser.add_argument(
        "--check",
        action="store_true",
        help="Check installation status (all scopes)",
    )
    setup_parser.add_argument(
        "--remove",
        action="store_true",
        help="Remove integration (requires --scope)",
    )
    setup_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmations, backup and overwrite",
    )

    # config subcommand
    config_parser = subparsers.add_parser(
        "config",
        help="Create or update statuskit.toml",
    )
    config_sub = config_parser.add_subparsers(dest="config_command", required=True, metavar="{init,sync}")

    init_parser = config_sub.add_parser("init", help="Write the default config template")
    init_parser.add_argument(
        "-s",
        "--scope",
        choices=["user", "project", "local"],
        default="user",
        help="Config scope (default: user)",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Reset an existing config to defaults (a backup is kept)",
    )

    sync_parser = config_sub.add_parser("sync", help="Rebuild the config from the current schema, keeping values")
    sync_parser.add_argument(
        "-s",
        "--scope",
        choices=["user", "project", "local"],
        default="user",
        help="Config scope (default: user)",
    )
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing (exit 1 if keys would be removed)",
    )

    return parser
