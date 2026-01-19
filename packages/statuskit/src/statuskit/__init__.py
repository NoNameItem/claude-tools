"""Modular statusline kit for Claude Code."""

import json
import sys
from argparse import Namespace

from termcolor import colored

from .cli import create_parser
from .core.config import load_config
from .core.loader import load_modules
from .core.models import RenderContext, StatusInput


def _handle_setup(args: Namespace) -> None:
    """Handle setup command."""
    from .setup.commands import check_installation
    from .setup.paths import Scope
    from .setup.ui import ConsoleUI

    if args.check:
        print(check_installation())
        return

    scope = Scope(args.scope)
    ui = None if args.force else ConsoleUI()

    if args.remove:
        _handle_remove(scope, args.force, ui)
    else:
        _handle_install(scope, args.force, ui)


def _handle_remove(scope, force: bool, ui) -> None:
    """Handle setup --remove command."""
    from .setup.commands import remove_hook

    result = remove_hook(scope, force=force, ui=ui)
    if result.not_installed:
        print(f"statuskit is not installed at {scope.value} scope.")
    elif result.success:
        print(f"\u2713 Removed statusline hook from {scope.value} scope.")
    else:
        print(f"Error: {result.message}")
        sys.exit(1)


def _handle_install(scope, force: bool, ui) -> None:
    """Handle setup install command."""
    from .setup.commands import install_hook

    result = install_hook(scope, force=force, ui=ui)
    if result.higher_scope_installed:
        print(f"statuskit is already installed at {result.higher_scope.value} scope.")
        print("The hook will work for this project too.")
        if result.config_created:
            print(f"\u2713 Created config file at {scope.value} scope.")
    elif result.already_installed:
        print(f"statuskit is already installed at {scope.value} scope.")
        if result.config_created:
            print("\u2713 Created config file.")
    elif result.success:
        print(f"\u2713 Added statusline hook to {scope.value} scope.")
        if result.backup_created:
            print("\u2713 Created backup of previous settings.")
        if result.config_created:
            print("\u2713 Created config file.")
        if result.gitignore_updated:
            print("\u2713 Added .claude/*.local.* to .gitignore")
        print("\nRun `claude` to see your new statusline!")
    else:
        print(f"Error: {result.message}")
        sys.exit(1)


def _render_statusline() -> None:
    """Read from stdin and render statusline."""
    config = load_config()

    try:
        raw_data = json.load(sys.stdin)
        data = StatusInput.from_dict(raw_data)
    except Exception as e:
        if config.debug:
            print(colored(f"[!] Failed to parse input: {e}", "red"))
        return

    ctx = RenderContext(debug=config.debug, data=data)
    modules = load_modules(config, ctx)

    for mod in modules:
        try:
            output = mod.render()
            if output:
                print(output)
        except Exception as e:
            if config.debug:
                print(colored(f"[!] {mod.name}: {e}", "red"))


def main() -> None:
    """Entry point for statuskit command."""
    parser = create_parser()
    args = parser.parse_args()

    if args.command == "setup":
        _handle_setup(args)
        return

    if sys.stdin.isatty():
        print("statuskit: reads JSON from stdin")
        print("Usage: echo '{...}' | statuskit")
        print("\nRun 'statuskit setup' to configure Claude Code integration.")
        return

    _render_statusline()


if __name__ == "__main__":
    main()
