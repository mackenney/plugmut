import textwrap

import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut.file_mutation import reset_plugin_operators
from mutmut_extras.operators.exception_handler import (
    operator_exception_handler,
    operators,
)


def _parse_handler(code: str) -> cst.ExceptHandler:
    """Parse a try/except block and return the first ExceptHandler node."""
    module = cst.parse_module(textwrap.dedent(code))
    try_stmt = module.body[0]
    assert isinstance(try_stmt, cst.Try)
    handler = try_stmt.handlers[0]
    assert isinstance(handler, cst.ExceptHandler)
    return handler


def _body_is_pass(handler: cst.ExceptHandler) -> bool:
    return (
        isinstance(handler.body, cst.IndentedBlock)
        and len(handler.body.body) == 1
        and isinstance(handler.body.body[0], cst.SimpleStatementLine)
        and len(handler.body.body[0].body) == 1
        and isinstance(handler.body.body[0].body[0], cst.Pass)
    )


class _TestPlugin:
    @hookimpl
    def mutmut_register_operators(self):
        return operators


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    monkeypatch.setenv("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    pm = get_plugin_manager()
    pm.register(_TestPlugin())
    yield
    reset_plugin_manager()
    reset_plugin_operators()


class TestOperatorExceptionHandler:
    def test_handler_with_call_produces_pass(self):
        handler = _parse_handler("""\
            try:
                x()
            except ValueError:
                handle_error()
        """)
        results = list(operator_exception_handler(handler))
        assert len(results) == 1
        assert _body_is_pass(results[0])

    def test_bare_except_with_multiple_statements_produces_pass(self):
        handler = _parse_handler("""\
            try:
                x()
            except:
                log()
                raise
        """)
        results = list(operator_exception_handler(handler))
        assert len(results) == 1
        assert _body_is_pass(results[0])

    def test_handler_already_pass_produces_no_mutations(self):
        handler = _parse_handler("""\
            try:
                x()
            except:
                pass
        """)
        results = list(operator_exception_handler(handler))
        assert results == []


class TestExceptionHandlerIntegration:
    def test_create_mutations_includes_exception_handler(self):
        code = textwrap.dedent("""\
            def foo():
                try:
                    risky()
                except ValueError:
                    handle_error()
        """)
        module, mutations = create_mutations(code)

        handler_mutations = [
            m
            for m in mutations
            if isinstance(m.mutated_node, cst.ExceptHandler)
            and _body_is_pass(m.mutated_node)
        ]
        assert len(handler_mutations) == 1
