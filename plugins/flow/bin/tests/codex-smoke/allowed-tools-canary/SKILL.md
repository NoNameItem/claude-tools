---
name: allowed-tools-canary
description: Use only for Flow's local Codex compatibility smoke.
allowed-tools: Read
---

Track one progress step, read the supplied fixture file with the native file
mechanism, and run `flow-require-bd` through the shell mechanism. Report which
mapped tools were available. Do not modify files or external state.
