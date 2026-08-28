"""Tests for sonar_release_gate.py — the Sonar verdict on a release-please PR."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from ..sonar_release_gate import (
    ReleaseTarget,
    component_from_ref,
    pick_analysis,
    resolve_target,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestComponentFromRef:
    def test_reads_the_component_from_a_release_ref(self) -> None:
        assert component_from_ref("release-please--branches--master--components--statuskit") == "statuskit"

    def test_a_feature_branch_is_not_a_release_ref(self) -> None:
        assert component_from_ref("feature/claude-tools-5vg.25-release-gate") is None

    def test_a_release_ref_without_a_component_is_unresolvable(self) -> None:
        assert component_from_ref("release-please--branches--master") is None


class TestResolveTarget:
    def test_a_python_package_maps_to_its_sonar_project(self, temp_repo: Path) -> None:
        assert resolve_target("statuskit", temp_repo) == ReleaseTarget(
            component="statuskit",
            project_key="NoNameItem_statuskit",
            path="packages/statuskit",
        )

    def test_a_plugin_has_no_sonar_project(self, temp_repo: Path) -> None:
        assert resolve_target("flow", temp_repo) is None

    def test_an_unknown_component_has_no_sonar_project(self, temp_repo: Path) -> None:
        assert resolve_target("nope", temp_repo) is None


def _commit(repo: Path, relative: str, message: str) -> str:
    """Commit a one-line file and return the new HEAD SHA."""
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{message}\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True)
    return head.stdout.strip()


class TestPickAnalysis:
    def test_takes_an_analysis_whose_code_is_the_released_code(self, temp_repo: Path) -> None:
        analysed = _commit(temp_repo, "packages/statuskit/src/statuskit/git.py", "feat: git module")
        base = _commit(temp_repo, "docs/notes.md", "docs: notes")  # Sonar never analyses this
        analyses = [{"key": "a1", "revision": analysed}]

        assert pick_analysis(analyses, base, "packages/statuskit", temp_repo) == analyses[0]

    def test_skips_an_analysis_older_than_a_package_change(self, temp_repo: Path) -> None:
        stale = _commit(temp_repo, "packages/statuskit/src/statuskit/git.py", "feat: git module")
        base = _commit(temp_repo, "packages/statuskit/src/statuskit/quota.py", "feat: quota module")

        assert pick_analysis([{"key": "a1", "revision": stale}], base, "packages/statuskit", temp_repo) is None

    def test_skips_an_analysis_ahead_of_the_release_base(self, temp_repo: Path) -> None:
        base = _commit(temp_repo, "packages/statuskit/src/statuskit/git.py", "feat: git module")
        ahead = _commit(temp_repo, "packages/statuskit/src/statuskit/quota.py", "feat: quota module")

        assert pick_analysis([{"key": "a2", "revision": ahead}], base, "packages/statuskit", temp_repo) is None

    def test_walks_down_to_an_older_usable_analysis(self, temp_repo: Path) -> None:
        usable = _commit(temp_repo, "packages/statuskit/src/statuskit/git.py", "feat: git module")
        base = _commit(temp_repo, "docs/notes.md", "docs: notes")
        ahead = _commit(temp_repo, "packages/statuskit/src/statuskit/quota.py", "feat: quota module")
        analyses = [{"key": "a2", "revision": ahead}, {"key": "a1", "revision": usable}]

        found = pick_analysis(analyses, base, "packages/statuskit", temp_repo)

        assert found is not None
        assert found["key"] == "a1"

    def test_an_unknown_revision_is_not_usable(self, temp_repo: Path) -> None:
        base = _commit(temp_repo, "packages/statuskit/src/statuskit/git.py", "feat: git module")

        assert pick_analysis([{"key": "a1", "revision": "0" * 40}], base, "packages/statuskit", temp_repo) is None


class TestWaitForReleaseAnalysis:
    TARGET = ReleaseTarget(component="statuskit", project_key="NoNameItem_statuskit", path="packages/statuskit")

    def test_returns_as_soon_as_a_usable_analysis_appears(
        self, temp_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from .. import sonar_release_gate as mod

        analysed = _commit(temp_repo, "packages/statuskit/src/statuskit/git.py", "feat: git module")
        base = _commit(temp_repo, "docs/notes.md", "docs: notes")
        pages = iter([[], [{"key": "a1", "revision": analysed}]])
        monkeypatch.setattr(mod, "fetch_analyses", lambda *args, **kwargs: next(pages))
        slept: list[float] = []

        found = mod.wait_for_release_analysis(self.TARGET, "master", None, base, temp_repo, sleep=slept.append)

        assert found is not None
        assert found["key"] == "a1"
        assert slept == [mod._POLL_INTERVAL_SECONDS]

    def test_gives_up_at_the_ceiling(self, temp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_release_gate as mod

        base = _commit(temp_repo, "packages/statuskit/src/statuskit/git.py", "feat: git module")
        monkeypatch.setattr(mod, "fetch_analyses", lambda *args, **kwargs: [])
        slept: list[float] = []

        assert mod.wait_for_release_analysis(self.TARGET, "master", None, base, temp_repo, sleep=slept.append) is None
        assert len(slept) == int(mod._POLL_CEILING_SECONDS // mod._POLL_INTERVAL_SECONDS)
