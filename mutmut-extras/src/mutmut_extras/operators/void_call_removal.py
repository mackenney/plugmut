"""Mutation operator: remove standalone function calls (void call removal)."""

from collections.abc import Iterable

import libcst as cst


def operator_void_call_removal(node: cst.SimpleStatementLine) -> Iterable[cst.SimpleStatementLine]:
    """Replace standalone call expressions with ``pass``.

    Targets lines like ``results.append(item)`` or ``logger.info("msg")``.
    Skip if body is already a single ``pass``.
    """
    if len(node.body) != 1:
        return
    stmt = node.body[0]
    if not isinstance(stmt, cst.Expr) or not isinstance(stmt.value, cst.Call):
        return
    yield node.with_changes(body=[cst.Pass()])


operators = [(cst.SimpleStatementLine, operator_void_call_removal)]
