import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut.file_mutation import reset_plugin_operators
from mutmut_extras.operators.comprehension_filter import (
    operator_comprehension_filter_removal,
    operators as comprehension_filter_ops,
)


def _compfor_node(code: str) -> cst.CompFor:
    """Parse a comprehension expression and extract the CompFor node."""
    module = cst.parse_module(f"x = {code}\n")
    assign = module.body[0]
    assert isinstance(assign, cst.SimpleStatementLine)
    target = assign.body[0]
    assert isinstance(target, cst.Assign)
    comp = target.value
    # Works for ListComp, SetComp, GeneratorExp
    assert hasattr(comp, "for_in")
    return comp.for_in


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    """Reset the plugin manager before and after each test."""
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    yield
    reset_plugin_manager()
    reset_plugin_operators()


class TestOperatorComprehensionFilter:
    def test_list_comp_with_filter(self):
        node = _compfor_node("[x for x in items if x > 0]")
        mutants = list(operator_comprehension_filter_removal(node))
        assert len(mutants) == 1
        assert mutants[0].ifs == ()

    def test_dict_comp_with_filter(self):
        node = _compfor_node("{k: v for k, v in d.items() if v is not None}")
        mutants = list(operator_comprehension_filter_removal(node))
        assert len(mutants) == 1

    def test_set_comp_with_filter(self):
        node = _compfor_node("{x for x in items if x > 0}")
        mutants = list(operator_comprehension_filter_removal(node))
        assert len(mutants) == 1

    def test_generator_with_filter(self):
        expr = cst.parse_expression("list(x for x in items if x > 0)")
        assert isinstance(expr, cst.Call)
        gen = expr.args[0].value
        assert isinstance(gen, cst.GeneratorExp)
        node = gen.for_in
        mutants = list(operator_comprehension_filter_removal(node))
        assert len(mutants) == 1

    def test_no_filter_no_mutation(self):
        node = _compfor_node("[x for x in items]")
        mutants = list(operator_comprehension_filter_removal(node))
        assert mutants == []


class TestComprehensionFilterIntegration:
    def test_create_mutations_includes_filter_removal(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(comprehension_filter_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = "def foo():\n    return [x for x in range(10) if x > 5]\n"
        module, mutations = create_mutations(source)

        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("if x > 5" not in code and "for x in range(10)" in code for code in mutated_codes)
