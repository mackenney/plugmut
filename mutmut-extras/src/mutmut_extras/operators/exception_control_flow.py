"""Mutation operator: replace except-pass bodies with break/continue/return."""

from collections.abc import Iterable

import libcst as cst


def _body_is_pass(body: cst.BaseSuite) -> bool:
    """Check if an except handler body is a single pass statement."""
    return (
        isinstance(body, cst.IndentedBlock)
        and len(body.body) == 1
        and isinstance(body.body[0], cst.SimpleStatementLine)
        and len(body.body[0].body) == 1
        and isinstance(body.body[0].body[0], cst.Pass)
    )


def _make_body(stmt: cst.BaseSmallStatement) -> cst.IndentedBlock:
    return cst.IndentedBlock(body=[cst.SimpleStatementLine(body=[stmt])])


def operator_exception_control_flow(node: cst.ExceptHandler) -> Iterable[cst.ExceptHandler]:
    """Replace except-pass bodies with break, continue, and return.

    Only operates on handlers whose body is a single `pass` statement.
    Generates break/continue (valid in loops) and return (valid in functions).
    Invalid variants (break outside loop) are filtered by mutmut's syntax validation.
    """
    if not _body_is_pass(node.body):
        return

    yield node.with_changes(body=_make_body(cst.Break()))
    yield node.with_changes(body=_make_body(cst.Continue()))
    yield node.with_changes(body=_make_body(cst.Return()))


operators = [(cst.ExceptHandler, operator_exception_control_flow)]
