"""Generation pipeline: prompt -> LLM API -> parse -> validate -> cache."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import click

from mutmut_llm.cache import (
    CacheEntry,
    CachedMutation,
    read_cache_entry,
    source_hash,
    write_cache_entry,
)
from mutmut_llm.config import LLMConfig
from mutmut_llm.prompts import SYSTEM_PROMPT, build_user_prompt, parse_llm_response
from mutmut_llm.scope import ScopeTarget, resolve_scope_deep
from mutmut_llm.validation import validate_mutation

if TYPE_CHECKING:
    from pathlib import Path


def run_generation(
    config: LLMConfig,
    paths: list[str],
    budget: int,
    dry_run: bool = False,
    base_dir: Path | None = None,
) -> int:
    """Generate LLM mutations for all functions in *paths*.

    Returns the number of API calls made.
    """
    if not config.enabled:
        click.echo("LLM plugin disabled (enabled=false in [tool.mutmut.llm]).")
        return 0

    if not dry_run and not config.is_configured:
        click.echo("Error: ANTHROPIC_API_KEY not set. Set it or use --dry-run.")
        return 0

    scope = resolve_scope_deep(paths, budget, config.max_mutations_per_function)

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

    return _generate_mutations(
        config, scope.targets, scope.budget_per_target, budget, base_dir
    )


def _generate_mutations(
    config: LLMConfig,
    targets: list[ScopeTarget],
    budget_per_target: dict[str, int],
    total_budget: int,
    base_dir: Path | None,
) -> int:
    """Call LLM for each uncached function. Returns API call count."""
    try:
        import anthropic
    except ImportError:
        click.echo(
            "Error: anthropic package not installed. Install with: pip install mutmut-llm"
        )
        return 0

    client = anthropic.Anthropic(api_key=config.api_key)
    api_calls = 0
    total_mutations = 0
    cache_kwargs = {"base_dir": base_dir} if base_dir else {}

    for target in targets:
        if api_calls >= total_budget:
            click.echo(f"\nBudget of {total_budget} API calls reached.")
            break

        src_hash = source_hash(target.source)
        cached = read_cache_entry(
            target.file_path, target.function_name, src_hash, **cache_kwargs
        )
        if cached is not None:
            click.echo(
                f"  {target.file_path}::{target.function_name} — cached ({len(cached.mutations)} mutations)"
            )
            continue

        max_mutations = budget_per_target.get(
            f"{target.file_path}::{target.function_name}",
            config.max_mutations_per_function,
        )
        click.echo(f"  {target.file_path}::{target.function_name} — generating...")

        mutations = _call_llm_and_validate(client, config, target, max_mutations)
        api_calls += 1
        total_mutations += len(mutations)

        entry = CacheEntry(
            function_name=target.function_name,
            file_path=target.file_path,
            source_hash=src_hash,
            mutations=[
                CachedMutation(
                    mutated_code=m["mutated_code"], description=m.get("description", "")
                )
                for m in mutations
            ],
            model=config.model,
        )
        write_cache_entry(entry, **cache_kwargs)

    click.echo(f"\nDone. {api_calls} API calls, {total_mutations} mutations generated.")
    return api_calls


def _call_llm_and_validate(
    client: object,
    config: LLMConfig,
    target: ScopeTarget,
    max_mutations: int,
) -> list[dict]:
    """Call LLM API, parse response, validate each mutation."""
    user_prompt = build_user_prompt(
        function_source=target.source,
        max_mutations=max_mutations,
        context=target.context,
    )

    try:
        response = client.messages.create(  # type: ignore[union-attr]
            model=config.model,
            max_tokens=config.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        warnings.warn(
            f"LLM API call failed for {target.function_name}: {e}", stacklevel=2
        )
        return []

    if response.stop_reason == "max_tokens":
        warnings.warn(
            f"Response truncated for {target.function_name} (hit max_tokens={config.max_tokens}). "
            "Increase max_tokens or reduce max_mutations_per_function.",
            stacklevel=2,
        )

    response_text = "".join(
        block.text for block in response.content if hasattr(block, "text")
    )
    mutations = parse_llm_response(response_text)

    valid: list[dict] = []
    for m in mutations:
        err = validate_mutation(m["mutated_code"], target.source)
        if err:
            click.echo(f"    Rejected: {err}")
        else:
            valid.append(m)

    return valid
