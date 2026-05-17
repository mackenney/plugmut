"""Generation pipeline: prompt -> LLM API -> parse -> validate -> cache."""

from __future__ import annotations

import asyncio
import random
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path

import click
from tqdm import tqdm

from mutmut_llm._io import clean_stale_temps
from mutmut_llm.cache import (
    CACHE_DIR,
    CacheEntry,
    CachedMutation,
    read_cache_entry,
    source_hash,
    write_cache_entry,
)
from mutmut_llm.config import LLMConfig
from mutmut_llm.pricing import calculate_cost

# Re-export moved symbols so existing imports from pipeline still work.
from mutmut_llm.generators.anthropic import (
    ErrorAction,
    GenerationResult,
    TrackedSemaphore,
    _call_llm_and_validate_async,
    _call_llm_async,
    _compute_backoff,
    _compute_concurrency,
    _sigint_handler,
    classify_error,
)
from mutmut_llm.prompts import (
    build_system_prompt,
    build_system_with_context,
    build_user_prompt,
    parse_llm_response,
)
from mutmut_llm.discovery import GenerationTarget, resolve_scope_deep
from mutmut_llm.validation import validate_mutation


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

    return asyncio.run(
        _generate_mutations_async(
            config, scope.targets, scope.budget_per_target, budget, base_dir
        )
    )


def _generate_mutations(
    config: LLMConfig,
    targets: list[GenerationTarget],
    budget_per_target: dict[str, int],
    total_budget: int,
    base_dir: Path | None,
) -> int:
    """Sync wrapper around _generate_mutations_async for backward compatibility."""
    return asyncio.run(
        _generate_mutations_async(
            config, targets, budget_per_target, total_budget, base_dir
        )
    )


def _call_llm_and_validate(
    client: object,
    config: LLMConfig,
    target: GenerationTarget,
    max_mutations: int,
) -> GenerationResult:
    """Call LLM API, parse response, validate each mutation."""
    system_blocks = build_system_with_context(
        context=target.context, ttl=config.cache_ttl
    )
    user_prompt = build_user_prompt(
        function_source=target.source,
        max_mutations=max_mutations,
    )

    try:
        response = client.messages.create(  # type: ignore[union-attr]
            model=config.model,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            system=system_blocks,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        warnings.warn(
            f"LLM API call failed for {target.function_name}: {e}", stacklevel=2
        )
        return GenerationResult(mutations=[])

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
    cache_creation_tokens = (
        getattr(usage, "cache_creation_input_tokens", 0) if usage else 0
    )
    cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) if usage else 0
    cost_usd = calculate_cost(
        config.model,
        input_tokens,
        output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
    )

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

    return GenerationResult(
        mutations=valid,
        cost_usd=cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
    )


async def _generate_mutations_async(
    config: LLMConfig,
    targets: list[GenerationTarget],
    budget_per_target: dict[str, int],
    total_budget: int,
    base_dir: "Path | None",
) -> int:
    """Async orchestrator for parallel mutation generation."""
    import anthropic

    effective_base = base_dir or Path(".")
    clean_stale_temps(effective_base / CACHE_DIR)
    system_prompt = build_system_prompt()

    client = anthropic.AsyncAnthropic(api_key=config.api_key)

    cache_kwargs: dict = {"base_dir": base_dir} if base_dir else {}
    cancel_event = asyncio.Event()

    sorted_targets = sorted(targets, key=lambda t: t.file_path)
    work_items: list[tuple[GenerationTarget, str, int]] = []

    for target in sorted_targets:
        if len(work_items) >= total_budget:
            click.echo(f"\nBudget of {total_budget} API calls reached.")
            break

        src_hash = source_hash(target.source)
        cached = read_cache_entry(
            target.file_path,
            target.function_name,
            src_hash,
            model=config.model,
            **cache_kwargs,
        )
        if cached is not None:
            click.echo(
                f"  {target.file_path}::{target.function_name} \u2014 cached ({len(cached.mutations)} mutations)"
            )
            continue

        max_mut = budget_per_target.get(
            f"{target.file_path}::{target.function_name}",
            config.max_mutations_per_function,
        )
        work_items.append((target, src_hash, max_mut))

    if not work_items:
        click.echo("All targets cached. Nothing to generate.")
        return 0

    concurrency = _compute_concurrency(len(work_items), config)
    semaphore = TrackedSemaphore(concurrency)

    tasks: list[tuple[GenerationTarget, str, asyncio.Task]] = []
    for target, src_hash, max_mut in work_items:
        coro = _call_llm_async(
            client, config, target, max_mut, semaphore, cancel_event, system_prompt
        )
        tasks.append((target, src_hash, asyncio.create_task(coro)))

    api_calls = 0
    total_mutations = 0
    total_cost = 0.0
    total_input = 0
    total_cache_read = 0
    total_cache_write = 0
    failed = 0

    pbar = tqdm(
        total=len(tasks),
        desc="Generating",
        unit="target",
    )

    with _sigint_handler(cancel_event):
        try:
            for target, src_hash, task in tasks:
                pbar.set_postfix(
                    in_flight=semaphore.in_flight, failed=failed, cost=total_cost
                )

                if cancel_event.is_set():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    pbar.update(1)
                    continue

                try:
                    result = await task
                except asyncio.CancelledError:
                    pbar.update(1)
                    continue
                except Exception as exc:
                    action = classify_error(exc)
                    if action == ErrorAction.STOP:
                        click.echo(f"\n*** FATAL: {exc} ***")
                        click.echo(
                            "Cancelling remaining tasks. Completed work has been saved."
                        )
                        cancel_event.set()
                        for _, _, t in tasks:
                            t.cancel()
                    failed += 1
                    pbar.update(1)
                    pbar.set_postfix(
                        in_flight=semaphore.in_flight, failed=failed, cost=total_cost
                    )
                    continue

                api_calls += 1
                total_mutations += len(result.mutations)
                total_cost += result.cost_usd
                total_input += result.input_tokens
                total_cache_read += result.cache_read_tokens
                total_cache_write += result.cache_creation_tokens

                entry = CacheEntry(
                    function_name=target.function_name,
                    file_path=target.file_path,
                    source_hash=src_hash,
                    mutations=[
                        CachedMutation(
                            mutated_code=m["mutated_code"],
                            description=m.get("description", ""),
                        )
                        for m in result.mutations
                    ],
                    model=config.model,
                    cost_usd=result.cost_usd,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cache_creation_tokens=result.cache_creation_tokens,
                    cache_read_tokens=result.cache_read_tokens,
                    generated_at=datetime.now(timezone.utc).isoformat(),
                )
                write_cache_entry(entry, **cache_kwargs)

                pbar.update(1)
                pbar.set_postfix(
                    in_flight=semaphore.in_flight, failed=failed, cost=total_cost
                )

        except KeyboardInterrupt:
            click.echo("\nForced exit. Cancelling all tasks...")
            for _, _, t in tasks:
                t.cancel()

    pbar.close()

    from mutmut_llm.pricing import format_cost

    cost_str = f" ({format_cost(total_cost)})" if total_cost > 0 else ""
    fail_str = f", {failed} failed" if failed else ""
    click.echo(
        f"\nDone. {api_calls} API calls, {total_mutations} mutations generated{fail_str}.{cost_str}"
    )

    if total_cache_read > 0:
        total_all_input = total_input + total_cache_read + total_cache_write
        if total_all_input > 0:
            pct = total_cache_read / total_all_input * 100
            click.echo(
                f"Cache hit rate: {pct:.0f}% ({total_cache_read} tokens read from cache)"
            )

    return api_calls
