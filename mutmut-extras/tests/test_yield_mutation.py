import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut.file_mutation import reset_plugin_operators
from mutmut_extras.operators.yield_mutation import (
    operator_yield_mutation,
    operators as yield_mutation_ops,
)


def _yield_node(code: str) -> cst.Yield:
    """Parse a function containing a yield and extract the Yield node."""
    module = cst.parse_module(f"def _gen():\n    {code}\n")
    func = module.body[0]
    assert isinstance(func, cst.FunctionDef)
    assert isinstance(func.body, cst.IndentedBlock)
    stmt_line = func.body.body[0]
    assert isinstance(stmt_line, cst.SimpleStatementLine)
    expr_stmt = stmt_line.body[0]
    assert isinstance(expr_stmt, cst.Expr)
    assert isinstance(expr_stmt.value, cst.Yield)
    return expr_stmt.value


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    """Reset the plugin manager before and after each test."""
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    yield
    reset_plugin_manager()
    reset_plugin_operators()


class TestOperatorYieldMutation:
    def test_yield_expr_becomes_none(self):
        node = _yield_node("yield item")
        mutants = list(operator_yield_mutation(node))
        assert len(mutants) == 1
        val = mutants[0].value
        assert isinstance(val, cst.Name)
        assert val.value == "None"

    def test_yield_call_becomes_none(self):
        node = _yield_node("yield compute()")
        mutants = list(operator_yield_mutation(node))
        assert len(mutants) == 1
        val = mutants[0].value
        assert isinstance(val, cst.Name)
        assert val.value == "None"

    def test_bare_yield_becomes_zero(self):
        node = _yield_node("yield")
        mutants = list(operator_yield_mutation(node))
        assert len(mutants) == 1
        val = mutants[0].value
        assert isinstance(val, cst.Integer)
        assert val.value == "0"

    def test_yield_none_no_mutation(self):
        node = _yield_node("yield None")
        mutants = list(operator_yield_mutation(node))
        assert mutants == []

    def test_yield_from_no_mutation(self):
        node = _yield_node("yield from items")
        mutants = list(operator_yield_mutation(node))
        assert mutants == []


class TestYieldMutationIntegration:
    def test_create_mutations_includes_yield_mutation(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(yield_mutation_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = "def gen():\n    yield 42\n"
        module, mutations = create_mutations(source)

        mutated_codes = []
        for mut in mutations:
            replaced = module.deep_replace(mut.original_node, mut.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("yield None" in code for code in mutated_codes)
