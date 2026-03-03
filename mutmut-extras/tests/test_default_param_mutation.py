import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut_extras.operators.default_param_mutation import (
    operator_default_param_mutation,
    operators as default_param_ops,
)


def _param_with_default(code: str) -> cst.Param:
    """Parse a function def and extract the first param with a default."""
    module = cst.parse_module(code + "\n    pass\n")
    func = module.body[0]
    assert isinstance(func, cst.FunctionDef)
    for param in func.params.params:
        if param.default is not None:
            return param
    raise AssertionError("No param with default found")


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    """Reset the plugin manager before and after each test."""
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    yield
    reset_plugin_manager()


class TestOperatorDefaultParamMutation:
    def test_bool_true_flips(self):
        node = _param_with_default("def f(x=True):")
        mutants = list(operator_default_param_mutation(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].default, cst.Name)
        assert mutants[0].default.value == "False"

    def test_bool_false_flips(self):
        node = _param_with_default("def f(x=False):")
        mutants = list(operator_default_param_mutation(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].default, cst.Name)
        assert mutants[0].default.value == "True"

    def test_none_becomes_zero(self):
        node = _param_with_default("def f(x=None):")
        mutants = list(operator_default_param_mutation(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].default, cst.Integer)
        assert mutants[0].default.value == "0"

    def test_integer_increments(self):
        node = _param_with_default("def f(x=100):")
        mutants = list(operator_default_param_mutation(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].default, cst.Integer)
        assert mutants[0].default.value == "101"

    def test_float_increments(self):
        node = _param_with_default("def f(x=1.5):")
        mutants = list(operator_default_param_mutation(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].default, cst.Float)
        assert abs(float(mutants[0].default.value) - 2.5) < 1e-9

    def test_name_becomes_none(self):
        node = _param_with_default("def f(x=SENTINEL):")
        mutants = list(operator_default_param_mutation(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].default, cst.Name)
        assert mutants[0].default.value == "None"

    def test_no_default_no_mutation(self):
        module = cst.parse_module("def f(x):\n    pass\n")
        func = module.body[0]
        assert isinstance(func, cst.FunctionDef)
        param = func.params.params[0]
        assert param.default is None
        mutants = list(operator_default_param_mutation(param))
        assert mutants == []


class TestDefaultParamMutationIntegration:
    def test_create_mutations_includes_default_param(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(default_param_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = "def process(items, reverse=False):\n    pass\n"
        module, mutations = create_mutations(source)

        mutated_codes = []
        for mut in mutations:
            replaced = module.deep_replace(mut.original_node, mut.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("reverse=True" in code for code in mutated_codes)
