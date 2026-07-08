# Git module: display current-branch PR/MR — design

- **Task:** claude-tools-5dl.20
- **Date:** 2026-07-08
- **Status:** approved (design)
- **Follow-up:** claude-tools-5dl.21 (universal module cache — will later consolidate this cache)

## Context

Claude Code's own UI does not reliably surface the pull/merge request tied to the
current branch. The statuskit git module (`packages/statuskit/src/statuskit/modules/git.py`)
already renders the branch, remote sync state, changes, and last commit; it is the
natural place to also show the branch's PR (GitHub) / MR (GitLab).

The module must work for GitHub (`gh`) and GitLab (`glab`), against both hosted
(github.com / gitlab.com) and self-hosted / Enterprise instances, and must degrade
quietly — a statusline can never block, prompt, or spam the network.

## Goals

- Show the PR/MR associated with the current branch: reference number and state
  (open / draft / merged / closed).
- Support GitHub and GitLab, hosted and self-hosted, via the official CLIs.
- Optionally render the reference as a clickable terminal hyperlink (OSC 8).
- Degrade silently when data is unavailable; explain every negative path in debug.
- Cache lookups so we do not hit the network on every statusline render.

## Non-goals

- No direct REST/token handling — we shell out to `gh`/`glab`, reusing their auth
  and host config (this is what makes self-hosted work for free).
- No interactive prompting or fallback across providers when a choice is explicit.
- No new core caching primitive here — this feature ships its own `PrCache`
  (mirroring `usage_limits`); consolidating both into a shared mechanism is the
  separate follow-up **claude-tools-5dl.21**.

## Display

Rendered on the status line (line 2), immediately **before** the sync indicator —
the PR/MR is a remote/upstream relationship, same family as ahead/behind:

```
main PR #42 ● ↑2 [+3 ~1] a1b2c3d 5m ago
```

Token: `PR #42 ●` (GitHub) / `MR !42 ●` (GitLab) — label + native reference
(`#` for GitHub PRs, `!` for GitLab MRs) + state glyph. The whole token is colored
by state; the glyph is redundant with color on purpose (colorblind-safe):

| State  | Glyph | Color   | GitHub source                    | GitLab source                        |
|--------|-------|---------|----------------------------------|--------------------------------------|
| open   | `●`   | green   | `state=OPEN`, `isDraft=false`    | `state=opened`, `draft=false`        |
| draft  | `○`   | yellow  | `state=OPEN`, `isDraft=true`     | `state=opened`, `draft=true`         |
| merged | `✓`   | magenta | `state=MERGED`                   | `state=merged`                       |
| closed | `✗`   | red     | `state=CLOSED`                   | `state=closed` / `locked`            |

State spread:

```
main PR #42 ● ↑2 [+3 ~1] a1b2c3d 5m ago    ← open, ahead 2
main PR #42 ○ ✓ a1b2c3d 5m ago             ← draft, synced + clean
main MR !42 ✓ ↑1↓3 a1b2c3d 5m ago          ← merged, diverged
main MR !42 ✗ ↓2 a1b2c3d 5m ago            ← closed, behind
```

### Clickable link (OSC 8)

When `pr_link` is on, the **whole token** is wrapped in an OSC 8 hyperlink to the
PR/MR web URL, composed with the state color:

```python
f"\033]8;;{web_url}\a{colored_token}\033]8;;\a"   # BEL terminator, per CC statusline docs
```

The Claude Code statusline officially passes OSC 8 through ("content is rendered
as-is, including ANSI colors and OSC 8 hyperlinks"). Supporting terminals (iTerm2,
Kitty, WezTerm) make it Cmd/Ctrl-clickable; non-supporting terminals (Terminal.app,
etc.) show the same text non-clickable — graceful, no artifacts. Windows Terminal
users may need `FORCE_HYPERLINK=1`; SSH/tmux may strip OSC sequences (both are the
user's environment, out of scope). The URL is already in the fetch JSON (`url` /
`web_url`), so linking costs no extra call.

## Architecture

Extends `GitModule` in `modules/git.py`. No new registered module.

### Params (added to `GitParams`)

| Param           | Type | Default  | Meaning                                             |
|-----------------|------|----------|-----------------------------------------------------|
| `show_pr`       | bool | `true`   | Master toggle for the PR/MR segment.                |
| `pr_provider`   | str  | `"auto"` | `auto` / `github` / `gitlab` — override detection.  |
| `pr_link`       | bool | `true`   | Wrap the token in an OSC 8 hyperlink.               |
| `pr_cache_ttl`  | int  | `90`     | Min seconds between network lookups (throttle).     |

### Methods

- `__init__` override — build a `PrCache` when `ctx.cache_dir` is set (mirrors
  `UsageLimitsModule.__init__`).
- `_get_pr() -> PrInfo | None` — orchestrates gates → provider resolution →
  cached/throttled fetch. Returns a small `PrInfo` (provider, number, state, url)
  or `None`.
- `_resolve_pr_provider(host) -> str | None` — the detection algorithm below;
  result cached per host.
- `_run_cli(provider, *args) -> CliResult` — runs `gh`/`glab`, returns a classified
  outcome (ok+stdout / no-pr / error+reason).
- `_render_pr(info) -> str` — formats label + reference + glyph, applies state
  color, wraps in OSC 8 when `pr_link`.

`_render_status_line` inserts the PR token between the branch and the sync segment.

## Provider detection

Reuses the `flow:review-comments` Phase-0 algorithm
(`plugins/flow/skills/review-comments/SKILL.md`), adapted for a non-interactive
statusline. Cheap gates first (`shutil.which`, no network), resolve in order:

1. `pr_provider` is `github` / `gitlab` → use it (explicit override wins).
2. `auto`: parse host from `git remote get-url origin` (SSH `git@HOST:group/repo.git`
   and HTTPS `https://HOST/group/repo.git`).
   - `github.com` → github; `gitlab.com` → gitlab (literal shortcut, no subprocess).
   - self-hosted / unknown host: match against each installed CLI's authenticated
     hosts (`gh auth status` / `glab auth status`). Host owned by exactly one → that
     provider. This is what makes self-hosted work without config.
   - owned by both → give up (ambiguous). Neither → name heuristic (`github` /
     `gitlab` in host); still nothing → give up.

The resolved provider is cached per host, so `auth status` runs at most once per host.

## Fetch & classification

Fetch with the `list` form so "no PR" is a clean, successful empty result rather
than an error:

- **GitHub:** `gh pr list --head <branch> --state all --json number,state,isDraft,title,url`
- **GitLab:** `glab mr list --source-branch <branch> --output json`
  (fields `iid`, `state`, `draft`/`work_in_progress`, `web_url`). `glab` flags vary
  by version; fall back to `glab api "projects/{id}/merge_requests?source_branch=<branch>"`.

Classification:

| Outcome                         | Meaning                    | Action                          |
|---------------------------------|----------------------------|---------------------------------|
| exit 0, empty list              | no PR/MR (normal)          | no segment; **no error debug**  |
| exit 0, non-empty               | found                      | pick one → render               |
| `TimeoutExpired`                | error                      | degrade + debug (error)         |
| `OSError`                       | binary vanished            | degrade + debug (error)         |
| nonzero exit                    | error (auth/network/etc.)  | degrade + debug (error, stderr) |

Selection when a branch has several (reused/reopened): precedence
**open → draft → merged → closed**, tie-broken by highest number (newest).

## Render flow & degradation

Every branch below degrades **silently** in normal mode. All negative branches log
*why* through the module's `self.debug` channel; "no PR" is logged as normal (not an
error), and `show_pr = false` logs nothing (intentional off).

1. `show_pr = false` → skip. No debug.
2. Branch **local-only** (`remote_status == no_upstream`) → skip; optional trace.
   No `which`, no network for clean local branches.
3. `has_gh`/`has_glab` via `which()`. **Neither → degrade + debug** "neither gh nor
   glab installed". Nothing downstream matters.
4. Resolve provider (above). Ambiguous / both / unknown → degrade + debug.
5. **Require the resolved provider's CLI.** Missing → degrade + debug
   ("<provider> detected/configured for <host> but <cli> not installed"). We never
   cross-fetch (a GitHub PR cannot be fetched by `glab`), and we honor an explicit
   `pr_provider` even if it then fails — we do not second-guess an explicit choice.
6. Fetch + classify (above). No PR → normal; timeout/error → debug error.

Case summary for the tricky combinations:

| Situation                                             | Outcome                                          |
|-------------------------------------------------------|--------------------------------------------------|
| Neither `gh` nor `glab` installed                     | degrade + debug (step 3)                          |
| Only `gh` installed, remote is GitLab                 | resolve gitlab → step 5 degrade + debug          |
| Only `glab` installed, remote is GitHub               | resolve github → step 5 degrade + debug          |
| `pr_provider=gitlab` but `glab` absent                | step 5 degrade + debug                            |
| `pr_provider=github` (explicit) but remote is GitLab  | honor override → fetch fails → debug (stderr)     |
| Self-hosted host authed in both CLIs                  | degrade + debug, ask user to set `pr_provider`    |
| CLI present but not authenticated for host            | fetch nonzero → degrade + debug (stderr)          |
| No PR for the branch (new branch)                     | no segment, normal, no error                      |

## Caching

`PrCache`, following the `usage_limits` `UsageCache` pattern
(`docs/plans/2026-01-27-usage-cache-design.md`):

- File `git_pr.json` in `RenderContext.cache_dir`. Atomic write
  (`tempfile.NamedTemporaryFile` in the cache dir + `Path.replace`), `mkdir(parents=True)`.
  Load returns `None` on missing / `JSONDecodeError` / `KeyError` / `OSError` —
  never raises. Safe under concurrent renders from multiple windows.
- **Refresh-first throttle** keyed on **`host + branch + HEAD sha`**: a commit or a
  branch switch invalidates the entry; otherwise reuse within `pr_cache_ttl`
  (default 90s). On a fetch error, keep any stale value but advance the attempt
  timestamp so the next render still throttles.
- Negative results ("no PR") are cached too, so a fresh branch does not re-query
  every render.
- The resolved provider is cached per host (see detection).

## Config & dependencies

- `[git]` table gains `show_pr`, `pr_provider`, `pr_link`, `pr_cache_ttl`.
- `gh` / `glab` are **optional** dependencies that gate this feature only — document
  them in the statuskit README and CLAUDE.md; the module degrades silently when they
  are absent.

## Testing

Follow existing statuskit patterns (`patch.object(mod, "_run_git")`-style dispatch,
`tmp_path` cache dirs, the `force_color` fixture):

- **Detection:** every branch of the resolution order — override, literal hosts,
  self-hosted via `auth status` (one CLI, both, neither), name heuristic, give-up.
- **Degradation:** each negative path (steps 1–6), asserting silent output and the
  presence/absence of debug messages (error vs normal vs off).
- **Fetch/classify:** no-PR-normal vs timeout/OSError/nonzero-error split; state
  mapping for both providers; multi-PR selection precedence.
- **Rendering:** per-state color and glyph; OSC 8 wrapping on/off.
- **Cache:** round-trip, throttle, invalidation on HEAD/branch change, per-host
  provider cache, atomic-write behavior.

## Debug

Every negative branch emits its reason through the module's existing `self.debug`
channel, distinguishing normal outcomes (no PR, local-only, feature off) from errors
(timeout, no auth, missing CLI, ambiguous provider).
