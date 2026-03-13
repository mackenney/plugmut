from __future__ import annotations

from mutmut.hookspecs import hookimpl
from mutmut_dedup.bytecode import bytecode_filter
from mutmut_dedup.normalize import deduplicate


@hookimpl(trylast=True)
def mutmut_filter_mutations(filename: str, mutations: list) -> list | None:
    result = deduplicate(mutations)
    result = bytecode_filter(result)
    if len(result) < len(mutations):
        return result
    return None
