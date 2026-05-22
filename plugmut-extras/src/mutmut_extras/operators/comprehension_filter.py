"""Mutation operator: remove comprehension filter (if clause)."""

from collections.abc import Iterable

import libcst as cst


def operator_comprehension_filter_removal(node: cst.CompFor) -> Iterable[cst.CompFor]:
    """Remove the ``if`` clause from a comprehension's ``for`` clause.

    ``[x for x in items if x > 0]`` becomes ``[x for x in items]``.
    """
    if not node.ifs:
        return
    yield node.with_changes(ifs=())


operators = [(cst.CompFor, operator_comprehension_filter_removal)]
