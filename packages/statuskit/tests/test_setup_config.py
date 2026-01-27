"""Tests for config file creation."""


class TestCreateConfig:
    """Tests for create_config function."""

    def test_creates_default_config(self, tmp_path):
        """Creates statuskit.toml with defaults."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / "statuskit.toml"
        create_config(config_path)

        assert config_path.exists()
        content = config_path.read_text()
        assert '# modules = ["model", "git", "usage_limits"]' in content

    def test_creates_parent_dirs(self, tmp_path):
        """Creates parent directories if needed."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / ".claude" / "statuskit.toml"
        create_config(config_path)

        assert config_path.exists()

    def test_does_not_overwrite_existing(self, tmp_path):
        """Does not overwrite existing config."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / "statuskit.toml"
        config_path.write_text("custom = true")

        create_config(config_path)

        assert config_path.read_text() == "custom = true"

    def test_returns_created_true(self, tmp_path):
        """Returns True when config was created."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / "statuskit.toml"
        result = create_config(config_path)

        assert result is True

    def test_returns_created_false_if_exists(self, tmp_path):
        """Returns False when config already existed."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / "statuskit.toml"
        config_path.write_text("existing = true")

        result = create_config(config_path)

        assert result is False
