import libcst as cst
import pytest
from mutmut.file_mutation import create_mutations
from mutmut.file_mutation import reset_plugin_operators
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager
from mutmut.plugin_manager import reset_plugin_manager
from mutmut_extras.operators.ternary import operator_ternary
from mutmut_extras.operators.ternary import operators as ternary_ops


@pytest.fixture(autouse=True)
def isolate_plugins(monkeypatch):
    monkeypatch.setenv("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    pm = get_plugin_manager()

    class TernaryPlugin:
        @hookimpl
        def mutmut_register_operators(self):
            return ternary_ops

    pm.register(TernaryPlugin())
    yield
    reset_plugin_manager()
    reset_plugin_operators()


class TestOperatorTernaryUnit:
    def test_produces_three_mutations(self):
        node = cst.parse_expression("x if cond else y")
        assert isinstance(node, cst.IfExp)
        mutations = list(operator_ternary(node))

        assert len(mutations) == 3

        module = cst.parse_module("")
        codes = [module.code_for_node(m) for m in mutations]

        assert "x" in codes
        assert "y" in codes
        assert "y if cond else x" in codes


class TestOperatorTernaryIntegration:
    def test_create_mutations_includes_ternary(self):
        source = "def foo(x):\n    return x if x > 0 else -x\n"

        module, mutations = create_mutations(source)
        mutant_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutant_codes.append(replaced.code)

        assert any("return x\n" in code for code in mutant_codes)
        assert any("return -x\n" in code for code in mutant_codes)
        assert any("-x if x > 0 else x" in code for code in mutant_codes)
