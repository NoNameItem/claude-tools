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

    return parser
