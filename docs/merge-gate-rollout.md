# Merge Gate Rollout — post-merge runbook

> **Not a subagent-executable plan.** Every step here mutates GitHub repository settings or
> waits on a live PR. Run it by hand, confirm each `--method PUT` / `--method DELETE` with the
> repository owner, and stop at the first unexpected output.

**Goal:** Make the `master` ruleset the single source of truth for merge rules, with CI failures
actually blocking merges, and confirm the new notification paths on live events.

**Design:** `docs/superpowers/specs/2026-08-01-notification-triggers-design.md` (Steps 2, 2a, 6 and
7 below come from this design; implementation plans live in `docs/superpowers/plans/`, which is
git-ignored, so no plan path is a durable reference here).

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

## Step 0 — Create `CODEX_NUDGE_TOKEN` (before the merge)

Automatic Codex reviews are switched off in the connector (2026-07-31), so the gate asks for each
review itself by posting `@codex review`. The connector attributes the request to the commenting
account and requires that account to hold a Codex subscription — a bot account cannot — so the
comment must be posted with a PAT of a real user.

1. Create a **fine-grained** PAT of the repository owner, scoped to `NoNameItem/claude-tools` only,
   with `Pull requests: read and write` and `Issues: read and write` (a PR comment is created
   through `issues/{n}/comments`, and GitHub checks both permissions depending on the object).
   Deliberately **not** `RELEASE_PLEASE_TOKEN`, which can write to `master`.
2. Add it as the repository secret `CODEX_NUDGE_TOKEN`.
3. Note its expiry date somewhere you will see it: on that day the gate starts failing on every
   PR. The failure is explicit and names the token — `_reusable-review-gate.yml` treats a failed
   comment POST as an error rather than falling through into waiting, precisely so an expired PAT
   does not look like "Codex is not responding".

**Until this branch lands**, every ordinary PR needs a hand-written `@codex review` from the
owner's account, because nothing on `master` nudges yet. On the branch's own PR the branch copy of
the gate does the nudging.

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
      "allowed_merge_methods": ["squash"]
    }},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": false,
      "do_not_enforce_on_create": false,
      "required_status_checks": [
        {"context": "Validate PR"},
        {"context": "Python CI Gate"},
        {"context": "Claude Code Plugin CI Gate"},
        {"context": "Review Gate"}
      ]
    }}
  ]
}
JSON
gh api --method PUT "repos/$REPO/rulesets/$RULESET_ID" --input /tmp/ruleset.json
```

Decisions encoded above, so a future reader does not "fix" them:

- **`squash` is the only allowed merge method** — merge commits are disabled repo-wide and conflict
  with linear history, and `rebase` was dropped on 2026-08-13 so that one PR always lands as exactly
  one commit. The repository setting matches: `allow_rebase_merge: false`. Rolling back means
  putting `"rebase"` back here *and* re-enabling the repository setting.
- **`strict_required_status_checks_policy: false`** — "update branch" must not re-trigger the
  reviewers (`claude-tools-5vg.4`).
- **`Review Gate` is a check run, not a commit status.** The gate now runs as a job of `pr.yml`
  under `pull_request`, where a job's check run is attributed to the head SHA automatically — so
  the hand-rolled `review-gate` status is gone, and the `review-gate-result` wrapper job publishes
  this context instead. The wrapper always runs (`if: always()`), so the context is always
  published by a job that actually executed; it fails fork PRs explicitly, which is what keeps them
  unmergeable, and passes a release-please PR, which needs no AI review.
- **`codex-nudge` is deliberately not required, and must never be added.** Like `pr-notify-anchor`
  it is bookkeeping: it records which `@codex review` comment was posted for this head SHA and the
  freshness cutoff the poll uses, so a re-run does not ask Codex twice. It is posted as `success`
  precisely so it never reads as an unfinished check.
- **`SonarCloud Code Analysis` is deliberately not required** — it only exists on PRs with Python
  changes, and a conditionally-present required check blocks a PR forever. The Quality Gate
  blocks through `Python CI Gate` instead (`sonar.qualitygate.wait=true`).
- **`pr-notify-anchor` is deliberately not required, and must never be added.** It is the
  notification's cross-run bookkeeping, not a verdict: it records which Telegram message the result
  should reply to, and a run whose Telegram send failed writes nothing at all. It is posted as
  `success` precisely so it never reads as an unfinished check — but making it required would let
  bookkeeping block a merge.
  Its description gains ` replied` once the result notification has answered the thread — the same
  marker, one more field, still not a verdict.
- **`bypass_actors` stays empty.**

## Step 2a — Swap the required context (time-critical)

Do this **immediately after the merge**, and do not open new PRs in between. Nothing publishes the
old `review-gate` commit status any more, so until the ruleset names `Review Gate` instead, every
new PR sits at *"Expected — waiting for status to be reported"*.

Naming the wrapper job `review-gate` — so the check run would satisfy the existing required
context and no ruleset edit would be needed — was considered and rejected: the window is
acceptable when nothing else is in flight, and the capitalised name matches the other three gates.

Note that the PR that lands this change runs under BOTH gates: the old one arrives from `master`
via `pull_request_target`, the new one from the branch. So its notifications arrive doubled, and
that is expected. It is the last PR on which that happens.

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
  `Review Gate`;
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
the released ones anyway. It is the same rendering a project's first release gets; see
`docs/superpowers/specs/2026-08-19-release-notification-sonar-delta-design.md`, "Degradation".

## Step 6 — Exercise the notification paths on a throwaway PR

Open a scratch PR against `master` and confirm, in order:

1. **Green path** — one silent opener carrying the commit list, then exactly one reply saying
   *Ready to merge*. `pr-notify-anchor` shows `msg:<id> replied` afterwards.
2. **The nudge** — the gate posts `@codex review` from the owner's account within seconds, Codex
   reacts 👀, and the comment is deleted once the review lands. `codex-nudge` on the head SHA reads
   `comment:<id>@<cutoff>`.
3. **Red path** — push a commit that fails lint. The reply says *Checks failed:* with the gate in
   bold, the check table bare (not collapsed), and the failing child job listed.
4. **Re-run** — re-run the failed job so it passes. Exactly one new reply arrives with the flipped
   verdict, and the gate does not ask Codex a second time (the marker is what prevents it).
5. **`edited`** — change the PR title. The checks re-run and no message is sent at all.
6. **Two pushes in quick succession** — the first thread receives a silent *Superseded by `<sha>`*
   reply; only the new SHA gets a verdict.
7. **Comments path** — leave an unresolved review comment and re-run. The verdict becomes
   *All checks passed, unresolved comments: 1*.
8. **Thread resolution sends nothing** — resolve the comment and confirm no message arrives. This
   is a known gap, not a defect: GitHub Actions has no `pull_request_review_thread` trigger, so
   `claude-tools-5vg.17` stays open (see Task 9). The PR becomes mergeable silently.
9. **Push pair** — merge the scratch PR and confirm the push pair on `master`, with the Sonar
   project-state block.
10. **Release PR** — on the next merge to master, the pending release PRs are force-pushed:
    only the component whose changelog entries actually changed sends a message; the others,
    whose changelog moved by one date, stay silent.
11. **Release merge** — merging a release PR produces no push pair, only the release pair
    (*Publishing…* / *Published to PyPI*). A failing release merge still notifies.

Close the scratch PR. When something misbehaves, the `PR Summary` job's `Decision:` log line
(`{"send":…,"reason":…,"verdict":…}`) names the branch of `pr_summary.py` that was taken.

## Step 7 — Pinning the notification implementation: decided against (`claude-tools-5vg.14`)

**Not a step any more.** This section used to instruct pinning the privileged notification code to
a trusted revision. That was decided against on 2026-08-25; it is kept here rather than deleted
because the rest of this runbook was executed with the pin still on the plan, and a reader who
finds Steps 0–6 done will otherwise look for the seventh.

**What was proposed** (decision of 2026-07-29, PR #119 round 5): run `telegram_notify.py` from the
action's own checkout (`${GITHUB_ACTION_PATH}`), replace `notify-start`'s local action reference
with `NoNameItem/claude-tools/.github/actions/telegram-notify@master` and drop its checkout, and
pin `_reusable-pr-summary.yml`'s checkout to `github.event.pull_request.base.sha`.

**What changed underneath it.** PR #124 reworked `review-gate.yml` into
`_reusable-review-gate.yml`, called from `pr.yml`, moving it from `pull_request_target` to
`pull_request`. The premise above — that the gate checks out the base branch and is therefore out
of scope — no longer holds: there are three jobs running PR-authored code under privilege, not two,
and the third holds `CODEX_NUDGE_TOKEN` (the owner's PAT), the most valuable of the three secrets.

**Why it was dropped.** On a `pull_request` event GitHub reads the workflow file itself from the PR
branch. A PR can therefore add a step that reads `TELEGRAM_BOT_TOKEN` or `CODEX_NUDGE_TOKEN`
directly, with or without the pin. Pinning the *scripts* does not close that; it only moves where a
malicious or accidental change has to appear — into the workflow diff instead of a Python diff.
That is worth something, but it is not what "pin the implementation" promised, and
`2026-08-01-notification-triggers-design.md` had already weighed exactly this trade for the gate
(`ref: base.sha`) and rejected it under this repository's threat model: same-repo PRs come only
from the owner and trusted collaborators, fork PRs never reach these jobs, and the realistic threat
is an accidental edit — which the workflow diff already surfaces. Applying the same reasoning to
`notify-start` and the summary produces the same answer.

The mechanics had also gone stale: `notify-start` cannot drop its checkout, because two of its
steps run `.github/scripts/pr_start.py` from the workspace (`pr.yml`, the "Read the anchor markers"
and "Build the start message" steps).

**Where the accepted boundary is documented:** `AGENTS.md`, "Do not flag" — `pr.yml`'s jobs holding
`statuses: write`, `CODEX_NUDGE_TOKEN` and the Telegram credentials while running PR-authored code,
and a PR being able to edit the workflow that gates it. The reasoning behind both lives in
`docs/superpowers/specs/2026-08-01-notification-triggers-design.md`, "Accepted trade-off".

Related and still open: `claude-tools-5vg.12` (fork guard on the pre-existing `secrets: inherit`
jobs) — an independent hardening item that this decision does not touch.

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
