from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import libcst as cst

if TYPE_CHECKING:
    from mutmut.file_mutation import Mutation


class _StripAnnotations(ast.NodeTransformer):
    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        self.generic_visit(node)
        node.returns = None
        for arg in [*node.args.args, *node.args.posonlyargs, *node.args.kwonlyargs]:
            arg.annotation = None
        if node.args.vararg:
            node.args.vararg.annotation = None
        if node.args.kwarg:
            node.args.kwarg.annotation = None
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST | None:
        if node.value is not None:
            return ast.Assign(targets=[node.target], value=node.value)
        return None


def normalize_mutation(node: cst.CSTNode) -> str:
    """Convert a CST node to a canonical string for dedup comparison.

    Strips whitespace, comments, quote style, and type annotations.
    Falls back to stripped source on SyntaxError.
    """
    try:
        source = (
            cst.Module(body=[node]).code
            if isinstance(node, cst.BaseCompoundStatement | cst.BaseSmallStatement)
            else cst.Module(body=[cst.SimpleStatementLine(body=[node])]).code
        )
    except Exception:
        try:
            source = cst.Module(body=[], default_newline="\n").code_for_node(node)
        except Exception:
            return repr(node)

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source.strip()

    tree = _StripAnnotations().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


def normalize_pair(original: cst.CSTNode, mutated: cst.CSTNode) -> tuple[str, str]:
    """Normalize both original and mutated nodes."""
    return normalize_mutation(original), normalize_mutation(mutated)


def deduplicate(mutations: list[Mutation]) -> list[Mutation]:
    """Remove mutations whose normalized mutated_node matches another at the same original_node.

    First occurrence wins.
    """
    if not mutations:
        return mutations

    groups: dict[int, list[Mutation]] = {}
    for m in mutations:
        groups.setdefault(id(m.original_node), []).append(m)

    result: list[Mutation] = []
    seen_by_site: dict[int, set[str]] = {}

    for m in mutations:
        site_id = id(m.original_node)
        seen = seen_by_site.setdefault(site_id, set())
        norm = normalize_mutation(m.mutated_node)
        if norm not in seen:
            seen.add(norm)
            result.append(m)

    return result
