import textwrap

import libcst as cst
import pytest
from mutmut.file_mutation import create_mutations
from mutmut.file_mutation import reset_plugin_operators
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager
from mutmut.plugin_manager import reset_plugin_manager
from mutmut_extras.operators.operand_swap import operator_operand_swap
from mutmut_extras.operators.operand_swap import operators as operand_swap_ops


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


class TestOperatorOperandSwap:
    def test_subtract_swap(self):
        node = _binop_node("a - b")
        mutants = list(operator_operand_swap(node))
        assert len(mutants) == 1
        code = cst.parse_module("").code_for_node(mutants[0])
        assert "b" in code.split("-")[0]  # b is on the left
        assert "a" in code.split("-")[1]  # a is on the right

    def test_divide_swap(self):
        node = _binop_node("a / b")
        mutants = list(operator_operand_swap(node))
        assert len(mutants) == 1
        m = mutants[0]
        assert isinstance(m.left, cst.Name) and m.left.value == "b"
        assert isinstance(m.right, cst.Name) and m.right.value == "a"

    def test_floor_divide_swap(self):
        node = _binop_node("a // b")
        mutants = list(operator_operand_swap(node))
        assert len(mutants) == 1
        m = mutants[0]
        assert isinstance(m.left, cst.Name) and m.left.value == "b"

    def test_modulo_swap(self):
        node = _binop_node("a % b")
        mutants = list(operator_operand_swap(node))
        assert len(mutants) == 1
        m = mutants[0]
        assert isinstance(m.left, cst.Name) and m.left.value == "b"

    def test_power_swap(self):
        node = _binop_node("a ** b")
        mutants = list(operator_operand_swap(node))
        assert len(mutants) == 1
        m = mutants[0]
        assert isinstance(m.left, cst.Name) and m.left.value == "b"

    def test_add_no_mutation(self):
        node = _binop_node("a + b")
        mutants = list(operator_operand_swap(node))
        assert mutants == []

    def test_multiply_no_mutation(self):
        node = _binop_node("a * b")
        mutants = list(operator_operand_swap(node))
        assert mutants == []

    def test_complex_operands(self):
        node = _binop_node("foo() - bar()")
        mutants = list(operator_operand_swap(node))
        assert len(mutants) == 1
        # left should now be bar(), right should be foo()
        assert isinstance(mutants[0].left, cst.Call)
        assert isinstance(mutants[0].right, cst.Call)


class TestOperandSwapIntegration:
    def test_create_mutations_includes_operand_swap(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(operand_swap_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent("""\
            def diff(a, b):
                return a - b
        """)
        module, mutations = create_mutations(source)
        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("b - a" in code for code in mutated_codes)

    def test_divide_integration(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(operand_swap_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent("""\
            def ratio(x, y):
                return x / y
        """)
        module, mutations = create_mutations(source)
        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("y / x" in code for code in mutated_codes)

    def test_produces_valid_syntax(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(operand_swap_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent("""\
            def calc(a, b, c):
                x = a - b
                y = a / c
                z = a % b
                w = a ** 2
                return x + y + z + w
        """)
        module, mutations = create_mutations(source)
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            cst.parse_module(replaced.code)  # Must be valid syntax
