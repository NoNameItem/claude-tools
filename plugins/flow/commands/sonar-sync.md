---
description: Sync SonarQube/SonarCloud issues with beads tasks (tech debt review or PR issues)
---

Invoke the `flow:syncing-sonarcloud` skill using the Skill tool and follow it exactly as presented to you.

**Pass all arguments** to the skill:
- If user provided a project key (e.g., `/flow:sonar-sync NoNameItem_statuskit`), use it in Step 1.
- If user provided `--pr <id>` (e.g., `/flow:sonar-sync NoNameItem_statuskit --pr 42`), use PR mode with that ID.

**IMPORTANT:** Do NOT call SonarQube MCP tools or bd commands BEFORE invoking the skill. The skill will tell you exactly what to do and in what order.
