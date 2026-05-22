from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING
from typing import cast

import libcst as cst

if TYPE_CHECKING:
    from mutmut.file_mutation import Mutation

_HAS_EXCEPTION_TABLE = sys.version_info >= (3, 11)


def _extract_signature(code: types.CodeType) -> tuple:
    """Recursively extract comparison-relevant fields from code object.

    Excludes metadata (line numbers, filename, stack size) — only semantic fields.
    Includes calling convention fields (argcount, posonly, kwonly) to distinguish
    functions with different signatures that produce identical bytecode bodies.
    """
    base = (
        code.co_code,
        tuple(_extract_signature(c) if isinstance(c, types.CodeType) else c for c in code.co_consts),
        code.co_names,
        code.co_varnames,
        code.co_freevars,
        code.co_cellvars,
        code.co_flags,
        code.co_name,
        code.co_argcount,
        code.co_posonlyargcount,
        code.co_kwonlyargcount,
    )
    if _HAS_EXCEPTION_TABLE:
        return base + (code.co_exceptiontable,)
    return base


def bytecode_signature(source: str) -> tuple | None:
    """Compile source and extract a comparison-relevant signature tuple.

    Returns None if source fails to compile (SyntaxError).
    """
    try:
        code = compile(source, "<mutant>", "exec")
    except SyntaxError:
        return None
    return _extract_signature(code)


def is_equivalent(original_source: str, mutated_source: str) -> bool:
    """True if original and mutated compile to identical bytecode signatures."""
    orig_sig = bytecode_signature(original_source)
    mut_sig = bytecode_signature(mutated_source)
    if orig_sig is None or mut_sig is None:
        return False
    return orig_sig == mut_sig


def group_by_bytecode(sources: list[str]) -> dict[tuple, list[int]]:
    """Group source strings by their bytecode signature.
    Returns {signature: [indices]}. Groups of size >1 are duplicates.
    Sources that fail to compile are excluded.
    """
    groups: dict[tuple, list[int]] = {}
    for i, source in enumerate(sources):
        sig = bytecode_signature(source)
        if sig is not None:
            groups.setdefault(sig, []).append(i)
    return groups


def bytecode_filter(mutations: list[Mutation]) -> list[Mutation]:
    """Remove mutations that are bytecode-equivalent to the original or bytecode-duplicates of each other.

    Mutations without contained_by_top_level_function (module-level) are always kept.
    If source reconstruction or compilation fails, the mutation is conservatively kept.
    """
    kept: list[Mutation] = []
    seen: dict[tuple, int] = {}

    for mutation in mutations:
        func = mutation.contained_by_top_level_function
        if func is None:
            kept.append(mutation)
            continue

        try:
            func_node = cast(cst.BaseCompoundStatement, func)
            orig_source = cst.Module(body=[func_node]).code
            mutated_func = func_node.deep_replace(mutation.original_node, mutation.mutated_node)
            mut_source = cst.Module(body=[cast(cst.BaseCompoundStatement, mutated_func)]).code
        except (SyntaxError, TypeError, ValueError, AttributeError):
            kept.append(mutation)
            continue

        # deep_replace returns the tree unchanged when original_node isn't found (identity match).
        # Without this guard, no-op replacements would be falsely classified as equivalent.
        if mutated_func is func:
            kept.append(mutation)
            continue

        orig_sig = bytecode_signature(orig_source)
        mut_sig = bytecode_signature(mut_source)

        if orig_sig is None or mut_sig is None:
            kept.append(mutation)
            continue

        if orig_sig == mut_sig:
            continue

        dedup_key = (id(mutation.original_node), id(func), mut_sig)
        if dedup_key in seen:
            continue

        seen[dedup_key] = len(kept)
        kept.append(mutation)

    return kept
