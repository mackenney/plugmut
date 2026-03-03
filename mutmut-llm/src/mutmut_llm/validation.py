"""Lightweight validation for LLM-generated mutations.

Two stages:
1. Syntax check via libcst (reject unparseable code).
2. Import guard — reject mutations that introduce new imports.
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


def validate_mutation(mutated_code: str, original_code: str) -> str | None:
    """Run syntax + import validation. Return first error or None."""
    err = validate_syntax(mutated_code)
    if err:
        return err
    return validate_imports(mutated_code, original_code)


def _extract_imports(code: str) -> set[str]:
    """Extract top-level import module names from *code*."""
    try:
        module = cst.parse_module(code)
    except cst.ParserSyntaxError:
        return set()

    imports: set[str] = set()
    for stmt in module.body:
        if not isinstance(stmt, cst.SimpleStatementLine):
            continue
        for item in stmt.body:
            if isinstance(item, cst.Import):
                if isinstance(item.names, (list, tuple)):
                    for alias in item.names:
                        if isinstance(alias, cst.ImportAlias):
                            imports.add(_name_to_str(alias.name))
            elif isinstance(item, cst.ImportFrom):
                if item.module:
                    imports.add(_name_to_str(item.module))
    return imports


def _name_to_str(name: cst.BaseExpression) -> str:
    """Convert a libcst Name or Attribute to a dotted string."""
    if isinstance(name, cst.Name):
        return name.value
    if isinstance(name, cst.Attribute):
        return f"{_name_to_str(name.value)}.{name.attr.value}"
    return str(name)
