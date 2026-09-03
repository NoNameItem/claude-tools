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


def _imported_modules(tree: ast.Module, package: str) -> set[str]:
    """Absolute names of everything a file in `package` imports, relative imports resolved.

    `package` is the file's own dotted name when the file is an `__init__.py` (a package is
    its own package), or its containing package's dotted name otherwise — see the call site.
    """
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
    packages = {path.parent.name for path in SRC.glob("*/__init__.py")}

    assert packages == set(FORBIDDEN)


def test_layers_never_import_upwards():
    """Every source file obeys the rule table."""
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        module = _module_name(path)
        layer = _layer_of(module)
        if layer is None:
            continue
        # A package's own `__init__.py` resolves relative imports against itself; an ordinary
        # submodule resolves them against its containing package (everything but its own name).
        package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
        for imported in _imported_modules(ast.parse(path.read_text(encoding="utf-8")), package):
            violations.extend(
                f"{module} imports {imported}"
                for banned in FORBIDDEN[layer]
                if imported == banned or imported.startswith(f"{banned}.")
            )

    assert violations == []


def test_imported_modules_resolves_relative_import_from_package_init():
    """A package's own `__init__.py` is its own package: two levels up from `beadboard.model`
    is `beadboard`, so `from ..ui import x` written there must resolve to `beadboard.ui`, not
    to `.ui` (which is what stripping `beadboard.model` by one more segment produces)."""
    tree = ast.parse("from ..ui import x\n")

    assert _imported_modules(tree, "beadboard.model") == {"beadboard.ui"}


def test_imported_modules_resolves_relative_import_from_submodule():
    """The same relative import written in an ordinary submodule (package `beadboard.service`,
    e.g. `beadboard/service/foo.py`) resolves identically, guarding the other half of the level
    arithmetic that the package-init case above exercises."""
    tree = ast.parse("from ..ui import x\n")

    assert _imported_modules(tree, "beadboard.service") == {"beadboard.ui"}
