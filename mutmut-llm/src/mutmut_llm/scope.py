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

    module_context = _build_module_context(module)
    targets: list[ScopeTarget] = []

    for stmt in module.body:
        if isinstance(stmt, cst.FunctionDef):
            targets.append(
                ScopeTarget(
                    file_path=file_path,
                    function_name=stmt.name.value,
                    source=module.code_for_node(stmt),
                    context=module_context,
                )
            )
        elif isinstance(stmt, cst.ClassDef):
            class_context = _build_class_context(module, stmt, module_context)
            for class_stmt in stmt.body.body:
                if isinstance(class_stmt, cst.FunctionDef):
                    qualified_name = f"{stmt.name.value}.{class_stmt.name.value}"
                    targets.append(
                        ScopeTarget(
                            file_path=file_path,
                            function_name=qualified_name,
                            source=module.code_for_node(class_stmt),
                            context=class_context,
                        )
                    )

    return targets


def _build_module_context(module: cst.Module) -> str:
    """Extract import statements as context for LLM prompts."""
    lines: list[str] = []
    for stmt in module.body:
        if isinstance(stmt, cst.SimpleStatementLine):
            for item in stmt.body:
                if isinstance(item, (cst.Import, cst.ImportFrom)):
                    lines.append(module.code_for_node(stmt).strip())
                    break
    return "\n".join(lines)


def _build_class_context(
    module: cst.Module, class_def: cst.ClassDef, module_context: str
) -> str:
    """Build context including class header for method mutations."""
    parts: list[str] = [f"class {class_def.name.value}"]
    if class_def.bases:
        bases = ", ".join(module.code_for_node(b) for b in class_def.bases)
        parts.append(f"({bases})")
    parts.append(":")
    class_header = "".join(parts)

    if module_context:
        return f"{module_context}\n\n{class_header}\n    ..."
    return f"{class_header}\n    ..."


def _branch_count(source: str) -> int:
    """Count branch-introducing AST nodes (excludes keywords in strings/comments)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.ExceptHandler, ast.With, ast.AsyncFor, ast.AsyncWith)):
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
