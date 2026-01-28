#!/usr/bin/env python3
"""Generate publish summary from job results.

Usage:
    Called from GitHub Actions workflow with NEEDS_JSON env var.

Example NEEDS_JSON:
    {
        "resolve": {"outputs": {"publish-targets": "[\"pypi\"]", ...}},
        "publish-pypi": {"result": "success", "outputs": {"summary-message": "..."}}
    }
"""

from __future__ import annotations

import json
import os
import sys


def generate_summary() -> str:
    """Generate markdown summary from job results.

    Reads NEEDS_JSON env var containing all job outputs.

    Returns:
        Markdown formatted summary string.
    """
    needs_json = os.environ.get("NEEDS_JSON", "{}")
    needs = json.loads(needs_json)

    # Get metadata from resolve job
    resolve_outputs = needs.get("resolve", {}).get("outputs", {})
    project_name = resolve_outputs.get("project-name", "unknown")
    version = resolve_outputs.get("version", "unknown")
    publish_targets_raw = resolve_outputs.get("publish-targets", "[]")
    publish_targets = json.loads(publish_targets_raw)

    lines = [
        "## Publish Summary",
        "",
        f"**Project:** {project_name}",
        f"**Version:** {version}",
        "",
        "### Results",
        "",
    ]

    # Status icons
    icons = {
        "success": "\u2705",  # ✅
        "failure": "\u274c",  # ❌
        "skipped": "\u23ed\ufe0f",  # ⏭️
        "cancelled": "\u26d4",  # ⛔
    }

    # Iterate over publish targets from resolve output
    for target in publish_targets:
        job_name = f"publish-{target}"
        job_data = needs.get(job_name, {})
        result = job_data.get("result", "not_found")
        message = job_data.get("outputs", {}).get("summary-message", "")

        icon = icons.get(result, "\u2753")  # ❓
        line = f"{icon} **{target}**: {result}"

        if message:
            # Indent multi-line messages
            indented = message.replace("\n", "\n   ")
            line += f"\n   {indented}"

        lines.append(line)
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    """Main entry point."""
    from pathlib import Path

    summary = generate_summary()

    # Write to GITHUB_STEP_SUMMARY if available
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a") as f:
            f.write(summary)
            f.write("\n")

    # Write to GITHUB_OUTPUT for use in other jobs
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a") as f:
            # Use heredoc-style delimiter for multiline output
            f.write("telegram-message<<EOF\n")
            f.write(summary)
            f.write("\nEOF\n")

    # Also print to stdout for debugging
    print(summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())
