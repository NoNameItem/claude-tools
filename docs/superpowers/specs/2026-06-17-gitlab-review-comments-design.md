# GitLab support in flow:review-comments

**Task:** claude-tools-elf.16
**Date:** 2026-06-17
**Status:** Design approved

## Problem

`flow:review-comments` processes unresolved PR review comments, but it is hard-wired
to GitHub: every platform-specific step shells out to `gh` / `gh api`, and the
collection subagent parses GitHub's comment schema. Teams working on GitLab merge
requests cannot use the skill.

## Goal

Extend the existing skill so it works on **both** GitHub PRs and GitLab MRs, against
both **gitlab.com and self-hosted** GitLab instances, while keeping the GitHub path
unchanged and preserving current behavior (reply-only, never resolve threads).

## Approach

One unified skill that **auto-detects** the platform and branches the platform-specific
I/O **inline in the prose** (no new `bin/` helpers, no test changes). The
platform-agnostic phases — categorize, analyze, apply, commit, push, summary — are
untouched.

Tradeoff accepted: GitLab normalization rules live in the SKILL.md prose and the
collection subagent prompt; they are not covered by unit tests. The implementation
must therefore verify the actual `glab` commands against a live GitLab instance.

### Command surface

```
/flow:review-comments [number] [--platform github|gitlab]
```

- `[number]` — PR number (GitHub) or MR iid (GitLab).
- `--platform` — optional override when detection is ambiguous.
- Frontmatter `allowed-tools` gains `Bash(glab:*)` alongside `Bash(gh:*)`.
- Frontmatter `description` updated to mention GitLab MRs.

## Platform detection (new Phase 0)

Resolve `PLATFORM` once, in this order:

1. `--platform github|gitlab` provided → use it. Done.
2. Parse the host from `git remote get-url origin`. Handle both forms:
   - SSH: `git@host:group/repo.git`
   - HTTPS: `https://host/group/repo(.git)`
3. Match the host against each CLI's authenticated hosts:
   - `gh auth status` → GitHub hosts (incl. GitHub Enterprise).
   - `glab auth status` → GitLab hosts (incl. self-hosted).
   - Host ∈ gh hosts → GitHub; host ∈ glab hosts → GitLab.
   - **This is the key to self-hosted support:** detection does not depend on the
     literal `gitlab.com` / `github.com` strings.
4. Fallback heuristic: hostname contains `gitlab` → GitLab; contains `github` →
   GitHub. Warn that CLI auth may be missing.
5. Still ambiguous / unknown → `AskUserQuestion` (GitHub / GitLab), or instruct the
   user to pass `--platform`.

## Concept & command mapping

| Concept | GitHub | GitLab |
|---|---|---|
| Unit | Pull Request (number) | Merge Request (iid) |
| CLI | `gh` | `glab` |
| Repo identifier | `owner/repo` via `gh repo view --json nameWithOwner` | URL-encoded project path `group%2Frepo` (from remote URL path) |
| Detect unit for current branch | `gh pr view --json number,title,headRefName,url` | `glab mr view` / `glab api "projects/{id}/merge_requests?source_branch={branch}&state=opened"` |
| Fetch threads | `gh api repos/{o}/{r}/pulls/{n}/comments --paginate` + `…/reviews` | `glab api "projects/{id}/merge_requests/{iid}/discussions" --paginate` |
| Thread model | flat comments linked by `in_reply_to_id` | `discussion.notes[]` is the thread natively |
| Authenticated user | `gh api user -q .login` | `glab api user -q .username` |
| Reply | `gh api repos/{o}/{r}/pulls/{n}/comments/{comment_id}/replies -f body=…` | `glab api "projects/{id}/merge_requests/{iid}/discussions/{discussion_id}/notes" -X POST -f body=…` |
| Skip as already-done | `already_replied` heuristic | `resolved == true` **or** `already_replied` |
| Outdated detection | `line == null && original_line` set | diff note `position.new_line == null` (with `old_line` set); a note with no `position` is a general comment, not outdated |
| Bot / summary | `coderabbitai` or `[bot]` | same heuristic (username matches `coderabbit` / `bot`); CodeRabbit's walkthrough is a non-`position` discussion → `(summary)` bucket |

> Implementation note: exact `glab api` placeholder/flag behavior (e.g. `:id`
> substitution, `--paginate`, `-q`) must be verified against a live `glab`; fall back
> to interpolating the explicit URL-encoded project path if placeholders are not
> supported.

## Affected phases

- **Phase 1 — detect & sync.** Branch GitHub vs GitLab to obtain identifiers
  (owner/repo + PR number, or project path + MR iid). The `git pull origin <branch>`
  sync step is unchanged.
- **Phase 2 — collect (single haiku subagent).** The subagent prompt gains two
  branches:
  - **GitHub branch:** current rules (root comments, `in_reply_to_id` threading,
    outdated via `line == null`, bot detection, `already_replied`).
  - **GitLab branch:** iterate discussions → each discussion is a thread;
    `notes[0]` (first non-system note) is the root, `notes[1..]` are replies; skip
    `system == true` notes; skip discussions that are resolved; map `position`
    (`new_path`, `new_line`, `line_range`) → `file:line` / `file:start-end`; apply
    the GitLab outdated rule; `already_replied` = latest note author == authenticated
    user.
  - Output keeps the **same TABLE + METADATA contract**, extended with:
    - `"platform"`: `"github"` | `"gitlab"`
    - `"discussion_id"`: GitLab discussion id (string), `null` on GitHub
  - so Phase 5.3 can pick the correct reply command. `id`/`comment_id` continues to
    carry the GitHub reply target.
- **Phases 3, 4, 5.1, 5.2, 5.4–5.6 — unchanged**, except:
  - Output wording says "PR/MR" as appropriate.
  - **Phase 5.3 (reply)** branches on `platform`:
    - GitHub: `gh api …/comments/{comment_id}/replies -f body=…`
    - GitLab: `glab api ".../discussions/{discussion_id}/notes" -X POST -f body=…`

## Edge cases (added)

- `glab` not installed or not authenticated → error message analogous to the existing
  GitHub API error case; stop, do not retry.
- Ambiguous platform → ask the user (or require `--platform`).
- Multiple remotes (e.g. GitHub origin + GitLab mirror) → use `origin`; allow
  `--platform` override.
- Self-hosted GitLab host → handled by CLI-auth-host matching in detection.
- GitLab general (non-`position`) discussions → `(summary)` / general bucket, same as
  GitHub's CodeRabbit summary handling.

## Out of scope

- Resolving / unresolving threads on either platform (parity: reply-only).
- MR/PR approval or merge.
- Auto-selecting a non-`origin` remote.
- Any `bin/` helper or test changes.
- Changes to GitHub-path behavior.

## Self-review

- Detection primary signal is CLI-auth-host matching, which is what enables
  self-hosted support without hardcoded hostnames.
- METADATA contract extended (not abstracted) with `platform` + `discussion_id`,
  keeping the existing GitHub fields intact for a low-risk GitHub path.
- Behavior parity (reply-only, never resolve) confirmed for both platforms.
