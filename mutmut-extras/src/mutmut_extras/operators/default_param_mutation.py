"""Mutation operator: mutate default parameter values.

Only generates mutations that mutmut's builtin operators cannot produce.
Builtins already handle: True↔False, integer increment, float increment,
and string mutations wherever they appear (including param defaults).
"""

from collections.abc import Iterable

import libcst as cst
import libcst.matchers as m


def operator_default_param_mutation(node: cst.Param) -> Iterable[cst.Param]:
    """Mutate default parameter values in ways builtins don't cover.

    - ``None`` → ``0``: builtins skip None
    - Non-literal defaults (names, calls, collections, etc.) → ``None``:
      builtins only mutate literal tokens, not compound expressions
    """
    if node.default is None:
        return

    default = node.default

    _BUILTIN_NAMES = {"True", "False"}

    if m.matches(default, m.Name("None")):
        # Builtins don't mutate None; replace with a concrete sentinel value
        yield node.with_changes(default=cst.Integer("0"))
    elif isinstance(default, cst.Name) and default.value not in _BUILTIN_NAMES:
        # Non-builtin name default (e.g. SENTINEL, MISSING): builtins only flip True/False
        yield node.with_changes(default=cst.Name("None"))
    elif not isinstance(default, (cst.Name, cst.Integer, cst.Float, cst.SimpleString, cst.FormattedString, cst.ConcatenatedString)):
        # Compound/collection default ([], {}, func()): builtins can't touch these
        yield node.with_changes(default=cst.Name("None"))


operators = [(cst.Param, operator_default_param_mutation)]
