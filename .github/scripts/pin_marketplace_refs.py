#!/usr/bin/env python3
"""Pin each marketplace plugin's source.ref to its release tag.

Run from CI (release-please.yml) after the release-please action when a release
PR was created/updated. For every plugin in marketplace.json whose source is a
tag-pinned git-subdir object, this writes the plugin's release tag into
source.ref ON that plugin's own release-please PR branch — atomic with the
version bump. Generic over all marketplace plugins; no plugin name is hardcoded.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MARKETPLACE = Path(".claude-plugin/marketplace.json")
RP_CONFIG = Path("release-please-config.json")
BRANCH_PREFIX = "release-please--branches--master--components--"
BOT_NAME = "release-please[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


@dataclass(frozen=True)
class PluginPin:
    """A marketplace plugin that can be pinned to a release tag."""

    name: str  # marketplace entry name (matches plugins[].name)
    path: str  # subdir within the repo, e.g. "plugins/flow"
    component: str  # release-please package-name (tag prefix + branch suffix)


def resolve_pins(marketplace: dict, rp_config: dict) -> list[PluginPin]:
    """Plugins with a git-subdir object source that map to a release-please package."""
    packages = rp_config.get("packages", {})
    pins: list[PluginPin] = []
    for entry in marketplace.get("plugins", []):
        source = entry.get("source")
        name = entry.get("name")
        if not isinstance(source, dict) or not name:
            continue  # legacy string source or malformed entry: not managed here
        path = source.get("path")
        if not path:
            continue
        component = packages.get(path, {}).get("package-name")
        if not component:
            continue  # no release-please package for this path
        pins.append(PluginPin(name=name, path=path, component=component))
    return pins


def release_branch_name(component: str) -> str:
    """The deterministic release-please PR branch for a component."""
    return f"{BRANCH_PREFIX}{component}"


def tag_name(component: str, version: str) -> str:
    """The release-please tag for a component+version, e.g. 'flow-2.2.0'."""
    return f"{component}-{version}"


def read_plugin_version(repo: Path, plugin_path: str) -> str:
    """Read the plugin.json version at <repo>/<plugin_path>/.claude-plugin/plugin.json."""
    data = json.loads((repo / plugin_path / ".claude-plugin" / "plugin.json").read_text())
    return data["version"]


def pin_marketplace_file(marketplace_path: Path, name: str, ref: str) -> bool:
    """Set plugins[name].source.ref = ref in the file. Return True if it changed."""
    data = json.loads(marketplace_path.read_text())
    changed = False
    for entry in data.get("plugins", []):
        source = entry.get("source")
        if entry.get("name") == name and isinstance(source, dict) and source.get("ref") != ref:
            source["ref"] = ref
            changed = True
    if changed:
        marketplace_path.write_text(json.dumps(data, indent=2) + "\n")
    return changed


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)  # noqa: S607


def _git_fetch_ok(repo: Path, branch: str) -> bool:
    """True if the remote branch exists and was fetched."""
    return (
        subprocess.run(
            ["git", "fetch", "origin", branch],  # noqa: S607
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )


def process_pin(repo: Path, pin: PluginPin) -> str | None:
    """Pin one plugin inside its release-please PR branch. Returns the tag if pushed."""
    branch = release_branch_name(pin.component)
    if not _git_fetch_ok(repo, branch):
        print(f"skip '{pin.name}': no open release PR ({branch})")
        return None

    _run_git(repo, "checkout", "-B", branch, f"origin/{branch}")
    tag = tag_name(pin.component, read_plugin_version(repo, pin.path))

    if not pin_marketplace_file(repo / MARKETPLACE, pin.name, tag):
        print(f"'{pin.name}' already pinned to {tag}")
        return None

    _run_git(repo, "add", str(MARKETPLACE))
    _run_git(repo, "commit", "-m", f"chore: pin {pin.name} marketplace ref to {tag}")
    _run_git(repo, "push", "origin", branch)
    print(f"pinned '{pin.name}' -> {tag}")
    return tag


def run(repo: Path) -> int:
    """Pin every resolvable plugin inside its release branch. Returns an exit code."""
    marketplace = json.loads((repo / MARKETPLACE).read_text())
    rp_config = json.loads((repo / RP_CONFIG).read_text())
    pins = resolve_pins(marketplace, rp_config)
    if not pins:
        return 0

    _run_git(repo, "config", "user.name", BOT_NAME)
    _run_git(repo, "config", "user.email", BOT_EMAIL)

    failed: list[str] = []
    for pin in pins:
        try:
            process_pin(repo, pin)
        except (subprocess.CalledProcessError, OSError, ValueError, KeyError) as exc:
            detail = ""
            if isinstance(exc, subprocess.CalledProcessError):
                detail = (exc.stderr or exc.stdout or "").strip()
            print(f"error pinning '{pin.name}': {exc} {detail}".rstrip())
            failed.append(pin.name)
    return 1 if failed else 0


def main() -> int:
    return run(Path.cwd())


if __name__ == "__main__":
    sys.exit(main())
