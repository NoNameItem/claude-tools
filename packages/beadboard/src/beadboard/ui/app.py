"""The Textual application shell.

Until the board screen (issue .5) exists, the application shows a placeholder: its job is to
prove that the console script, the dependency and the import graph all work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.app import App
from textual.binding import Binding
from textual.widgets import Footer, Header, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType


class BeadboardApp(App[None]):
    """Root application. Screens are mounted by later issues of the epic."""

    TITLE = "beadboard"

    BINDINGS: ClassVar[list[BindingType]] = [Binding("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        """Build the widget tree of the placeholder screen."""
        yield Header()
        yield Static("beadboard — under construction", id="placeholder")
        yield Footer()
