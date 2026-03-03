"""Mutation operator: return <expr> -> return None."""

from collections.abc import Iterable

import libcst as cst
import libcst.matchers as m


def operator_return_none(node: cst.Return) -> Iterable[cst.Return]:
    """Mutate ``return <expr>`` to ``return None``. Skip bare return and return None."""
    if node.value is None:
        return
    if m.matches(node.value, m.Name("None")):
        return
    yield node.with_changes(value=cst.Name("None"))


operators = [(cst.Return, operator_return_none)]
