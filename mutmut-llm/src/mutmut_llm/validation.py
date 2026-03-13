"""Lightweight validation for LLM-generated mutations.

Three stages:
1. Syntax check via libcst (reject unparseable code).
2. Import guard — reject mutations that introduce new imports.
3. Pragma guard — reject mutations that modify ``# pragma: no mutate`` lines.
"""

from __future__ import annotations

import libcst as cst


def validate_syntax(code: str) -> str | None:
    """Return None if *code* parses, or an error message."""
    try:
        cst.parse_module(code)
        return None
    except cst.ParserSyntaxError as e:
        return f"Syntax error: {e}"


def validate_imports(mutated_code: str, original_code: str) -> str | None:
    """Return None if no new imports, or an error message listing them."""
    original = _extract_imports(original_code)
    mutated = _extract_imports(mutated_code)
    new = mutated - original
    if new:
        return f"New imports: {', '.join(sorted(new))}"
    return None


def _has_pragma(line: str) -> bool:
    """Detect ``# pragma: no mutate`` in *line*, case-insensitively and regardless of spacing after ``#``."""
    stripped = line.lstrip()
    idx = stripped.find("#")
    if idx == -1:
        return False
    comment = " ".join(stripped[idx + 1 :].split()).lower()
    return "pragma: no mutate" in comment


def validate_pragmas(mutated_code: str, original_code: str) -> str | None:
    """Reject mutations that modify lines marked with ``# pragma: no mutate``."""
    original_lines = original_code.splitlines()
    mutated_lines = mutated_code.splitlines()

    pragma_lines = [
        (i, line) for i, line in enumerate(original_lines) if _has_pragma(line)
    ]

    if not pragma_lines:
        return None

    for idx, original_line in pragma_lines:
        if idx >= len(mutated_lines) or mutated_lines[idx] != original_line:
            return f"Pragma-marked line modified: {original_line.strip()!r}"

    return None


def validate_mutation(mutated_code: str, original_code: str) -> str | None:
    """Run syntax + import + pragma validation. Return first error or None."""
    err = validate_syntax(mutated_code)
    if err:
        return err
    err = validate_imports(mutated_code, original_code)
    if err:
        return err
    return validate_pragmas(mutated_code, original_code)


class _ImportCollector(cst.CSTVisitor):
    """Walks the entire tree to find imports at any nesting level."""

    def __init__(self) -> None:
        self.imports: set[str] = set()

    def visit_Import(self, node: cst.Import) -> None:
        if isinstance(node.names, (list, tuple)):
            for alias in node.names:
                if isinstance(alias, cst.ImportAlias):
                    self.imports.add(_name_to_str(alias.name))

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if node.module:
            self.imports.add(_name_to_str(node.module))


def _extract_imports(code: str) -> set[str]:
    """Extract all import module names from *code*, including nested scopes."""
    try:
        module = cst.parse_module(code)
    except cst.ParserSyntaxError:
        return set()

    collector = _ImportCollector()
    module.visit(collector)
    return collector.imports


def _name_to_str(name: cst.BaseExpression) -> str:
    """Convert a libcst Name or Attribute to a dotted string."""
    if isinstance(name, cst.Name):
        return name.value
    if isinstance(name, cst.Attribute):
        return f"{_name_to_str(name.value)}.{name.attr.value}"
    return str(name)
