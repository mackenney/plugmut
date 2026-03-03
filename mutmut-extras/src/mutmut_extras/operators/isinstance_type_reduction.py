"""Mutation operator: reduce isinstance type tuples by removing one type at a time."""

from collections.abc import Iterable

import libcst as cst
import libcst.matchers as m


def operator_isinstance_type_reduction(node: cst.Call) -> Iterable[cst.Call]:
    """Remove one type at a time from isinstance(x, (A, B, ...)) tuple.

    isinstance(x, (A, B)) yields:
      - isinstance(x, A)  (B removed, tuple unwrapped)
      - isinstance(x, B)  (A removed, tuple unwrapped)
    isinstance(x, (A, B, C)) yields:
      - isinstance(x, (B, C))
      - isinstance(x, (A, C))
      - isinstance(x, (A, B))

    Skip if: not isinstance call, second arg is not a tuple, tuple has < 2 elements.
    """
    # Must be isinstance(...)
    if not m.matches(node.func, m.Name("isinstance")):
        return
    # Must have exactly 2 args
    if len(node.args) != 2:
        return
    second_arg = node.args[1].value
    # Second arg must be a Tuple
    if not isinstance(second_arg, cst.Tuple):
        return
    elements = second_arg.elements
    if len(elements) < 2:
        return

    for i in range(len(elements)):
        remaining = [e for j, e in enumerate(elements) if j != i]
        if len(remaining) == 1:
            # Unwrap single-element tuple: isinstance(x, (A,)) -> isinstance(x, A)
            new_type = remaining[0].value
        else:
            # Fix comma on last element: remove trailing comma
            fixed = []
            for j, elem in enumerate(remaining):
                if j == len(remaining) - 1:
                    # Last element: remove trailing comma
                    fixed.append(elem.with_changes(comma=cst.MaybeSentinel.DEFAULT))
                else:
                    fixed.append(elem)
            new_type = second_arg.with_changes(elements=fixed)

        new_second_arg = node.args[1].with_changes(value=new_type)
        yield node.with_changes(args=[node.args[0], new_second_arg])


operators = [(cst.Call, operator_isinstance_type_reduction)]
