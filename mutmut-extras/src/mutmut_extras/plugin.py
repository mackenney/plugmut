"""mutmut-extras plugin: registers additional mutation operators via pluggy."""

from mutmut.hookspecs import hookimpl
from mutmut.node_mutation import OPERATORS_TYPE

from mutmut_extras.operators.assert_true import operators as assert_true_ops
from mutmut_extras.operators.comprehension_filter import operators as comprehension_filter_ops
from mutmut_extras.operators.default_param_mutation import operators as default_param_ops
from mutmut_extras.operators.exception_handler import operators as exception_handler_ops
from mutmut_extras.operators.fstring_mutation import operators as fstring_ops
from mutmut_extras.operators.return_none import operators as return_none_ops
from mutmut_extras.operators.reverse_iteration import operators as reverse_iteration_ops
from mutmut_extras.operators.slice_removal import operators as slice_removal_ops
from mutmut_extras.operators.super_call_deletion import operators as super_call_ops
from mutmut_extras.operators.ternary import operators as ternary_ops
from mutmut_extras.operators.void_call_removal import operators as void_call_ops
from mutmut_extras.operators.yield_mutation import operators as yield_mutation_ops


@hookimpl
def mutmut_register_operators() -> OPERATORS_TYPE:
    return [
        *return_none_ops,
        *exception_handler_ops,
        *ternary_ops,
        *assert_true_ops,
        *slice_removal_ops,
        *void_call_ops,
        *yield_mutation_ops,
        *comprehension_filter_ops,
        *super_call_ops,
        *fstring_ops,
        *default_param_ops,
        *reverse_iteration_ops,
    ]
