"""Tests for sonar_release_gate.py — the Sonar verdict on a release-please PR."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..sonar_release_gate import ReleaseTarget, component_from_ref, resolve_target

if TYPE_CHECKING:
    from pathlib import Path


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
