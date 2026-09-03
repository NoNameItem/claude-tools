"""Tests for beadboard.ui.app."""

from beadboard.ui.app import BeadboardApp
from textual.binding import Binding
from textual.widgets import Footer, Header, Static


def test_compose_yields_header_placeholder_and_footer():
    """compose() assembles the three widgets of the placeholder screen."""
    widgets = list(BeadboardApp().compose())

    assert [type(widget) for widget in widgets] == [Header, Static, Footer]


def test_quit_binding_is_declared():
    """`q` quits — the only interaction the empty application supports."""
    bindings = {(binding.key, binding.action) for binding in BeadboardApp.BINDINGS if isinstance(binding, Binding)}

    assert ("q", "quit") in bindings
