"""Mutation operator: replace function body with `pass` (function deletion)."""

from collections.abc import Iterable

import libcst as cst


def operator_function_deletion(node: cst.FunctionDef) -> Iterable[cst.FunctionDef]:
    """Replace function body with `pass`, creating a 'deleted function' mutation."""
    pass_body = cst.IndentedBlock(body=[cst.SimpleStatementLine(body=[cst.Pass()])])
    if node.body.deep_equals(pass_body):
        return
    yield node.with_changes(body=pass_body)


operators = [(cst.FunctionDef, operator_function_deletion)]
