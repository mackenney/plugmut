"""LLM mutation operator for mutmut.

Reads pre-generated mutations from the Library (populated by ``mutmut generate``)
and yields mutated ``FunctionDef`` nodes through mutmut's standard operator interface.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable

import libcst as cst

from mutmut_llm.library import Library, source_hash

_library: Library | None = None


def set_library(library: Library) -> None:
    """Set the Library instance for operator use. Called by plugin during configure."""
    global _library
    _library = library


def reset_library() -> None:
    """Reset the Library instance. For testing."""
    global _library
    _library = None

def operator_llm(node: cst.FunctionDef) -> Iterable[cst.FunctionDef]:
    """Yield LLM-generated mutations for a function.

    Looks up pre-generated mutations by source hash via Library.query().
    Returns nothing when no Library is configured or no entries match.
    """
    if _library is None:
        return

    func_source = cst.Module(body=[node]).code
    src_hash = source_hash(func_source)

    entries = _library.query(src_hash)
    if not entries:
        return

    func_name = node.name.value
    seen: set[str] = set()
    for entry in entries:
        for mutation in entry.mutations:
            code = mutation["mutated_code"]
            if code in seen:
                continue
            seen.add(code)
            mutated_node = _parse_mutation(code, func_name)
            if mutated_node is not None:
                yield mutated_node


def _parse_mutation(mutated_code: str, func_name: str) -> cst.FunctionDef | None:
    """Parse mutated code into a FunctionDef node matching *func_name*.

    Returns None if code is invalid or doesn't contain the expected function.
    """
    try:
        module = cst.parse_module(mutated_code)
    except cst.ParserSyntaxError:
        warnings.warn(
            f"LLM mutation for {func_name} has invalid syntax, skipping", stacklevel=2
        )
        return None

    for stmt in module.body:
        if isinstance(stmt, cst.FunctionDef) and stmt.name.value == func_name:
            return stmt

    warnings.warn(
        f"LLM mutation for {func_name} doesn't contain expected function definition, skipping",
        stacklevel=2,
    )
    return None
