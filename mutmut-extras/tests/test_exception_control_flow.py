import textwrap

import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut.file_mutation import reset_plugin_operators
from mutmut_extras.operators.exception_control_flow import (
    operator_exception_control_flow,
    operators as control_flow_ops,
)


def _parse_handler(code: str) -> cst.ExceptHandler:
    module = cst.parse_module(textwrap.dedent(code))
    try_stmt = module.body[0]
    assert isinstance(try_stmt, cst.Try)
    handler = try_stmt.handlers[0]
    assert isinstance(handler, cst.ExceptHandler)
    return handler


def _first_stmt(handler: cst.ExceptHandler):
    """Get the first statement in the handler body."""
    assert isinstance(handler.body, cst.IndentedBlock)
    line = handler.body.body[0]
    assert isinstance(line, cst.SimpleStatementLine)
    return line.body[0]


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    yield
    reset_plugin_manager()
    reset_plugin_operators()


class TestOperatorExceptionControlFlow:
    def test_pass_yields_three_mutations(self):
        handler = _parse_handler("""\
            try:
                x()
            except ValueError:
                pass
        """)
        mutants = list(operator_exception_control_flow(handler))
        assert len(mutants) == 3

    def test_pass_yields_break(self):
        handler = _parse_handler("""\
            try:
                x()
            except ValueError:
                pass
        """)
        mutants = list(operator_exception_control_flow(handler))
        assert isinstance(_first_stmt(mutants[0]), cst.Break)

    def test_pass_yields_continue(self):
        handler = _parse_handler("""\
            try:
                x()
            except ValueError:
                pass
        """)
        mutants = list(operator_exception_control_flow(handler))
        assert isinstance(_first_stmt(mutants[1]), cst.Continue)

    def test_pass_yields_return(self):
        handler = _parse_handler("""\
            try:
                x()
            except ValueError:
                pass
        """)
        mutants = list(operator_exception_control_flow(handler))
        assert isinstance(_first_stmt(mutants[2]), cst.Return)

    def test_non_pass_body_no_mutation(self):
        handler = _parse_handler("""\
            try:
                x()
            except ValueError:
                handle_error()
        """)
        mutants = list(operator_exception_control_flow(handler))
        assert mutants == []

    def test_multi_statement_body_no_mutation(self):
        handler = _parse_handler("""\
            try:
                x()
            except ValueError:
                log()
                raise
        """)
        mutants = list(operator_exception_control_flow(handler))
        assert mutants == []

    def test_bare_except_pass(self):
        handler = _parse_handler("""\
            try:
                x()
            except:
                pass
        """)
        mutants = list(operator_exception_control_flow(handler))
        assert len(mutants) == 3


class TestExceptionControlFlowIntegration:
    def test_create_mutations_in_loop_context(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(control_flow_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent('''\
            def process(items):
                for item in items:
                    try:
                        handle(item)
                    except ValueError:
                        pass
        ''')
        module, mutations = create_mutations(source)
        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("break" in code for code in mutated_codes)
        assert any("continue" in code for code in mutated_codes)
        assert any("return" in code for code in mutated_codes)

    def test_produces_valid_syntax(self):
        """All mutations should be syntactically valid Python (even break/continue outside loop,
        since we wrap them in a function)."""
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(control_flow_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = textwrap.dedent('''\
            def foo():
                try:
                    bar()
                except TypeError:
                    pass
        ''')
        module, mutations = create_mutations(source)
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            # Note: break/continue outside loop is a semantic error, not a syntax error
            # libcst will still parse it fine
            cst.parse_module(replaced.code)
