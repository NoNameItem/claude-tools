---
description: Start working on a beads task (task selection, branch management, context display)
---

Invoke the `flow:starting-task` skill using the Skill tool and follow it exactly as presented to you.

**If the user provided a task ID argument** (e.g., `/flow:start 5dl`), pass it to the skill so it can filter the task tree using `--root <task-id>`.

**IMPORTANT:** Do NOT run any commands (bd ready, bd graph, git, etc.) BEFORE invoking the skill. The skill will tell you exactly what commands to run and in what order.
