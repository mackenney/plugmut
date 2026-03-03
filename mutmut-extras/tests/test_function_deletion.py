import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut_extras.operators.function_deletion import (
    operator_function_deletion,
    operators as function_deletion_ops,
)


def _func_node(code: str) -> cst.FunctionDef:
    """Parse source code and extract the first FunctionDef node."""
    module = cst.parse_module(code)
    for node in module.body:
        if isinstance(node, cst.FunctionDef):
            return node
        if isinstance(node, cst.ClassDef):
            for child in node.body.body:
                if isinstance(child, cst.FunctionDef):
                    return child
    raise AssertionError("No FunctionDef found in source")


PASS_BODY = cst.IndentedBlock(body=[cst.SimpleStatementLine(body=[cst.Pass()])])


class TestOperatorFunctionDeletion:
    def test_function_deletion_basic(self):
        node = _func_node("def foo():\n    return 1\n")
        mutants = list(operator_function_deletion(node))
        assert len(mutants) == 1
        assert isinstance(mutants[0].body, cst.IndentedBlock)
        assert len(mutants[0].body.body) == 1
        stmt = mutants[0].body.body[0]
        assert isinstance(stmt, cst.SimpleStatementLine)
        assert isinstance(stmt.body[0], cst.Pass)

    def test_function_deletion_multiline(self):
        source = (
            "def compute(x, y):\n"
            "    result = x + y\n"
            "    if result > 0:\n"
            "        return result\n"
            "    return -result\n"
        )
        node = _func_node(source)
        mutants = list(operator_function_deletion(node))
        assert len(mutants) == 1

    def test_function_deletion_already_pass(self):
        node = _func_node("def noop():\n    pass\n")
        mutants = list(operator_function_deletion(node))
        assert mutants == []

    def test_function_deletion_with_docstring(self):
        source = (
            "def documented():\n"
            '    """This function has a docstring."""\n'
            "    return 42\n"
        )
        node = _func_node(source)
        mutants = list(operator_function_deletion(node))
        assert len(mutants) == 1
        assert mutants[0].body.deep_equals(PASS_BODY)

    def test_function_deletion_typed_return(self):
        node = _func_node("def foo() -> int:\n    return 1\n")
        mutants = list(operator_function_deletion(node))
        assert len(mutants) == 1
        assert mutants[0].returns is not None
        assert isinstance(mutants[0].returns.annotation, cst.Name)
        assert mutants[0].returns.annotation.value == "int"
        assert mutants[0].body.deep_equals(PASS_BODY)

    def test_function_deletion_method(self):
        source = (
            "class MyClass:\n"
            "    def method(self):\n"
            "        return self.value\n"
        )
        node = _func_node(source)
        mutants = list(operator_function_deletion(node))
        assert len(mutants) == 1
        assert mutants[0].name.value == "method"
        assert mutants[0].body.deep_equals(PASS_BODY)


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    """Reset the plugin manager before and after each test."""
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    yield
    reset_plugin_manager()


class TestFunctionDeletionIntegration:
    def test_create_mutations_includes_function_deletion(self):
        class _TestPlugin:
            @hookimpl
            def mutmut_register_operators(self):
                return list(function_deletion_ops)

        pm = get_plugin_manager()
        pm.register(_TestPlugin())

        source = "def greet(name):\n    return f'Hello {name}'\n"
        module, mutations = create_mutations(source)

        mutated_codes = []
        for m in mutations:
            replaced = module.deep_replace(m.original_node, m.mutated_node)
            assert isinstance(replaced, cst.Module)
            mutated_codes.append(replaced.code)

        assert any("pass" in code and "Hello" not in code for code in mutated_codes)


class TestFunctionDeletionSyntaxValid:
    @pytest.mark.parametrize(
        "source",
        [
            "def f():\n    return 42\n",
            "def f(x, y):\n    z = x + y\n    return z\n",
            "def f() -> int:\n    return 1\n",
            'def f():\n    """docstring"""\n    return None\n',
            "def f(self):\n    self.x = 1\n    self.save()\n",
            "def f():\n    for i in range(10):\n        print(i)\n",
            "async def f():\n    await something()\n",
        ],
        ids=[
            "simple_return",
            "multi_statement",
            "typed_return",
            "docstring",
            "method_like",
            "loop_body",
            "async_def",
        ],
    )
    def test_mutation_produces_valid_python(self, source):
        node = _func_node(source)
        for mutant in operator_function_deletion(node):
            module = cst.parse_module(source)
            replaced = module.deep_replace(node, mutant)
            assert isinstance(replaced, cst.Module)
            cst.parse_module(replaced.code)
