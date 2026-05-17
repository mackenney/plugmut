from __future__ import annotations

from typing import TYPE_CHECKING

from mutmut.normalize import normalize_mutation, normalize_pair

if TYPE_CHECKING:
    from mutmut.file_mutation import Mutation

__all__ = ["normalize_mutation", "normalize_pair", "deduplicate"]


def deduplicate(mutations: list[Mutation]) -> list[Mutation]:
    """Remove mutations whose normalized mutated_node matches another at the same original_node.

    First occurrence wins.
    """
    if not mutations:
        return mutations

    seen_by_site: dict[int, set[str]] = {}

    result: list[Mutation] = []
    for m in mutations:
        site_id = id(m.original_node)
        seen = seen_by_site.setdefault(site_id, set())
        norm = normalize_mutation(m.mutated_node)
        if norm not in seen:
            seen.add(norm)
            result.append(m)

    return result
