"""Mutation operator: reverse iteration order in for loops."""

from collections.abc import Iterable

import libcst as cst
import libcst.matchers as m


def operator_reverse_iteration(node: cst.For) -> Iterable[cst.For]:
    """Wrap for-loop iterable in ``reversed()``.

    ``for item in items:`` becomes ``for item in reversed(items):``.
    """
    iter_expr = node.iter
    if isinstance(iter_expr, cst.Call) and m.matches(iter_expr.func, m.Name("reversed")):
        return
    reversed_call = cst.Call(
        func=cst.Name("reversed"),
        args=[cst.Arg(value=iter_expr)],
    )
    yield node.with_changes(iter=reversed_call)


operators = [(cst.For, operator_reverse_iteration)]
