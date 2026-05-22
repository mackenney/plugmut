"""Mutation operator: s.strip() -> s.lstrip() and s.strip() -> s.rstrip()."""

from collections.abc import Iterable

import libcst as cst


def operator_strip_to_partial(node: cst.Call) -> Iterable[cst.Call]:
    """Mutate zero-arg strip() to lstrip() and rstrip().

    Skip if strip() has arguments (strip with custom chars is different).
    """
    if not isinstance(node.func, cst.Attribute):
        return
    if node.func.attr.value != "strip":
        return
    # Only match zero-arg calls
    if node.args:
        return
    yield node.with_deep_changes(node.func.attr, value="lstrip")
    yield node.with_deep_changes(node.func.attr, value="rstrip")


operators = [(cst.Call, operator_strip_to_partial)]
