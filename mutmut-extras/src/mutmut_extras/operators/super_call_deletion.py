"""Mutation operator: delete super() method calls."""

from collections.abc import Iterable

import libcst as cst
import libcst.matchers as m


def operator_super_call_deletion(node: cst.SimpleStatementLine) -> Iterable[cst.SimpleStatementLine]:
    """Replace ``super().method(...)`` calls with ``pass``.

    Targets patterns like ``super().__init__(x, y)`` and ``super().save()``.
    """
    if len(node.body) != 1:
        return
    stmt = node.body[0]
    if not isinstance(stmt, cst.Expr) or not isinstance(stmt.value, cst.Call):
        return
    call = stmt.value
    if not m.matches(
        call.func,
        m.Attribute(value=m.Call(func=m.Name("super"))),
    ):
        return
    yield node.with_changes(body=[cst.Pass()])


operators = [(cst.SimpleStatementLine, operator_super_call_deletion)]
