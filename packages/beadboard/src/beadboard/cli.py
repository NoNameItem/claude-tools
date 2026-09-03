"""Console entry point.

This module is the composition root: it is the one place allowed to reach into any layer,
because assembling them is its job.
"""

from __future__ import annotations

from beadboard.ui.app import BeadboardApp


def main() -> int:
    """Run the application and return the process exit code."""
    BeadboardApp().run()
    return 0
