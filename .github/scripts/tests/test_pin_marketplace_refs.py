"""Tests for pin_marketplace_refs.py."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class TestResolvePins:
    def test_object_source_resolved(self) -> None:
        from ..pin_marketplace_refs import PluginPin, resolve_pins

        marketplace = {
            "plugins": [
                {
                    "name": "flow",
                    "source": {
                        "source": "git-subdir",
                        "url": "NoNameItem/claude-tools",
                        "path": "plugins/flow",
                        "ref": "flow-2.1.0",
                    },
                }
            ]
        }
        rp_config = {"packages": {"plugins/flow": {"package-name": "flow"}}}
        assert resolve_pins(marketplace, rp_config) == [PluginPin(name="flow", path="plugins/flow", component="flow")]

    def test_string_source_skipped(self) -> None:
        from ..pin_marketplace_refs import resolve_pins

        marketplace = {"plugins": [{"name": "legacy", "source": "./plugins/legacy"}]}
        rp_config = {"packages": {"plugins/legacy": {"package-name": "legacy"}}}
        assert resolve_pins(marketplace, rp_config) == []

    def test_unmapped_path_skipped(self) -> None:
        from ..pin_marketplace_refs import resolve_pins

        marketplace = {
            "plugins": [
                {
                    "name": "flow",
                    "source": {"source": "git-subdir", "url": "x", "path": "plugins/flow", "ref": "flow-1.0.0"},
                }
            ]
        }
        rp_config = {"packages": {}}  # no release-please package for this path
        assert resolve_pins(marketplace, rp_config) == []


class TestNames:
    def test_tag_name(self) -> None:
        from ..pin_marketplace_refs import tag_name

        assert tag_name("flow", "2.2.0") == "flow-2.2.0"

    def test_release_branch_name(self) -> None:
        from ..pin_marketplace_refs import release_branch_name

        assert release_branch_name("flow") == "release-please--branches--master--components--flow"


class TestPinMarketplaceFile:
    def test_changes_ref_and_preserves_others(self, tmp_path: Path) -> None:
        from ..pin_marketplace_refs import pin_marketplace_file

        mp = tmp_path / "marketplace.json"
        mp.write_text(
            json.dumps(
                {
                    "name": "mp",
                    "plugins": [
                        {
                            "name": "flow",
                            "description": "keep me",
                            "source": {
                                "source": "git-subdir",
                                "url": "NoNameItem/claude-tools",
                                "path": "plugins/flow",
                                "ref": "flow-2.1.0",
                            },
                        }
                    ],
                },
                indent=2,
            )
            + "\n"
        )

        changed = pin_marketplace_file(mp, "flow", "flow-2.2.0")

        assert changed is True
        data = json.loads(mp.read_text())
        entry = data["plugins"][0]
        assert entry["source"]["ref"] == "flow-2.2.0"
        assert entry["description"] == "keep me"  # other fields untouched
        assert data["name"] == "mp"

    def test_idempotent_when_already_pinned(self, tmp_path: Path) -> None:
        from ..pin_marketplace_refs import pin_marketplace_file

        original = (
            json.dumps(
                {
                    "plugins": [
                        {
                            "name": "flow",
                            "source": {
                                "source": "git-subdir",
                                "url": "x",
                                "path": "plugins/flow",
                                "ref": "flow-2.2.0",
                            },
                        }
                    ]
                },
                indent=2,
            )
            + "\n"
        )
        mp = tmp_path / "marketplace.json"
        mp.write_text(original)

        changed = pin_marketplace_file(mp, "flow", "flow-2.2.0")

        assert changed is False
        assert mp.read_text() == original  # byte-for-byte unchanged
