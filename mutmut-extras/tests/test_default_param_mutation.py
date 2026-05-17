import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut.file_mutation import reset_plugin_operators
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
    monkeypatch.setenv("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    yield
    reset_plugin_manager()
    reset_plugin_operators()


class TestOperatorDefaultParamMutation:
    # Unique cases: builtins don't handle these

    def test_none_becomes_zero(self):
        node = _param_with_default("def f(x=None):")
        mutants = list(operator_default_param_mutation(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].default, cst.Integer)
        assert mutants[0].default.value == "0"

    def test_name_sentinel_becomes_none(self):
        node = _param_with_default("def f(x=SENTINEL):")
        mutants = list(operator_default_param_mutation(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].default, cst.Name)
        assert mutants[0].default.value == "None"

    # Cases builtins already handle: operator must NOT generate these

    def test_bool_true_not_mutated(self):
        node = _param_with_default("def f(x=True):")
        mutants = list(operator_default_param_mutation(node))
        assert mutants == []

    def test_bool_false_not_mutated(self):
        node = _param_with_default("def f(x=False):")
        mutants = list(operator_default_param_mutation(node))
        assert mutants == []

    def test_integer_not_mutated(self):
        node = _param_with_default("def f(x=100):")
        mutants = list(operator_default_param_mutation(node))
        assert mutants == []

    def test_float_not_mutated(self):
        node = _param_with_default("def f(x=1.5):")
        mutants = list(operator_default_param_mutation(node))
        assert mutants == []

    def test_string_not_mutated(self):
        node = _param_with_default('def f(x="hello"):')
        mutants = list(operator_default_param_mutation(node))
        assert mutants == []

    def test_no_default_no_mutation(self):
        module = cst.parse_module("def f(x):\n    pass\n")
        func = module.body[0]
        assert isinstance(func, cst.FunctionDef)
        param = func.params.params[0]
        assert param.default is None
        mutants = list(operator_default_param_mutation(param))
        assert mutants == []


class TestDefaultParamMutationIntegration:
    def test_create_mutations_includes_none_to_zero(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(default_param_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = "def process(items, timeout=None):\n    pass\n"
        module, mutations = create_mutations(source)

        mutated_codes = []
        for mut in mutations:
            replaced = module.deep_replace(mut.original_node, mut.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("timeout=0" in code for code in mutated_codes)

    def test_create_mutations_includes_sentinel_to_none(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(default_param_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = "def process(items, sentinel=MISSING):\n    pass\n"
        module, mutations = create_mutations(source)

        mutated_codes = []
        for mut in mutations:
            replaced = module.deep_replace(mut.original_node, mut.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("sentinel=None" in code for code in mutated_codes)
