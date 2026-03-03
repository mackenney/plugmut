import textwrap

import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut_extras.operators.isinstance_type_reduction import (
    operator_isinstance_type_reduction,
    operators as isinstance_ops,
)


def _call_node(code: str) -> cst.Call:
    expr = cst.parse_expression(code)
    assert isinstance(expr, cst.Call)
    return expr


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    yield
    reset_plugin_manager()


class TestOperatorIsinstanceTypeReduction:
    def test_two_types_yields_two_mutations(self):
        node = _call_node("isinstance(x, (int, str))")
        mutants = list(operator_isinstance_type_reduction(node))
        assert len(mutants) == 2

    def test_two_types_unwraps_to_single(self):
        node = _call_node("isinstance(x, (int, str))")
        mutants = list(operator_isinstance_type_reduction(node))
        codes = [cst.parse_module("").code_for_node(m) for m in mutants]
        assert any("isinstance(x, str)" in c for c in codes)
        assert any("isinstance(x, int)" in c for c in codes)

    def test_three_types_yields_three_mutations(self):
        node = _call_node("isinstance(x, (int, str, float))")
        mutants = list(operator_isinstance_type_reduction(node))
        assert len(mutants) == 3

    def test_three_types_keeps_tuple(self):
        node = _call_node("isinstance(x, (int, str, float))")
        mutants = list(operator_isinstance_type_reduction(node))
        codes = [cst.parse_module("").code_for_node(m) for m in mutants]
        # Each mutation removes one type, keeping remaining as tuple
        assert any("(str, float)" in c for c in codes)
        assert any("(int, float)" in c for c in codes)
        assert any("(int, str)" in c for c in codes)

    def test_single_type_no_mutation(self):
        node = _call_node("isinstance(x, int)")
        mutants = list(operator_isinstance_type_reduction(node))
        assert mutants == []

    def test_single_element_tuple_no_mutation(self):
        node = _call_node("isinstance(x, (int,))")
        mutants = list(operator_isinstance_type_reduction(node))
        assert mutants == []

    def test_not_isinstance_no_mutation(self):
        node = _call_node("issubclass(x, (int, str))")
        mutants = list(operator_isinstance_type_reduction(node))
        assert mutants == []

    def test_plain_call_no_mutation(self):
        node = _call_node("foo(x, y)")
        mutants = list(operator_isinstance_type_reduction(node))
        assert mutants == []


class TestIsinstanceTypeReductionIntegration:
    def test_create_mutations_includes_reductions(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(isinstance_ops)

            @hookimpl
            def mutmut_allowlist_calls(self):
                return ["isinstance"]

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent('''\
            def check(x):
                return isinstance(x, (int, str))
        ''')
        module, mutations = create_mutations(source)
        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("isinstance(x, str)" in code for code in mutated_codes)
        assert any("isinstance(x, int)" in code for code in mutated_codes)

    def test_produces_valid_syntax(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(isinstance_ops)

            @hookimpl
            def mutmut_allowlist_calls(self):
                return ["isinstance"]

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent('''\
            def check(x):
                if isinstance(x, (int, str, float)):
                    return True
                return False
        ''')
        module, mutations = create_mutations(source)
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            cst.parse_module(replaced.code)
