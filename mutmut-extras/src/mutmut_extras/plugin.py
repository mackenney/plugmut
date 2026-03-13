"""mutmut-extras plugin: registers additional mutation operators via pluggy."""

from mutmut.hookspecs import hookimpl
from mutmut.node_mutation import OPERATORS_TYPE

from mutmut_extras.operators.assert_true import operators as assert_true_ops
from mutmut_extras.operators.comprehension_filter import (
    operators as comprehension_filter_ops,
)
from mutmut_extras.operators.default_param_mutation import (
    operators as default_param_ops,
)
from mutmut_extras.operators.exception_control_flow import (
    operators as exception_control_flow_ops,
)
from mutmut_extras.operators.exception_handler import operators as exception_handler_ops
from mutmut_extras.operators.exception_type_broadening import (
    operators as exception_type_broadening_ops,
)
from mutmut_extras.operators.fstring_mutation import operators as fstring_ops
from mutmut_extras.operators.function_deletion import operators as function_deletion_ops
from mutmut_extras.operators.operand_swap import operators as operand_swap_ops
from mutmut_extras.operators.remove_boundary_offset import (
    operators as boundary_offset_ops,
)
from mutmut_extras.operators.return_none import operators as return_none_ops
from mutmut_extras.operators.reverse_iteration import operators as reverse_iteration_ops
from mutmut_extras.operators.slice_removal import operators as slice_removal_ops
from mutmut_extras.operators.startswith_endswith_swap import (
    operators as startswith_endswith_ops,
)
from mutmut_extras.operators.strip_to_partial import operators as strip_to_partial_ops
from mutmut_extras.operators.super_call_deletion import operators as super_call_ops
from mutmut_extras.operators.ternary import operators as ternary_ops
from mutmut_extras.operators.void_call_removal import operators as void_call_ops
from mutmut_extras.operators.yield_mutation import operators as yield_mutation_ops


def _tag_operators(ops: OPERATORS_TYPE, source: str) -> OPERATORS_TYPE:
    """Stamp each operator callable with __mutmut_source__ so the core can track attribution."""
    for _node_type, func in ops:
        func.__mutmut_source__ = source  # type: ignore[attr-defined]
    return ops


@hookimpl
def mutmut_register_operators() -> OPERATORS_TYPE:
    all_ops: OPERATORS_TYPE = [
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
        *function_deletion_ops,
        *default_param_ops,
        *reverse_iteration_ops,
        *startswith_endswith_ops,
        *strip_to_partial_ops,
        *operand_swap_ops,
        *boundary_offset_ops,
        *exception_type_broadening_ops,
        *exception_control_flow_ops,
    ]
    return _tag_operators(all_ops, "mutmut-extras")
