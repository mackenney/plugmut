"""Scope resolution for LLM mutation generation.

Deep mode only (v1): walk source paths, extract all functions via libcst.
PR and targeted modes deferred to Step 8.
"""

from __future__ import annotations

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
) -> ScopeResult:
    """Deep mode: extract all functions from *paths* (files or directories)."""
    targets: list[ScopeTarget] = []

    for source_file in _discover_python_files(paths):
        targets.extend(_extract_functions(source_file))

    alloc = _allocate_budget(targets, budget, max_per_function)
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


def _allocate_budget(
    targets: list[ScopeTarget],
    total_budget: int,
    max_per_function: int,
) -> dict[str, int]:
    """Uniform budget allocation: equal per function, capped at max_per_function and total_budget."""
    if not targets or total_budget <= 0:
        return {}

    per_function = min(max_per_function, max(1, total_budget // len(targets)))
    alloc: dict[str, int] = {}
    remaining = total_budget
    for t in targets:
        n = min(per_function, remaining)
        if n <= 0:
            break
        alloc[f"{t.file_path}::{t.function_name}"] = n
        remaining -= n
    return alloc
