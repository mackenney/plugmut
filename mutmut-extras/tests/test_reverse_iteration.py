import textwrap

import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut_extras.operators.reverse_iteration import (
    operator_reverse_iteration,
    operators as reverse_iteration_ops,
)


def _for_node(code: str) -> cst.For:
    """Parse a for loop and return the For node."""
    module = cst.parse_module(textwrap.dedent(code))
    stmt = module.body[0]
    assert isinstance(stmt, cst.For)
    return stmt


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    """Reset the plugin manager before and after each test."""
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    yield
    reset_plugin_manager()


class TestOperatorReverseIteration:
    def test_simple_for_loop(self):
        node = _for_node("for x in items:\n    pass\n")
        mutants = list(operator_reverse_iteration(node))
        assert len(mutants) == 1
        call = mutants[0].iter
        assert isinstance(call, cst.Call)
        assert isinstance(call.func, cst.Name) and call.func.value == "reversed"
        assert isinstance(call.args[0].value, cst.Name) and call.args[0].value.value == "items"

    def test_for_range(self):
        node = _for_node("for i in range(10):\n    pass\n")
        mutants = list(operator_reverse_iteration(node))
        assert len(mutants) == 1
        call = mutants[0].iter
        assert isinstance(call, cst.Call)
        assert isinstance(call.func, cst.Name) and call.func.value == "reversed"
        # The wrapped expression is range(10)
        inner = call.args[0].value
        assert isinstance(inner, cst.Call)
        assert isinstance(inner.func, cst.Name) and inner.func.value == "range"

    def test_for_enumerate(self):
        node = _for_node("for i, x in enumerate(items):\n    pass\n")
        mutants = list(operator_reverse_iteration(node))
        assert len(mutants) == 1

    def test_already_reversed_no_mutation(self):
        node = _for_node("for x in reversed(items):\n    pass\n")
        mutants = list(operator_reverse_iteration(node))
        assert mutants == []

    def test_async_for_no_mutation(self):
        # reversed() breaks async iteration protocol; async for must be skipped
        code = "async def f():\n    async for x in aiter:\n        pass\n"
        module = cst.parse_module(code)
        func = module.body[0]
        assert isinstance(func, cst.FunctionDef)
        stmt = func.body.body[0]
        assert isinstance(stmt, cst.For)
        mutants = list(operator_reverse_iteration(stmt))
        assert mutants == []

class TestReverseIterationIntegration:
    def test_create_mutations_includes_reverse_iteration(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(reverse_iteration_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = "def process(items):\n    for item in items:\n        pass\n"
        module, mutations = create_mutations(source)

        mutated_codes = []
        for mut in mutations:
            replaced = module.deep_replace(mut.original_node, mut.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("reversed(items)" in code for code in mutated_codes)
