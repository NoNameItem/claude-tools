"""The epic's layering rule, enforced instead of documented.

The test parses the sources with `ast` rather than importing them: parsing works on empty
packages, needs neither Textual nor bd at collection time, and catches a violation that sits
inside a branch which never executes.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "beadboard"

# Layer -> module prefixes that layer may not import. `ui` may import anything; `cli.py` is the
# composition root and is not a layer at all.
FORBIDDEN: dict[str, frozenset[str]] = {
    "model": frozenset({"textual", "beadboard.sources", "beadboard.repository", "beadboard.service", "beadboard.ui"}),
    "sources": frozenset({"textual", "beadboard.repository", "beadboard.service", "beadboard.ui"}),
    "repository": frozenset({"textual", "beadboard.sources", "beadboard.service", "beadboard.ui"}),
    "service": frozenset({"textual", "beadboard.ui"}),
    "ui": frozenset(),
}

# What a module at the package root — `__init__.py` and anything else that is not `cli.py` —
# may not import. Only `cli.py` assembles the layers; the package initializer is a marker
# module, not a second composition root, so it reaches into no layer at all.
ROOT_FORBIDDEN = frozenset({"textual", *(f"beadboard.{layer}" for layer in FORBIDDEN)})


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
            # Without a level this is an absolute import, and the parser guarantees a module
            # name; with one, the module name (if any) hangs off the resolved prefix.
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                prefix = ".".join(parts[: len(parts) - node.level + 1])
                base = f"{prefix}.{base}" if base else prefix
            # `from beadboard import ui` names the module `ui` only as an imported name, so
            # recording `base` alone would let a forbidden `beadboard.ui` through.
            imported.add(base)
            imported.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
    return imported


def _forbidden_for(module: str, path: Path) -> frozenset[str] | None:
    """The prefixes `module` may not import, or None when the module is exempt.

    Exactly one module is exempt: `cli.py`, the composition root, whose job is to assemble
    every layer. The package's own `__init__.py` is not a second composition root — it, and
    any other module sitting outside a layer package, answers to `ROOT_FORBIDDEN`.
    """
    parts = module.split(".")
    if len(parts) > 1 and parts[1] in FORBIDDEN:
        return FORBIDDEN[parts[1]]
    if module == "beadboard.cli" and path.name == "cli.py":
        return None
    return ROOT_FORBIDDEN


def test_rule_table_covers_every_layer_package():
    """Renaming or adding a layer package must fail here, not go unnoticed."""
    packages = {path.parent.name for path in SRC.glob("*/__init__.py")}

    assert packages == set(FORBIDDEN)


def test_layers_never_import_upwards():
    """Every source file obeys the rule table."""
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        module = _module_name(path)
        banned_prefixes = _forbidden_for(module, path)
        if banned_prefixes is None:
            continue
        # A package's own `__init__.py` resolves relative imports against itself; an ordinary
        # submodule resolves them against its containing package (everything but its own name).
        package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
        for imported in _imported_modules(ast.parse(path.read_text(encoding="utf-8")), package):
            violations.extend(
                f"{module} imports {imported}"
                for banned in banned_prefixes
                if imported == banned or imported.startswith(f"{banned}.")
            )

    assert violations == []


def test_imported_modules_resolves_relative_import_from_package_init():
    """A package's own `__init__.py` is its own package: two levels up from `beadboard.model`
    is `beadboard`, so `from ..ui import x` written there must resolve to `beadboard.ui`, not
    to `.ui` (which is what stripping `beadboard.model` by one more segment produces)."""
    tree = ast.parse("from ..ui import x\n")

    assert _imported_modules(tree, "beadboard.model") == {"beadboard.ui", "beadboard.ui.x"}


def test_imported_modules_resolves_relative_import_from_submodule():
    """The same relative import written in an ordinary submodule (package `beadboard.service`,
    e.g. `beadboard/service/foo.py`) resolves identically, guarding the other half of the level
    arithmetic that the package-init case above exercises."""
    tree = ast.parse("from ..ui import x\n")

    assert _imported_modules(tree, "beadboard.service") == {"beadboard.ui", "beadboard.ui.x"}


def test_imported_modules_tracks_the_module_named_by_a_from_import():
    """`from beadboard import ui` names the forbidden module as an imported name, not as the
    module the import is from. Recording only the latter would report `beadboard` — which no
    rule bans — and let the upward import through."""
    tree = ast.parse("from beadboard import ui\n")

    assert "beadboard.ui" in _imported_modules(tree, "beadboard.model")


def test_imported_modules_tracks_the_module_named_by_a_bare_relative_import():
    """The relative spelling of the same import, `from .. import ui`, has no module part at
    all — the forbidden name lives only in the imported names."""
    tree = ast.parse("from .. import ui\n")

    assert "beadboard.ui" in _imported_modules(tree, "beadboard.model")


def test_only_cli_is_exempt_from_the_rule_table():
    """`cli.py` assembles the layers, so it may reach into all of them. The package's own
    `__init__.py` is a marker module, not a second composition root: it answers to
    `ROOT_FORBIDDEN` and must not be skipped the way `cli.py` is."""
    assert _forbidden_for("beadboard.cli", SRC / "cli.py") is None
    assert _forbidden_for("beadboard", SRC / "__init__.py") == ROOT_FORBIDDEN
