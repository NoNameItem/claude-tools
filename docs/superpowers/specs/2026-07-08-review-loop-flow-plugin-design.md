# Generalize review-loop and move it into the flow plugin — Design Spec

**Date:** 2026-07-08
**Task:** `claude-tools-elf.25` (Generalize review-loop and move it into the flow plugin — research + implementation)
**Status:** agreed in brainstorming, ready for planning
**Predecessors:** [`2026-07-03-review-loop-skill-design.md`](2026-07-03-review-loop-skill-design.md) (original skill), [`2026-07-06-review-loop-redesign-design.md`](2026-07-06-review-loop-redesign-design.md) (push-based convergence — the basis for this design)

## Goal

Today `review-loop` lives as a **project skill** in `.claude/skills/review-loop/` and is hard-wired to claude-tools:

- the `wait_for_checks.py` helper hardcodes two anchors — `ANCHOR_CHECK_RUN = "claude-review"`, `ANCHOR_STATUS = "review-gate"`;
- it is invoked by the absolute path `${CLAUDE_SKILL_DIR}/bin/wait_for_checks.py`;
- GitHub-only (`gh`), even though `flow:review-comments` is already cross-platform (GitHub + GitLab);
- `DEFAULT_WAIT_TIMEOUT` is hard-coupled to `review-gate.yml` (§8 of the previous design).

The goal is to **generalize the skill (drop every binding to gate names, paths, platform) and move it into the flow plugin** as `/flow:review-loop`, mirroring the other flow skills. Task DoD: record the feasibility decision; on a positive outcome — a working `/flow:review-loop` in `plugins/flow/skills/` with no hardcoded paths.

**Feasibility verdict: positive.** The loop control-flow (redesign 2026-07-06) is already platform-agnostic — convergence is decided by the fact of a push (`HEAD_after` vs `HEAD_before`), not by counting threads. The only genuinely project-coupled piece is the **anchor mechanism** in `wait_for_checks.py`, and it can be replaced with a name-agnostic signal. Generalization is real → we implement it.

## §0 Research: event subscription vs polling

Part of the task is to check whether timeout-based polling can be replaced with event subscription. Two studies were run (GitHub and GitLab). Result:

| | GitHub | GitLab |
|---|---|---|
| Push channel without your own server | **None at all** | **Exists** — GraphQL subscriptions over ActionCable (`wss://<host>/-/cable`), PAT auth |
| Usable as the wait backbone? | — | **No** |
| Why | Webhooks need a public HTTP receiver; no GraphQL subscriptions; no SSE/stream for check events; Events API is poll-only, 30 s–6 h latency, carries no `check_run`/`status` | The `ciPipelineStatusUpdated(pipelineId:)` subscription requires an **already-existing** pipeline GID → it cannot observe pipeline creation; the subscription itself is WIP/internal with no stability guarantee |

**Decision: polling is the backbone on both platforms.** The GitLab subscription is recorded as a possible future optimization (saving on the second half — terminal detection — once the pipeline is already discovered), but we do not build it in v1: a hand-rolled ActionCable protocol + an unstable API do not pay off.

Delegating the wait to a CLI (`gh pr checks --watch`, `glab ci status --live`) was also evaluated: both lose the SHA pin and cannot survive the materialization race (`gh` exits immediately with "no checks" on a fresh head — cli/cli#7401, closed as not planned; `glab` follows the branch head with no `--sha` and does not wait for a not-yet-created pipeline). That is a regression of exactly the robustness the helper was built for. Rejected — we keep our own poller.

## §1 What is coupled today, and what we generalize

| Piece | Current binding | Generalization |
|---|---|---|
| Anchors `claude-review` / `review-gate` in `wait_for_checks.py` | hardcoded gate names | replace with a name-agnostic materialization signal (§3) |
| `${CLAUDE_SKILL_DIR}/bin/wait_for_checks.py` | project-skill path | move to `plugins/flow/bin/flow-wait-ci`, call by bare name |
| GitHub-only (`gh`) | one platform | add a GitLab backend (`glab`); the skill is cross-platform (§5) |
| `DEFAULT_WAIT_TIMEOUT` ↔ `review-gate.yml` | hard coupling invariant | a generalized "generous default" + graceful degradation to interactive `exit 2` (§4) |
| SKILL description/body with claude-tools names | skill text | generic rewrite |
| `flow:review-comments` | already a flow skill, cross-platform | reused verbatim, untouched |

## §2 Architecture

**Approach: one platform-agnostic skill + one wait helper with two backends.**

```
plugins/flow/
├─ skills/review-loop/SKILL.md         # /flow:review-loop — generic loop, no repo/gate/platform names
└─ bin/
   ├─ flow-wait-ci                      # single CLI, backend selected by --platform
   └─ tests/test_flow_wait_ci.py        # state-machine tests for both backends
```

- **Skill** is platform-agnostic: it resolves the platform and the PR/MR via Phase 0/1 of `review-comments`, runs the loop, calls `flow-wait-ci` by bare name and `flow:review-comments` via the **Skill** tool.
- **`flow-wait-ci`** hides the platform differences behind a single exit-code contract. Inside — a GitHub backend (`gh api graphql`) and a GitLab backend (`glab api`).
- **Platform detection is not duplicated**: the skill resolves `PLATFORM` (review-comments Phase 0 algorithm) and passes `--platform` to the helper.

**Rejected alternatives:** delegating to `gh/glab --watch` (§0, robustness regression); two separate helpers `…-github`/`…-gitlab` (duplicates the argument/exit-code/head-moved scaffolding and blurs the single contract).

## §3 `flow-wait-ci` — contract and algorithm

### CLI

```
flow-wait-ci <PR/MR-number> <sha> --platform <github|gitlab>
```

The helper derives the repo/project identifier itself (`gh repo view --json nameWithOwner` / URL-encoded project path from the remote), as the current `_repo()` does.

### Exit codes

| Code | Meaning | Skill's reaction |
|---|---|---|
| `0` | pipeline materialized and terminal; stdout has one line per check `<name> <conclusion/status>` | normal path: red-gate → review-comments |
| `2` | timeout (deadline before terminal) | plain-text prompt: wait more / process now (round PARTIAL) / stop |
| `3` | head moved during the wait | re-capture `HEAD_before`, wait again |
| `4` | **(new)** after the grace window there are no checks/pipeline at all | "no CI/bots on this PR — nothing to ride", stop with an explanation |
| `1` | usage error | a call bug; fix the call (do not treat as timeout) |

Codes `0/1/2/3` keep the semantics of the current `wait_for_checks.py`. `4` is a generalization beyond claude-tools: an arbitrary repo's PR may have no CI/bots, and a silent "clean convergence" would lie ("bots have nothing to say" ≠ "there are no bots").

`failed` (for the red-gate and to color the final report) is computed by the **skill** from `exit 0` stdout, as today: a check "failed" if its conclusion/status is not in the "green" list (GitHub: not in `{success, neutral, skipped}`; GitLab: not in `{success, skipped, manual, scheduled}` — i.e. only `failed`/`canceled` count as red, while the blocking `manual`/`scheduled` do not trip the red-gate).

### GitHub backend

A single poll reads by `sha` (name-agnostic, via `*CountsByState` — no name enumeration):

```graphql
query($owner:String!, $repo:String!, $pr:Int!, $sha:GitObjectID!) {
  repository(owner:$owner, name:$repo) {
    pullRequest(number:$pr) { mergeStateStatus headRefOid }
    object(oid:$sha) { ... on Commit { statusCheckRollup {
      state
      contexts(first:100) {
        checkRunCount    checkRunCountsByState    { state count }
        statusContextCount statusContextCountsByState { state count }
        nodes {
          __typename
          ... on CheckRun     { name status conclusion }
          ... on StatusContext { context state }
        }
      }
    }}}
  }
}
```

**"Not yet materialized, keep waiting" if any of:**
- `mergeStateStatus == UNKNOWN` (GitHub is still computing mergeability);
- `statusCheckRollup == null` **and** the grace window has not elapsed (fresh head, nothing registered);
- `rollup.state == EXPECTED` (a required context exists but has not reported yet);
- `checkRunCountsByState` has a non-terminal state `{QUEUED, IN_PROGRESS, PENDING, WAITING, REQUESTED}`;
- `statusContextCountsByState` has `{PENDING, EXPECTED}`.

**Terminal** — when none of the above holds **and** the counts match the previous poll (stability window). Then: re-check `pullRequest.headRefOid` != `sha` → `exit 3`; otherwise print `nodes` and `exit 0`. If `rollup == null`/empty and the grace window elapsed → `exit 4`.

Why the dual signal (rollup + stability): research showed `EXPECTED` is reliable only for required **status contexts**, but **not** for a missing required **check-run** (a renamed / filter-skipped / matrix-mismatch job → the rollup can read `SUCCESS` while the PR is actually blocked). So rollup/`mergeStateStatus` is a strengthening for gated repos (claude-tools' required gates `claude-review`/`review-gate` are picked up **automatically**), while the **stability window** is the universal base: it covers the empty start, late-registering checks, and repos with no required checks at all (where the rollup can be `null`).

### GitLab backend

A poll reads the MR head pipeline (a single authoritative status — unlike GitHub's N independent checks):

```graphql
query($fullPath:ID!, $iid:String!) {
  project(fullPath:$fullPath) { mergeRequest(iid:$iid) {
    headPipeline { id sha status }   # SUCCESS/FAILED/CANCELED/SKIPPED/MANUAL/RUNNING/...
    detailedMergeStatus
    diffHeadSha
  }}
}
```
(or REST: `glab api "projects/:id/pipelines?sha=<sha>&order_by=id&sort=desc"` — with multiple pipelines per SHA, take the MR `head_pipeline` or the newest by `id`.)

**"Keep waiting" if:** no pipeline for `sha` yet and the grace window has not elapsed; or the status is active `{created, waiting_for_resource, preparing, pending, running}`.
**Terminal:** `{success, failed, canceled, skipped}` + the blocking `{manual, scheduled}` (waiting forever is wrong). Print the failed jobs (`glab api projects/:id/pipelines/:pid/jobs`, `status=failed` and `allow_failure=false`). Re-check the MR head sha (`diffHeadSha`) != `sha` → `exit 3`. Grace elapsed with no pipeline → `exit 4`.

**GitLab gotchas (handle in the implementation):** merge-request/detached pipelines run on `refs/merge-requests/:iid/head` (ref ≠ branch) → filter by **`sha`**/`head_pipeline`, not by ref; `workflow:rules` may never create a pipeline → grace window and `exit 4`; `manual`/blocked will never reach `success` → terminal-for-waiting.

## §4 Interval and timeout defaults

Zero new env knobs are exposed (deliberately: we do not resurrect "per-repo config"). The stability window is derived from the interval; grace is a baked-in constant.

| Parameter | Value | Rationale |
|---|---|---|
| `WAIT_INTERVAL` (poll cadence) | **30 s** | the pipeline runs for minutes — the granularity is invisible and gentle on rate limits; a rollup GraphQL query is cheap (~1 point of 5000/hour). The current, proven value |
| `WAIT_TIMEOUT` (deadline → `exit 2`) | **1800 s / 30 min** | not "give up" but "check in with the human" via interactive `exit 2`; generous yet finite. Covers heavy pipelines; anything longer is caught by the prompt |
| Grace for emptiness → `exit 4` | **180 s / 3 min** (monotonic, independent of the interval) | absorbs slow pipeline creation under load; only bites when there genuinely is no CI (a rare one-off) |
| Stability window | **1 interval (30 s)** | derived: two consecutive polls with identical counts = stable; adds +30 s to finish detection, invisible against minutes |

`WAIT_INTERVAL` / `WAIT_TIMEOUT` remain **only as a test seam** (tests set them to 0/small for fast runs, as today), not a user config surface. An under-estimated timeout never yields a wrong result — it degrades to `exit 2`. The hard coupling invariant with `review-gate.yml` (§8 of the previous design) is dropped: one line remains — "the default is generous; if the pipeline runs longer, the timeout prompt fires".

## §5 Skill `/flow:review-loop`

The control-flow **does not change** relative to redesign 2026-07-06 (§2/§3 of that design) — it is already platform-agnostic (push-based convergence):

```
0. Resolve platform + PR/MR   → Phase 0 (detect) and Phase 1 (resolve) from review-comments
1. Iteration:
   a. HEAD_before             → gh: pr headRefOid / glab: MR .sha
   b. closed/merged?          → stop
   c. flow-wait-ci            → 0 / 2 (plain-text prompt) / 3 (re-capture) / 4 (no CI → stop)
   d. red-gate                → failed non-empty → plain-text "run anyway / stop"
   e. flow:review-comments    → verbatim, via the Skill tool (already cross-platform)
   f. HEAD_after
   g. convergence by push      → push→loop; no push→stop + warn about unpushed local commits
```

**What changes in SKILL.md vs the current project skill:**
- drop all names `claude-tools`/`claude-review`/`review-gate` — the description and body become generic;
- cross-platform: everywhere "PR/MR", branches/SHA/head per platform (as in review-comments);
- call `flow-wait-ci` by bare name instead of `${CLAUDE_SKILL_DIR}/bin/wait_for_checks.py`;
- handle the new `exit 4`;
- `allowed-tools:` `Skill(flow:review-comments) Bash(gh:*) Bash(glab:*) Bash(git:*) Bash(flow-wait-ci:*) Read`.

**Preserved:** timeout-PARTIAL (`exit 2`), head-moved restart (`exit 3`), red-gate (d), the unpushed check (`git rev-parse HEAD` vs `HEAD_after`), the round indicator + `повторно`/`repeat` tracking (in-session, from review-comments output), interactivity instead of a hard cap, reply-only (resolving threads and merging stay with the human).

**Terminators:** clean convergence (g) · partial hand-off (g) · red-check hand-off (g) · **no CI (`exit 4`, c)** · PR/MR merged/closed (b) · user "stop" at the timeout prompt (c) · user "stop" at the red-gate (d) · user "no" at review-comments Phase 3 · user Esc.

## §6 Migration

**Remove** (project skill): all of `.claude/skills/review-loop/` — `SKILL.md`, `bin/wait_for_checks.py`, `bin/tests/`.

**Create** (plugin): `plugins/flow/skills/review-loop/SKILL.md`, `plugins/flow/bin/flow-wait-ci`, `plugins/flow/bin/tests/test_flow_wait_ci.py`.

**Update:**
- `plugins/flow/README.md` — the skills list (+ `/flow:review-loop`) and the bin-helpers list (+ `flow-wait-ci`; the "bin/ helpers" section).
- `plugins/flow/CHANGELOG.md` — an entry for the new skill.
- `pyproject.toml` `[tool.ruff] extend-include` — already covers `plugins/flow/bin/flow-*` via the glob; `flow-wait-ci` is included automatically.
- Plugin version — bump via release-please: `feat(flow)` → minor (3.0.0 → 3.1.0). `plugin.json` does not list skills (auto-discovery), so no manual edit there.
- `.github/workflows/review-gate.yml` — **untouched** (it is a separate claude-tools-specific gate; the helper is no longer bound to its name).

**Scope/label:** changes only in `plugins/flow/` + `docs/` → single-package-commit is satisfied; commits with scope `(flow)`, label `flow`. `docs/` + one project = one commit with that project's scope (the hook only fails on 2+ packages).

**Dogfooding:** the `.claude/skills/` skill is visible only in this repo on a merged branch; the plugin `/flow:review-loop` becomes available wherever flow is installed. On a feature branch, before merge, the plugin skill is not visible to a main-dir session (on `master`) — test from a fresh session inside the worktree or via a temporary symlink into `~/.claude/skills/`.

## §7 Testing

- **`flow-wait-ci`** → `plugins/flow/bin/tests/test_flow_wait_ci.py`. Stub `gh`/`glab` (as the current `wait_for_checks.py` test stubs `gh`), driving the state machine through scenarios for **both** backends: materialize→terminal; empty start (rollup null / no pipeline) → wait → `exit 4` after grace; `EXPECTED`/pending → wait → terminal; stability window (counts "jitter" → wait; matched → terminal); `exit 2` (timeout); `exit 3` (head-moved); `exit 1` (usage). GitLab specifics: multiple pipelines per SHA (take head/newest), `manual`/blocked as terminal, detached ref matched by `sha`. The plugin CI runs `bin/tests/` on every PR.
- **SKILL.md** (behavioral) → `writing-skills` RED→GREEN + a dogfood skeptic. Baseline on the current project-skill text, GREEN on the generic plugin one. Scenarios: generic description with no claude-tools names; cross-platform branches (gh/glab); `flow-wait-ci` called by bare name; handling `exit 4` (no CI → stop with an explanation); preserved push→loop / timeout-PARTIAL / head-moved / red-gate / unpushed warning.
- **review-comments** — **unchanged** (reused verbatim); nothing to test.

## §8 Accepted limitations and future work

- **GitLab event subscription** (§0) — real (PAT-authenticated ActionCable), but not built in v1: it cannot see materialization + the API is WIP. Recorded as a possible future optimization of terminal detection.
- **GitHub `EXPECTED` does not cover a missing required check-run** (§3) — compensated by the stability window; a strict "required-but-no-node" check would need parsing the rulesets endpoint (`repos/…/rules/branches/…`), not done in v1 (YAGNI; stability covers the practical cases).
- **`exit 4` "no CI"** is based on the grace timeout (3 min) — under extremely slow pipeline creation a false `exit 4` is possible; the cost is a one-off restart. Acceptable trade-off.
- The push-based convergence limitations from redesign 2026-07-06 §10 (does not distinguish "silence" from reply-only in the final text; a resolved-but-bot-last thread until elf.24) are **inherited unchanged**.

## §9 Proposed decomposition (for `/flow:decompose`)

The task is large — after the spec is approved, split into subtasks:

1. **`flow-wait-ci` GitHub backend + tests** — port `wait_for_checks.py` onto the name-agnostic signal (rollup + stability + `mergeStateStatus`), `exit 4`, move into `plugins/flow/bin/`.
2. **`flow-wait-ci` GitLab backend + tests** — head pipeline, grace, the detached/workflow-rules/manual gotchas.
3. **Generic SKILL `/flow:review-loop`** — rewrite without names, cross-platform, bare-name call, `exit 4`; RED→GREEN.
4. **Migration + docs** — remove the project skill, README/CHANGELOG, version.

Dependencies: 3 depends on 1 (the helper contract); 2 can run in parallel with 1; 4 goes last.

## Sources (research §0/§3)

- GitHub GraphQL schema (`StatusState.EXPECTED`, `StatusCheckRollup`, `*CountsByState`, `RequirableByPullRequest.isRequired`, `MergeStateStatus`): https://docs.github.com/en/graphql/reference/enums , https://docs.github.com/en/graphql/reference/objects
- GitHub REST combined status / check-runs (only reported ones, no "expected"): https://docs.github.com/en/rest/commits/statuses , https://docs.github.com/en/rest/checks/runs
- GitHub rulesets (`Get rules for a branch`, Metadata:read): https://docs.github.com/en/rest/repos/rules
- `gh pr checks --watch` "no checks" race (cli/cli#7401, closed as not planned): https://github.com/cli/cli/issues/7401
- GitHub Events API (poll-only, no check events): https://docs.github.com/en/rest/activity/events
- GitLab Pipelines API (`sha`, status enum, `latest`): https://docs.gitlab.com/api/pipelines/ ; Commits (`last_pipeline`): https://docs.gitlab.com/api/commits/
- GitLab MR pipelines / detached / `workflow:rules`: https://docs.gitlab.com/ci/pipelines/merge_request_pipelines/
- GitLab GraphQL subscriptions (WIP; ActionCable bearer auth; `ciPipelineStatusUpdated` needs a pipeline GID): https://docs.gitlab.com/development/real_time/ ; https://gitlab.com/gitlab-org/gitlab/-/raw/master/app/graphql/subscriptions/ci/pipelines/status_updated.rb
- GitLab MR discussions/notes (the inline-comment analog): https://docs.gitlab.com/api/discussions/
