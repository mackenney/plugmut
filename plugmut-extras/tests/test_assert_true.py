import libcst as cst
import pytest
from mutmut.file_mutation import create_mutations
from mutmut.file_mutation import reset_plugin_operators
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager
from mutmut.plugin_manager import reset_plugin_manager
from mutmut_extras.operators.assert_true import operator_assert_true


def _parse_assert(code: str) -> cst.Assert:
    """Parse an assert statement and return the Assert node."""
    stmt = cst.parse_statement(code)
    assert isinstance(stmt, cst.SimpleStatementLine)
    node = stmt.body[0]
    assert isinstance(node, cst.Assert)
    return node


def test_assert_condition_mutates_to_true():
    node = _parse_assert("assert x > 0")
    results = list(operator_assert_true(node))
    assert len(results) == 1
    test_node = results[0].test
    assert isinstance(test_node, cst.Name)
    assert test_node.value == "True"


def test_assert_with_message_preserves_message():
    node = _parse_assert('assert x > 0, "must be positive"')
    results = list(operator_assert_true(node))
    assert len(results) == 1
    test_node = results[0].test
    assert isinstance(test_node, cst.Name)
    assert test_node.value == "True"
    assert results[0].msg is not None
    module = cst.parse_module("")
    code = module.code_for_node(results[0])
    assert '"must be positive"' in code


def test_assert_true_produces_no_mutations():
    node = _parse_assert("assert True")
    results = list(operator_assert_true(node))
    assert len(results) == 0


def test_assert_false_mutates_to_true():
    node = _parse_assert("assert False")
    results = list(operator_assert_true(node))
    assert len(results) == 1
    test_node = results[0].test
    assert isinstance(test_node, cst.Name)
    assert test_node.value == "True"


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    monkeypatch.setenv("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    pm = get_plugin_manager()

    class _TestPlugin:
        @hookimpl
        def mutmut_register_operators(self):
            return [(cst.Assert, operator_assert_true)]

    pm.register(_TestPlugin())
    yield
    reset_plugin_manager()
    reset_plugin_operators()


def test_create_mutations_assert():
    code = """\
def foo(x):
    assert x > 0
    return x
"""
    _module, mutations = create_mutations(code)
    # Expect at least the assert True mutation (plus built-in mutations on x > 0)
    assert_true_mutations = [
        m
        for m in mutations
        if isinstance(m.mutated_node, cst.Assert)
        and isinstance(m.mutated_node.test, cst.Name)
        and m.mutated_node.test.value == "True"
    ]
    assert len(assert_true_mutations) == 1
