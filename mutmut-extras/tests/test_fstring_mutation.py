import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut.file_mutation import reset_plugin_operators
from mutmut_extras.operators.fstring_mutation import (
    operator_fstring_mutation,
    operators as fstring_mutation_ops,
)


def _fstring_expr(fstring_code: str) -> cst.FormattedStringExpression:
    """Parse an f-string and extract the first FormattedStringExpression."""
    expr = cst.parse_expression(fstring_code)
    assert isinstance(expr, (cst.FormattedString, cst.ConcatenatedString))

    class _Finder(cst.CSTVisitor):
        def __init__(self):
            self.found = None

        def visit_FormattedStringExpression(self, node):
            if self.found is None:
                self.found = node

    finder = _Finder()
    expr_wrapper = cst.parse_module(f"x = {fstring_code}\n")
    expr_wrapper.visit(finder)
    assert finder.found is not None
    return finder.found


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    """Reset the plugin manager before and after each test."""
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    yield
    reset_plugin_manager()
    reset_plugin_operators()


class TestOperatorFstringMutation:
    def test_simple_name_expr(self):
        node = _fstring_expr('f"hello {name}"')
        mutants = list(operator_fstring_mutation(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].expression, cst.SimpleString)
        assert mutants[0].expression.value == "'XX'"

    def test_call_expr(self):
        node = _fstring_expr('f"result: {compute()}"')
        mutants = list(operator_fstring_mutation(node))
        assert len(mutants) == 1

    def test_complex_expr(self):
        node = _fstring_expr('f"total: {a + b}"')
        mutants = list(operator_fstring_mutation(node))
        assert len(mutants) == 1

    def test_already_xx_no_mutation(self):
        node = cst.FormattedStringExpression(expression=cst.SimpleString("'XX'"))
        mutants = list(operator_fstring_mutation(node))
        assert mutants == []


class TestFstringMutationIntegration:
    def test_create_mutations_includes_fstring_mutation(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(fstring_mutation_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = "def greet(name):\n    return f\"Hello {name}!\"\n"
        module, mutations = create_mutations(source)

        mutated_codes = []
        for mut in mutations:
            replaced = module.deep_replace(mut.original_node, mut.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("{'XX'}" in code for code in mutated_codes)
