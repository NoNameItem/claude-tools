# Merge Gate Rollout — post-merge runbook

> **Not a subagent-executable plan.** Every step here mutates GitHub repository settings or
> waits on a live PR. Run it by hand, confirm each `--method PUT` / `--method DELETE` with the
> repository owner, and stop at the first unexpected output.

**Goal:** Make the `master` ruleset the single source of truth for merge rules, with CI failures
actually blocking merges, and confirm the new notification paths on live events.

**Companion plan:** `docs/superpowers/plans/2026-07-28-pr-merge-gate-and-notifications.md`
(Tasks 1–12 — all repository changes).
**Design:** `docs/superpowers/specs/2026-07-27-pr-merge-gate-and-notifications-design.md` (Part 1).

## Why this is separate

The order is a hard constraint of the design, not a preference:

> Required contexts with the new names only exist after the workflow change is on `master`.

Configuring the ruleset first would require checks that never appear, and GitHub reports those as
*"Expected — Waiting for status to be reported"* — blocking every PR indefinitely, including the
one that would fix it. So this runbook starts only after the companion plan's PR is **merged**,
which is separated from Task 12 by a push, a PR, several review rounds and a merge.

## Prerequisites

- [ ] The companion plan's PR is **merged into `master`**.
- [ ] A push-triggered run of `Push` has completed on `master` after the merge (this is what
      records `sonar.projectVersion` for the first time — Step 5 checks it).
- [ ] You have `gh` authenticated with admin rights on `NoNameItem/claude-tools`.

```bash
REPO=NoNameItem/claude-tools
```

## Step 1 — Capture the current configuration (this is the rollback)

```bash
gh api "repos/$REPO/rulesets" --jq '.[] | {id, name, target, enforcement}'
RULESET_ID=<id of "master merge gate">
gh api "repos/$REPO/rulesets/$RULESET_ID" > /tmp/ruleset-before.json
gh api "repos/$REPO/branches/master/protection" > /tmp/protection-before.json
```

Keep both files until Step 4 has verified the new configuration. They are the only way back.

## Step 2 — Write the consolidated ruleset

```bash
cat > /tmp/ruleset.json <<'JSON'
{
  "name": "master merge gate",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {"ref_name": {"include": ["refs/heads/master"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "required_linear_history"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 0,
      "dismiss_stale_reviews_on_push": false,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_review_thread_resolution": true,
      "allowed_merge_methods": ["squash", "rebase"]
    }},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": false,
      "do_not_enforce_on_create": false,
      "required_status_checks": [
        {"context": "Validate PR"},
        {"context": "Python CI Gate"},
        {"context": "Claude Code Plugin CI Gate"},
        {"context": "review-gate"}
      ]
    }}
  ]
}
JSON
gh api --method PUT "repos/$REPO/rulesets/$RULESET_ID" --input /tmp/ruleset.json
```

Decisions encoded above, so a future reader does not "fix" them:

- **`merge` dropped from `allowed_merge_methods`** — merge commits are disabled repo-wide and
  conflict with linear history.
- **`strict_required_status_checks_policy: false`** — "update branch" must not re-trigger the
  reviewers (`claude-tools-5vg.4`).
- **`review-gate` is required although fork PRs never publish it** — that is precisely what keeps
  fork PRs unmergeable, as `review-gate.yml:66-69` documents.
- **`SonarCloud Code Analysis` is deliberately not required** — it only exists on PRs with Python
  changes, and a conditionally-present required check blocks a PR forever. The Quality Gate
  blocks through `Python CI Gate` instead (`sonar.qualitygate.wait=true`).
- **`pr-notify` is deliberately not required, and must never be added.** It is the
  notification's cross-run marker, not a verdict: it sits at `pending` for as long as the checks
  are genuinely still running, and the run that decides to stay silent leaves it untouched by
  design. Making it required would let a bookkeeping status block a merge.
- **`bypass_actors` stays empty.**

## Step 3 — Delete the classic branch protection

```bash
gh api --method DELETE "repos/$REPO/branches/master/protection"
```

## Step 4 — Verify the consolidated gate

```bash
gh api "repos/$REPO/rules/branches/master" --jq '[.[] | .type]'
gh api "repos/$REPO/rules/branches/master" \
  --jq '[.[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context]'
gh api "repos/$REPO/branches/master/protection" 2>&1 | head -3
```

Expected:
- rule types include `deletion`, `non_fast_forward`, `required_linear_history`, `pull_request`,
  `required_status_checks`;
- the contexts are exactly `Validate PR`, `Python CI Gate`, `Claude Code Plugin CI Gate`,
  `review-gate`;
- the protection call returns `Branch not protected` (404).

The second command is also what `_reusable-pr-summary.yml` reads at notification time — if it
returns an empty list, every PR notification will go silent, so do not leave this step half-done.

**Open PRs created before the merge** lack `Python CI Gate` / `Claude Code Plugin CI Gate` on
their head SHA and will need a push or a re-run before they can merge.

## Step 5 — Confirm the `projectVersion` seeding

```bash
curl -s "https://sonarcloud.io/api/project_analyses/search?project=NoNameItem_statuskit&category=VERSION" \
  | python3 -m json.tool | head -20
```

Expected: at least one analysis carrying a `VERSION` event with the current version.

Until a **second** `VERSION` event exists, release notifications legitimately fall back to the
current state of `master` with no version-to-version delta. That is not an error state and must
not be reported as one — releases are cut from `master` right after the merge, so the numbers are
the released ones anyway.

## Step 6 — Exercise the notification paths on a throwaway PR

Open a scratch PR against `master` and confirm, in order:

1. **Green path** — one silent opener, then exactly one reply saying *Ready to merge* once both
   producers have finished. The `pr-notify` status shows `msg:<id> v:ready`.
2. **Red path** — push a commit that fails lint. The reply says *Checks failed:* with the gate in
   bold, the check table bare (not collapsed), and the failing child job listed.
3. **Re-run** — re-run the failed job so it passes. A **new** reply arrives with the flipped
   verdict, because the marker's recorded verdict differed.
4. **Duplicate suppression** — re-run a passing job. No new message.
5. **Comments path** — leave an unresolved review comment and re-run. The verdict becomes
   *All checks passed, unresolved comments: 1*.
6. **Superseded gate** — push twice in quick succession. The surviving poll for the old SHA sends
   nothing; only the new SHA notifies.
7. **Push pair** — merge the scratch PR and confirm the push pair on `master`, with the Sonar
   project-state block.
8. **Release pair** — on the next release-please merge, confirm the release pair with the notes block.

Close the scratch PR. When something misbehaves, the `PR Summary` job's `Decision:` log line
(`{"send":…,"reason":…,"verdict":…}`) names the branch of `pr_summary.py` that was taken.

## Rollback

```bash
gh api --method PUT "repos/$REPO/rulesets/$RULESET_ID" --input /tmp/ruleset-before.json
```

The classic branch protection can be restored from `/tmp/protection-before.json` through
`PUT /repos/{owner}/{repo}/branches/master/protection`, but note that its JSON needs reshaping —
the GET response is not accepted verbatim by the PUT endpoint.

Rolling the *repository* change back is a separate matter: reverting the merge would remove the
`Python CI Gate` contexts while the ruleset still requires them, blocking all PRs. Revert the
ruleset first, then the code.

## Closing out

```bash
bd close <this task's id> --reason="ruleset consolidated; notification paths verified on a live PR"
bd dolt push
```
