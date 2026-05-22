from __future__ import annotations

import libcst as cst
from mutmut_dedup.normalize import normalize_mutation


def _parse_expr(source: str) -> cst.BaseExpression:
    """Parse a single expression from source."""
    mod = cst.parse_module(source)
    stmt = mod.body[0]
    assert isinstance(stmt, cst.SimpleStatementLine)
    return stmt.body[0].value  # ty: ignore[unresolved-attribute]


def _parse_stmt(source: str) -> cst.BaseStatement:
    """Parse a single statement from source."""
    mod = cst.parse_module(source)
    return mod.body[0]


class TestWhitespaceNormalization:
    def test_different_whitespace_same_result(self):
        a = _parse_expr("1  +  2\n")
        b = _parse_expr("1+2\n")
        assert normalize_mutation(a) == normalize_mutation(b)


class TestQuoteNormalization:
    def test_single_vs_double_quotes(self):
        a = _parse_expr("'hello'\n")
        b = _parse_expr('"hello"\n')
        assert normalize_mutation(a) == normalize_mutation(b)


class TestAnnotationStripping:
    def test_annotated_vs_unannotated_function(self):
        a = _parse_stmt("def f(x: int) -> str:\n    return str(x)\n")
        b = _parse_stmt("def f(x):\n    return str(x)\n")
        assert normalize_mutation(a) == normalize_mutation(b)

    def test_ann_assign_with_value_vs_plain_assign(self):
        a = _parse_stmt("x: int = 5\n")
        b = _parse_stmt("x = 5\n")
        assert normalize_mutation(a) == normalize_mutation(b)

    def test_annotation_only_handled(self):
        node = _parse_stmt("x: int\n")
        result = normalize_mutation(node)
        assert isinstance(result, str)
        assert len(result) > 0


class TestSyntaxErrorFallback:
    def test_fallback_to_stripped_source(self):
        node = cst.Name("some_invalid_thing")
        result = normalize_mutation(node)
        assert isinstance(result, str)
        assert len(result) > 0


class TestIdempotence:
    def test_same_node_same_output(self):
        node = _parse_expr("a + b\n")
        assert normalize_mutation(node) == normalize_mutation(node)

    def test_structurally_identical_nodes(self):
        a = _parse_expr("a + b\n")
        b = _parse_expr("a + b\n")
        assert normalize_mutation(a) == normalize_mutation(b)
