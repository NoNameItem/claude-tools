"""Tests for resolve_publish module."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


class TestParseReleaseTag:
    """Tests for parse_release_tag function."""

    def test_parses_simple_tag(self) -> None:
        """Should parse component-version format."""
        from ..resolve_publish import parse_release_tag

        result = parse_release_tag("statuskit-0.2.0")
        assert result == ("statuskit", "0.2.0")

    def test_parses_prerelease_tag(self) -> None:
        """Should parse prerelease version."""
        from ..resolve_publish import parse_release_tag

        result = parse_release_tag("statuskit-0.2.0-alpha.1")
        assert result == ("statuskit", "0.2.0-alpha.1")

    def test_invalid_tag_raises(self) -> None:
        """Should raise for invalid tag format."""
        from ..resolve_publish import parse_release_tag

        with pytest.raises(ValueError, match="Invalid release tag"):
            parse_release_tag("invalid")


class TestResolvePublish:
    """Tests for resolve_publish function."""

    def test_resolves_python_package(self, temp_repo: Path) -> None:
        """Should resolve Python package with pypi publish target."""
        from ..resolve_publish import resolve_publish

        # Create release-please-config.json
        (temp_repo / "release-please-config.json").write_text("""\
{
  "packages": {
    "packages/statuskit": {
      "package-name": "statuskit"
    }
  }
}
""")
        result = resolve_publish("statuskit-0.2.0", temp_repo)

        assert result["project_name"] == "statuskit"
        assert result["project_path"] == "packages/statuskit"
        assert result["project_type"] == "python"
        assert result["version"] == "0.2.0"
        assert result["publish_targets"] == ["pypi"]

    def test_resolves_plugin_no_publish(self, temp_repo: Path) -> None:
        """Should resolve plugin with empty publish targets."""
        from ..resolve_publish import resolve_publish

        (temp_repo / "release-please-config.json").write_text("""\
{
  "packages": {
    "plugins/flow": {
      "package-name": "flow"
    }
  }
}
""")
        result = resolve_publish("flow-1.0.0", temp_repo)

        assert result["project_name"] == "flow"
        assert result["project_path"] == "plugins/flow"
        assert result["project_type"] == "claude_code_plugin"
        assert result["version"] == "1.0.0"
        assert result["publish_targets"] == []

    def test_unknown_component_raises(self, temp_repo: Path) -> None:
        """Should raise for unknown component."""
        from ..resolve_publish import resolve_publish

        (temp_repo / "release-please-config.json").write_text('{"packages": {}}')

        with pytest.raises(ValueError, match="Unknown component"):
            resolve_publish("unknown-1.0.0", temp_repo)
