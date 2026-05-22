"""Mutation operator: replace f-string expressions with fixed string."""

from collections.abc import Iterable

import libcst as cst


def operator_fstring_mutation(node: cst.FormattedStringExpression) -> Iterable[cst.FormattedStringExpression]:
    """Replace f-string interpolated expressions with ``'XX'``.

    ``f"Hello {name}"`` becomes ``f"Hello {'XX'}"``.
    """
    if isinstance(node.expression, cst.SimpleString) and node.expression.value == "'XX'":
        return
    yield node.with_changes(expression=cst.SimpleString("'XX'"))


operators = [(cst.FormattedStringExpression, operator_fstring_mutation)]
