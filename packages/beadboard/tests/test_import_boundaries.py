"""The epic's layering rule, enforced instead of documented.

The test parses the sources with `ast` rather than importing them: parsing works on empty
packages, needs neither Textual nor bd at collection time, and catches a violation that sits
inside a branch which never executes.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "beadboard"

# Layer -> module prefixes that layer may not import. `ui` may import anything; the package
# root (`__init__.py`, `cli.py`) is the composition root and is not a layer at all.
FORBIDDEN: dict[str, frozenset[str]] = {
    "model": frozenset({"textual", "beadboard.sources", "beadboard.repository", "beadboard.service", "beadboard.ui"}),
    "sources": frozenset({"textual", "beadboard.repository", "beadboard.service", "beadboard.ui"}),
    "repository": frozenset({"textual", "beadboard.sources", "beadboard.service", "beadboard.ui"}),
    "service": frozenset({"textual", "beadboard.ui"}),
    "ui": frozenset(),
}


def _module_name(path: Path) -> str:
    """`.../src/beadboard/ui/app.py` -> `beadboard.ui.app`."""
    parts = list(path.relative_to(SRC.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_modules(tree: ast.Module, module: str) -> set[str]:
    """Absolute names of everything `module` imports, relative imports resolved."""
    package = module.rsplit(".", 1)[0] if "." in module else module
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                prefix = ".".join(parts[: len(parts) - node.level + 1])
                imported.add(f"{prefix}.{node.module}" if node.module else prefix)
            elif node.module:
                imported.add(node.module)
    return imported


def _layer_of(module: str) -> str | None:
    """The layer a module belongs to, or None for the composition root."""
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[1] in FORBIDDEN else None


def test_rule_table_covers_every_layer_package():
    """Renaming or adding a layer package must fail here, not go unnoticed."""
    packages = {path.parent.name for path in SRC.rglob("__init__.py") if path.parent != SRC}

    assert packages == set(FORBIDDEN)


def test_layers_never_import_upwards():
    """Every source file obeys the rule table."""
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        module = _module_name(path)
        layer = _layer_of(module)
        if layer is None:
            continue
        for imported in _imported_modules(ast.parse(path.read_text(encoding="utf-8")), module):
            violations.extend(
                f"{module} imports {imported}"
                for banned in FORBIDDEN[layer]
                if imported == banned or imported.startswith(f"{banned}.")
            )

    assert violations == []
