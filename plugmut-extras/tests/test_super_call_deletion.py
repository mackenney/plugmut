import libcst as cst
import pytest
from mutmut.file_mutation import create_mutations
from mutmut.file_mutation import reset_plugin_operators
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager
from mutmut.plugin_manager import reset_plugin_manager
from mutmut_extras.operators.super_call_deletion import operator_super_call_deletion
from mutmut_extras.operators.super_call_deletion import operators as super_call_deletion_ops


def _parse_stmt(code: str) -> cst.SimpleStatementLine:
    """Parse a single statement line."""
    stmt = cst.parse_statement(code)
    assert isinstance(stmt, cst.SimpleStatementLine)
    return stmt


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    """Reset the plugin manager before and after each test."""
    monkeypatch.setenv("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    yield
    reset_plugin_manager()
    reset_plugin_operators()


class TestOperatorSuperCallDeletion:
    def test_super_init(self):
        node = _parse_stmt("super().__init__(x, y)")
        mutants = list(operator_super_call_deletion(node))
        assert len(mutants) == 1
        assert len(mutants[0].body) == 1
        assert isinstance(mutants[0].body[0], cst.Pass)

    def test_super_method(self):
        node = _parse_stmt("super().save()")
        mutants = list(operator_super_call_deletion(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].body[0], cst.Pass)

    def test_super_with_args(self):
        # super(MyClass, self) is still Call(func=Name("super"))
        node = _parse_stmt("super(MyClass, self).__init__()")
        mutants = list(operator_super_call_deletion(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].body[0], cst.Pass)

    def test_regular_call_no_mutation(self):
        node = _parse_stmt("foo()")
        mutants = list(operator_super_call_deletion(node))
        assert mutants == []

    def test_method_call_no_mutation(self):
        # obj.method() is not a super() call
        node = _parse_stmt("obj.method()")
        mutants = list(operator_super_call_deletion(node))
        assert mutants == []

    def test_assignment_no_mutation(self):
        node = _parse_stmt("x = super().__init__()")
        mutants = list(operator_super_call_deletion(node))
        assert mutants == []


class TestSuperCallDeletionIntegration:
    def test_create_mutations_includes_super_deletion(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(super_call_deletion_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = "class Child(Parent):\n    def __init__(self, x):\n        super().__init__(x)\n        self.x = x\n"
        module, mutations = create_mutations(source)

        mutated_codes = []
        for mut in mutations:
            replaced = module.deep_replace(mut.original_node, mut.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("pass" in code for code in mutated_codes)
