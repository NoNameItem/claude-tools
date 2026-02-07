---
description: Process GitHub PR review comments (apply fixes, argue against invalid, reply on GitHub)
---

Invoke the `flow:reviewing-comments` skill using the Skill tool and follow it exactly as presented to you.

**Pass all arguments** to the skill:
- If user provided a PR number (e.g., `/flow:review-comments 42`), pass it to Phase 1.

**IMPORTANT:** Do NOT call `gh api` or `gh pr` commands BEFORE invoking the skill. The skill will tell you exactly what to do and in what order.
