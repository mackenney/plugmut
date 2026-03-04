from __future__ import annotations

import libcst as cst
from mutmut.file_mutation import Mutation

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
    return stmt.body[0].value  # type: ignore[attr-defined]


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
