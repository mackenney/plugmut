"""Mutation operator: s.startswith(x) <-> s.endswith(x)."""

from collections.abc import Iterable

import libcst as cst
import libcst.matchers as m


def operator_startswith_endswith_swap(node: cst.Call) -> Iterable[cst.Call]:
    """Swap startswith/endswith calls."""
    # Match: something.startswith(...) or something.endswith(...)
    # node.func must be cst.Attribute with attr.value in {"startswith", "endswith"}
    if not isinstance(node.func, cst.Attribute):
        return
    attr_name = node.func.attr.value
    if attr_name == "startswith":
        yield node.with_deep_changes(node.func.attr, value="endswith")
    elif attr_name == "endswith":
        yield node.with_deep_changes(node.func.attr, value="startswith")


operators = [(cst.Call, operator_startswith_endswith_swap)]
