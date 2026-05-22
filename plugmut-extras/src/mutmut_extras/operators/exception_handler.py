"""Mutation operator that replaces exception handler bodies with `pass`."""

from collections.abc import Iterable

import libcst as cst


def operator_exception_handler(node: cst.ExceptHandler) -> Iterable[cst.ExceptHandler]:
    """Replace the body of an except handler with ``pass``.

    Skip if the body is already a single ``pass`` statement.
    """
    if (
        isinstance(node.body, cst.IndentedBlock)
        and len(node.body.body) == 1
        and isinstance(node.body.body[0], cst.SimpleStatementLine)
        and len(node.body.body[0].body) == 1
        and isinstance(node.body.body[0].body[0], cst.Pass)
    ):
        return

    yield node.with_changes(
        body=cst.IndentedBlock(body=[cst.SimpleStatementLine(body=[cst.Pass()])]),
    )


operators = [(cst.ExceptHandler, operator_exception_handler)]
