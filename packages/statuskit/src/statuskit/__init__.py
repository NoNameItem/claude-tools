"""Modular statusline kit for Claude Code."""

import json
import sys

from termcolor import colored

from .core.config import load_config
from .core.loader import load_modules
from .core.models import RenderContext, StatusInput


def main() -> None:
    """Entry point for statuskit command."""
    # 1. Check stdin
    if sys.stdin.isatty():
        print("statuskit: reads JSON from stdin")
        print("Usage: echo '{...}' | statuskit")
        return

    # 2. Load config
    config = load_config()

    # 3. Read data from Claude Code
    try:
        raw_data = json.load(sys.stdin)
        data = StatusInput.from_dict(raw_data)
    except Exception as e:
        if config.debug:
            print(colored(f"[!] Failed to parse input: {e}", "red"))
        return

    # 4. Create context
    ctx = RenderContext(debug=config.debug, data=data)

    # 5. Load modules
    modules = load_modules(config, ctx)

    # 6. Render modules
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
