# review-gate — accept the Codex review receipt, and say what Codex did when it times out

**Task:** claude-tools-5vg.31
**Date:** 2026-10-22
**Status:** design

Mockups: none — the output is CI log text.

## Problem

PR #151 (head `a84dae4d57dea301ea163a58897ed55335a5221d`): `review-gate / review-gate-poll` timed
out after 25 min — "Codex has not reviewed a84dae4 within 25 min" — although Codex answered 2.5 min
after the nudge. Its answer was issue comment 6328012482, created `2026-10-21T22:32:32Z`:

```
<!-- codex-review-receipt:v1 -->

Codex Review: Didn't find any major issues. :rocket:

**Reviewed commit:** `a84dae4d57`
…
```

The nudge cutoff recorded in the `codex-nudge` marker is `2026-10-21T22:29:55Z`. PR #152, nudged in
the same minute, passed in 2 min. The same failure already happened on #151 at `3975fc8` (receipt at
`2026-10-21T01:12:55Z`, both runs red).

### Root cause

`review_gate.py decide` accepts two kinds of evidence:

1. a Codex PR review pinned to `head_sha` and submitted after the cutoff — Codex creates one only
   when it **has** findings;
2. a Codex 👍 on the PR body created after the cutoff.

Around 2026-10-20 Codex changed what 👍 means. It now reacts with 👍 only when its internal
`codex-review-state` says `has_unresolved_findings: false` for the **whole PR**. On #151 that flag
has stayed `true` since the `59ec29a` round, through every later clean round, although all 7 Codex
threads are resolved on GitHub; on #152 it reset on the first clean round. So a clean round on a PR
that Codex still considers "dirty" produces neither a SHA-pinned review nor a 👍, and the gate can
only time out. Why Codex keeps the flag set is internal to Codex; the gate must not depend on it.

What Codex does post on **every** clean round is the receipt above: a new issue comment, one per
round, naming the reviewed commit. Observed on #149 (`84a8364893`), #150 (`f680163acc`), #152
(`c76bdb6e7e`) and all three clean rounds of #151 (`75200defce`, `3975fc8c78`, `a84dae4d57`).

The second half of the problem: diagnosing this took a dig through `userContentEdits` of the summary
comment, because the timeout error says the same thing whether Codex was silent or answered in a
form the gate did not recognise. Codex has changed its signalling once; it will again.

## Goals

- A clean Codex round on the head commit opens the gate, whatever Codex thinks about the rest of the
  PR.
- When the gate does time out, the log tells "Codex was silent" apart from "Codex was active, but
  left nothing the gate accepts" — and in the second case shows what it left.

## Non-goals

- No early failure. The gate keeps waiting the full 25 min even when it sees Codex activity it does
  not recognise: 👀 reactions and in-place summary edits are normal while a review is in progress,
  so failing early would fire falsely. (Considered and declined by the owner.)
- No change to the nudge, the `codex-nudge` marker, the cutoff, the head-moved check, the timeout
  or the interval.
- The summary comment's `codex-review-state` is **not** evidence (see Decision 2).
- No notifications (Telegram etc.) about a timeout.

## Anti-goals

- **A false pass.** Anything that opens the gate for a commit Codex did not review — another SHA, an
  older round, a comment someone else wrote, a summary comment edited in place — is worse than
  today's false timeout.
- **A gate that waits forever while looking healthy.** The workflow branches on the exact string
  `pass`. Any change to the CLI's stdout that breaks that comparison silently turns every run into
  a 25-min timeout.

## Decision

### 1. A third kind of evidence: the review receipt

`decide` passes when, in addition to today's two paths (both kept unchanged), there is an issue
comment on the PR that satisfies **all** of:

- author login is exactly `chatgpt-codex-connector[bot]` (`CODEX_BOT`);
- the body contains the HTML comment marker `codex-review-receipt:v1`, matched as a whole marker —
  `<!--\s*codex-review-receipt:v1\s*-->` — so that `codex-review-receipt:v2` or `…:v10` do **not**
  match (deliberate: a new version is a format change to look at, and it will show up in the
  breakdown, Decision 3);
- the body has a `**Reviewed commit:** \`<sha>\`` line whose `<sha>` is lowercase hex, at least 7
  characters long, and a prefix of `head_sha` (Codex currently writes 10 characters);
- `created_at` is strictly newer than the cutoff (same string comparison as the other two paths;
  `null`/missing → not fresh, never a crash).

`updated_at` plays no part in the pass decision. The receipt text ("Didn't find any major issues",
the emoji) is not checked. A receipt that has the marker but no parsable `Reviewed commit` line is
`wait`, not an error.

### 2. What deliberately does not count

- **The summary comment** (`<!-- codex-pull-request-review-summary -->` with
  `<!-- codex-review-state:v1 {…} -->`). It carries the full head SHA and `status: completed`, which
  makes it the most tempting false pass — but Codex creates it once and edits it in place, so
  neither its `created_at` (old) nor its `updated_at` (moves on every Codex action, including the
  start of a review) says *which round* it describes. It appears in the breakdown only.
- Receipts of another version, receipts for another SHA, receipts older than the cutoff, receipts by
  any other author.

### 3. A breakdown on every poll

Each poll iteration prints one human-readable line describing what the gate saw **after the
cutoff**, per channel, and why each item did or did not count. It replaces today's
`Not yet (decision=wait). Sleeping 30s…` (the "sleeping" part can stay). Shape (exact wording is the
builder's call):

```
since 2026-10-21T22:29:55Z — reviews: none · reactions: none · comments: 6328012482 receipt:v1 a84dae4d57 (head ✓) · 6292793328 summary, state a84dae4d57 completed, edited 22:32:35Z
```

The breakdown covers Codex-authored items only:

- **reviews** submitted after the cutoff, with their `commit_id` (head or not);
- **reactions** on the PR body created after the cutoff, with their `content` (`+1`, `eyes`, …);
- **issue comments** created **or** updated after the cutoff: id, the `codex-*` markers found in
  the body, the `Reviewed commit` SHA if any, and — for `codex-review-state:v1` — the JSON that
  follows the marker inside the same HTML comment, read as `code_review.commit_sha` and
  `code_review.status` when they parse (if they don't, markers only; never a crash). Observed
  shape: `<!-- codex-review-state:v1 {"code_review":{"commit_sha":"<40 hex>","has_any_findings":…,
  "has_unresolved_findings":…,"status":"completed"},"security_review":{…}} -->`.

### 4. Two timeout errors

At the deadline the error depends on whether any Codex-authored item from the breakdown exists:

- **None** — today's message, unchanged in substance: Codex has not reviewed `<sha>` within 25 min;
  re-run once Codex finishes, the marker prevents a second nudge.
- **Some, but none accepted** — a distinct message: Codex was active on the PR after the nudge, but
  left nothing the gate accepts as a review of `<sha>`; followed by the list of those items (id,
  time, markers, SHAs, as in the breakdown) and the same re-run hint. This is the message that says
  "the format changed again".

`::error::` takes a single line. The list is printed as plain lines first and the run ends with a
one-line `::error::` (or the builder encodes newlines as `%0A`; either is fine).

### 5. Division of labour: bash fetches, Python decides

The repo's existing split (`pr_summary.py` mirrors `review_gate.py` on purpose) holds: the
workflow does I/O, the script decides, and everything that decides is unit-tested. That includes
marker and SHA parsing, the breakdown, and the choice between the two timeout messages. The task
card suggested extracting the SHA in jq; that is rejected — a regex in jq has no tests, and a jq
filter on `codex-review-receipt:v1` would drop exactly the unrecognised comments the breakdown must
report.

## Interfaces

### `review_gate.py`

- `decide()` keeps returning `"pass"` / `"wait"` (a `str`). It gains a `comments` argument; the
  existing two paths are untouched.
- The breakdown is a **separate** pure function (name the builder's call), so `decide` stays the
  single-responsibility verdict and its existing tests remain valid.
- The timeout message choice is a pure function too, tested for both branches.
- **CLI contract:** `decide` prints the verdict — and only the verdict — on **stdout**, exactly as
  today; the breakdown goes to **stderr** (both land in the Actions log). The timeout report is
  either another subcommand or an option — builder's call — as long as its text comes from Python.
- **Payload:** stdin JSON gains a `comments` key, read as `payload.get("comments", [])`, so existing
  callers and tests keep working. Each comment:
  `{"id": int, "user": {"login": str}, "created_at": str|null, "updated_at": str|null, "body": str}`
  where `body` is a head slice of the real body (below).

### `_reusable-review-gate.yml`

Inside the poll loop, next to reviews and reactions:

- fetch `repos/$REPO/issues/$PR/comments?since=$cutoff` with `--paginate` and the existing
  per-page-array + `jq -s 'add // []'` pattern. `since` filters on `updated_at` and is inclusive,
  which is exactly "created or updated after the cutoff" for the breakdown; Python still enforces
  strict `created_at > cutoff` for the receipt;
- in jq keep Codex-authored comments only, and only `id`, `user.login`, `created_at`, `updated_at`
  and `.body[:2000]`. Both markers and the `Reviewed commit` line sit in the first few hundred
  characters; the slice keeps the `--argjson` argument far below Linux's 128 KiB per-argument limit
  even on a long PR;
- pass the list into the payload as `comments`;
- print the script's stderr breakdown each iteration; at the deadline, print the timeout report
  from Python instead of the hard-coded error.

Cost: one more `gh api` call per 30 s, ~50 per 25-min run — well inside `GITHUB_TOKEN` limits.

The job already has `issues: read`, which covers issue comments; no permission change.

## Tests (first, in `.github/scripts/tests/test_review_gate.py`)

Use a real 40-character hex head SHA for everything that touches prefixes (the current
`HEAD = "head1234"` is not hex). Build the #151 fixture from the real data: head
`a84dae4d57dea301ea163a58897ed55335a5221d`, cutoff `2026-10-21T22:29:55Z`, receipt 6328012482 body
(as quoted above, trimmed to the marker and `Reviewed commit` line is enough) created
`2026-10-21T22:32:32Z`, plus the summary comment 6292793328 with its `codex-review-state:v1` for
`a84dae4d57…` / `completed`, updated `2026-10-21T22:32:35Z`, created `2026-10-20T14:07:41Z`.

`decide`:

- #151-shaped payload — receipt only, no 👍, no review → `pass`;
- receipt for another SHA → `wait`;
- receipt created before the cutoff (and created == cutoff) → `wait`;
- receipt by a non-bot author → `wait`;
- `Reviewed commit` shorter than 7 characters (even if it is a prefix of head) → `wait`;
- marker present, no `Reviewed commit` line → `wait`, no exception;
- `codex-review-receipt:v2` (and `:v10`) with a matching SHA → `wait`;
- summary comment alone, full head SHA, `completed`, updated after the cutoff → `wait`;
- receipt with `created_at: null` → `wait`;
- the existing review / 👍 cases unchanged.

Breakdown and timeout report:

- nothing after the cutoff → the "silent" message;
- only the summary comment updated after the cutoff → the "active but not accepted" message, listing
  it with its markers and state SHA/status;
- a `v2` receipt → listed with its marker;
- a malformed `codex-review-state` JSON → listed by markers, no exception.

CLI:

- `decide` on stdout is still exactly `pass` / `wait` with a `comments` key present **and** absent
  (`TestCli` keeps its `out == "pass"` assertion).

## Documentation to update

- `review_gate.py` module docstring ("Pass requires …", the usage example's payload) and the
  `decide` docstring.
- `_reusable-review-gate.yml` comments that go stale: step 4's "Codex signals via
  reactions/reviews", and the `issues: read # reactions …` permission comment (it now also reads
  issue comments).
- `pr.yml`, the caller's `permissions:` comment ("`issues: read` for reactions on the PR") — the
  same fix, since that block must mirror the reusable workflow's.
- `docs/superpowers/specs/2026-08-01-notification-triggers-design.md`: a short amendment pointing at
  this document where it says `review_gate.py` has "unchanged decision logic" (the Files table) and
  in Part 2's "Wait" step.

## Verification and acceptance

1. **Unit tests** above pass; ruff, `uv run ty check` (pathless) clean.
2. **Local replay against live #151, before merge.** The workflow has no unit tests, so run the new
   jq pipeline locally with `gh api` (read-only) against #151 and pipe the result into
   `review_gate.py decide --cutoff 2026-10-21T22:29:55Z --head-sha a84dae4d57dea301ea163a58897ed55335a5221d`.
   Expected: `pass` on stdout and a breakdown on stderr that names receipt 6328012482 as accepted
   and the summary comment as seen. Then run the timeout report on the same data with the receipt
   filtered out, to see the second message on real input.
3. **This PR's own gate run.** `actions/checkout` takes the PR merge ref, so the fix PR's gate
   already runs the new script.
4. **Unblock #151 after merge** — a manual step, not code. A plain "Re-run job" likely re-runs the
   old script from the original merge ref (unverified), so trigger a fresh `pull_request` event
   instead (edit the PR body, or close/reopen). Precondition: #151 must merge cleanly into the new
   `master` — GitHub builds no merge ref for a conflicting PR, and then no run starts. The
   `codex-nudge` marker keeps cutoff `2026-10-21T22:29:55Z`, so the existing 22:32:32 receipt
   satisfies the new rule without a new Codex round. Expected: the gate goes green within one poll.

## Who decided what

Decided by the owner: the receipt as a third evidence path with both existing paths kept; a
per-poll breakdown and two timeout messages (options 1 + 2); no early failure (option 3 declined);
the summary comment as diagnostics only; unblocking #151 as a manual acceptance step.

Designer's calls (not discussed, settled while writing):

- verdict on stdout, breakdown on stderr — protects the exact-`pass` comparison;
- the receipt marker matched as a whole `v1` HTML comment, so `v2`/`v10` do not count;
- parsing in Python on a 2000-character body slice, instead of SHA extraction in jq as the task
  card suggested;
- fetching with `?since=$cutoff` rather than all comments;
- a receipt created exactly at the cutoff is `wait` (strictly newer, like the other two paths).

## Risks and limitations

- **Codex may change the receipt format.** Then the gate times out again — but now with the second
  message, which lists the comment and its markers. That is the point of Decisions 3 and 4.
- **A 7-character prefix is not a proof.** Two commits sharing a 7–10-character prefix on the same
  PR, with a receipt for the other one created after the current nudge, is not a realistic case;
  accepted.
- **The 2000-character slice** assumes markers and the `Reviewed commit` line stay near the top of
  the body. If Codex moves them down, the receipt is not recognised and the second timeout message
  names the comment — a visible failure, not a silent one.
- **Re-run semantics** (point 4 above) are unverified; the fresh-event route avoids depending on
  them.
