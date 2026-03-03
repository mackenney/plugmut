"""Syntax validation tests for all mutmut-extras operators.

Every mutation produced by every operator must generate syntactically valid Python.
This file tests both via direct operator calls (unit) and via create_mutations (integration).
"""

import libcst as cst
import pytest

from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut_extras.operators.assert_true import operator_assert_true
from mutmut_extras.operators.exception_handler import operator_exception_handler
from mutmut_extras.operators.return_none import operator_return_none
from mutmut_extras.operators.slice_removal import operator_slice_removal
from mutmut_extras.operators.ternary import operator_ternary
from mutmut_extras.plugin import mutmut_register_operators


@pytest.fixture(autouse=True)
def isolate_plugins(monkeypatch):
    """Register all extras operators in an isolated plugin manager."""
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    pm = get_plugin_manager()

    class AllOps:
        @hookimpl
        def mutmut_register_operators(self):
            return mutmut_register_operators()

    pm.register(AllOps())
    yield
    reset_plugin_manager()


def _assert_all_mutations_parse(source: str) -> list[str]:
    """Create mutations for *source*, assert every one parses, return mutated codes."""
    module, mutations = create_mutations(source)
    codes = []
    for i, m in enumerate(mutations):
        replaced = module.deep_replace(m.original_node, m.mutated_node)
        assert isinstance(replaced, cst.Module)
        mutated_code = replaced.code
        try:
            cst.parse_module(mutated_code)
        except cst.ParserSyntaxError:
            pytest.fail(f"Mutation {i} produced invalid syntax:\n{mutated_code}")
        codes.append(mutated_code)
    return codes


SAMPLE_SOURCES = {
    "return_int": "def f():\n    return 42\n",
    "return_call": "def f():\n    return foo()\n",
    "return_nested_func": "def f():\n    def g():\n        return bar()\n    return g()\n",
    "except_simple": (
        "def f():\n    try:\n        g()\n    except ValueError:\n        return -1\n"
    ),
    "except_bare": (
        "def f():\n    try:\n        g()\n    except:\n        log()\n        raise\n"
    ),
    "except_nested_try": (
        "def f():\n"
        "    try:\n"
        "        try:\n"
        "            g()\n"
        "        except TypeError:\n"
        "            handle()\n"
        "    except ValueError:\n"
        "        fallback()\n"
    ),
    "ternary_simple": "def f(x):\n    return x if x > 0 else -x\n",
    "ternary_nested": "def f(x):\n    return x if x > 0 else (x if x == 0 else -x)\n",
    "ternary_in_binop": "def f(x):\n    return (x if x > 0 else -x) + 1\n",
    "ternary_as_arg": "def f(x):\n    foo(x if x > 0 else -x)\n",
    "assert_simple": "def f(x):\n    assert x > 0\n",
    "assert_with_msg": "def f(x):\n    assert x > 0, 'must be positive'\n",
    "assert_in_conditional": "def f(x):\n    if x:\n        assert x > 0\n",
    "slice_lower_upper": "def f(items):\n    return items[1:5]\n",
    "slice_step_only": "def f(items):\n    return items[::2]\n",
    "slice_full": "def f(items):\n    return items[1:5:2]\n",
    "slice_in_call": "def f(items):\n    return foo(items[1:5])\n",
}


@pytest.mark.parametrize(
    "label,source", list(SAMPLE_SOURCES.items()), ids=list(SAMPLE_SOURCES.keys())
)
def test_all_mutations_produce_valid_syntax(label, source):
    _assert_all_mutations_parse(source)


class TestReturnNoneUnitSyntax:
    """Directly call operator_return_none and verify mutated AST produces valid code."""

    @pytest.mark.parametrize(
        "code",
        [
            "return 42",
            "return foo()",
            "return a + b",
            "return [x for x in items]",
        ],
    )
    def test_return_none_valid_syntax(self, code):
        stmt = cst.parse_statement(code)
        assert isinstance(stmt, cst.SimpleStatementLine)
        node = stmt.body[0]
        assert isinstance(node, cst.Return)
        for mutant in operator_return_none(node):
            module = cst.parse_module(
                f"def f():\n    {cst.parse_module('').code_for_node(mutant)}\n"
            )
            assert module is not None


class TestExceptionHandlerUnitSyntax:
    """Directly call operator_exception_handler and verify output."""

    def test_handler_body_replaced_with_pass(self):
        source = "try:\n    g()\nexcept ValueError:\n    return -1\n"
        module = cst.parse_module(source)
        try_stmt = module.body[0]
        assert isinstance(try_stmt, cst.Try)
        assert len(try_stmt.handlers) >= 1

        for handler in try_stmt.handlers:
            for mutant in operator_exception_handler(handler):
                replaced = module.deep_replace(handler, mutant)
                assert isinstance(replaced, cst.Module)
                cst.parse_module(replaced.code)


class TestTernaryUnitSyntax:
    """Directly call operator_ternary and verify all yielded nodes are BaseExpression.

    The ternary operator yields node.body and node.orelse, which replace a cst.IfExp
    in the tree. Since IfExp, Name, UnaryOperation, BinaryOperation, etc. are all
    BaseExpression subtypes, deep_replace handles the substitution correctly in any
    expression context (assignments, returns, function arguments, binary ops, etc.).
    """

    @pytest.mark.parametrize(
        "expr",
        [
            "x if cond else y",
            "x if cond else (a if c2 else b)",
            "a + b if cond else c - d",
        ],
    )
    def test_all_mutations_are_base_expressions(self, expr):
        node = cst.parse_expression(expr)
        assert isinstance(node, cst.IfExp)
        for mutant in operator_ternary(node):
            assert isinstance(mutant, cst.BaseExpression), (
                f"Ternary operator yielded {type(mutant).__name__}, not BaseExpression"
            )


class TestAssertTrueUnitSyntax:
    """Directly call operator_assert_true and verify output."""

    @pytest.mark.parametrize(
        "code",
        [
            "assert x > 0",
            "assert x > 0, 'msg'",
            "assert foo()",
        ],
    )
    def test_assert_mutations_valid(self, code):
        stmt = cst.parse_statement(code)
        assert isinstance(stmt, cst.SimpleStatementLine)
        node = stmt.body[0]
        assert isinstance(node, cst.Assert)
        for mutant in operator_assert_true(node):
            result = cst.parse_module(
                f"def f():\n    {cst.parse_module('').code_for_node(mutant)}\n"
            )
            assert result is not None


class TestSliceRemovalUnitSyntax:
    """Directly call operator_slice_removal and verify output."""

    @pytest.mark.parametrize(
        "subscript_expr,expected_count",
        [
            ("items[1:5]", 2),
            ("items[::2]", 1),
            ("items[1:5:2]", 3),
        ],
    )
    def test_slice_mutations_valid(self, subscript_expr, expected_count):
        expr = cst.parse_expression(subscript_expr)
        assert isinstance(expr, cst.Subscript)
        slice_node = expr.slice[0].slice
        assert isinstance(slice_node, cst.Slice)
        mutants = list(operator_slice_removal(slice_node))
        assert len(mutants) == expected_count
        for mutant in mutants:
            new_expr = expr.with_deep_changes(
                slice_node,
                **{
                    "lower": mutant.lower,
                    "upper": mutant.upper,
                    "step": mutant.step,
                    "second_colon": mutant.second_colon,
                },
            )
            code = cst.parse_module("").code_for_node(new_expr)
            cst.parse_module(f"x = {code}\n")


class TestTernaryContexts:
    """Verify ternary mutations produce valid code in various expression contexts."""

    def test_assignment_context(self):
        source = "def f(x):\n    result = x if cond else y\n"
        codes = _assert_all_mutations_parse(source)
        assert any("result = x\n" in c for c in codes), (
            f"Missing 'result = x' in {codes}"
        )
        assert any("result = y\n" in c for c in codes), (
            f"Missing 'result = y' in {codes}"
        )
        assert any("y if cond else x" in c for c in codes), (
            f"Missing swapped ternary in {codes}"
        )

    def test_return_with_arithmetic(self):
        source = "def f(x):\n    return (a if c else b) + 1\n"
        codes = _assert_all_mutations_parse(source)
        assert len(codes) >= 3

    def test_function_argument(self):
        source = "def f(x, z):\n    foo(x if c else y, z)\n"
        codes = _assert_all_mutations_parse(source)
        assert len(codes) >= 3

    def test_list_comprehension(self):
        source = "def f(items):\n    return [x if x > 0 else -x for x in items]\n"
        codes = _assert_all_mutations_parse(source)
        assert len(codes) >= 3

    def test_nested_ternary(self):
        source = "def f(x):\n    return a if c1 else (b if c2 else d)\n"
        codes = _assert_all_mutations_parse(source)
        # Outer: a, (b if c2 else d), swap; Inner: b, d, swap
        assert len(codes) >= 6

    def test_ternary_in_dict_value(self):
        source = "def f(x):\n    return {'key': x if cond else y}\n"
        codes = _assert_all_mutations_parse(source)
        assert len(codes) >= 3

    def test_ternary_in_fstring(self):
        source = "def f(x):\n    return f'{x if cond else y}'\n"
        codes = _assert_all_mutations_parse(source)
        assert len(codes) >= 3
