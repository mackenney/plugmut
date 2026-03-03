import textwrap

import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut_extras.operators.exception_type_broadening import (
    operator_exception_type_broadening,
    operators as broadening_ops,
)


def _parse_handler(code: str) -> cst.ExceptHandler:
    module = cst.parse_module(textwrap.dedent(code))
    try_stmt = module.body[0]
    assert isinstance(try_stmt, cst.Try)
    handler = try_stmt.handlers[0]
    assert isinstance(handler, cst.ExceptHandler)
    return handler


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    yield
    reset_plugin_manager()


class TestOperatorExceptionTypeBroadening:
    def test_specific_to_exception(self):
        handler = _parse_handler("""\
            try:
                x()
            except ValueError:
                pass
        """)
        mutants = list(operator_exception_type_broadening(handler))
        assert len(mutants) == 1
        assert isinstance(mutants[0].type, cst.Name)
        assert mutants[0].type.value == "Exception"

    def test_already_exception_no_mutation(self):
        handler = _parse_handler("""\
            try:
                x()
            except Exception:
                pass
        """)
        mutants = list(operator_exception_type_broadening(handler))
        assert mutants == []

    def test_base_exception_no_mutation(self):
        handler = _parse_handler("""\
            try:
                x()
            except BaseException:
                pass
        """)
        mutants = list(operator_exception_type_broadening(handler))
        assert mutants == []

    def test_bare_except_no_mutation(self):
        handler = _parse_handler("""\
            try:
                x()
            except:
                pass
        """)
        mutants = list(operator_exception_type_broadening(handler))
        assert mutants == []

    def test_tuple_types_yields_multiple(self):
        handler = _parse_handler("""\
            try:
                x()
            except (ValueError, KeyError):
                pass
        """)
        mutants = list(operator_exception_type_broadening(handler))
        # 1 for replacing entire tuple + 2 for replacing each individual type
        assert len(mutants) == 3

    def test_tuple_first_mutation_is_exception(self):
        handler = _parse_handler("""\
            try:
                x()
            except (ValueError, KeyError):
                pass
        """)
        mutants = list(operator_exception_type_broadening(handler))
        # First mutation: entire tuple replaced with Exception
        assert isinstance(mutants[0].type, cst.Name)
        assert mutants[0].type.value == "Exception"

    def test_tuple_individual_replacements(self):
        handler = _parse_handler("""\
            try:
                x()
            except (ValueError, KeyError):
                pass
        """)
        mutants = list(operator_exception_type_broadening(handler))
        # Second mutation: (Exception, KeyError)
        assert isinstance(mutants[1].type, cst.Tuple)
        # Third mutation: (ValueError, Exception)
        assert isinstance(mutants[2].type, cst.Tuple)

    def test_type_error_broadened(self):
        handler = _parse_handler("""\
            try:
                x()
            except TypeError:
                pass
        """)
        mutants = list(operator_exception_type_broadening(handler))
        assert len(mutants) == 1
        assert mutants[0].type.value == "Exception"

    def test_tuple_with_exception_already(self):
        handler = _parse_handler("""\
            try:
                x()
            except (Exception, KeyError):
                pass
        """)
        mutants = list(operator_exception_type_broadening(handler))
        # Full tuple replacement + only KeyError gets individual replacement (Exception is skipped)
        assert len(mutants) == 2


class TestExceptionTypeBroadeningIntegration:
    def test_create_mutations_broadens(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(broadening_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent('''\
            def foo():
                try:
                    risky()
                except ValueError:
                    handle()
        ''')
        module, mutations = create_mutations(source)
        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("except Exception" in code for code in mutated_codes)

    def test_produces_valid_syntax(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(broadening_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent('''\
            def foo():
                try:
                    risky()
                except (ValueError, KeyError):
                    handle()
        ''')
        module, mutations = create_mutations(source)
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            cst.parse_module(replaced.code)
