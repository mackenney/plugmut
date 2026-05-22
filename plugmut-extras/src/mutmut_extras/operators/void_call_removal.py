"""Mutation operator: remove standalone function calls (void call removal)."""

from collections.abc import Iterable

import libcst as cst
import libcst.matchers as m


def operator_void_call_removal(node: cst.SimpleStatementLine) -> Iterable[cst.SimpleStatementLine]:
    """Replace standalone call expressions with ``pass``.

    Targets lines like ``results.append(item)`` or ``logger.info("msg")``.
    Skip if body is already a single ``pass``.
    Skips ``super().method()`` calls — those are handled by super_call_deletion.
    """
    if len(node.body) != 1:
        return
    stmt = node.body[0]
    if not isinstance(stmt, cst.Expr) or not isinstance(stmt.value, cst.Call):
        return
    call = stmt.value
    if m.matches(call.func, m.Attribute(value=m.Call(func=m.Name("super")))):
        return
    yield node.with_changes(body=[cst.Pass()])


operators = [(cst.SimpleStatementLine, operator_void_call_removal)]
