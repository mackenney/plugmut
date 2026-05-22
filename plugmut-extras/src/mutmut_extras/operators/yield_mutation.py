"""Mutation operator: mutate yield expressions."""

from collections.abc import Iterable

import libcst as cst
import libcst.matchers as m


def operator_yield_mutation(node: cst.Yield) -> Iterable[cst.Yield]:
    """Mutate yield expressions.

    ``yield expr`` becomes ``yield None`` (skip if already None).
    Bare ``yield`` becomes ``yield 0``.
    ``yield from`` is skipped.
    """
    if isinstance(node.value, cst.From):
        return
    if node.value is None:
        # bare yield → yield 0
        yield node.with_changes(value=cst.Integer("0"))
        return
    if m.matches(node.value, m.Name("None")):
        return
    yield node.with_changes(value=cst.Name("None"))


operators = [(cst.Yield, operator_yield_mutation)]
