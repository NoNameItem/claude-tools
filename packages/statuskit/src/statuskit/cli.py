"""CLI argument parsing for statuskit."""

import argparse
from importlib.metadata import version


def get_version() -> str:
    """Get statuskit version from package metadata."""
    try:
        return version("statuskit")
    except Exception:
        return "0.1.0"  # fallback for development


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for statuskit CLI."""
    parser = argparse.ArgumentParser(
        prog="statuskit",
        description="Modular statusline for Claude Code",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"statuskit {get_version()}",
    )
    return parser
