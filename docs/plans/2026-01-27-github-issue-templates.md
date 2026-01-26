# GitHub Issue Templates Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add GitHub issue templates for bug reports and feature requests for statuskit and flow projects.

**Architecture:** YAML form templates in `.github/ISSUE_TEMPLATE/`. Each template auto-applies project and type labels. No workflows needed.

**Tech Stack:** GitHub Issue Forms (YAML)

**Design:** `docs/plans/2026-01-27-github-issue-templates-design.md`

---

### Task 1: Create directory and config.yml

**Files:**
- Create: `.github/ISSUE_TEMPLATE/config.yml`

**Step 1: Create config.yml**

```yaml
blank_issues_enabled: false
contact_links: []
```

**Step 2: Commit**

```bash
git add .github/ISSUE_TEMPLATE/config.yml
git commit -m "ci: add issue template config"
```

---

### Task 2: Create statuskit-bug.yml

**Files:**
- Create: `.github/ISSUE_TEMPLATE/statuskit-bug.yml`

**Step 1: Create statuskit-bug.yml**

```yaml
name: "Bug Report: statuskit"
description: Report a bug in the statuskit package
labels: ["statuskit", "bug"]
body:
  - type: input
    id: version
    attributes:
      label: Statuskit Version
      description: What version of statuskit are you using?
      placeholder: "0.1.0"
    validations:
      required: true

  - type: input
    id: os-python
    attributes:
      label: OS / Python Version
      description: Your operating system and Python version
      placeholder: "macOS 14.0, Python 3.12"
    validations:
      required: true

  - type: input
    id: claude-code-version
    attributes:
      label: Claude Code Version
      description: What version of Claude Code CLI are you using?
      placeholder: "1.0.0"
    validations:
      required: true

  - type: textarea
    id: description
    attributes:
      label: Description
      description: Describe the bug
    validations:
      required: true

  - type: textarea
    id: steps
    attributes:
      label: Steps to Reproduce
      description: Steps to reproduce the behavior
      placeholder: |
        1. Run statuskit with '...'
        2. See error
    validations:
      required: true

  - type: textarea
    id: expected
    attributes:
      label: Expected Behavior
      description: What did you expect to happen?
    validations:
      required: true
```

**Step 2: Commit**

```bash
git add .github/ISSUE_TEMPLATE/statuskit-bug.yml
git commit -m "ci: add statuskit bug report template"
```

---

### Task 3: Create statuskit-feature.yml

**Files:**
- Create: `.github/ISSUE_TEMPLATE/statuskit-feature.yml`

**Step 1: Create statuskit-feature.yml**

```yaml
name: "Feature Request: statuskit"
description: Suggest a feature for the statuskit package
labels: ["statuskit", "enhancement"]
body:
  - type: textarea
    id: description
    attributes:
      label: Description
      description: Describe the feature you'd like
    validations:
      required: true

  - type: textarea
    id: use-case
    attributes:
      label: Use Case
      description: Why do you need this feature? What problem does it solve?
    validations:
      required: true

  - type: textarea
    id: proposed-solution
    attributes:
      label: Proposed Solution
      description: How do you envision this working?
    validations:
      required: false

  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives Considered
      description: What alternatives have you considered?
    validations:
      required: false
```

**Step 2: Commit**

```bash
git add .github/ISSUE_TEMPLATE/statuskit-feature.yml
git commit -m "ci: add statuskit feature request template"
```

---

### Task 4: Create flow-bug.yml

**Files:**
- Create: `.github/ISSUE_TEMPLATE/flow-bug.yml`

**Step 1: Create flow-bug.yml**

```yaml
name: "Bug Report: flow"
description: Report a bug in the flow plugin
labels: ["flow", "bug"]
body:
  - type: input
    id: version
    attributes:
      label: Flow Plugin Version
      description: What version of the flow plugin are you using?
      placeholder: "1.0.0"
    validations:
      required: true

  - type: input
    id: claude-code-version
    attributes:
      label: Claude Code Version
      description: What version of Claude Code CLI are you using?
      placeholder: "1.0.0"
    validations:
      required: true

  - type: textarea
    id: description
    attributes:
      label: Description
      description: Describe the bug
    validations:
      required: true

  - type: textarea
    id: steps
    attributes:
      label: Steps to Reproduce
      description: Steps to reproduce the behavior
      placeholder: |
        1. Run '/flow:...'
        2. See error
    validations:
      required: true

  - type: textarea
    id: expected
    attributes:
      label: Expected Behavior
      description: What did you expect to happen?
    validations:
      required: true
```

**Step 2: Commit**

```bash
git add .github/ISSUE_TEMPLATE/flow-bug.yml
git commit -m "ci: add flow bug report template"
```

---

### Task 5: Create flow-feature.yml

**Files:**
- Create: `.github/ISSUE_TEMPLATE/flow-feature.yml`

**Step 1: Create flow-feature.yml**

```yaml
name: "Feature Request: flow"
description: Suggest a feature for the flow plugin
labels: ["flow", "enhancement"]
body:
  - type: textarea
    id: description
    attributes:
      label: Description
      description: Describe the feature you'd like
    validations:
      required: true

  - type: textarea
    id: use-case
    attributes:
      label: Use Case
      description: Why do you need this feature? What problem does it solve?
    validations:
      required: true

  - type: textarea
    id: proposed-solution
    attributes:
      label: Proposed Solution
      description: How do you envision this working?
    validations:
      required: false

  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives Considered
      description: What alternatives have you considered?
    validations:
      required: false
```

**Step 2: Commit**

```bash
git add .github/ISSUE_TEMPLATE/flow-feature.yml
git commit -m "ci: add flow feature request template"
```

---

### Task 6: Ensure labels exist

**Step 1: Create labels (skip existing)**

```bash
gh label create statuskit --color 0E8A16 --description "Statuskit package" 2>/dev/null || true
gh label create flow --color 1D76DB --description "Flow plugin" 2>/dev/null || true
gh label create bug --color D73A4A --description "Something isn't working" 2>/dev/null || true
gh label create enhancement --color A2EEEF --description "New feature or request" 2>/dev/null || true
```

**Step 2: Verify labels**

```bash
gh label list | grep -E "(statuskit|flow|bug|enhancement)"
```

Expected: All 4 labels listed.

---

### Task 7: Push and verify

**Step 1: Push branch**

```bash
git push -u origin HEAD
```

**Step 2: Create PR**

```bash
gh pr create --title "ci: add GitHub issue templates" --label "repo" --body "$(cat <<'EOF'
## Summary
Add GitHub issue templates for bug reports and feature requests.

## Templates
- `statuskit-bug.yml` - Bug report for statuskit package
- `statuskit-feature.yml` - Feature request for statuskit
- `flow-bug.yml` - Bug report for flow plugin
- `flow-feature.yml` - Feature request for flow

## How it works
- Each template auto-applies project label (`statuskit`/`flow`) and type label (`bug`/`enhancement`)
- `blank_issues_enabled: false` directs users to use templates
- All required fields ensure we get necessary info for triage
EOF
)"
```

**Step 3: Verify templates on GitHub**

Open the PR link and navigate to Issues → New Issue to verify templates appear correctly.
