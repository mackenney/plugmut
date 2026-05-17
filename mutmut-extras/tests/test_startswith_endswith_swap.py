import textwrap

import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut.file_mutation import reset_plugin_operators
from mutmut_extras.operators.startswith_endswith_swap import (
    operator_startswith_endswith_swap,
    operators as startswith_endswith_ops,
)


def _call_node(code: str) -> cst.Call:
    """Parse an expression and return the Call node."""
    expr = cst.parse_expression(code)
    assert isinstance(expr, cst.Call)
    return expr


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    yield
    reset_plugin_manager()
    reset_plugin_operators()


class TestOperatorStartswithEndswithSwap:
    def test_startswith_to_endswith(self):
        node = _call_node('s.startswith("foo")')
        mutants = list(operator_startswith_endswith_swap(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].func, cst.Attribute)
        assert mutants[0].func.attr.value == "endswith"

    def test_endswith_to_startswith(self):
        node = _call_node('s.endswith("bar")')
        mutants = list(operator_startswith_endswith_swap(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].func, cst.Attribute)
        assert mutants[0].func.attr.value == "startswith"

    def test_other_method_no_mutation(self):
        node = _call_node('s.find("x")')
        mutants = list(operator_startswith_endswith_swap(node))
        assert mutants == []

    def test_plain_function_call_no_mutation(self):
        node = _call_node("foo()")
        mutants = list(operator_startswith_endswith_swap(node))
        assert mutants == []

    def test_no_args_still_mutates(self):
        # startswith/endswith with no args is invalid Python at runtime but CST allows it
        node = _call_node("s.startswith()")
        mutants = list(operator_startswith_endswith_swap(node))
        assert len(mutants) == 1
        assert mutants[0].func.attr.value == "endswith"

    def test_multiple_args(self):
        # startswith accepts a tuple arg
        node = _call_node('s.startswith(("a", "b"))')
        mutants = list(operator_startswith_endswith_swap(node))
        assert len(mutants) == 1
        assert mutants[0].func.attr.value == "endswith"

    def test_chained_call(self):
        # x.strip().startswith("foo") — the outer call is startswith
        node = _call_node('x.strip().startswith("foo")')
        mutants = list(operator_startswith_endswith_swap(node))
        assert len(mutants) == 1
        assert mutants[0].func.attr.value == "endswith"


class TestStartswithEndswithIntegration:
    def test_create_mutations_swaps(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(startswith_endswith_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent('''\
            def foo(s):
                return s.startswith("prefix")
        ''')
        module, mutations = create_mutations(source)
        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any('endswith("prefix")' in code for code in mutated_codes)

    def test_endswith_integration(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(startswith_endswith_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent('''\
            def foo(s):
                return s.endswith(".py")
        ''')
        module, mutations = create_mutations(source)
        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any('startswith(".py")' in code for code in mutated_codes)
