import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut_extras.operators.void_call_removal import (
    operator_void_call_removal,
    operators as void_call_removal_ops,
)


def _parse_stmt(code: str) -> cst.SimpleStatementLine:
    """Parse a statement and assert it's a SimpleStatementLine."""
    stmt = cst.parse_statement(code)
    assert isinstance(stmt, cst.SimpleStatementLine)
    return stmt


class TestOperatorVoidCallRemoval:
    def test_standalone_function_call(self):
        node = _parse_stmt("foo()")
        mutants = list(operator_void_call_removal(node))
        assert len(mutants) == 1
        assert len(mutants[0].body) == 1
        assert isinstance(mutants[0].body[0], cst.Pass)

    def test_method_call(self):
        node = _parse_stmt("obj.method()")
        mutants = list(operator_void_call_removal(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].body[0], cst.Pass)

    def test_chained_method_call(self):
        node = _parse_stmt("obj.method().chain()")
        mutants = list(operator_void_call_removal(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].body[0], cst.Pass)

    def test_non_call_expr_no_mutation(self):
        node = _parse_stmt("x")
        mutants = list(operator_void_call_removal(node))
        assert mutants == []

    def test_assignment_no_mutation(self):
        node = _parse_stmt("x = foo()")
        mutants = list(operator_void_call_removal(node))
        assert mutants == []

    def test_multiple_statements_no_mutation(self):
        node = _parse_stmt("foo(); bar()")
        mutants = list(operator_void_call_removal(node))
        assert mutants == []


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    """Reset the plugin manager before and after each test."""
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    yield
    reset_plugin_manager()


class TestVoidCallRemovalIntegration:
    def test_create_mutations_includes_void_call_removal(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(void_call_removal_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = "def foo():\n    bar()\n    return 1"
        module, mutations = create_mutations(source)

        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("pass" in code for code in mutated_codes)
