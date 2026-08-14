"""Tests for changelog_section.py — top-section parsing, entry comparison, config lookup."""

from __future__ import annotations

import json

from ..changelog_section import (
    Section,
    changelog_path_for,
    component_from_branch,
    entries_changed,
    parse_top_section,
)

# Verbatim shape of packages/statuskit/CHANGELOG.md: an h1 preamble, then release-please's
# linked-version headings with a date in parentheses.
CHANGELOG = """\
# Changelog

All notable changes to this project will be documented in this file.

## [0.5.1](https://github.com/NoNameItem/claude-tools/compare/statuskit-0.5.0...statuskit-0.5.1) (2026-07-31)


### Documentation

* **statuskit:** describe what the git module renders ([#120](https://x/120)) ([53704e5](https://x/1))

## [0.5.0](https://github.com/NoNameItem/claude-tools/compare/statuskit-0.4.0...statuskit-0.5.0) (2026-07-21)


### Features

* **statuskit:** dynamic per-model usage limits ([#112](https://x/112)) ([291b32e](https://x/2))
"""

# The same file after somebody else's merge force-pushed the release PR: only the date moved.
CHANGELOG_REBASED = CHANGELOG.replace("(2026-07-31)", "(2026-08-01)")

# The same file after a merge that belongs to THIS component: a new entry in the top section.
CHANGELOG_NEW_ENTRY = CHANGELOG.replace(
    "### Documentation\n",
    (
        "### Features\n\n"
        "* **statuskit:** new module ([#121](https://x/121)) ([abc1234](https://x/3))\n\n"
        "### Documentation\n"
    ),
)

CONFIG = {
    "packages": {
        "packages/statuskit": {"package-name": "statuskit", "changelog-path": "CHANGELOG.md"},
        "plugins/flow": {"package-name": "flow", "changelog-path": "CHANGELOG.md"},
    }
}


class TestParseTopSection:
    def test_reads_version_date_and_entries(self):
        section = parse_top_section(CHANGELOG)
        assert section is not None
        assert section.version == "0.5.1"
        assert section.date == "2026-07-31"
        assert section.entries == [
            "### Documentation",
            "* **statuskit:** describe what the git module renders ([#120](https://x/120)) ([53704e5](https://x/1))",
        ]

    def test_stops_at_the_next_version_heading(self):
        section = parse_top_section(CHANGELOG)
        assert section is not None
        assert not any("0.5.0" in entry for entry in section.entries)

    def test_bare_heading_without_a_link(self):
        section = parse_top_section("## 1.2.3 (2026-01-01)\n\n* a fix\n")
        assert section == Section(version="1.2.3", date="2026-01-01", entries=["* a fix"])

    def test_heading_without_a_date(self):
        section = parse_top_section("## Unreleased\n\n* a fix\n")
        assert section == Section(version="Unreleased", date="", entries=["* a fix"])

    def test_no_section_at_all(self):
        assert parse_top_section("# Changelog\n\nNothing released yet.\n") is None

    def test_empty_text(self):
        assert parse_top_section("") is None


class TestEntriesChanged:
    def test_pure_rebase_only_moves_the_date(self):
        assert entries_changed(CHANGELOG, CHANGELOG_REBASED) is False

    def test_a_new_entry_is_a_change(self):
        assert entries_changed(CHANGELOG, CHANGELOG_NEW_ENTRY) is True

    def test_missing_before_file_is_a_change(self):
        assert entries_changed(None, CHANGELOG) is True

    def test_unparsable_before_file_is_a_change(self):
        assert entries_changed("# Changelog\n", CHANGELOG) is True

    def test_missing_after_file_says_nothing(self):
        # Nothing to announce — the notification would have no content.
        assert entries_changed(CHANGELOG, None) is False


class TestComponentFromBranch:
    def test_release_please_branch(self):
        assert component_from_branch("release-please--branches--master--components--statuskit") == "statuskit"

    def test_other_branch(self):
        assert component_from_branch("feature/whatever") is None

    def test_release_please_branch_without_a_component(self):
        assert component_from_branch("release-please--branches--master") is None


class TestChangelogPathFor:
    def test_known_component(self):
        assert changelog_path_for(CONFIG, "statuskit") == "packages/statuskit/CHANGELOG.md"

    def test_unknown_component(self):
        assert changelog_path_for(CONFIG, "nope") is None

    def test_default_changelog_name(self):
        config = {"packages": {"packages/x": {"package-name": "x"}}}
        assert changelog_path_for(config, "x") == "packages/x/CHANGELOG.md"


class TestCli:
    def test_section_subcommand(self, capsys, monkeypatch):
        import sys

        from .. import changelog_section

        monkeypatch.setattr(sys, "argv", ["changelog_section.py", "section"])
        monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(CHANGELOG))
        assert changelog_section.main() == 0
        assert json.loads(capsys.readouterr().out)["version"] == "0.5.1"
