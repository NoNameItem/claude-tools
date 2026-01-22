"""Tests for gitignore handling."""

import subprocess


class TestIsInGitRepo:
    """Tests for is_in_git_repo function."""

    def test_returns_true_in_git_repo(self, tmp_path, monkeypatch):
        """Returns True when in a git repository."""
        from statuskit.setup.gitignore import is_in_git_repo

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        monkeypatch.chdir(tmp_path)

        assert is_in_git_repo() is True

    def test_returns_false_outside_git_repo(self, tmp_path, monkeypatch):
        """Returns False when not in a git repository."""
        from statuskit.setup.gitignore import is_in_git_repo

        monkeypatch.chdir(tmp_path)

        assert is_in_git_repo() is False


class TestIsFileIgnored:
    """Tests for is_file_ignored function."""

    def test_ignored_file_returns_true(self, tmp_path, monkeypatch):
        """Returns True for ignored file."""
        from statuskit.setup.gitignore import is_file_ignored

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        (tmp_path / ".gitignore").write_text("*.local.*\n")
        monkeypatch.chdir(tmp_path)

        assert is_file_ignored(".claude/settings.local.json") is True

    def test_not_ignored_file_returns_false(self, tmp_path, monkeypatch):
        """Returns False for non-ignored file."""
        from statuskit.setup.gitignore import is_file_ignored

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        monkeypatch.chdir(tmp_path)

        assert is_file_ignored(".claude/settings.json") is False

    def test_covered_by_directory_pattern(self, tmp_path, monkeypatch):
        """Returns True when covered by directory pattern."""
        from statuskit.setup.gitignore import is_file_ignored

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        (tmp_path / ".gitignore").write_text(".claude/\n")
        monkeypatch.chdir(tmp_path)

        assert is_file_ignored(".claude/settings.local.json") is True


class TestEnsureLocalFilesIgnored:
    """Tests for ensure_local_files_ignored function."""

    def test_adds_pattern_when_not_ignored(self, tmp_path, monkeypatch):
        """Adds pattern to .gitignore when files not ignored."""
        from statuskit.setup.gitignore import ensure_local_files_ignored

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        monkeypatch.chdir(tmp_path)

        result = ensure_local_files_ignored()

        assert result is True
        assert ".claude/*.local.*" in (tmp_path / ".gitignore").read_text()

    def test_creates_gitignore_if_missing(self, tmp_path, monkeypatch):
        """Creates .gitignore if it doesn't exist."""
        from statuskit.setup.gitignore import ensure_local_files_ignored

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        monkeypatch.chdir(tmp_path)

        result = ensure_local_files_ignored()

        assert result is True
        assert (tmp_path / ".gitignore").exists()

    def test_returns_false_when_already_ignored(self, tmp_path, monkeypatch):
        """Returns False when files already ignored."""
        from statuskit.setup.gitignore import ensure_local_files_ignored

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        (tmp_path / ".gitignore").write_text(".claude/*.local.*\n")
        monkeypatch.chdir(tmp_path)

        result = ensure_local_files_ignored()

        assert result is False

    def test_returns_false_when_not_in_git_repo(self, tmp_path, monkeypatch):
        """Returns False when not in git repository."""
        from statuskit.setup.gitignore import ensure_local_files_ignored

        monkeypatch.chdir(tmp_path)

        result = ensure_local_files_ignored()

        assert result is False
        assert not (tmp_path / ".gitignore").exists()

    def test_preserves_existing_content(self, tmp_path, monkeypatch):
        """Preserves existing .gitignore content."""
        from statuskit.setup.gitignore import ensure_local_files_ignored

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        (tmp_path / ".gitignore").write_text("node_modules/\n.env\n")
        monkeypatch.chdir(tmp_path)

        ensure_local_files_ignored()

        content = (tmp_path / ".gitignore").read_text()
        assert "node_modules/" in content
        assert ".env" in content
        assert ".claude/*.local.*" in content
