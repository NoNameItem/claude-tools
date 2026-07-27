"""Tests for pin_marketplace_refs.py."""

from __future__ import annotations

import json
import subprocess
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


class TestMultipleMarketplaceFiles:
    @staticmethod
    def _write(path: Path, ref: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "plugins": [
                        {
                            "name": "flow",
                            "source": {
                                "source": "git-subdir",
                                "url": "https://github.com/NoNameItem/claude-tools",
                                "path": "plugins/flow",
                                "ref": ref,
                            },
                        }
                    ]
                },
                indent=2,
            )
            + "\n"
        )

    def test_pins_every_existing_file(self, tmp_path: Path) -> None:
        from ..pin_marketplace_refs import pin_all_marketplaces

        self._write(tmp_path / ".claude-plugin" / "marketplace.json", "flow-1.0.0")
        self._write(tmp_path / ".agents" / "plugins" / "marketplace.json", "flow-1.0.0")

        changed = pin_all_marketplaces(tmp_path, "flow", "flow-1.1.0")

        assert [path.as_posix() for path in changed] == [
            ".claude-plugin/marketplace.json",
            ".agents/plugins/marketplace.json",
        ]
        for rel in changed:
            assert json.loads((tmp_path / rel).read_text())["plugins"][0]["source"]["ref"] == "flow-1.1.0"

    def test_absent_file_is_skipped(self, tmp_path: Path) -> None:
        from ..pin_marketplace_refs import pin_all_marketplaces

        self._write(tmp_path / ".claude-plugin" / "marketplace.json", "flow-1.0.0")

        changed = pin_all_marketplaces(tmp_path, "flow", "flow-1.1.0")

        assert [path.as_posix() for path in changed] == [".claude-plugin/marketplace.json"]

    def test_resolve_all_pins_deduplicates(self) -> None:
        from ..pin_marketplace_refs import PluginPin, resolve_all_pins

        marketplace = {
            "plugins": [
                {
                    "name": "flow",
                    "source": {
                        "source": "git-subdir",
                        "url": "https://github.com/NoNameItem/claude-tools",
                        "path": "plugins/flow",
                        "ref": "flow-1.0.0",
                    },
                }
            ]
        }
        rp_config = {"packages": {"plugins/flow": {"package-name": "flow"}}}

        # The same plugin listed in both marketplace files must pin once.
        pins = resolve_all_pins([marketplace, marketplace], rp_config)

        assert pins == [PluginPin(name="flow", path="plugins/flow", component="flow")]


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_repo_with_remote(tmp_path):
    """A working repo on master with a bare 'origin' remote and the flow plugin."""
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "master")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@test.com")

    (repo / ".claude-plugin").mkdir()
    (repo / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "mp",
                "plugins": [
                    {
                        "name": "flow",
                        "description": "x",
                        "source": {
                            "source": "git-subdir",
                            "url": "NoNameItem/claude-tools",
                            "path": "plugins/flow",
                            "ref": "flow-1.0.0",
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    (repo / "release-please-config.json").write_text(
        json.dumps({"packages": {"plugins/flow": {"package-name": "flow"}}}, indent=2) + "\n"
    )
    codex_mp = repo / ".agents" / "plugins"
    codex_mp.mkdir(parents=True)
    (codex_mp / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "mp-codex",
                "plugins": [
                    {
                        "name": "flow",
                        "description": "x",
                        "source": {
                            "source": "git-subdir",
                            "url": "https://github.com/NoNameItem/claude-tools",
                            "path": "plugins/flow",
                            "ref": "flow-1.0.0",
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )

    plugin_cp = repo / "plugins" / "flow" / ".claude-plugin"
    plugin_cp.mkdir(parents=True)
    (plugin_cp / "plugin.json").write_text(json.dumps({"name": "flow", "version": "1.0.0"}) + "\n")

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore: init")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "master")
    return repo


def test_run_pins_release_branch(tmp_path: Path) -> None:
    from ..pin_marketplace_refs import run

    repo = _make_repo_with_remote(tmp_path)
    branch = "release-please--branches--master--components--flow"

    # Simulate the release-please PR branch: plugin.json bumped to 1.1.0.
    _git(repo, "checkout", "-b", branch)
    pj = repo / "plugins" / "flow" / ".claude-plugin" / "plugin.json"
    pj.write_text(json.dumps({"name": "flow", "version": "1.1.0"}) + "\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore(flow): release 1.1.0")
    _git(repo, "push", "-u", "origin", branch)
    _git(repo, "checkout", "master")

    rc = run(repo)
    assert rc == 0

    # The pushed branch on origin now pins marketplace.json to flow-1.1.0.
    shown = subprocess.run(
        ["git", "show", f"origin/{branch}:.claude-plugin/marketplace.json"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert json.loads(shown)["plugins"][0]["source"]["ref"] == "flow-1.1.0"

    codex_shown = subprocess.run(
        ["git", "show", f"origin/{branch}:.agents/plugins/marketplace.json"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert json.loads(codex_shown)["plugins"][0]["source"]["ref"] == "flow-1.1.0"


def test_run_noop_without_release_branch(tmp_path: Path) -> None:
    from ..pin_marketplace_refs import run

    repo = _make_repo_with_remote(tmp_path)
    # No release branch exists -> run() must succeed and change nothing.
    assert run(repo) == 0
    assert (
        json.loads((repo / ".claude-plugin" / "marketplace.json").read_text())["plugins"][0]["source"]["ref"]
        == "flow-1.0.0"
    )
    log = subprocess.run(["git", "log", "--oneline"], cwd=repo, check=True, capture_output=True, text=True).stdout
    assert len(log.strip().splitlines()) == 1  # only the init commit; nothing pinned


def test_run_returns_1_on_plugin_error(tmp_path: Path) -> None:
    from ..pin_marketplace_refs import run

    repo = _make_repo_with_remote(tmp_path)
    branch = "release-please--branches--master--components--flow"

    # Release branch exists but its plugin.json is gone -> read_plugin_version fails.
    _git(repo, "checkout", "-b", branch)
    _git(repo, "rm", "plugins/flow/.claude-plugin/plugin.json")
    _git(repo, "commit", "-m", "chore(flow): break plugin.json")
    _git(repo, "push", "-u", "origin", branch)
    _git(repo, "checkout", "master")

    assert run(repo) == 1
