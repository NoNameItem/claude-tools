# GitHub Issue Templates Design

## Overview

GitHub issue templates for the claude-tools monorepo. Separate templates per project for clarity.

## File Structure

```
.github/
└── ISSUE_TEMPLATE/
    ├── config.yml
    ├── statuskit-bug.yml
    ├── statuskit-feature.yml
    ├── flow-bug.yml
    └── flow-feature.yml
```

## Templates

### Labels

| Template | Labels |
|----------|--------|
| statuskit-bug | `statuskit`, `bug` |
| statuskit-feature | `statuskit`, `enhancement` |
| flow-bug | `flow`, `bug` |
| flow-feature | `flow`, `enhancement` |

Labels are set via `labels:` field in YAML — GitHub applies them automatically.

### statuskit-bug.yml

| Field | Type | Required |
|-------|------|----------|
| Version | input | yes |
| OS / Python version | input | yes |
| Claude Code version | input | yes |
| Description | textarea | yes |
| Steps to reproduce | textarea | yes |
| Expected behavior | textarea | yes |

### flow-bug.yml

| Field | Type | Required |
|-------|------|----------|
| Version | input | yes |
| Claude Code version | input | yes |
| Description | textarea | yes |
| Steps to reproduce | textarea | yes |
| Expected behavior | textarea | yes |

### statuskit-feature.yml / flow-feature.yml

| Field | Type | Required |
|-------|------|----------|
| Description | textarea | yes |
| Use case | textarea | yes |
| Proposed solution | textarea | no |
| Alternatives considered | textarea | no |

### config.yml

```yaml
blank_issues_enabled: false
contact_links: []
```

## Prerequisites

Create labels if missing:

```bash
gh label create statuskit --color 0E8A16 --description "Statuskit package"
gh label create flow --color 1D76DB --description "Flow plugin"
gh label create bug --color D73A4A --description "Something isn't working"
gh label create enhancement --color A2EEEF --description "New feature or request"
```
