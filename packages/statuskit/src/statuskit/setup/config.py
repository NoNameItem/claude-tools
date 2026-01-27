"""Config file creation for setup command."""

from pathlib import Path

DEFAULT_CONFIG = """\
# Statuskit configuration
# See: https://pypi.org/project/claude-statuskit/
#
# All options shown with default values (commented out).
# Uncomment and modify as needed.

# ─────────────────────────────────────────────────────────────
# Global settings
# ─────────────────────────────────────────────────────────────

# Modules to display (in order)
# modules = ["model", "git", "usage_limits"]

# Enable debug output
# debug = false

# Cache directory
# cache_dir = "~/.cache/statuskit"

# ─────────────────────────────────────────────────────────────
# Model module: model name, session duration, context usage
# ─────────────────────────────────────────────────────────────

# [model]
# show_duration = true
# show_context = true
# context_format = "free"  # "free", "used", "ratio", "bar"
# context_compact = false
# context_threshold_green = 50
# context_threshold_yellow = 25

# ─────────────────────────────────────────────────────────────
# Git module: branch, status, location
# ─────────────────────────────────────────────────────────────

# [git]
# show_project = true
# show_worktree = true
# show_folder = true
# show_branch = true
# show_remote_status = true
# show_changes = true
# show_commit = true
# commit_age_format = "relative"  # "relative", "compact"

# ─────────────────────────────────────────────────────────────
# Usage limits module: API quota tracking (5h session, 7d weekly)
# ─────────────────────────────────────────────────────────────

# [usage_limits]
# show_session = true
# show_weekly = true
# show_sonnet = false
# show_reset_time = true
# multiline = true
# show_progress_bar = false
# bar_width = 10
# session_time_format = "remaining"  # "remaining", "reset_at"
# weekly_time_format = "reset_at"    # "remaining", "reset_at"
# sonnet_time_format = "reset_at"    # "remaining", "reset_at"
# cache_ttl = 60
"""


def create_config(path: Path) -> bool:
    """Create statuskit.toml with default content.

    Does not overwrite existing file.
    Returns True if file was created, False if it already existed.
    """
    if path.exists():
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG)
    return True
