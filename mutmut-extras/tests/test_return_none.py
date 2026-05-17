import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut.file_mutation import reset_plugin_operators
from mutmut_extras.operators.return_none import (
    operator_return_none,
    operators as return_none_ops,
)


def _return_node(code: str) -> cst.Return:
    """Parse a return statement and extract the Return CST node."""
    stmt = cst.parse_statement(code)
    assert isinstance(stmt, cst.SimpleStatementLine)
    node = stmt.body[0]
    assert isinstance(node, cst.Return)
    return node


class TestOperatorReturnNone:
    def test_return_int(self):
        node = _return_node("return 42")
        mutants = list(operator_return_none(node))
        assert len(mutants) == 1
        val = mutants[0].value
        assert isinstance(val, cst.Name)
        assert val.value == "None"

    def test_return_name(self):
        node = _return_node("return x")
        mutants = list(operator_return_none(node))
        assert len(mutants) == 1
        val = mutants[0].value
        assert isinstance(val, cst.Name)
        assert val.value == "None"

    def test_return_call(self):
        node = _return_node("return foo()")
        mutants = list(operator_return_none(node))
        assert len(mutants) == 1
        val = mutants[0].value
        assert isinstance(val, cst.Name)
        assert val.value == "None"

    def test_bare_return_no_mutation(self):
        node = _return_node("return")
        mutants = list(operator_return_none(node))
        assert mutants == []

    def test_return_none_no_mutation(self):
        node = _return_node("return None")
        mutants = list(operator_return_none(node))
        assert mutants == []


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    """Reset the plugin manager before and after each test."""
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    yield
    reset_plugin_manager()
    reset_plugin_operators()


class TestReturnNoneIntegration:
    def test_create_mutations_includes_return_none(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(return_none_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = "def foo(): return 42"
        module, mutations = create_mutations(source)

        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("return None" in code for code in mutated_codes)
