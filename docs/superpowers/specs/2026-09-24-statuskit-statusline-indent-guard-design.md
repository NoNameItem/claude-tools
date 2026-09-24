# StatusKit: keep leading indentation alive in the Claude Code statusline

**Date:** 2026-09-24
**Task:** claude-tools-5dl.23
**Module:** `packages/statuskit/src/statuskit/__init__.py`

## Problem

In multiline mode `usage_limits` nests per-model rows under their group's overall row with a
two-space indent (rule from `2026-07-19-statuskit-usage-dynamic-models-design.md`,
"Multiline — nested view"):

```
Usage:
├ Session: 11% (2h 30m)
└ Weekly:  2% (Thu 17:00)
  ├ Fable:  34% (Fri 03:59)
  └ Opus:   88% (Fri 03:59)
```

statuskit prints exactly that, but the real Claude Code statusline shows the model rows flush
with `Session`/`Weekly`, so the tree reads as two stacked `└` and the grouping is lost.

## Findings that shape the design

- **Claude Code trims every line.** In the Claude Code 2.1.281 binary the statusline command
  result is post-processed as
  `stdout.trim().split("\n").flatMap((line) => line.trim() || []).join("\n")`.
  Each line's leading and trailing JS whitespace is removed and whitespace-only lines are
  dropped. This is not something statuskit can configure.
- **JS `trim()` strips every Unicode space, not just ASCII.** Checked in node: U+0020, U+00A0
  (NBSP), U+2007, U+202F and U+3000 are all stripped as leading characters. U+2800 (braille
  pattern blank), U+200B, U+2060, U+3164 and ESC survive. A non-breaking space is therefore
  not a fix.
- **An ANSI escape in front is not reliable.** Moving the indent inside a coloured span makes
  the line start with ESC, which survives `trim()`, but colours are optional: with
  `colors = false` in the config, or `NO_COLOR` in the environment (termcolor honours it over
  `FORCE_COLOR`), no escape is emitted and the indent is stripped again.
- **Zero-width guards risk width disagreement.** Ink measures U+200B/U+2060 as width 0, while
  terminals disagree on how wide they are; a mismatch shifts everything after it. U+2800 is a
  regular width-1 character everywhere and has no ink.
- **Only one producer today.** The nested model row in `usage_limits._render_multiline` is the
  only place statuskit emits a line with leading spaces.

## Design

The trimming is a property of the Claude Code statusline, so it is handled at the one place
statuskit hands text to it — the `print` in `_render_statusline` — not inside modules.

- A private helper `_guard_indent(text: str) -> str` and a constant
  `_INDENT_GUARD = "⠀"` live in `statuskit/__init__.py` next to `_render_statusline`. The
  constant's comment names the Claude Code post-processing above as the reason it exists.
- `_render_statusline` prints `_guard_indent(output)` instead of `output`.
- `_guard_indent` splits on `"\n"` and, for every line that starts with an ASCII space,
  replaces **that first space** with `_INDENT_GUARD`. The rest of the line is untouched, so
  the indent keeps its exact column width (two spaces become `"⠀ "`).
- Modules keep writing plain spaces. `usage_limits` does not change, and neither do its tests
  (`fable_line.startswith("  ")` stays valid at module level). Any future module, including
  external ones, gets working indentation for free.

### Edge cases

| Line | Behaviour | Why |
|---|---|---|
| no leading space | unchanged | nothing to protect |
| starts with ESC (coloured or `[!] …` error lines) | unchanged | already survives `trim()` |
| whitespace only | unchanged | Claude Code drops it today; guarding it would turn it into a visible blank line |
| starts with a tab | unchanged | replacing a tab with a width-1 guard would change the width; no module emits tabs |

The debug/error `print(colored(...))` calls in `_render_statusline` bypass the helper; they
start with ESC or `[` and are unaffected by the trimming anyway.

### Out of scope

- Changing the nested layout itself (connectors, indent width) — the two-space rule stands.
- Trailing whitespace, which Claude Code also trims — nothing relies on it.

## Files

- `packages/statuskit/src/statuskit/__init__.py` — `_INDENT_GUARD`, `_guard_indent`, the
  `print` call in `_render_statusline`.
- `packages/statuskit/tests/test_main.py` — tests below.

## Testing (TDD)

1. **Unit, `_guard_indent`:** a two-space-indented line becomes `"⠀ "` + rest; a line with
   no indent, a whitespace-only line, a tab-indented line and an ESC-leading line are returned
   unchanged; a multi-line mix guards only the indented lines and preserves line order and
   count.
2. **Regression against Claude Code's trimming:** a Python helper reproduces JS `trim()` with
   an explicit JS whitespace set (including U+00A0 and the Zs spaces). After
   `_guard_indent` and that trim, an indented line still starts 2 columns to the right of a
   top-level line. The same helper applied to the unguarded text shows the indent disappearing,
   which pins down the failure this fix exists for.
3. **Integration, `_render_statusline`:** with a stub module whose output has an indented
   line, stdout contains the guarded line.

## Acceptance

Visual, in the real Claude Code statusline of the user's terminal: model rows appear indented
by two columns under `Weekly`, both with colours on and with `colors = false`.
