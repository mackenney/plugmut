import libcst as cst
import pytest
from mutmut.file_mutation import create_mutations
from mutmut.file_mutation import reset_plugin_operators
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager
from mutmut.plugin_manager import reset_plugin_manager
from mutmut_extras.operators.slice_removal import operator_slice_removal
from mutmut_extras.operators.slice_removal import operators as slice_removal_ops


def _slice_node(code: str) -> cst.Slice:
    """Parse a subscript expression and extract the Slice CST node."""
    node = cst.parse_expression(code)
    assert isinstance(node, cst.Subscript)
    slc = node.slice[0].slice
    assert isinstance(slc, cst.Slice)
    return slc


class TestOperatorSliceRemoval:
    def test_lower_and_upper(self):
        """items[1:5] -> items[:5], items[1:]"""
        slc = _slice_node("items[1:5]")
        mutants = list(operator_slice_removal(slc))
        assert len(mutants) == 2
        assert mutants[0].lower is None and mutants[0].upper is not None
        assert mutants[1].lower is not None and mutants[1].upper is None

    def test_step_only(self):
        """items[::2] -> items[::]"""
        slc = _slice_node("items[::2]")
        mutants = list(operator_slice_removal(slc))
        assert len(mutants) == 1
        assert mutants[0].step is None

    def test_all_three(self):
        """items[1:5:2] -> 3 mutations"""
        slc = _slice_node("items[1:5:2]")
        mutants = list(operator_slice_removal(slc))
        assert len(mutants) == 3

    def test_step_removal_drops_trailing_colon(self):
        """items[1:5:2] with step removed -> items[1:5], not items[1:5:]"""
        expr = cst.parse_expression("items[1:5:2]")
        assert isinstance(expr, cst.Subscript)
        slc = expr.slice[0].slice
        assert isinstance(slc, cst.Slice)
        mutants = list(operator_slice_removal(slc))
        step_removed = [m for m in mutants if m.step is None]
        assert len(step_removed) == 1
        new_expr = expr.with_changes(slice=[cst.SubscriptElement(slice=step_removed[0])])
        rendered = cst.Module(body=[cst.SimpleStatementLine(body=[cst.Expr(new_expr)])]).code.strip()
        assert rendered == "items[1:5]"

    def test_bare_slice_no_mutation(self):
        """items[:] -> no mutations"""
        slc = _slice_node("items[:]")
        mutants = list(operator_slice_removal(slc))
        assert mutants == []


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    """Reset the plugin manager before and after each test."""
    monkeypatch.setenv("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    yield
    reset_plugin_manager()
    reset_plugin_operators()


class TestSliceRemovalIntegration:
    def test_create_mutations_removes_slice_components(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(slice_removal_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = "def foo(items):\n    return items[1:5]\n"
        module, mutations = create_mutations(source)

        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("items[:5]" in code for code in mutated_codes)
        assert any("items[1:]" in code for code in mutated_codes)
        # Built-in operators also fire (e.g. integer boundary mutations),
        # so we only check that our 2 slice mutations are present.
        assert sum("items[:5]" in c or "items[1:]" in c for c in mutated_codes) == 2
