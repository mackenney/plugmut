"""Mutation operator: remove +1/-1 boundary offsets from binary expressions."""

from collections.abc import Iterable

import libcst as cst


def _is_integer_one(node: cst.BaseExpression) -> bool:
    return isinstance(node, cst.Integer) and node.value == "1"


def operator_remove_boundary_offset(node: cst.BinaryOperation) -> Iterable[cst.BaseExpression]:
    """Remove +1/-1 boundary offsets.

    expr + 1 -> expr
    expr - 1 -> expr
    1 + expr -> expr
    """
    if isinstance(node.operator, (cst.Add, cst.Subtract)) and _is_integer_one(node.right):
        yield node.left
    elif isinstance(node.operator, cst.Add) and _is_integer_one(node.left):
        yield node.right


operators = [(cst.BinaryOperation, operator_remove_boundary_offset)]
