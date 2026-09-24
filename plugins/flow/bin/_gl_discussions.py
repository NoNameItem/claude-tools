"""GitLab MR discussions as GraphQL reports them — the only place GitLab exposes account type.

A GitLab REST note's `author` carries `id, username, name, state, locked, avatar_url, web_url`
and nothing that says "bot"; `GET /users/:id` has no such field for a non-admin either. GraphQL
`UserCore.bot` does. Imported by BOTH `flow-review-collect` (a username → bot map that sets
`is_bot`) and `flow-review-resolve-gate` (the live state of one discussion right before it is
resolved), so the two can never disagree on what a GitLab bot is.

A discussion's GraphQL id is `gid://gitlab/Discussion/<id>`, where `<id>` is the REST discussion
id the collector stores as `discussion_id` / `resolve_id`.
"""

from __future__ import annotations

import json

import _git

GID_PREFIX = "gid://gitlab/Discussion/"

_QUERY = (
    "query($fullPath:ID!,$iid:String!,$cursor:String){"
    "project(fullPath:$fullPath){mergeRequest(iid:$iid){"
    "discussions(first:100,after:$cursor){"
    "nodes{id resolved notes(first:100){pageInfo{hasNextPage} nodes{system author{username bot}}}}"
    "pageInfo{hasNextPage endCursor}}}}}"
)


def project_path() -> str:
    """The current repo's GitLab project path, decoded (`group/sub/repo`) — the form GraphQL's
    `fullPath` takes, unlike the URL-encoded form the REST paths use."""
    return json.loads(_git.api_run(["glab", "repo", "view", "--output", "json"]))["path_with_namespace"]


def walk(full_path: str, iid: object) -> list[dict]:
    """Every discussion node of the MR, across all pages.

    Never returns a partial walk: a page that cannot be read, carries GraphQL `errors`, lacks the
    expected shape, or says `hasNextPage` with no cursor to follow raises
    `_git.ApiUnavailableError`. The gate must not judge a thread it did not see, and the collector
    must not silently call the authors of unread pages humans without saying so.
    """
    nodes: list[dict] = []
    cursor: str | None = None
    while True:
        cmd = ["glab", "api", "graphql", "-f", f"query={_QUERY}", "-f", f"fullPath={full_path}", "-f", f"iid={iid}"]
        if cursor is not None:
            cmd += ["-f", f"cursor={cursor}"]
        try:
            page = json.loads(_git.api_run(cmd))
        except ValueError as exc:
            msg = f"GitLab GraphQL discussions query for {full_path}!{iid} returned malformed JSON"
            raise _git.ApiUnavailableError(msg, permanent=False) from exc
        if not isinstance(page, dict):
            msg = (
                f"GitLab GraphQL discussions query for {full_path}!{iid} returned {type(page).__name__}, not an object"
            )
            raise _git.ApiUnavailableError(msg, permanent=False)
        if page.get("errors"):
            msg = f"GitLab GraphQL discussions query for {full_path}!{iid} returned errors: {page['errors']}"
            raise _git.ApiUnavailableError(msg, permanent=True)
        try:
            conn = page["data"]["project"]["mergeRequest"]["discussions"]
            nodes += conn.get("nodes") or []
            info = conn.get("pageInfo") or {}
        except (KeyError, TypeError, AttributeError) as exc:
            # A null project / mergeRequest (wrong path, no access) or a null connection.
            msg = f"GitLab GraphQL discussions query for {full_path}!{iid} returned no discussions"
            raise _git.ApiUnavailableError(msg, permanent=False) from exc
        if not info.get("hasNextPage"):
            return nodes
        if not info.get("endCursor"):
            msg = f"GitLab GraphQL discussions query for {full_path}!{iid} returned an unfollowable page"
            raise _git.ApiUnavailableError(msg, permanent=False)
        cursor = info["endCursor"]


def discussion_id(node: dict) -> str:
    """The REST discussion id behind a GraphQL discussion node."""
    gid = str(node.get("id") or "")
    return gid[len(GID_PREFIX) :] if gid.startswith(GID_PREFIX) else gid


def notes_of(node: dict) -> list[dict]:
    """The discussion's non-system notes, in order. System notes ("changed the description") are
    platform bookkeeping, not anyone speaking in the thread."""
    return [n for n in ((node.get("notes") or {}).get("nodes") or []) if not n.get("system")]


def bot_by_username(nodes: list[dict]) -> dict[str, bool]:
    """username → `UserCore.bot` for every note author the walk saw."""
    out: dict[str, bool] = {}
    for node in nodes:
        for note in notes_of(node):
            author = note.get("author") or {}
            name = author.get("username")
            if name is not None:
                out[str(name)] = author.get("bot") is True
    return out
