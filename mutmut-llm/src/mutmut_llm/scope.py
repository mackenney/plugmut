"""Scope resolution for LLM mutation generation.

Deep mode only (v1): walk source paths, extract all functions via libcst.
PR and targeted modes deferred to Step 8.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

import libcst as cst


@dataclass
class ScopeTarget:
    file_path: str
    function_name: str
    source: str
    context: str = ""


@dataclass
class ScopeResult:
    targets: list[ScopeTarget]
    mode: str
    budget: int
    budget_per_target: dict[str, int] = field(default_factory=dict)


def resolve_scope_deep(
    paths: list[str],
    budget: int,
    max_per_function: int = 5,
    min_per_function: int = 2,
) -> ScopeResult:
    """Deep mode: extract all functions from *paths* (files or directories)."""
    targets: list[ScopeTarget] = []

    for source_file in _discover_python_files(paths):
        targets.extend(_extract_functions(source_file))

    alloc = _allocate_budget(targets, budget, max_per_function, min_per_function)
    return ScopeResult(
        targets=targets, mode="deep", budget=budget, budget_per_target=alloc
    )


def _discover_python_files(paths: list[str]) -> list[str]:
    """Expand paths (files and directories) into .py file list."""
    result: list[str] = []
    for p_str in paths:
        p = Path(p_str)
        if p.is_file() and p.suffix == ".py":
            result.append(str(p))
        elif p.is_dir():
            result.extend(str(f) for f in sorted(p.rglob("*.py")))
    return result


def _extract_functions(file_path: str) -> list[ScopeTarget]:
    """Extract all functions from a Python file."""
    try:
        source = Path(file_path).read_text()
        module = cst.parse_module(source)
    except Exception:
        return []

    targets: list[ScopeTarget] = []

    for stmt in module.body:
        if isinstance(stmt, cst.FunctionDef):
            func_source = module.code_for_node(stmt)
            module_context = _build_module_context(module, func_source)
            targets.append(
                ScopeTarget(
                    file_path=file_path,
                    function_name=stmt.name.value,
                    source=func_source,
                    context=module_context,
                )
            )
        elif isinstance(stmt, cst.ClassDef):
            for class_stmt in stmt.body.body:
                if isinstance(class_stmt, cst.FunctionDef):
                    func_source = module.code_for_node(class_stmt)
                    module_context = _build_module_context(module, func_source)
                    class_context = _build_class_context(
                        module,
                        stmt,
                        module_context,
                        target_function_name=class_stmt.name.value,
                    )
                    qualified_name = f"{stmt.name.value}.{class_stmt.name.value}"
                    targets.append(
                        ScopeTarget(
                            file_path=file_path,
                            function_name=qualified_name,
                            source=func_source,
                            context=class_context,
                        )
                    )

    return targets


class _NameCollector(cst.CSTVisitor):
    """Collect all Name node values (identifier references) in a CST subtree."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: cst.Name) -> None:
        self.names.add(node.value)


def _referenced_names(source: str) -> set[str]:
    """Return the set of identifiers referenced in source, excluding string literals and comments."""
    try:
        tree = cst.parse_module(source)
    except cst.ParserSyntaxError:
        return set()
    collector = _NameCollector()
    tree.visit(collector)
    return collector.names


def _build_module_context(module: cst.Module, function_source: str) -> str:
    """Extract imports and module-level constants relevant to the target function."""
    func_names = _referenced_names(function_source)
    lines: list[str] = []

    for stmt in module.body:
        if isinstance(stmt, cst.SimpleStatementLine):
            for item in stmt.body:
                if isinstance(item, (cst.Import, cst.ImportFrom)):
                    # Wildcard imports are always included: can't determine usage statically.
                    if isinstance(item, cst.ImportFrom) and isinstance(
                        item.names, cst.ImportStar
                    ):
                        lines.append(module.code_for_node(stmt).strip())
                    else:
                        imported_names = _extract_imported_names(item)
                        if imported_names & func_names:
                            lines.append(module.code_for_node(stmt).strip())
                    break
                elif isinstance(item, (cst.Assign, cst.AnnAssign)):
                    assign_names = _extract_assign_targets(item)
                    if assign_names & func_names:
                        lines.append(module.code_for_node(stmt).strip())
                    break

    return "\n".join(lines)


def _extract_imported_names(node: cst.Import | cst.ImportFrom) -> set[str]:
    """Extract the locally-bound names from an import statement."""
    names: set[str] = set()
    if isinstance(node, cst.ImportFrom) and isinstance(node.names, (list, tuple)):
        for alias in node.names:
            if isinstance(alias, cst.ImportAlias):
                if alias.asname and isinstance(alias.asname.name, cst.Name):
                    names.add(alias.asname.name.value)
                elif isinstance(alias.name, cst.Name):
                    names.add(alias.name.value)
                elif isinstance(alias.name, cst.Attribute):
                    # from x import a.b -> bound name is the full dotted path's last segment
                    names.add(_rightmost_name(alias.name))
    elif isinstance(node, cst.Import) and isinstance(node.names, (list, tuple)):
        for alias in node.names:
            if isinstance(alias, cst.ImportAlias):
                if alias.asname and isinstance(alias.asname.name, cst.Name):
                    names.add(alias.asname.name.value)
                elif isinstance(alias.name, cst.Name):
                    names.add(alias.name.value)
                elif isinstance(alias.name, cst.Attribute):
                    # import a.b.c -> Python binds "a" in local scope (no asname)
                    names.add(_leftmost_name(alias.name))
    return names


def _rightmost_name(node: cst.Attribute | cst.Name) -> str:
    if isinstance(node, cst.Name):
        return node.value
    return node.attr.value


def _leftmost_name(node: cst.Attribute | cst.Name) -> str:
    if isinstance(node, cst.Name):
        return node.value
    assert isinstance(node.value, (cst.Attribute, cst.Name))
    return _leftmost_name(node.value)


def _extract_assign_targets(node: cst.Assign | cst.AnnAssign) -> set[str]:
    """Extract target names from an assignment statement."""
    names: set[str] = set()
    if isinstance(node, cst.AnnAssign):
        if isinstance(node.target, cst.Name):
            names.add(node.target.value)
    elif isinstance(node, cst.Assign):
        for target in node.targets:
            if isinstance(target.target, cst.Name):
                names.add(target.target.value)
    return names


def _build_class_context(
    module: cst.Module,
    class_def: cst.ClassDef,
    module_context: str,
    target_function_name: str = "",
) -> str:
    """Build context with class header, attributes, and method signatures.

    Skips the target function's own stub to avoid it appearing twice in context.
    """
    parts: list[str] = []

    header = f"class {class_def.name.value}"
    if class_def.bases:
        bases = ", ".join(
            module.code_for_node(b.value).strip() for b in class_def.bases
        )
        header += f"({bases})"
    header += ":"
    parts.append(header)

    for stmt in class_def.body.body:
        if isinstance(stmt, cst.SimpleStatementLine):
            code = module.code_for_node(stmt).strip()
            parts.append(f"    {code}")
        elif isinstance(stmt, cst.FunctionDef):
            if target_function_name and stmt.name.value == target_function_name:
                continue  # target already provided as full source; skip stub
            sig = _extract_signature(module, stmt)
            parts.append(f"    {sig}")

    class_block = "\n".join(parts)
    if module_context:
        return f"{module_context}\n\n{class_block}"
    return class_block


def _extract_signature(module: cst.Module, func: cst.FunctionDef) -> str:
    """Extract ``def name(params) -> ret: ...`` from a FunctionDef."""
    params_code = module.code_for_node(func.params).strip()
    name = func.name.value

    decorators = ""
    for dec in func.decorators:
        dec_code = module.code_for_node(dec).strip()
        decorators += f"{dec_code}\n    "

    ret = ""
    if func.returns:
        ret_code = module.code_for_node(func.returns.annotation).strip()
        ret = f" -> {ret_code}"

    return f"{decorators}def {name}({params_code}){ret}: ..."


def _branch_count(source: str) -> int:
    """Count branch-introducing AST nodes (excludes keywords in strings/comments)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(
            node,
            (
                ast.If,
                ast.For,
                ast.While,
                ast.Try,
                ast.ExceptHandler,
                ast.With,
                ast.AsyncFor,
                ast.AsyncWith,
            ),
        ):
            count += 1
    return count


def compute_mutation_budget(
    source: str, min_budget: int = 2, max_budget: int = 10
) -> int:
    """Scale mutation budget by function complexity (lines + branching)."""
    lines = [
        line
        for line in source.strip().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    effective = max(1, len(lines) - 1)
    base = effective // 3
    branch_bonus = _branch_count(source) // 3
    return min(max_budget, max(min_budget, base + branch_bonus))


def _allocate_budget(
    targets: list[ScopeTarget],
    total_budget: int,
    max_per_function: int,
    min_per_function: int = 2,
) -> dict[str, int]:
    """Complexity-weighted budget allocation per function, scaled to fit total_budget."""
    if not targets or total_budget <= 0:
        return {}

    keys = [f"{t.file_path}::{t.function_name}" for t in targets]
    raw_budgets = [
        compute_mutation_budget(
            t.source, min_budget=min_per_function, max_budget=max_per_function
        )
        for t in targets
    ]

    total_raw = sum(raw_budgets)
    if total_raw <= total_budget:
        return dict(zip(keys, raw_budgets))

    # Scale down proportionally, respecting total_budget hard cap
    scale = total_budget / total_raw
    scaled = [max(1, int(v * scale)) for v in raw_budgets]

    # Trim excess by reducing largest-first until we fit
    remaining = sum(scaled) - total_budget
    if remaining > 0:
        indices = sorted(range(len(scaled)), key=lambda i: scaled[i], reverse=True)
        for i in indices:
            if remaining <= 0:
                break
            if scaled[i] > 1:
                scaled[i] -= 1
                remaining -= 1

    # If still over (all at 1), truncate to only budget-many targets
    alloc: dict[str, int] = {}
    budget_left = total_budget
    for k, v in zip(keys, scaled):
        if budget_left <= 0:
            break
        n = min(v, budget_left)
        alloc[k] = n
        budget_left -= n

    return alloc
