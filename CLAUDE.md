# CLAUDE.md

Custom tools and scripts for Claude Code.

## Project Structure

```
claude-tools/
├── statusline/
│   ├── statusline.py   # Main statusline script (symlinked to ~/.claude/)
│   └── install.sh      # Installation script
└── docs/plans/         # Design documents
```

## Statusline

The statusline receives JSON on stdin from Claude Code and outputs formatted multi-line status.

**Testing locally:**
```bash
echo '{"model":{"display_name":"Test"},"workspace":{"current_dir":"/tmp","project_dir":"/tmp"},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":1000}}}' | python statusline/statusline.py
```

## Key Files

- `~/.claude/statusline.py` - symlink to `statusline/statusline.py`
- `~/.claude/statusline.conf` - user config (autocompact, show_quota, etc.)
- `~/.cache/claude-tools/` - quota cache, session state