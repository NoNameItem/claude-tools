#!/usr/bin/env python3
"""Convert ty concise output to reviewdog rdjsonl format.

ty concise format: file:line:col: level[code] message
rdjsonl format: one JSON diagnostic per line

Usage:
    ty check --output-format concise | python ty_to_rdjsonl.py
"""

import json
import re
import sys

# Pattern for ty concise output: file:line:col: level[code] message
TY_PATTERN = re.compile(
    r"^(?P<path>[^:]+):(?P<line>\d+):(?P<col>\d+): "
    r"(?P<level>error|warning|info)\[(?P<code>[^\]]+)\] "
    r"(?P<message>.+)$"
)

SEVERITY_MAP = {
    "error": "ERROR",
    "warning": "WARNING",
    "info": "INFO",
}


def convert_line(line: str) -> dict | None:
    """
    Parse a Ty concise output line into a reviewdog rdjsonl diagnostic dictionary.
    
    Parameters:
        line (str): A single line of Ty concise output in the form
            "file:line:col: level[code] message".
    
    Returns:
        dict | None: A diagnostic dictionary with keys:
            - message: diagnostic message string.
            - location: object containing:
                - path: file path string.
                - range.start.line: integer line number.
                - range.start.column: integer column number.
            - severity: mapped severity string (RDJSONL).
            - code.value: diagnostic code string.
            - source.name: set to "ty".
        Returns `None` if the input line does not match the expected pattern.
    """
    match = TY_PATTERN.match(line.strip())
    if not match:
        return None

    return {
        "message": match.group("message"),
        "location": {
            "path": match.group("path"),
            "range": {
                "start": {
                    "line": int(match.group("line")),
                    "column": int(match.group("col")),
                }
            },
        },
        "severity": SEVERITY_MAP.get(match.group("level"), "ERROR"),
        "code": {
            "value": match.group("code"),
        },
        "source": {
            "name": "ty",
        },
    }


def main() -> None:
    """Read ty output from stdin and write rdjsonl to stdout."""
    for line in sys.stdin:
        diagnostic = convert_line(line)
        if diagnostic:
            print(json.dumps(diagnostic))


if __name__ == "__main__":
    main()