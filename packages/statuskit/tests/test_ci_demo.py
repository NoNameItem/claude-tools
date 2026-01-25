"""Demo tests for CI reporting."""


def test_passing():
    """This test passes."""
    assert 1 + 1 == 2


def test_failing():
    """This test fails intentionally."""
    assert 1 + 1 == 3, "Math is broken"
