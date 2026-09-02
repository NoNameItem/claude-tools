# Statusline Rewrite Design

## Problem

Current `~/.claude/statusline.sh` has grown to ~1030 lines through iterative development. Issues:
- **Visual glitches**: ANSI color codes "leak" into following lines (especially DIM)
- **Hard to maintain**: Complex bash with eval-based pseudo-associative arrays for tree building

## Solution

Rewrite in Python for cleaner code and reliable ANSI handling.

## Requirements

### What to display

1. **Line 1**: Model + session duration + context window
   ```
   [Claude Opus 4.5] 2h 15m | Context: 150,000 free (75.0%)
   ```

2. **Line 2**: Directory + git status
   ```
   tkbeads | master ✓ [+2 ~1]  abc123 2 hours ago
   ```

3. **Lines 3+**: Beads tasks (hierarchical tree)
   ```
   Task: [T] Implement feature (fqr.2) [P2] [in_progress]
   ```
   Or with multiple tasks:
   ```
   Tasks:
   └─[F] Parent feature (fqr) [P1] [in_progress]
     └─[T] Child task (fqr.2) [P2] [in_progress]
   ```

4. **Quota lines**: API quota usage
   ```
   Quota:
   ├ Session: 15% (3h 20m)
   └ Weekly: 8% (Thu 17:00)
   ```

### What to remove (vs current)

- Message count per session
- Session cost calculation
- Token delta display (`[+2,500]`)

## Architecture

```
~/Coding/claude-tools/
├── statusline/
│   ├── statusline.py      # Main script
│   └── install.sh         # Creates symlink to ~/.claude/
└── docs/plans/
```

### Module structure inside statusline.py

```python
# 1. Colors and formatting
class Style:
    """ANSI codes with guaranteed RESET"""
    DIM = "\033[2m"
    RESET = "\033[0m"
    # ...

    @staticmethod
    def wrap(code: str, text: str) -> str:
        """Wrap text in color code with guaranteed RESET"""
        return f"{code}{text}{Style.RESET}"

# 2. Output sections (each independent)
class ModelSection:      # [Model] duration | Context: ...
class GitSection:        # dir | branch status [changes]
class BeadsSection:      # Task tree
class QuotaSection:      # Quota with session/weekly

# 3. Data
@dataclass
class StatusInput:       # Parse JSON from Claude Code stdin
    model: str
    session_id: str
    cwd: str
    project_dir: str
    context_window_size: int
    current_usage: dict
    # ...

    @classmethod
    def from_stdin(cls) -> "StatusInput":
        data = json.load(sys.stdin)
        # ...

# 4. Main
def main():
    data = StatusInput.from_stdin()
    config = load_config()

    sections = [
        ModelSection(data, config),
        GitSection(data),
        BeadsSection(data),
        QuotaSection(config),
    ]

    for section in sections:
        output = section.render()
        if output:
            print(output)
```

### Key principle

Each section is completely independent. It receives data, returns a ready string. Sections don't know about each other → can't interfere.

### Color leak prevention

```python
class Style:
    @staticmethod
    def wrap(code: str, text: str) -> str:
        return f"{code}{text}{Style.RESET}"

    @classmethod
    def dim(cls, text: str) -> str:
        return cls.wrap(cls.DIM, text)

    @classmethod
    def green(cls, text: str) -> str:
        return cls.wrap(cls.GREEN, text)
```

Every color application goes through `wrap()` which guarantees RESET.

## File locations

- **Source**: `~/Coding/claude-tools/statusline/statusline.py`
- **Runtime**: `~/.claude/statusline.py` (symlink to source)
- **Config**: `~/.claude/statusline.conf` (unchanged format)
- **Cache**: `~/.cache/claude-tools/` (quota cache, session state)

## Expected size

~300-400 lines vs current 1030 lines.

## Installation

```bash
# From claude-tools repo
./statusline/install.sh
```

Creates symlink so edits in repo immediately work in Claude Code.