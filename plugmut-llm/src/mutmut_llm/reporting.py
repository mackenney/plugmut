"""Terminal table reporting for mutation run results.

No external dependencies — plain string formatting only.
"""

from __future__ import annotations

from .pricing import format_cost
from .storage import RunResult


def format_mutant_name(mutant_name: str) -> tuple[str, str, str]:
    """Extract (file, display_name, mutant_id) from a mutant name.

    Handles mutmut's actual naming conventions:
    - ``x_`` prefix on function names (e.g. ``x_foo__mutmut_1``)
    - ``ǁ`` (U+01C1) as class-name separator (e.g. ``xǁMyClassǁmethod__mutmut_2``)
    - Dotted module prefix (e.g. ``some.module.x_foo__mutmut_1``)
    """
    CLASS_NAME_SEPARATOR = "\u01c1"

    if "__mutmut_" in mutant_name:
        base, mutant_id = mutant_name.rsplit("__mutmut_", 1)
    else:
        base, mutant_id = mutant_name, "?"

    parts = base.split(".")
    if len(parts) >= 2:
        qualified_name = parts[-1]
        module_parts = parts[:-1]
        file_path = "/".join(module_parts) + ".py"
    else:
        qualified_name = base
        file_path = "?"

    if qualified_name.startswith("x" + CLASS_NAME_SEPARATOR):
        segments = qualified_name.split(CLASS_NAME_SEPARATOR)
        class_name = segments[1]
        func_name = segments[2] if len(segments) > 2 else class_name
        display_name = f"{class_name}.{func_name}"
    elif qualified_name.startswith("x_"):
        display_name = qualified_name[2:]
    else:
        display_name = qualified_name

    return file_path, display_name, mutant_id


def format_run_summary(run: RunResult) -> str:
    """Format a one-line summary of a run."""
    total = len(run.results)
    killed = sum(1 for r in run.results if r.status == "killed")
    survived = sum(1 for r in run.results if r.status == "survived")
    timeout = sum(1 for r in run.results if r.status == "timeout")
    llm_count = sum(1 for r in run.results if r.is_llm)
    builtin_count = total - llm_count

    kill_rate = (killed / total * 100) if total > 0 else 0

    parts = [
        f"Total: {total}",
        f"Killed: {killed}",
        f"Survived: {survived}",
    ]
    if timeout:
        parts.append(f"Timeout: {timeout}")
    parts.append(f"Kill rate: {kill_rate:.1f}%")

    llm_label = f"LLM: {llm_count}"
    if run.total_llm_cost_usd > 0:
        llm_label += f" ({format_cost(run.total_llm_cost_usd)})"
    parts.append(f"{llm_label}, Builtin: {builtin_count}")

    return " | ".join(parts)


def format_run_table(run: RunResult) -> str:
    """Format a full table of mutant results.

    Survived mutants sort first for visibility.
    """
    if not run.results:
        return "No results."

    lines = []
    lines.append(f"{'Status':<12} {'Type':<8} {'File':<40} {'Function':<25} {'Mutant'}")
    lines.append("-" * 100)

    for r in sorted(run.results, key=lambda x: (x.status != "survived", x.mutant_name)):
        file_path, function, mutant_id = format_mutant_name(r.mutant_name)
        type_label = "llm" if r.is_llm else "builtin"
        lines.append(f"{r.status:<12} {type_label:<8} {file_path:<40} {function:<25} {mutant_id}")

    lines.append("")
    lines.append(format_run_summary(run))

    return "\n".join(lines)
