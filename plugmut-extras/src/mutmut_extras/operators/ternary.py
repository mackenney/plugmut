"""Mutation operator for ternary/conditional expressions (x if cond else y)."""

from collections.abc import Iterable

import libcst as cst


def operator_ternary(node: cst.IfExp) -> Iterable[cst.CSTNode]:
    """Mutate ternary expressions: ``x if cond else y`` -> ``x``, ``y``, or swap branches."""
    # Yielding node.body and node.orelse (both BaseExpression) to replace a
    # cst.IfExp (also BaseExpression) is safe: deep_replace handles the
    # substitution correctly in any expression context -- assignments, returns,
    # binary ops, function arguments, list comprehensions, f-strings, etc.
    # Verified by test_syntax_validation.py across all these contexts.

    yield node.body
    yield node.orelse
    yield node.with_changes(body=node.orelse, orelse=node.body)


operators = [(cst.IfExp, operator_ternary)]
