# Review-Comments Card Emission Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Phase 4.2 card of `flow:review-comments` impossible to silently omit, and bound an oversized `diff_hunk` in the helper so the skill never has to decide how much of it to show.

**Architecture:** Two independent changes. (1) `flow-comment-card` caps a long `diff_hunk` at render time — the `@@` header, a `… N lines omitted …` marker, and the last `MAX_HUNK_BODY_LINES` lines, because a GitHub `diff_hunk` always ends at the commented line. Verified against the code: GitLab rows carry `diff_hunk: None` (the collector attaches a bounded `snippet` instead), so the cap only ever touches GitHub hunks; and Phase 3 reads single-row extracts from `flow-review-ledger get`, never the card, so analysis keeps the full hunk. (2) `SKILL.md` Phase 4.2 states the per-card reply as a two-part **contract** (card stdout verbatim, then the decision prompt) rather than as a reminder, with Red Flags / Common Rationalizations rows as secondary defence.

**Tech Stack:** Python 3.9-compatible stdlib helpers in `plugins/flow/bin/`, pytest (`plugins/flow/bin/tests/`), ruff, ty, markdown skill documents.

**Spec:** beads task `claude-tools-elf.45` (`bd show claude-tools-elf.45`) — problem statement, the PR #113 incident, and the acceptance criteria. The design was agreed in chat on 2026-08-30 and is reproduced in full in this plan; there is no separate spec file.

## Global Constraints

- Helpers in `plugins/flow/bin/` are stdlib-only and **Python 3.9-compatible** — `from __future__ import annotations` is already imported, so `X | Y` is allowed in annotations only, never at runtime.
- Helper output is **English** (matches `flow-task-card`, `flow-task-tree`); the marker string is English too.
- Before every commit touching Python: `uv run ruff format <files>`, `uv run ruff check --fix <files>`, then `uv run ty check` **pathless** (whole project).
- Plugin tests are not in `testpaths` yet (`claude-tools-5vg.26`), so run them explicitly: `uv run pytest plugins/flow/bin/tests`.
- Commit titles use the `flow` scope: `fix(flow): …`. PR label `flow`.
- No `git commit --amend`, no force-push. `git push` only after explicit confirmation from the user.
- Any linter suppression needs an inline reason; the existing `# ruff: noqa: INP001` line at the top of the test file already carries one — do not add new suppressions.
- The skill edit in Task 2 goes through **superpowers:writing-skills**, whose Iron Law applies: a baseline (RED) pressure run before the edit, a verification (GREEN) run after it.

---

### Task 1: Cap an oversized `diff_hunk` in `flow-comment-card`

**Files:**
- Modify: `plugins/flow/bin/flow-comment-card` (constants near `CATEGORY_EMOJI`:24-32; `render_code`:119-135)
- Test: `plugins/flow/bin/tests/test_flow_comment_card.py` (add to `class TestRenderCode`:172)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `MAX_HUNK_BODY_LINES: int = 40` and `cap_diff_hunk(diff_hunk: str) -> str` in module `flow_comment_card`; `render_code` applies the cap before fencing. Task 2's SKILL.md wording quotes the cap shape (header + `… N lines omitted …` marker + last 40 lines) and must match this behaviour exactly.

- [ ] **Step 1: Write the failing tests**

Append to `plugins/flow/bin/tests/test_flow_comment_card.py` inside `class TestRenderCode` (keep the existing tests above it), and add `cap_diff_hunk = _mod.cap_diff_hunk` next to the other `_mod` bindings at the top of the file:

```python
    def test_hunk_shorter_than_the_cap_is_untouched(self):
        hunk = "@@ -1,3 +1,3 @@\n-old\n+new"
        assert render_code({"diff_hunk": hunk}) == f"```diff\n{hunk}\n```"

    def test_hunk_exactly_at_the_cap_is_untouched(self):
        body = [f"+line {i}" for i in range(40)]
        hunk = "\n".join(["@@ -1,40 +1,40 @@", *body])
        assert cap_diff_hunk(hunk) == hunk

    def test_long_hunk_keeps_header_marker_and_tail(self):
        body = [f"+line {i}" for i in range(44)]
        hunk = "\n".join(["@@ -1,44 +1,44 @@", *body])
        capped = cap_diff_hunk(hunk).split("\n")
        assert capped[0] == "@@ -1,44 +1,44 @@"
        assert capped[1] == (
            "… 4 lines omitted — hunk capped to the last 40 lines "
            "(the comment anchors to the last line) …"
        )
        assert capped[2] == "+line 4"  # the first four body lines are gone
        assert capped[-1] == "+line 43"  # the anchored line survives
        assert len(capped) == 42  # header + marker + 40 body lines

    def test_long_hunk_without_a_header_still_caps(self):
        body = [f"+line {i}" for i in range(41)]
        capped = cap_diff_hunk("\n".join(body)).split("\n")
        assert capped[0] == (
            "… 1 line omitted — hunk capped to the last 40 lines "
            "(the comment anchors to the last line) …"
        )
        assert capped[-1] == "+line 40"
        assert len(capped) == 41  # marker + 40 body lines

    def test_render_code_caps_the_hunk_it_fences(self):
        hunk = "\n".join(["@@ -1,50 +1,50 @@", *[f"+line {i}" for i in range(50)]])
        rendered = render_code({"diff_hunk": hunk})
        assert "lines omitted" in rendered
        assert "+line 0" not in rendered
        assert "+line 49" in rendered

    def test_snippet_is_never_capped(self):
        text = "\n".join(f"line {i}" for i in range(60))
        rendered = render_code({"diff_hunk": None, "snippet": {"lang": "python", "text": text}})
        assert "lines omitted" not in rendered
        assert "line 0" in rendered
        assert "line 59" in rendered
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest plugins/flow/bin/tests/test_flow_comment_card.py -k "cap or omitted or snippet_is_never" -v
```

Expected: collection error / FAIL — `AttributeError: module 'flow_comment_card' has no attribute 'cap_diff_hunk'`.

- [ ] **Step 3: Implement the cap**

In `plugins/flow/bin/flow-comment-card`, add the constant below `FALLBACK_EMOJI = "⚪"` (line 32):

```python
# A GitHub `diff_hunk` can be the entire new file (444 lines on PR #113). The comment always
# anchors to the LAST line of the hunk, so the tail is the part worth showing: cap the body and
# say how much was dropped. Display-only — the ledger row and the Phase 3 subagents keep the
# full hunk.
MAX_HUNK_BODY_LINES = 40
```

Add the function directly above `render_code`:

```python
def cap_diff_hunk(diff_hunk: str) -> str:
    """Return the hunk with its body capped to the last MAX_HUNK_BODY_LINES lines.

    The `@@` header (when present) is kept as the coordinate anchor, followed by a marker
    line naming how many lines were dropped. A hunk at or below the cap is returned unchanged.
    """
    lines = diff_hunk.split("\n")
    header = []
    body = lines
    if lines and lines[0].startswith("@@"):
        header = [lines[0]]
        body = lines[1:]
    if len(body) <= MAX_HUNK_BODY_LINES:
        return diff_hunk
    omitted = len(body) - MAX_HUNK_BODY_LINES
    noun = "line" if omitted == 1 else "lines"
    marker = (
        f"… {omitted} {noun} omitted — hunk capped to the last {MAX_HUNK_BODY_LINES} lines "
        "(the comment anchors to the last line) …"
    )
    return "\n".join([*header, marker, *body[-MAX_HUNK_BODY_LINES:]])
```

Then change the `diff_hunk` branch of `render_code` (currently lines 125-128) to cap **before** fencing, so the fence width is computed from what is actually printed:

```python
    diff_hunk = card.get("diff_hunk")
    if diff_hunk:
        diff_hunk = cap_diff_hunk(diff_hunk)
        fence = _fence(diff_hunk)
        return f"{fence}diff\n{diff_hunk}\n{fence}"
```

Extend the `render_code` docstring's first line to mention the cap:

```python
    """diff_hunk (capped to its last MAX_HUNK_BODY_LINES lines) as a fenced ```diff block;
    else snippet as a fenced ```{lang} block; else ''.
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest plugins/flow/bin/tests/test_flow_comment_card.py -v
```

Expected: PASS, including every pre-existing test in the file (the short-hunk cases must stay byte-identical).

- [ ] **Step 5: Run the whole plugin test suite, lint and type check**

```bash
uv run pytest plugins/flow/bin/tests
uv run ruff format plugins/flow/bin/flow-comment-card plugins/flow/bin/tests/test_flow_comment_card.py
uv run ruff check --fix plugins/flow/bin/flow-comment-card plugins/flow/bin/tests/test_flow_comment_card.py
uv run ty check
```

Expected: all tests pass, ruff reports no remaining issues, ty reports no errors.

- [ ] **Step 6: Commit**

```bash
git add plugins/flow/bin/flow-comment-card plugins/flow/bin/tests/test_flow_comment_card.py
git commit -m "fix(flow): cap an oversized diff_hunk in flow-comment-card"
```

---

### Task 2: Make the Phase 4.2 card emission non-skippable in `SKILL.md`

**Files:**
- Modify: `plugins/flow/skills/review-comments/SKILL.md` (Phase 4.2 at :440-470; `## Red Flags - STOP` at :1119; `## Common Rationalizations` at :1151)
- Test: pressure scenarios run through subagents (no file) — fixtures under the session scratchpad

**Interfaces:**
- Consumes: `cap_diff_hunk` behaviour from Task 1 — the wording states the cap shape (header + `… N lines omitted …` + last 40 lines) and must not describe anything Task 1 does not do.
- Produces: no code. The skill contract other phases rely on is unchanged.

- [ ] **Step 1: Invoke the writing-skills skill**

```
Skill(superpowers:writing-skills)
```

Its Iron Law governs this task: **no skill edit without a failing test first.** The relevant classification from its "Match the Form to the Failure" table is *"Omits a required element from something they already produce" → structural: a REQUIRED slot in the template they fill in*, **not** prose reminders near the template. That is why Step 4 below writes a two-part reply contract and keeps the Red Flags rows as secondary defence only.

- [ ] **Step 2: Build the pressure-test fixture**

Write the fixture into the session scratchpad (not the repo) — a ledger with one row whose `diff_hunk` is a whole 444-line new file, plus a verdict:

```bash
FIX="$(mktemp -d)/elf45"; mkdir -p "$FIX"   # scratch only — never inside the repo
uv run python - "$FIX" <<'PY'
import json, sys
from pathlib import Path

fix = Path(sys.argv[1])
hunk = "\n".join(["@@ -0,0 +1,444 @@"] + [f"+    line {i} of the new file" for i in range(444)])
# `rows` is a DICT keyed by thread key — `_ledger.find_row_by_ref` iterates `rows.values()`,
# and `_structure_is_sound` rejects a list, which would degrade the file to an empty ledger and
# make the helper exit 1 with "ref 'C1' not found".
ledger = {
    "schema": 1,
    "unit": {"platform": "github", "repo": "NoNameItem/claude-tools", "number": 113},
    "round": 1,
    "next_ref": {"U": 1, "C": 2},
    "rows": {
        "comment:1": {
            "ref": "C1",
            "kind": "inline",
            "user": "coderabbitai",
            "is_bot": True,
            "body": "This helper reads the file twice; hoist the read out of the loop.",
            "path": "plugins/flow/bin/flow-review-collect",
            "line": 444,
            "start_line": None,
            "outdated": False,
            "diff_hunk": hunk,
            "snippet": None,
            "thread": [],
            "status": "open",
        }
    },
}
(fix / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
(fix / "verdict-C1.json").write_text(
    json.dumps(
        {
            "category": "correctness",
            "thought": "The read is inside the loop; hoisting it is a real improvement.",
            "suggested": "fix",
        }
    ),
    encoding="utf-8",
)
print(fix)
PY
```

Verify the helper renders a capped card against it before testing any agent:

```bash
flow-comment-card --ledger "$FIX/ledger.json" --ref C1 --verdict "$FIX/verdict-C1.json" | head -8
```

Expected: the header line, the blockquote, then the `@@` header, the `… 404 lines omitted …` marker and the tail.

- [ ] **Step 3: RED — baseline run against the CURRENT wording**

Dispatch **two** independent general-purpose subagents with this prompt (paste the CURRENT Phase 4.2 text — extract it with `awk '/^#### 4\.2\./,/^\*\*Decision invariants/' plugins/flow/skills/review-comments/SKILL.md` — where the placeholder says so):

```
You are running Phase 4.2 of the flow:review-comments skill. Your final report IS your reply to
the user — the user reads nothing else from you, no tool results.

<phase-4.2>
[paste the current Phase 4.2 text verbatim]
</phase-4.2>

The ledger is at <FIX>/ledger.json and the verdict at <FIX>/verdict-C1.json.
Do Phase 4.2 for ref C1 and stop.
```

Record for each run: did the report contain the card body (the `### 🔴 C1 · correctness · …` header AND the fenced diff)? Note the exact rationalization when it did not.

Expected baseline: at least one run asks the decision question without carrying the card into the report — the PR #113 failure. If **both** runs emit it, keep the scenario but add pressure (a second, longer comment in the ledger; an instruction that the user is in a hurry) until the failure reproduces; a skill edit with no observed failure is not testable.

- [ ] **Step 4: GREEN — write the reply contract into Phase 4.2**

In `plugins/flow/skills/review-comments/SKILL.md`, insert this block immediately **after** the paragraph ending "…is ever assembled into a shell command (untrusted-data rule)." and **before** the `**⚠️ NO OUTER FENCE…` paragraph (emit-at-all comes before how-to-emit):

```markdown
**The reply that carries this card has exactly two parts, in this order:**

1. the helper's stdout, copied **verbatim** — every line it printed, from the `### ` header to
   the last line of the take;
2. the decision prompt below.

Nothing goes between them, and nothing replaces part 1. Running the helper is not showing the
card: a Bash tool result is visible to **you**, and the user reads only your reply. If the
helper printed a card and your reply does not carry it, the card was never shown — that is the
PR #113 failure this contract exists to prevent.

Part 1 is copied whole at any size. `flow-comment-card` already caps an oversized `diff_hunk`
itself — it keeps the `@@` header, prints a `… N lines omitted …` marker, and shows the last 40
lines, where the comment anchors — so its stdout is always the whole card. You never shorten,
window, or summarize it.
```

- [ ] **Step 5: Add the Red Flags and Common Rationalizations rows**

In `## Red Flags - STOP`, directly **above** the existing `- "I'll wrap the card in a ``` fence…` bullet (omission comes before formatting):

```markdown
- "The card is in the tool output, the user can see it" → They cannot. The user reads your reply, never a tool result. Copy the helper's stdout into the reply, in full.
- "This hunk is hundreds of lines, I'll show just the relevant part" → `flow-comment-card` already capped it. Emit exactly what it printed.
```

In `## Common Rationalizations`, directly **above** the existing `| "Wrap the card in a fence for clarity" |` row:

```markdown
| "I ran the helper, so the card is shown" | Running it rendered the card for YOU. The user sees only your reply — copy stdout into it verbatim, every line. |
| "The hunk is huge, I'll trim it to the relevant lines" | The helper caps oversized hunks itself (header + `… N lines omitted …` + last 40 lines). Trimming further only removes what the user was meant to see. |
```

- [ ] **Step 6: GREEN — re-run the same scenario against the edited wording**

Dispatch two fresh subagents with the identical prompt from Step 3, pasting the **edited** Phase 4.2 text instead.

Expected: both reports contain the full card (header, blockquote, fenced diff with the `… 404 lines omitted …` marker, `**Thought:**` / `**Suggested:**`) followed by the decision prompt.

If a run still omits or trims the card, REFACTOR: add the exact rationalization it used as a new Common Rationalizations row, tighten the contract wording, and re-run Step 6. Do not proceed with a failing scenario.

- [ ] **Step 7: Check the skill still parses and reads correctly**

```bash
uv run python .github/scripts/validate_plugin.py plugins/flow
grep -n "exactly two parts\|lines omitted" plugins/flow/skills/review-comments/SKILL.md
```

Expected: `validate_plugin.py` exits 0 (the same check plugin CI runs); the grep shows the contract block in Phase 4.2 plus the two new Red Flags / Rationalizations mentions.

- [ ] **Step 8: Commit**

```bash
git add plugins/flow/skills/review-comments/SKILL.md
git commit -m "fix(flow): make the Phase 4.2 card emission a reply contract"
```

---

### Task 3: Close out the branch

**Files:**
- Modify: none (verification and PR only)

**Interfaces:**
- Consumes: both commits from Tasks 1-2.
- Produces: a PR labelled `flow` referencing `claude-tools-elf.45`.

- [ ] **Step 1: Full verification**

```bash
uv run pytest plugins/flow/bin/tests
uv run ty check
uv run ruff check plugins/flow/bin plugins/flow/skills
git status
```

Expected: tests pass, ty clean, ruff clean, working tree contains only the two committed changes.

- [ ] **Step 2: Confirm the push with the user**

Ask in plain text (`Push to origin/fix/claude-tools-elf.45-review-comments-harden-phase-4?` with a one-line summary of the two commits) and wait for the answer. Never push unasked.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin HEAD
gh pr create \
  --title "fix(flow): harden Phase 4.2 card emission" \
  --label "flow" \
  --body "$(cat <<'EOF'
## Summary
- `flow-comment-card` caps an oversized `diff_hunk` at render time (header + `… N lines omitted …` + last 40 lines).
- Phase 4.2 states the per-card reply as a two-part contract, so the card can no longer be silently left in the tool output.
- Red Flags / Common Rationalizations cover the omission and the trim-it-myself cases.

Closes claude-tools-elf.45.
EOF
)"
```

- [ ] **Step 4: Finish the task**

Run `/flow:done` once the PR is open and green.
