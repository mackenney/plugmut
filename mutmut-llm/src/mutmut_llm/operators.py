"""LLM mutation operator for mutmut.

Reads pre-generated mutations from the file cache (populated by ``mutmut generate``)
and yields mutated ``FunctionDef`` nodes through mutmut's standard operator interface.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable

import libcst as cst

from mutmut_llm.cache import CacheEntry, list_cache_entries, source_hash

_cache_index: dict[str, list[CacheEntry]] | None = None


def _reset_cache_index() -> None:
    """Reset the in-memory cache index (for tests)."""
    global _cache_index
    _cache_index = None


def _build_cache_index() -> dict[str, list[CacheEntry]]:
    """Build index from all cache entries, keyed by source_hash.

    source_hash is the primary key — avoids bare-vs-qualified name mismatch
    (operator sees "bar", cache may store "Foo.bar").
    Values are lists so entries from multiple models and identical functions
    in different files all coexist instead of overwriting each other.
    """
    index: dict[str, list[CacheEntry]] = {}
    for entry in list_cache_entries():
        index.setdefault(entry.source_hash, []).append(entry)
    return index


def _get_cache_index() -> dict[str, list[CacheEntry]]:
    """Get or build the cache index."""
    global _cache_index
    if _cache_index is None:
        _cache_index = _build_cache_index()
    return _cache_index


def operator_llm(node: cst.FunctionDef) -> Iterable[cst.FunctionDef]:
    """Yield LLM-generated mutations for a function.

    Looks up pre-generated mutations by source hash. Merges mutations from
    all cached models, deduplicated by mutated_code.
    """
    func_source = cst.Module(body=[node]).code
    src_hash = source_hash(func_source)

    index = _get_cache_index()
    entries = index.get(src_hash, [])
    if not entries:
        return

    func_name = node.name.value
    seen: set[str] = set()
    for entry in entries:
        for cached in entry.mutations:
            if cached.mutated_code in seen:
                continue
            seen.add(cached.mutated_code)
            mutated_node = _parse_mutation(cached.mutated_code, func_name)
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
