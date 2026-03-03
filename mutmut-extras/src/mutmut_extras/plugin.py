"""mutmut-extras plugin: registers additional mutation operators via pluggy."""

from mutmut.hookspecs import hookimpl
from mutmut.node_mutation import OPERATORS_TYPE

from mutmut_extras.operators.assert_true import operators as assert_true_ops
from mutmut_extras.operators.exception_handler import operators as exception_handler_ops
from mutmut_extras.operators.return_none import operators as return_none_ops
from mutmut_extras.operators.slice_removal import operators as slice_removal_ops
from mutmut_extras.operators.ternary import operators as ternary_ops


@hookimpl
def mutmut_register_operators() -> OPERATORS_TYPE:
    return [
        *return_none_ops,
        *exception_handler_ops,
        *ternary_ops,
        *assert_true_ops,
        *slice_removal_ops,
    ]
