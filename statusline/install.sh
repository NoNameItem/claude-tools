#!/bin/bash
# Install statusline by creating symlink to ~/.claude/

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/statusline.py"
TARGET="$HOME/.claude/statusline.py"

if [[ ! -f "$SOURCE" ]]; then
    echo "Error: $SOURCE not found"
    exit 1
fi

# Backup existing if it's not a symlink
if [[ -f "$TARGET" && ! -L "$TARGET" ]]; then
    echo "Backing up existing $TARGET to ${TARGET}.bak"
    mv "$TARGET" "${TARGET}.bak"
fi

# Create symlink
ln -sf "$SOURCE" "$TARGET"
echo "Installed: $TARGET -> $SOURCE"

# Create cache directory
mkdir -p "$HOME/.cache/claude-tools"
echo "Created cache directory: ~/.cache/claude-tools/"