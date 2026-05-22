from __future__ import annotations

import libcst as cst
from mutmut.file_mutation import Mutation
from mutmut_dedup.bytecode import bytecode_filter
from mutmut_dedup.normalize import deduplicate


def _make_mutation(original: cst.CSTNode, mutated: cst.CSTNode) -> Mutation:
    return Mutation(
        original_node=original,
        mutated_node=mutated,
        contained_by_top_level_function=None,
    )


def _parse_expr(source: str) -> cst.BaseExpression:
    mod = cst.parse_module(source)
    stmt = mod.body[0]
    assert isinstance(stmt, cst.SimpleStatementLine)
    return stmt.body[0].value  # ty: ignore[unresolved-attribute]


class TestDeduplicateEmpty:
    def test_empty_list(self):
        assert deduplicate([]) == []


class TestDeduplicateSingle:
    def test_single_mutation_unchanged(self):
        orig = _parse_expr("a + b\n")
        mut = _parse_expr("a - b\n")
        mutations = [_make_mutation(orig, mut)]
        assert deduplicate(mutations) == mutations


class TestDeduplicateDifferentMutations:
    def test_different_mutated_nodes_both_kept(self):
        orig = _parse_expr("a + b\n")
        mut1 = _parse_expr("a - b\n")
        mut2 = _parse_expr("a * b\n")
        mutations = [_make_mutation(orig, mut1), _make_mutation(orig, mut2)]
        assert len(deduplicate(mutations)) == 2


class TestDeduplicateSameSite:
    def test_identical_normalized_at_same_site_deduped(self):
        orig = _parse_expr("a + b\n")
        mut1 = _parse_expr("a  -  b\n")
        mut2 = _parse_expr("a-b\n")
        mutations = [_make_mutation(orig, mut1), _make_mutation(orig, mut2)]
        result = deduplicate(mutations)
        assert len(result) == 1
        assert result[0] is mutations[0]


class TestDeduplicateDifferentSites:
    def test_identical_normalized_at_different_sites_both_kept(self):
        orig1 = _parse_expr("a + b\n")
        orig2 = _parse_expr("c + d\n")
        mut1 = _parse_expr("a - b\n")
        mut2 = _parse_expr("a - b\n")
        mutations = [_make_mutation(orig1, mut1), _make_mutation(orig2, mut2)]
        assert len(deduplicate(mutations)) == 2


class TestDeduplicateMultiple:
    def test_three_mutations_one_dup_removed(self):
        orig = _parse_expr("x + y\n")
        mut_a = _parse_expr("x - y\n")
        mut_b = _parse_expr("x  -  y\n")
        mut_c = _parse_expr("x * y\n")
        mutations = [
            _make_mutation(orig, mut_a),
            _make_mutation(orig, mut_b),
            _make_mutation(orig, mut_c),
        ]
        result = deduplicate(mutations)
        assert len(result) == 2
        assert result[0] is mutations[0]
        assert result[1] is mutations[2]


class TestDeduplicateOrderPreservation:
    def test_first_occurrence_wins(self):
        orig = _parse_expr("a + b\n")
        mut1 = _parse_expr("a-b\n")
        mut2 = _parse_expr("a  -  b\n")
        mutations = [_make_mutation(orig, mut1), _make_mutation(orig, mut2)]
        result = deduplicate(mutations)
        assert len(result) == 1
        assert result[0] is mutations[0]


def _make_func_mutation(func_node: cst.FunctionDef, original: cst.CSTNode, mutated: cst.CSTNode) -> Mutation:
    return Mutation(
        original_node=original,
        mutated_node=mutated,
        contained_by_top_level_function=func_node,
    )


class TestBytecodeFilterEquivalent:
    def test_identity_mutation_removed(self):
        """A mutation where mutated_node == original_node produces identical bytecode and is removed."""
        mod = cst.parse_module("def f(): return 1\n")
        func = mod.body[0]
        assert isinstance(func, cst.FunctionDef)
        ret_node = func.body.body[0].value  # ty: ignore[unresolved-attribute]
        mutations = [_make_func_mutation(func, ret_node, ret_node)]
        result = bytecode_filter(mutations)
        assert len(result) == 0


class TestBytecodeFilterModuleLevel:
    def test_module_level_mutations_always_kept(self):
        orig = _parse_expr("a + b\n")
        mut = _parse_expr("a - b\n")
        mutations = [_make_mutation(orig, mut)]
        result = bytecode_filter(mutations)
        assert len(result) == 1
        assert result[0] is mutations[0]


class TestBytecodeFilterDuplicates:
    def test_same_bytecode_different_nodes_deduped(self):
        """Two mutations that produce the same bytecode on the same original_node: only first kept."""
        mod = cst.parse_module("def f(x):\n    return x + 1\n")
        func = mod.body[0]
        assert isinstance(func, cst.FunctionDef)
        orig_node = func.body.body[0].body[0].value  # ty: ignore[unresolved-attribute]
        mut1 = cst.parse_expression("x  +  2")
        mut2 = cst.parse_expression("x+2")
        mutations = [
            _make_func_mutation(func, orig_node, mut1),
            _make_func_mutation(func, orig_node, mut2),
        ]
        result = bytecode_filter(mutations)
        assert len(result) == 1
        assert result[0] is mutations[0]


class TestBytecodeFilterMixed:
    def test_mixed_filtering(self):
        """5 mutations: 1 equivalent, 2 bytecode-duplicates, 2 unique → 3 remain."""
        mod = cst.parse_module("def f(x):\n    return x + 1\n")
        func = mod.body[0]
        assert isinstance(func, cst.FunctionDef)
        orig_node = func.body.body[0].body[0].value  # ty: ignore[unresolved-attribute]

        m_equiv = _make_func_mutation(func, orig_node, orig_node)
        m_dup1 = _make_func_mutation(func, orig_node, cst.parse_expression("x  +  2"))
        m_dup2 = _make_func_mutation(func, orig_node, cst.parse_expression("x+2"))
        m_unique1 = _make_func_mutation(func, orig_node, cst.parse_expression("x - 1"))
        m_unique2 = _make_func_mutation(func, orig_node, cst.parse_expression("x * 1"))

        mutations = [m_equiv, m_dup1, m_dup2, m_unique1, m_unique2]
        result = bytecode_filter(mutations)
        assert len(result) == 3
        assert m_equiv not in result
        assert m_dup1 in result
        assert m_dup2 not in result
        assert m_unique1 in result
        assert m_unique2 in result


class TestBytecodeFilterSyntaxError:
    def test_reconstruction_error_kept(self):
        """If source reconstruction raises, the mutation is conservatively kept."""
        from unittest.mock import patch

        mod = cst.parse_module("def f(): return 1\n")
        func = mod.body[0]
        assert isinstance(func, cst.FunctionDef)
        ret_node = func.body.body[0].value  # ty: ignore[unresolved-attribute]
        mut_node = cst.parse_expression("2")

        mutation = _make_func_mutation(func, ret_node, mut_node)
        with patch(
            "mutmut_dedup.bytecode.cst.Module",
            side_effect=TypeError("reconstruction failed"),
        ):
            result = bytecode_filter([mutation])
        assert len(result) == 1
