"""Tests for sonar_release_gate.py — the Sonar verdict on a release-please PR."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from ..sonar_release_gate import (
    ReleaseTarget,
    component_from_ref,
    pick_analysis,
    resolve_target,
)

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

    def test_an_unknown_component_maps_to_no_target(self, temp_repo: Path) -> None:
        # `resolve_target` alone cannot distinguish this from `flow`'s legitimate skip above —
        # both come back `None`. `main` tells them apart by checking `discover_projects` directly
        # before calling this function; see `TestMain.test_an_unknown_component_fails_closed`.
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


OK_STATUS = {
    "status": "OK",
    "conditions": [
        {"status": "OK", "metricKey": "violations", "comparator": "GT", "errorThreshold": "0", "actualValue": "0"},
    ],
}

ERROR_STATUS = {
    "status": "ERROR",
    "conditions": [
        {"status": "ERROR", "metricKey": "violations", "comparator": "GT", "errorThreshold": "0", "actualValue": "13"},
        {
            "status": "OK",
            "metricKey": "coverage",
            "comparator": "LT",
            "errorThreshold": "80",
            "actualValue": "93.4",
        },
    ],
}

ANALYSIS = {"key": "a1", "revision": "effda08fc354f37fc640ed47c14d8e56885171b0", "date": "2026-08-28T14:45:38+0000"}


class TestFetchStatus:
    def test_asks_for_the_named_analysis(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_release_gate as mod

        seen: list[str] = []

        def fake_fetch(url: str, token: str | None) -> dict:
            seen.append(url)
            return {"projectStatus": OK_STATUS}

        monkeypatch.setattr(mod, "fetch_json", fake_fetch)

        assert mod.fetch_status("a1", None) == OK_STATUS
        assert "qualitygates/project_status" in seen[0]
        assert "analysisId=a1" in seen[0]

    def test_retries_before_giving_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_release_gate as mod

        monkeypatch.setattr(mod, "fetch_json", lambda url, token: None)
        slept: list[float] = []

        assert mod.fetch_status("a1", None, sleep=slept.append) is None
        assert len(slept) == mod._API_ATTEMPTS - 1

    def test_a_late_answer_still_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_release_gate as mod

        answers = iter([None, {"projectStatus": OK_STATUS}])
        monkeypatch.setattr(mod, "fetch_json", lambda url, token: next(answers))

        assert mod.fetch_status("a1", None, sleep=lambda seconds: None) == OK_STATUS


class TestRenderReport:
    def test_names_the_analysis_and_every_condition(self) -> None:
        from .. import sonar_release_gate as mod

        report = mod.render_report(ERROR_STATUS, ANALYSIS, "NoNameItem_statuskit")

        assert "NoNameItem_statuskit" in report
        assert "effda08" in report
        assert "2026-08-28T14:45:38+0000" in report
        assert "`violations`" in report
        assert "need ≤ 0" in report
        assert "13" in report
        assert "93.4%" in report


class TestMain:
    def _args(self, base_sha: str) -> list[str]:
        return [
            "--head-ref=release-please--branches--master--components--statuskit",
            f"--base-sha={base_sha}",
        ]

    def test_a_passing_gate_exits_zero_and_writes_the_summary(
        self, temp_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from .. import sonar_release_gate as mod

        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        monkeypatch.setattr(mod, "wait_for_release_analysis", lambda *args, **kwargs: ANALYSIS)
        monkeypatch.setattr(mod, "fetch_status", lambda *args, **kwargs: OK_STATUS)
        monkeypatch.setattr(sys, "argv", ["sonar_release_gate.py", *self._args("abc1234"), f"--repo-root={temp_repo}"])

        assert mod.main() == 0
        assert "NoNameItem_statuskit" in summary.read_text()

    def test_a_failing_gate_exits_one(self, temp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_release_gate as mod

        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(mod, "wait_for_release_analysis", lambda *args, **kwargs: ANALYSIS)
        monkeypatch.setattr(mod, "fetch_status", lambda *args, **kwargs: ERROR_STATUS)
        monkeypatch.setattr(sys, "argv", ["sonar_release_gate.py", *self._args("abc1234"), f"--repo-root={temp_repo}"])

        assert mod.main() == 1

    def test_a_component_without_a_sonar_project_is_skipped(
        self, temp_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from .. import sonar_release_gate as mod

        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(
            mod, "wait_for_release_analysis", lambda *args, **kwargs: pytest.fail("must not call Sonar")
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "sonar_release_gate.py",
                "--head-ref=release-please--branches--master--components--flow",
                "--base-sha=abc1234",
                f"--repo-root={temp_repo}",
            ],
        )

        assert mod.main() == 0
        assert "flow" in capsys.readouterr().out

    def test_an_unknown_component_fails_closed(
        self, temp_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A renamed package, a stale release-please-config.json, or a broken checkout would all
        # produce a head ref naming a component nothing in the repo recognises. That must not read
        # the same as `flow`'s legitimate "not a Sonar project" skip above.
        from .. import sonar_release_gate as mod

        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(
            mod, "wait_for_release_analysis", lambda *args, **kwargs: pytest.fail("must not call Sonar")
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "sonar_release_gate.py",
                "--head-ref=release-please--branches--master--components--nope",
                "--base-sha=abc1234",
                f"--repo-root={temp_repo}",
            ],
        )

        assert mod.main() == 1
        assert "nope" in capsys.readouterr().out

    def test_no_usable_analysis_fails_closed(self, temp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_release_gate as mod

        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(mod, "wait_for_release_analysis", lambda *args, **kwargs: None)
        monkeypatch.setattr(sys, "argv", ["sonar_release_gate.py", *self._args("abc1234"), f"--repo-root={temp_repo}"])

        assert mod.main() == 1

    def test_an_unanswered_api_fails_closed(self, temp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_release_gate as mod

        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(mod, "wait_for_release_analysis", lambda *args, **kwargs: ANALYSIS)
        monkeypatch.setattr(mod, "fetch_status", lambda *args, **kwargs: None)
        monkeypatch.setattr(sys, "argv", ["sonar_release_gate.py", *self._args("abc1234"), f"--repo-root={temp_repo}"])

        assert mod.main() == 1

    def test_a_ref_without_a_component_fails_closed(self, temp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from .. import sonar_release_gate as mod

        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "sonar_release_gate.py",
                "--head-ref=release-please--branches--master",
                "--base-sha=abc1234",
                f"--repo-root={temp_repo}",
            ],
        )

        assert mod.main() == 1
