# StatusKit: clear the open SonarCloud code smells

**Date:** 2026-09-24
**Task:** claude-tools-4u3 (epic "StatusKit Sonar Issues")
**Modules:** `packages/statuskit/src/statuskit/modules/git.py`,
`packages/statuskit/src/statuskit/modules/usage_limits.py`,
`packages/statuskit/src/statuskit/core/schema.py`

## Problem

The epic tracks the SonarCloud findings on `NoNameItem_statuskit`: cognitive complexity over the
15 allowed (`python:S3776`), exception tuples listing a subclass of another member
(`python:S5713`), and one malformed suppression comment (`python:S7632`). All of them are
maintainability smells; none changes what statuskit renders.

## State of the findings

Checked against the master analysis of `e1d21be` on 2026-09-24. The task titles still carry the
line numbers from 2026-08-30; the code has moved since.

| Task | Sonar key | Rule | Current location | Status |
|---|---|---|---|---|
| 4u3.2 | AZ-FJo7AI4bRIMOOsse1 | S3776 | — | already CLOSED (code rewritten in #143); task closed |
| 4u3.3 | AZ-FJo7AI4bRIMOOssez | S3776 (29) | `usage_limits.py:551` `UsageCache.load` | open |
| 4u3.4 | AZ-FJo7AI4bRIMOOssey | S3776 (31) | `usage_limits.py:232` `_parse_limits_array` | open |
| 4u3.5 | AZ-FJo7AI4bRIMOOsse2 | S3776 (23) | `usage_limits.py:981` `_visible_groups` | open |
| 4u3.6 | AZ-FJo7AI4bRIMOOsse3 | S3776 (22) | `usage_limits.py:1019` `_render_multiline` | open |
| 4u3.7 | AZ9LfqLdJecd4IOuhSJf | S3776 (17) | `git.py:236` `parse_github_pr_list` | open |
| 4u3.8 | AZ75uqmIFx_Rr5qRFKE- | S3776 (18) | `schema.py:137` `_type_msg` | open |
| 4u3.9 | AZ9LfqLdJecd4IOuhSJi | S7632 | `git.py:624` `noqa` in `_run_cli` | open |
| 4u3.10 | AZ-FJo7AI4bRIMOOsse0 | S5713 | `usage_limits.py:658` `UsageCache.load` | open |
| 4u3.11 | AZ9LfqLdJecd4IOuhSJe | S5713 | `git.py:138` `PrCache.load` | open |
| 4u3.12 | AZ9LfqLdJecd4IOuhSJg | S5713 | `git.py:248` `parse_github_pr_list` | open |
| 4u3.13 | AZ9LfqLdJecd4IOuhSJh | S5713 | `git.py:278` `parse_gitlab_mr_list` | open |

## Constraint

**Pure refactoring.** Every function keeps its signature, return values, and error handling.
Where code is reordered (parse-then-dedupe, the flattened tree render), the design states why
the result is identical, and a test pins the case the reordering could have broken.

## Design

### Redundant exception classes (S5713)

`json.JSONDecodeError` subclasses `ValueError`. Every flagged tuple already lists `ValueError`,
so `json.JSONDecodeError` is dropped. The broader class stays, so the set of caught exceptions
is unchanged (the narrower-only variant would stop catching `datetime.fromisoformat`'s
`ValueError` in `PrCache.load`).

`parse_github_pr_list` and `parse_gitlab_mr_list` open with the same decode-and-check-for-a-list
prologue. It moves into one helper, so the corrected `except` exists once:

```python
def _load_json_array(stdout: str) -> list | None:
    """Decode a CLI's JSON output; None when it is not valid JSON or not a JSON array."""
```

### `git.py` — `parse_github_pr_list` complexity

Besides `_load_json_array`, the fork check moves into `_is_foreign_pr(item, owner) -> bool`
(owner given, head owner present, and the case-folded logins differ). The loop keeps the
dict check, the fork skip, and the number/state validation.

### `git.py:624` — suppression comment syntax (S7632)

The line reads
`# noqa: S603 - cmd is a fixed [binary, *args] list; no shell, no user-controlled executable`.
Other `# noqa: CODE - reason` comments in the same project are not flagged, and they contain no
comma, bracket, or `*`. The likely trigger is that Sonar splits the code list on commas. That
is inferred, not confirmed. The reason is reworded in plain words without any of those
characters and stays inline on the same line, as the repo's suppression convention requires.
The PR's Sonar analysis confirms or refutes the fix.

### `schema.py` — `_type_msg` complexity

The generic-alias branch (`list[str]`: container check, then element check) moves into
`_generic_type_msg(raw, origin, expected_type) -> str | None`. `_type_msg` keeps its
single-exit `msg` style and calls the helper from the first branch.

### `usage_limits.py` — `_parse_limits_array` complexity

- A helper `_non_empty_str(value: object) -> str | None` replaces the three repetitions of
  "a non-empty string, else None" (scope model, scope surface, and the cached row's
  model/surface below).
- The scoped-item branch moves into `_parse_scoped_limit(item, scope) -> UsageLimit | None`:
  malformed scope → None, model from `scope.model.display_name`, surface from
  `scope.surface`, no usable label → None, else `_parse_limit_fields(...)`. The `_as_dict`
  call guarded by an `isinstance(..., dict)` check is dropped as redundant.
- The nested `group_for` closure is replaced by an up-front `key not in _GROUP_WINDOWS` skip and
  `groups.setdefault(...)`. As before, a group is created before its item is parsed and empty
  groups are filtered out at the end.
- Dedupe order changes from "skip if the scope was seen, then parse" to "parse, then skip if
  unusable or seen". A scope is still added to `seen_scopes` only when its row parsed, so the
  outcome is the same: the first *usable* row per `(group, model, surface)` wins.

### `usage_limits.py` — `UsageCache.load` complexity

Sonar counts a nested function's body towards the enclosing function, so the two closures move
to module level:

- `_deserialize_limit(d: object) -> UsageLimit | None` — the former `deserialize_limit`,
  unchanged in what it accepts or rejects. Its comment about type-checking `label` and
  `utilization` here, not at render time, moves with it.
- `_deserialize_groups(groups_raw: list) -> list[UsageGroup]` keeps the inner
  `try/except (ValueError, TypeError, AttributeError)` that turns a malformed group
  (e.g. an unhashable `key`) into `[]`. **That `try` must stay inside the helper.** If the error
  reached `load`'s outer `except`, `load` would return None and lose `last_attempt_at`, the only
  thing throttling a failing API. `load` keeps the non-list check (legacy
  `{session,weekly,sonnet}` cache or unreadable payload → `[]`). The parameter is a bare `list`
  rather than `object`: ty narrows `isinstance(object, list)` to `list[object]`, which would
  type the group `key` as `object`, while a bare `list` keeps the elements `Unknown`, as the
  untyped cache JSON was before.
- `stamps_only()` disappears: `load` builds one `UsageData` whose `groups` is whatever
  `_deserialize_groups` returned. That is the same object `stamps_only()` produced whenever the
  groups were a miss.
- The identical `resets_at` parsing in `_parse_limit_fields` and the cached-row deserializer
  becomes `_parse_reset_time(value: object) -> datetime | None`. A non-string or empty value, or
  an unparseable one, gives None. The naive-datetime handling is untouched: such a value is kept
  naive and normalized at render time, as today.

### `usage_limits.py` — `_visible_groups` complexity

The per-model decision (hidden by `models_never_show`, else shown when in `models_always_show`,
used, or carrying a reset time; matched on the full label and on the bare model name) moves
into a module function `_model_visible(m, always, never) -> bool`. The overall-row switch moves
into a method `_show_overall(g) -> bool`.

### `usage_limits.py` — `_render_multiline` complexity

The render splits into two passes:

1. Build `top: list[tuple[str, list[str]]]`, one entry per top-level row with its nested child
   rows. A group with a visible overall row contributes `(overall_row, model_rows)`. A group
   without one contributes each model row as its own top-level entry with no children.
2. Emit `├`/`└` for the top-level rows by position in `top`, and `  ├`/`  └` for the children
   by position in their own list.

This is identical to the old per-branch logic because `_visible_groups` only returns groups that
contribute at least one row. The last group's last top-level row is therefore the last entry of
`top`, which is exactly the old `is_last_top and j == len(models) - 1` condition.

## Testing

The existing suites cover `git.py` (malformed JSON, fork filtering, owner case-folding) and
`schema.py` (generic list checks, bool/int strictness). Three `usage_limits` cases that the
refactor could silently break are not covered yet. They are added first and pass on the
current code:

1. **Cache with an unhashable group key.** `{"data": {"groups": [{"key": ["x"]}]}, ...}` loads
   as `UsageData` with its timestamps and `groups == []`, not None.
2. **Tree connectors without an overall row.** Exact `├`/`└` prefixes when a middle group has no
   overall row, and when the last group has none (its models are top-level, and the final one
   gets `└`).
3. **Duplicate scope whose first row is unusable.** The first row has a non-numeric `percent`
   and the second a valid one: the second is kept.

Local gates: `uv run pytest` (all suites), `ruff format` and `ruff check` on changed files,
and a pathless `uv run ty check`. Sonar complexity is not re-measured locally. The PR's
SonarCloud analysis is the check, and it must add no new issues.

## Closing the tasks

The PR's quality gate only reports **new** issues. The 11 open issue keys turn CLOSED when
master is analysed after the merge. The beads children are closed after that analysis, each
confirmed by querying its Sonar key, not on the strength of a green PR.
