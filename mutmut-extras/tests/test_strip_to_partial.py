import textwrap

import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut.file_mutation import reset_plugin_operators
from mutmut_extras.operators.strip_to_partial import (
    operator_strip_to_partial,
    operators as strip_ops,
)


def _call_node(code: str) -> cst.Call:
    expr = cst.parse_expression(code)
    assert isinstance(expr, cst.Call)
    return expr


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    yield
    reset_plugin_manager()
    reset_plugin_operators()


class TestOperatorStripToPartial:
    def test_strip_yields_two_mutations(self):
        node = _call_node("s.strip()")
        mutants = list(operator_strip_to_partial(node))
        assert len(mutants) == 2
        names = {m.func.attr.value for m in mutants}
        assert names == {"lstrip", "rstrip"}

    def test_strip_with_args_no_mutation(self):
        node = _call_node('s.strip("x")')
        mutants = list(operator_strip_to_partial(node))
        assert mutants == []

    def test_lstrip_no_mutation(self):
        node = _call_node("s.lstrip()")
        mutants = list(operator_strip_to_partial(node))
        assert mutants == []

    def test_rstrip_no_mutation(self):
        node = _call_node("s.rstrip()")
        mutants = list(operator_strip_to_partial(node))
        assert mutants == []

    def test_other_method_no_mutation(self):
        node = _call_node("s.split()")
        mutants = list(operator_strip_to_partial(node))
        assert mutants == []

    def test_plain_function_no_mutation(self):
        node = _call_node("strip()")
        mutants = list(operator_strip_to_partial(node))
        assert mutants == []

    def test_chained_strip(self):
        # "  hello  ".encode().decode().strip()
        node = _call_node("x.encode().decode().strip()")
        mutants = list(operator_strip_to_partial(node))
        assert len(mutants) == 2


class TestStripToPartialIntegration:
    def test_create_mutations_includes_strip_partials(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(strip_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent('''\
            def clean(s):
                return s.strip()
        ''')
        module, mutations = create_mutations(source)
        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("lstrip()" in code for code in mutated_codes)
        assert any("rstrip()" in code for code in mutated_codes)

    def test_strip_with_args_not_mutated(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(strip_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent('''\
            def clean(s):
                return s.strip("x")
        ''')
        module, mutations = create_mutations(source)
        # Should have no strip-related mutations (only builtins if any)
        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert not any("lstrip" in code for code in mutated_codes)
        assert not any("rstrip" in code for code in mutated_codes)
