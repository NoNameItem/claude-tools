# Waive AI reviews for release-please PRs — Design

**Date:** 2026-07-07
**Status:** Approved, not yet implemented.
**Scope:** repo (`.github/workflows/review-gate.yml`, `.github/workflows/claude-code-review.yml`)
**Task:** claude-tools-5vg.6 (bug; epic claude-tools-5vg, Repo-level tasks)
**Related:** claude-tools-5vg.1 (Codex drops a *synchronize* push after already reviewing) —
same subsystem (`review-gate.yml` reliability), different failure mode. This bug is Codex
**never** reviewing a bot-authored release PR at all.
**Builds on:** `2026-06-26-pr-review-merge-gate-design.md` (the `claude-review` + `review-gate`
merge gate) and `2026-07-01-harden-review-gate-design.md` (the `pull_request_target` /
posted-status architecture this exemption slots into).

---

## 1. Problem & Context

The `master` ruleset requires two AI-review status checks on every PR:

- **`claude-review`** — the check run of the `claude-review` job in `claude-code-review.yml`
  (`pull_request`; runs the `anthropics/claude-code-action`).
- **`review-gate`** — a **commit status** the `review-gate-poll` job posts to the PR head SHA
  (`pull_request_target`), asserting Codex reviewed the head commit.

**release-please PRs never satisfy `review-gate`.** Observed on PR #68 (`chore(statuskit):
release 0.4.0`, branch `release-please--branches--master--components--statuskit`, head
`f5baef9`, 2026-07-07): every other check was green (`claude-review`, Python CI, SonarCloud,
Plugin CI), but `review-gate-poll` polled ~25 min and failed:

> `Codex has not reviewed f5baef9… within 25 min.`

Across the PR's entire history there is **not one** Codex review or comment — the connector
never picks up these bot-generated release PRs. Both open release PRs are affected (#68
statuskit, #91 flow).

**Consequence:** release-please PRs cannot merge without a manual `@codex review` nudge + a
`review-gate` re-run on **every** release, blocking the automated release flow.

**Intent (decided during brainstorming):** a release PR is release-please's generated version
bump + CHANGELOG + marketplace-ref pins. There is no value in either AI reviewing it. So waive
**both** `review-gate` (Codex) and `claude-review` (Claude) for release PRs. They stay gated by
**Python CI + "require conversation resolution" + manual merge**.

## 2. Decisions

| Decision | Choice |
|---|---|
| Detection | A PR is a release PR **iff** `github.event.pull_request.head.ref` starts with `release-please--` (release-please's deterministic branch naming). Read as an expression / env var — **never** interpolated into a shell `run:`. |
| `review-gate` | Required context is a **posted status**, so the job must run and post it. Early-exit **before the poll loop**: on a release ref, `post_status success` and `exit 0`. |
| `claude-review` | Required context is the **job's own check run**, so keep the job running and let it go **green** without work: a "waive" step that runs (and passes) for release PRs + guard checkout / action steps with the negation. |
| Ruleset | **Unchanged** — both contexts stay required for all PRs; release PRs satisfy them via the two workflow edits. |
| `review_gate.py` | **Untouched** — the exemption is workflow orchestration (skip the poll), not a Codex-freshness decision. Keeping it out of `decide()` preserves that function's single responsibility. |

## 3. Why the two checks need different mechanisms

The required check is published differently for each (see
`2026-07-01-harden-review-gate-design.md`):

- `review-gate` is a **commit status** the job POSTs to the head SHA. If the job does not post
  it, the required context is **missing** → PR blocked. Skipping the job via `if:` therefore
  does **not** help — we must run the job and post `success`.
- `claude-review` is the **job's check run** (job id `claude-review`). Making the job conclude
  `success` — even with the Claude action skipped — yields a real green check that satisfies
  the requirement. This does not rely on GitHub's "skipped job = passing" semantics.

## 4. Change 1 — `review-gate.yml`

Add `HEAD_REF` to the gate step's `env`:

```yaml
        env:
          # …existing…
          HEAD_REF: ${{ github.event.pull_request.head.ref }}
```

Immediately after `post_status()` and the `EXIT` trap are set up, **before** the `pending`
post and the poll loop, insert:

```bash
# release-please PRs are bot-generated version bumps / CHANGELOG / marketplace-ref pins.
# Codex never reviews them and Claude's review is waived too (see claude-code-review.yml);
# they stay gated by Python CI + conversation resolution + manual merge. Pass immediately.
if [[ "$HEAD_REF" == release-please--* ]]; then
  post_status success "release-please PR — AI review not required"
  RESULT_POSTED=1
  echo "release-please PR (head=$HEAD_REF) — review-gate waived."
  exit 0
fi
```

`exit 0` with `RESULT_POSTED=1` makes the `EXIT` trap a no-op (fires only on `rc != 0`).
Reading `head.ref` as a string is safe under `pull_request_target`: the invariant is "never
*check out* / execute head code," which this does not — the ref name is only glob-matched, and
it is passed via `env` (never spliced into a command).

## 5. Change 2 — `claude-code-review.yml`

Keep the job's `if:` (fork + dependabot guard) as-is so the job still runs for a same-repo
release PR and produces its required `claude-review` check run. Replace the steps with:

```yaml
    steps:
      - name: Waive review for release-please PR
        if: ${{ startsWith(github.event.pull_request.head.ref, 'release-please--') }}
        env:
          HEAD_REF: ${{ github.event.pull_request.head.ref }}
        run: echo "release-please PR ($HEAD_REF) — Claude review not required; job passes to satisfy the required 'claude-review' check."

      - name: Checkout repository
        if: ${{ !startsWith(github.event.pull_request.head.ref, 'release-please--') }}
        uses: actions/checkout@v4
        with:
          fetch-depth: 1
          persist-credentials: false

      - name: Run Claude Code Review
        if: ${{ !startsWith(github.event.pull_request.head.ref, 'release-please--') }}
        id: claude-review
        uses: anthropics/claude-code-action@v1
        with:
          # …unchanged…
```

For a release PR only the "Waive" step runs → the job concludes **success** → `claude-review`
is green. For a normal PR the "Waive" step skips and checkout + action run as before. The ref
is passed via `env` (not interpolated into the `run:` string) to avoid script injection.

## 6. Security / accepted limitation

Detection is by branch name, so a **write-access** user could open a `release-please--*`
branch to waive both AI reviews. Write access is already the trust boundary on this repo
(forks are excluded from both gates; direct pushes to `master` are blocked); Python CI +
conversation resolution + manual merge still apply. This is the same class of accepted,
documented limitation as the gate's §10 base-change caveat. Branch-prefix alone (no `label`
corroboration) is sufficient — a write-access adversary could set a label just as easily, so a
second signal adds no real security, only guards against an accidental human branch-name
collision, which is not a concern worth the extra logic.

## 7. Rollout / verification

1. **Land the fix on `master`** via a normal (non-release) PR — both `claude-review` and
   `review-gate` run and review it as usual.
2. **Existing #68 / #91:** press **Update branch** on each (needed regardless, to pull the
   latest `master`). That merges the patched `master` into the head branch, firing
   `synchronize`:
   - `review-gate.yml` (`pull_request_target`, base = patched `master`) detects the release
     ref → posts `review-gate` = success.
   - `claude-code-review.yml` (`pull_request`, head now contains the fix via the merge) skips
     the action → the job goes green.
   Both required checks satisfied → PRs mergeable. *No manual `review-gate` re-run needed.*
3. **Future release PRs:** release-please rebuilds its branch off `master` (now carrying both
   edits), so every new release PR is exempt from creation.

## 8. Testing

`review_gate.py` is unchanged, so its unit tests are unaffected and none are added — the
exemption is a workflow-orchestration branch, not a freshness decision. Verification is
empirical (step 7.2/7.3: observe the release checks resolve green with the action / poll
skipped) plus the repo's existing YAML/actionlint pre-commit checks. The branch-prefix match
is a single glob in each workflow, low enough risk not to warrant extracting a tested helper.
