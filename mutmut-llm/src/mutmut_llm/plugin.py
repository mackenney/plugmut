"""mutmut-llm plugin: LLM-powered mutation operator for mutmut.

Registers:
- ``operator_llm`` (FunctionDef operator) via ``mutmut_register_operators``
- ``mutmut generate`` CLI command via ``mutmut_register_commands``
- ``mutmut llm-status`` CLI command for cache/run status
- Config loading via ``mutmut_configure``
- Run result tracking via ``mutmut_post_test`` / ``mutmut_post_run``
- LLM mutant identification via ``mutmut_mutations_created``
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from datetime import timezone

import click
import libcst as cst

from mutmut.hookspecs import hookimpl
from mutmut.node_mutation import OPERATORS_TYPE

from mutmut_llm.cache import list_cache_entries
from mutmut_llm.config import LLMConfig
from mutmut_llm.config import load_config
from mutmut_llm.pricing import format_cost
from mutmut_llm.operators import _reset_cache_index
from mutmut_llm.operators import operator_llm
from mutmut_llm.reporting import format_run_summary
from mutmut_llm.storage import MutantResult
from mutmut_llm.storage import RunResult
from mutmut_llm.storage import load_latest_run
from mutmut_llm.storage import new_run
from mutmut_llm.storage import save_run

_llm_config: LLMConfig | None = None
_mutmut_paths: list[str] = []
_llm_mutant_names: set[str] = set()
_current_run: RunResult | None = None


def _extract_function_name(mutant_name: str) -> str:
    """Extract the bare function name from a mangled mutant name.

    Mirrors mutmut's ``orig_function_and_class_names_from_key`` logic:
    - ``x_func__mutmut_1`` -> ``func``
    - ``xǁClassǁmethod__mutmut_2`` -> ``method``
    - Dotted module prefix (e.g. ``mod.x_func__mutmut_1``) is stripped.
    """
    CLASS_NAME_SEPARATOR = "\u01c1"

    base = mutant_name.partition("__mutmut_")[0]
    # Strip module prefix if present (e.g. "some.module.x_func")
    _, _, base = base.rpartition(".")

    if CLASS_NAME_SEPARATOR in base:
        parts = base.split(CLASS_NAME_SEPARATOR)
        # Format: "x", "ClassName", "method" — return "ClassName.method"
        class_name = parts[-2]
        method_name = parts[-1]
        return f"{class_name}.{method_name}"

    if base.startswith("x_"):
        return base[2:]

    return base


def _llm_mutation_count_by_function() -> dict[str, int]:
    """Count LLM mutations per function name from the cache, deduplicated.

    Entries sharing the same source_hash (same function body) may come from
    different models and contain overlapping mutations. We deduplicate by
    mutated_code within each (source_hash, function_name) group, matching
    operator_llm's behavior which groups by source_hash.

    Different functions that happen to share a source_hash (e.g. identical
    bodies in different files) each get their own count. operator_llm merges
    them by hash, so each function_name gets the full deduplicated set.
    """
    by_hash_and_func: dict[tuple[str, str], list[CacheEntry]] = defaultdict(list)
    for entry in list_cache_entries():
        by_hash_and_func[(entry.source_hash, entry.function_name)].append(entry)

    # operator_llm deduplicates by source_hash across all function names,
    # so each function_name with the same hash sees the same merged set.
    deduped_by_hash: dict[str, set[str]] = defaultdict(set)
    for (src_hash, _func_name), entries in by_hash_and_func.items():
        for entry in entries:
            for m in entry.mutations:
                deduped_by_hash[src_hash].add(m.mutated_code)

    counts: dict[str, int] = defaultdict(int)
    func_names_by_hash: dict[str, set[str]] = defaultdict(set)
    for src_hash, func_name in by_hash_and_func:
        func_names_by_hash[src_hash].add(func_name)

    for src_hash, unique_mutations in deduped_by_hash.items():
        for func_name in func_names_by_hash[src_hash]:
            counts[func_name] += len(unique_mutations)
    return counts


@hookimpl
def mutmut_configure(config: object) -> None:
    global _llm_config, _mutmut_paths, _current_run
    _llm_mutant_names.clear()
    _reset_cache_index()
    _llm_config = load_config()
    if hasattr(config, "paths_to_mutate"):
        _mutmut_paths = [str(p) for p in config.paths_to_mutate]
    _current_run = new_run()


@hookimpl
def mutmut_register_operators() -> OPERATORS_TYPE:
    if _llm_config and _llm_config.enabled:
        return [(cst.FunctionDef, operator_llm)]
    return []


@hookimpl
def mutmut_mutations_created(
    filename: str, source_by_mutant_name: dict[str, str]
) -> None:
    """Identify which mutants came from the LLM operator.

    For each function, builtin operators run first. The LLM operator appends
    its mutations after. So for a function with B builtin + L LLM mutations,
    the last L mutant indices belong to the LLM operator.
    """
    llm_counts = _llm_mutation_count_by_function()
    if not llm_counts:
        return

    # Group mutant names by function name, preserving order
    mutants_by_func: dict[str, list[str]] = defaultdict(list)
    for mutant_name in source_by_mutant_name:
        func_name = _extract_function_name(mutant_name)
        mutants_by_func[func_name].append(mutant_name)

    for func_name, mutant_names in mutants_by_func.items():
        llm_count = llm_counts.get(func_name, 0)
        if llm_count <= 0:
            continue
        # LLM mutations are the last `llm_count` in the list
        llm_mutants = mutant_names[-llm_count:]
        _llm_mutant_names.update(llm_mutants)


@hookimpl
def mutmut_post_test(
    mutant_name: str, exit_code: int, status: str, duration: float
) -> None:
    if _current_run is None:
        return
    _current_run.results.append(
        MutantResult(
            mutant_name=mutant_name,
            status=status,
            duration=duration,
            is_llm=mutant_name in _llm_mutant_names,
        )
    )


@hookimpl
def mutmut_post_run(source_file_mutation_data: Sequence) -> None:
    if _current_run is None:
        return
    _current_run.completed_at = datetime.now(timezone.utc).isoformat()

    # Sums across ALL cached entries regardless of model. After running with
    # model A then B, this reports A+B total. Per-model breakdown would require
    # filtering by the active model config, which we intentionally skip here
    # to keep the cost field a simple cumulative metric.
    entries = list_cache_entries()
    _current_run.total_llm_cost_usd = sum(e.cost_usd for e in entries)
    _current_run.total_input_tokens = sum(e.input_tokens for e in entries)
    _current_run.total_output_tokens = sum(e.output_tokens for e in entries)

    save_run(_current_run)


@hookimpl
def mutmut_register_commands(cli_group: object) -> None:
    @cli_group.command()  # type: ignore[union-attr]
    @click.option("--budget", type=int, default=20, help="Max API calls.")
    @click.option("--dry-run", is_flag=True, help="Show functions without calling LLM.")
    @click.option(
        "--paths", multiple=True, help="Paths to scan (overrides mutmut config)."
    )
    def generate(budget: int, dry_run: bool, paths: tuple[str, ...]) -> None:
        """Generate LLM mutations for functions in scope."""
        from mutmut_llm.pipeline import run_generation

        config = _llm_config or load_config()
        scan_paths = list(paths) if paths else (_mutmut_paths or ["src"])
        run_generation(config=config, paths=scan_paths, budget=budget, dry_run=dry_run)

    @cli_group.command("llm-status")  # type: ignore[union-attr]
    def llm_status() -> None:
        """Show LLM mutation cache stats, latest run, and config."""
        config = _llm_config or load_config()

        entries = list_cache_entries()
        total_mutations = sum(len(e.mutations) for e in entries)
        total_cost = sum(e.cost_usd for e in entries)
        click.echo(f"LLM config: enabled={config.enabled}, model={config.model}")
        click.echo(f"Cache: {len(entries)} functions, {total_mutations} mutations")
        if total_cost > 0:
            avg = total_cost / len(entries) if entries else 0
            click.echo(f"Total generation cost: {format_cost(total_cost)}")
            click.echo(f"Average cost per function: {format_cost(avg)}")

        latest = load_latest_run()
        if latest:
            click.echo(f"Latest run ({latest.run_id}): {format_run_summary(latest)}")
        else:
            click.echo("No runs recorded.")
