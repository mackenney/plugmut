"""Mutation operator: assert <condition> -> assert True."""

from collections.abc import Iterable

import libcst as cst


def operator_assert_true(node: cst.Assert) -> Iterable[cst.Assert]:
    """Mutate ``assert <condition>`` to ``assert True``. Skip if already True."""
    if isinstance(node.test, cst.Name) and node.test.value == "True":
        return
    yield node.with_changes(test=cst.Name("True"))


operators = [(cst.Assert, operator_assert_true)]
