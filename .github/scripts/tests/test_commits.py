"""Tests for conventional commit parsing."""

from __future__ import annotations

from ..commits import parse_commit_message


class TestParseCommitMessage:
    """Tests for parse_commit_message function."""

    def test_basic_format(self) -> None:
        """Should parse basic conventional commit."""
        result = parse_commit_message("feat(statuskit): add git module")

        assert result is not None
        assert result.type == "feat"
        assert result.scope == "statuskit"
        assert result.description == "add git module"
        assert result.breaking is False

    def test_without_scope(self) -> None:
        """Should parse commit without scope."""
        result = parse_commit_message("docs: update README")

        assert result is not None
        assert result.type == "docs"
        assert result.scope is None
        assert result.description == "update README"

    def test_breaking_with_bang(self) -> None:
        """Should detect breaking change with ! marker."""
        result = parse_commit_message("feat(api)!: change response format")

        assert result is not None
        assert result.breaking is True

    def test_all_valid_types(self) -> None:
        """Should accept all valid commit types."""
        valid_types = [
            "feat",
            "fix",
            "docs",
            "style",
            "refactor",
            "test",
            "chore",
            "ci",
            "revert",
            "build",
            "perf",
        ]

        for commit_type in valid_types:
            result = parse_commit_message(f"{commit_type}: description")
            assert result is not None, f"Type '{commit_type}' should be valid"
            assert result.type == commit_type

    def test_case_insensitive(self) -> None:
        """Should handle case variations."""
        result = parse_commit_message("FEAT(statuskit): add feature")

        assert result is not None
        assert result.type == "feat"  # Normalized to lowercase

    def test_invalid_format(self) -> None:
        """Should return None for invalid format."""
        invalid_messages = [
            "add new feature",
            "feature: without type",
            "feat add module",  # Missing colon
            ": empty type",
            "",
        ]

        for msg in invalid_messages:
            assert parse_commit_message(msg) is None, f"'{msg}' should be invalid"

    def test_merge_commit(self) -> None:
        """Should return None for merge commits."""
        result = parse_commit_message("Merge branch 'feature/x' into main")
        assert result is None

    def test_revert_github_format(self) -> None:
        """Should return None for GitHub's revert format (not conventional)."""
        result = parse_commit_message('Revert "feat(statuskit): add feature"')
        assert result is None

    def test_revert_conventional_format(self) -> None:
        """Should accept conventional revert format."""
        result = parse_commit_message("revert(statuskit): add feature")

        assert result is not None
        assert result.type == "revert"
        assert result.scope == "statuskit"
