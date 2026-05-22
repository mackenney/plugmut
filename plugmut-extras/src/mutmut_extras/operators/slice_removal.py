"""Mutation operator: remove individual components of slice expressions."""

from collections.abc import Iterable

import libcst as cst


def operator_slice_removal(node: cst.Slice) -> Iterable[cst.Slice]:
    """Remove each non-None component (lower, upper, step) of a slice, one at a time."""
    if node.lower is not None:
        yield node.with_changes(lower=None)

    if node.upper is not None:
        yield node.with_changes(upper=None)

    if node.step is not None:
        yield node.with_changes(step=None, second_colon=cst.MaybeSentinel.DEFAULT)


operators = [(cst.Slice, operator_slice_removal)]
