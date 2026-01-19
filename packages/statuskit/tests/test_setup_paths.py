"""Tests for setup path resolution."""

from pathlib import Path

from statuskit.setup.paths import Scope, get_config_path, get_settings_path


class TestScope:
    """Tests for Scope enum."""

    def test_scope_values(self):
        """Scope has user, project, local values."""
        assert Scope.USER.value == "user"
        assert Scope.PROJECT.value == "project"
        assert Scope.LOCAL.value == "local"

    def test_scope_from_string(self):
        """Scope can be created from string."""
        assert Scope("user") == Scope.USER
        assert Scope("project") == Scope.PROJECT
        assert Scope("local") == Scope.LOCAL


class TestGetSettingsPath:
    """Tests for get_settings_path function."""

    def test_user_scope(self):
        """User scope returns ~/.claude/settings.json."""
        path = get_settings_path(Scope.USER)
        assert path == Path.home() / ".claude" / "settings.json"

    def test_project_scope(self):
        """Project scope returns .claude/settings.json."""
        path = get_settings_path(Scope.PROJECT)
        assert path == Path(".claude") / "settings.json"

    def test_local_scope(self):
        """Local scope returns .claude/settings.local.json."""
        path = get_settings_path(Scope.LOCAL)
        assert path == Path(".claude") / "settings.local.json"


class TestGetConfigPath:
    """Tests for get_config_path function."""

    def test_user_scope(self):
        """User scope returns ~/.claude/statuskit.toml."""
        path = get_config_path(Scope.USER)
        assert path == Path.home() / ".claude" / "statuskit.toml"

    def test_project_scope(self):
        """Project scope returns .claude/statuskit.toml."""
        path = get_config_path(Scope.PROJECT)
        assert path == Path(".claude") / "statuskit.toml"

    def test_local_scope(self):
        """Local scope returns .claude/statuskit.local.toml."""
        path = get_config_path(Scope.LOCAL)
        assert path == Path(".claude") / "statuskit.local.toml"
