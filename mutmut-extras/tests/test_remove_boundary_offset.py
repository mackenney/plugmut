import textwrap

import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut.file_mutation import reset_plugin_operators
from mutmut_extras.operators.remove_boundary_offset import (
    operator_remove_boundary_offset,
    operators as boundary_ops,
)


def _binop_node(code: str) -> cst.BinaryOperation:
    expr = cst.parse_expression(code)
    assert isinstance(expr, cst.BinaryOperation)
    return expr


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    monkeypatch.setenv("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    yield
    reset_plugin_manager()
    reset_plugin_operators()


class TestOperatorRemoveBoundaryOffset:
    def test_expr_plus_one(self):
        node = _binop_node("x + 1")
        mutants = list(operator_remove_boundary_offset(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0], cst.Name)
        assert mutants[0].value == "x"

    def test_expr_minus_one(self):
        node = _binop_node("x - 1")
        mutants = list(operator_remove_boundary_offset(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0], cst.Name)
        assert mutants[0].value == "x"

    def test_one_plus_expr(self):
        node = _binop_node("1 + x")
        mutants = list(operator_remove_boundary_offset(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0], cst.Name)
        assert mutants[0].value == "x"

    def test_one_minus_expr_no_mutation(self):
        # 1 - x is NOT the same pattern (removing gives x, not the intended boundary fix)
        node = _binop_node("1 - x")
        mutants = list(operator_remove_boundary_offset(node))
        assert mutants == []

    def test_len_minus_one(self):
        node = _binop_node("len(x) - 1")
        mutants = list(operator_remove_boundary_offset(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0], cst.Call)

    def test_plus_two_no_mutation(self):
        node = _binop_node("x + 2")
        mutants = list(operator_remove_boundary_offset(node))
        assert mutants == []

    def test_multiply_one_no_mutation(self):
        node = _binop_node("x * 1")
        mutants = list(operator_remove_boundary_offset(node))
        assert mutants == []

    def test_complex_left_expr(self):
        node = _binop_node("a + b + 1")
        # This parses as (a + b) + 1 due to left-associativity
        mutants = list(operator_remove_boundary_offset(node))
        assert len(mutants) == 1
        # Result should be the (a + b) BinaryOperation
        assert isinstance(mutants[0], cst.BinaryOperation)

    def test_call_plus_one(self):
        node = _binop_node("foo() + 1")
        mutants = list(operator_remove_boundary_offset(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0], cst.Call)


class TestRemoveBoundaryOffsetIntegration:
    def test_create_mutations_removes_offset(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(boundary_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent('''\
            def last_index(items):
                return len(items) - 1
        ''')
        module, mutations = create_mutations(source)
        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        # Should have a mutation that removes the - 1, leaving just len(items)
        assert any("return len(items)" in code and "- 1" not in code for code in mutated_codes)

    def test_produces_valid_syntax(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(boundary_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent('''\
            def boundaries(items, n):
                a = len(items) - 1
                b = n + 1
                c = 1 + n
                return a, b, c
        ''')
        module, mutations = create_mutations(source)
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            cst.parse_module(replaced.code)
