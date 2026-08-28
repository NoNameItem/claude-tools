"""Tests for release_merge.py — is this push to master a release-please merge?"""

from __future__ import annotations

from ..release_merge import is_release_merge

MANIFEST = ".release-please-manifest.json"


def _commit(**files) -> dict:
    return {"added": [], "modified": [], "removed": [], **files}


class TestIsReleaseMerge:
    def test_squashed_release_merge(self):
        assert is_release_merge([_commit(modified=[MANIFEST, "packages/statuskit/CHANGELOG.md"])]) is True

    def test_two_commit_shape_manifest_not_in_the_head(self):
        # A rebase merge of the flow release PR: the head is the pin commit from
        # pin_marketplace_refs.py and the manifest is one commit further back. Reading only the
        # head commit would miss it.
        commits = [
            _commit(modified=[MANIFEST, "plugins/flow/CHANGELOG.md"]),
            _commit(modified=[".claude-plugin/marketplace.json"]),
        ]
        assert is_release_merge(commits) is True

    def test_ordinary_merge(self):
        assert is_release_merge([_commit(modified=["packages/statuskit/src/statuskit/cli.py"])]) is False

    def test_empty_push(self):
        assert is_release_merge([]) is False

    def test_commit_without_a_modified_key(self):
        # The payload is GitHub's, not ours — a missing key must not raise.
        assert is_release_merge([{"id": "abc"}]) is False

    def test_a_file_whose_name_merely_ends_with_the_manifest(self):
        assert is_release_merge([_commit(modified=["docs/.release-please-manifest.json.md"])]) is False
