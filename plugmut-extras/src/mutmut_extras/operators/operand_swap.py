"""Mutation operator: swap operands of non-commutative binary operations."""

from collections.abc import Iterable

import libcst as cst

NON_COMMUTATIVE_OPS = (
    cst.Subtract,
    cst.Divide,
    cst.FloorDivide,
    cst.Modulo,
    cst.Power,
)


def operator_operand_swap(node: cst.BinaryOperation) -> Iterable[cst.BinaryOperation]:
    """Swap left and right operands for non-commutative operators.

    a - b -> b - a, a / b -> b / a, a // b -> b // a, a % b -> b % a, a ** b -> b ** a.
    Skip commutative operators (Add, Multiply, BitAnd, BitOr, BitXor).
    """
    if not isinstance(node.operator, NON_COMMUTATIVE_OPS):
        return
    yield node.with_changes(left=node.right, right=node.left)


operators = [(cst.BinaryOperation, operator_operand_swap)]
