"""Mutation operator: mutate default parameter values."""

from collections.abc import Iterable

import libcst as cst
import libcst.matchers as m


def operator_default_param_mutation(node: cst.Param) -> Iterable[cst.Param]:
    """Mutate default parameter values.

    ``def f(x=False, limit=100)`` becomes ``def f(x=True, limit=101)``.
    """
    if node.default is None:
        return

    default = node.default
    new_default: cst.BaseExpression | None = None

    if m.matches(default, m.Name("True")):
        new_default = cst.Name("False")
    elif m.matches(default, m.Name("False")):
        new_default = cst.Name("True")
    elif m.matches(default, m.Name("None")):
        new_default = cst.Integer("0")
    elif isinstance(default, cst.Integer):
        new_default = cst.Integer(str(int(default.value) + 1))
    elif isinstance(default, cst.Float):
        new_default = cst.Float(str(float(default.value) + 1.0))
    else:
        new_default = cst.Name("None")

    if new_default is not None:
        yield node.with_changes(default=new_default)


operators = [(cst.Param, operator_default_param_mutation)]
