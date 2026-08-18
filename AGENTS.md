# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd dolt pull          # Pull task changes from the remote
bd dolt push          # Push task changes to the remote
```

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt commit  # flush working set before sync (no-op when auto-commit is on)
   bd dolt pull
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

## Review guidelines

For automated PR review (e.g. Codex). Focus on what CI does NOT catch — logic, security,
design. CI already enforces conventional-commit scope, `ruff` lint/format, and `ty`
type-checking; do not re-report those. Nested `AGENTS.md` (e.g. `packages/statuskit/`,
`plugins/flow/`) adds rules for its subtree.

**Secrets (P0).** Never accept a credential in a diff — `.beads-credential-key` especially.
`.beads/config.yaml`, `.beads/metadata.json`, `.beads/*.port` are per-machine/gitignored;
flag any change that force-adds them to git.

**GitHub Actions security (P1).** For `.github/workflows/` (not mechanically checked):
- `actions/checkout` should set `persist-credentials: false` unless the credential is
  genuinely reused later in the job.
- Any job using repository secrets must guard against fork PRs, e.g.
  `if: github.event.pull_request.head.repo.full_name == github.repository`.
- `permissions:` must be least-privilege — read-only unless a write scope is exercised.
- Never pair `pull_request_target` with a checkout of untrusted PR-head code. (No workflow
  here uses `pull_request_target` any more; the rule stands for anything new.)

**Suppressions (P1).** Flag newly added `# noqa` / `# type: ignore` (or equivalent) without
an inline justification — CI passes *because* the warning is suppressed, so only review
catches it. Policy is fix-don't-suppress.

**Report a recurring class in one pass, whole-file.** Many defects here come in *classes* with
several sibling sites, so reviewing only the changed line surfaces one site per round — five
fix-and-re-review cycles for what is really one class. When you flag an instance of a class like
those below, **sweep the whole file you are reviewing for its other sites and report them
together**, rather than stopping at the first occurrence on the changed line:
- untrusted reviewer data (a file path, a `bd` title/description, a reply body, an applied path)
  inlined into shell command *source* — check every command site; double-quoting a literal does not
  stop `$(...)`/backticks;
- a hard-coded ` ``` ` fence wrapping content that can itself contain a fence — check every emitter;
- a helper invoked bare (`cmd`) that the frontmatter grants only as `Bash(cmd:*)` — cross-check
  every invoked helper against `allowed-tools` for both the bare and `:*` forms;
- a line/offset range computed without a `max(1, …)` clamp — check every range computation for the
  top-of-file (lines 1–4) boundary.

**Do not flag (intentional — treat as non-issues):**
- Actions pinned to `@vN` version tags instead of full commit SHAs — repo prefers readable
  tags.
- Russian-language text in comments, docs, commits, or PR descriptions — bilingual repo.
- Anything CI already enforces: commit/PR scope, `ruff` lint/format, `ty` types.
- `pr.yml`'s jobs holding `statuses: write`, `CODEX_NUDGE_TOKEN` and the Telegram credentials
  while running PR-authored code. This is a deliberate, documented trade-off, not an oversight:
  the gate had to move onto `pull_request` so it could be tested before merge, same-repo PRs come
  only from trusted developers, and fork PRs never reach these jobs. See
  `docs/superpowers/specs/2026-08-01-notification-triggers-design.md`, "Accepted trade-off".
- A PR being able to edit the workflow that gates it. Accepted for the same reason, and visible in
  the workflow diff during review.

