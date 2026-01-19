"""Modular statusline kit for Claude Code."""

import json
import sys

from termcolor import colored

from .cli import create_parser
from .core.config import load_config
from .core.loader import load_modules
from .core.models import RenderContext, StatusInput


def main() -> None:
    """Entry point for statuskit command."""
    # Parse CLI arguments first
    parser = create_parser()
    parser.parse_args()  # handles --version, --help, exits if needed

    # Main mode: read from stdin
    if sys.stdin.isatty():
        print("statuskit: reads JSON from stdin")
        print("Usage: echo '{...}' | statuskit")
        return

    # Load config
    config = load_config()

    # Read data from Claude Code
    try:
        raw_data = json.load(sys.stdin)
        data = StatusInput.from_dict(raw_data)
    except Exception as e:
        if config.debug:
            print(colored(f"[!] Failed to parse input: {e}", "red"))
        return

    # Create context
    ctx = RenderContext(debug=config.debug, data=data)

    # Load modules
    modules = load_modules(config, ctx)

    # Render modules
    for mod in modules:
        try:
            output = mod.render()
            if output:
                print(output)
        except Exception as e:
            if config.debug:
                print(colored(f"[!] {mod.name}: {e}", "red"))


if __name__ == "__main__":
    main()
