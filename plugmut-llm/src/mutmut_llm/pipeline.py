"""Compatibility shim: re-exports pipeline symbols from their new locations.

All generation logic now lives in generators/anthropic.py and plugin.py.
This module exists only for backward compatibility with existing imports.
"""

from __future__ import annotations

from pathlib import Path

import click

from mutmut_llm.generators.anthropic import ErrorAction as ErrorAction
from mutmut_llm.generators.anthropic import GenerationResult as GenerationResult
from mutmut_llm.generators.anthropic import TrackedSemaphore as TrackedSemaphore
from mutmut_llm.generators.anthropic import _call_llm_and_validate_async as _call_llm_and_validate_async
from mutmut_llm.generators.anthropic import _call_llm_async as _call_llm_async
from mutmut_llm.generators.anthropic import _compute_backoff as _compute_backoff
from mutmut_llm.generators.anthropic import _compute_concurrency as _compute_concurrency
from mutmut_llm.generators.anthropic import _sigint_handler as _sigint_handler
from mutmut_llm.generators.anthropic import classify_error as classify_error

__all__ = [
    "ErrorAction",
    "GenerationResult",
    "TrackedSemaphore",
    "_call_llm_and_validate_async",
    "_call_llm_async",
    "_compute_backoff",
    "_compute_concurrency",
    "_sigint_handler",
    "classify_error",
    "run_generation",
]


def run_generation(
    config,
    paths: list[str],
    budget: int,
    dry_run: bool = False,
    base_dir: Path | None = None,
) -> int:
    """Generate LLM mutations for all functions in *paths*.

    Compatibility shim around AnthropicGenerator. Returns the number of API calls made.
    """
    from mutmut_llm.discovery import resolve_scope_deep
    from mutmut_llm.generators.anthropic import AnthropicGenerator
    from mutmut_llm.library import Library

    if not config.enabled:
        click.echo("LLM plugin disabled (enabled=false in [tool.plugmut.llm]).")
        return 0

    if not dry_run and not config.is_configured:
        click.echo("Error: ANTHROPIC_API_KEY not set. Set it or use --dry-run.")
        return 0

    scope = resolve_scope_deep(
        paths,
        budget,
        config.max_mutations_per_function,
        config.min_mutations_per_function,
    )

    if not scope.targets:
        click.echo("No functions found in scope.")
        return 0

    click.echo(f"Found {len(scope.targets)} functions in scope (deep mode).")

    if dry_run:
        click.echo("\nDry run — functions that would be mutated:")
        for t in scope.targets:
            n = scope.budget_per_target.get(f"{t.file_path}::{t.function_name}", 0)
            click.echo(f"  {t.file_path}::{t.function_name} (budget: {n})")
        return 0

    library = Library(base_dir=base_dir or Path("."))
    generator = AnthropicGenerator(config=config)
    stats = generator.run(
        targets=scope.targets,
        budget_per_target=scope.budget_per_target,
        library=library,
        total_budget=budget,
    )
    return stats.api_calls
