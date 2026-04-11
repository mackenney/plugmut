"""Generation pipeline: prompt -> LLM API -> parse -> validate -> cache."""

from __future__ import annotations

import asyncio
import enum
import random
import signal
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
from mutmut_llm.prompts import (
    build_system_with_context,
    build_user_prompt,
    parse_llm_response,
)
from mutmut_llm.scope import ScopeTarget, resolve_scope_deep
from mutmut_llm.validation import validate_mutation


class ErrorAction(enum.Enum):
    RETRY = "retry"  # Transient error, retry with backoff
    SKIP = "skip"    # Permanent error for this target, move on
    STOP = "stop"    # Fatal error, cancel all remaining work


_QUOTA_KEYWORDS = frozenset({
    "credit",
    "billing",
    "spending limit",
    "payment",
    "insufficient funds",
    "quota exceeded",
})


def classify_error(exc: Exception) -> ErrorAction:
    """Classify an API exception into a retry action."""
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return ErrorAction.STOP

    if isinstance(exc, anthropic.PermissionDeniedError):
        return ErrorAction.STOP

    if isinstance(exc, anthropic.RateLimitError):
        msg = str(exc).lower()
        if any(kw in msg for kw in _QUOTA_KEYWORDS):
            return ErrorAction.STOP
        return ErrorAction.RETRY

    overloaded_cls = getattr(anthropic, "OverloadedError", None)
    if overloaded_cls is not None and isinstance(exc, overloaded_cls):
        return ErrorAction.RETRY

    if isinstance(exc, anthropic.InternalServerError):
        return ErrorAction.RETRY

    if isinstance(exc, (anthropic.APITimeoutError, anthropic.APIConnectionError)):
        return ErrorAction.RETRY

    skip_types: list[type] = [anthropic.BadRequestError, anthropic.NotFoundError]
    too_large_cls = getattr(anthropic, "RequestTooLargeError", None)
    if too_large_cls is not None:
        skip_types.append(too_large_cls)
    if isinstance(exc, tuple(skip_types)):
        return ErrorAction.SKIP

    return ErrorAction.SKIP


class TrackedSemaphore:
    """Semaphore that tracks the number of currently acquired slots."""

    def __init__(self, value: int) -> None:
        self._semaphore = asyncio.Semaphore(value)
        self._in_flight = 0

    @property
    def in_flight(self) -> int:
        return self._in_flight

    async def __aenter__(self) -> "TrackedSemaphore":
        await self._semaphore.acquire()
        self._in_flight += 1
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self._in_flight -= 1
        self._semaphore.release()


@contextmanager
def _sigint_handler(cancel_event: "asyncio.Event"):
    """Context manager that installs a SIGINT handler setting cancel_event."""

    def handler(signum, frame):
        cancel_event.set()

    old_handler = signal.signal(signal.SIGINT, handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, old_handler)



def _compute_concurrency(n_targets: int, config: "LLMConfig") -> int:
    """Dynamic concurrency: n_targets // 3, clamped to [min_concurrency, max_concurrency]."""
    return max(config.min_concurrency, min(n_targets // 3, config.max_concurrency))


@dataclass
class GenerationResult:
    mutations: list[dict]
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


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
    effective_base = base_dir or Path(".")
    clean_stale_temps(effective_base / CACHE_DIR)

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
    total_cost = 0.0
    total_input = 0
    total_cache_read = 0
    total_cache_write = 0
    cache_kwargs = {"base_dir": base_dir} if base_dir else {}

    sorted_targets = sorted(targets, key=lambda t: t.file_path)

    for target in sorted_targets:
        if api_calls >= total_budget:
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
                f"  {target.file_path}::{target.function_name} — cached ({len(cached.mutations)} mutations)"
            )
            continue

        max_mutations = budget_per_target.get(
            f"{target.file_path}::{target.function_name}",
            config.max_mutations_per_function,
        )
        click.echo(f"  {target.file_path}::{target.function_name} — generating...")

        result = _call_llm_and_validate(client, config, target, max_mutations)
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
                    mutated_code=m["mutated_code"], description=m.get("description", "")
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

    from mutmut_llm.pricing import format_cost

    cost_str = f" ({format_cost(total_cost)})" if total_cost > 0 else ""
    click.echo(
        f"\nDone. {api_calls} API calls, {total_mutations} mutations generated.{cost_str}"
    )
    if total_cache_read > 0:
        total_all_input = total_input + total_cache_read + total_cache_write
        if total_all_input > 0:
            pct = total_cache_read / total_all_input * 100
            click.echo(
                f"Cache hit rate: {pct:.0f}% ({total_cache_read} tokens read from cache)"
            )
    return api_calls


def _call_llm_and_validate(
    client: object,
    config: LLMConfig,
    target: ScopeTarget,
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


async def _call_llm_and_validate_async(
    client,  # anthropic.AsyncAnthropic
    config: LLMConfig,
    target: ScopeTarget,
    max_mutations: int,
) -> GenerationResult:
    """Async version of _call_llm_and_validate."""
    system_blocks = build_system_with_context(context=target.context, ttl=config.cache_ttl)
    user_prompt = build_user_prompt(function_source=target.source, max_mutations=max_mutations)

    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=config.model,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                system=system_blocks,
                messages=[{"role": "user", "content": user_prompt}],
            ),
            timeout=config.request_timeout_seconds,
        )
    except asyncio.TimeoutError:
        warnings.warn(
            f"LLM API call timed out for {target.function_name}", stacklevel=2
        )
        raise

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
    cache_creation_tokens = getattr(usage, "cache_creation_input_tokens", 0) if usage else 0
    cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) if usage else 0
    cost_usd = calculate_cost(
        config.model, input_tokens, output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
    )

    if response.stop_reason == "max_tokens":
        warnings.warn(
            f"Response truncated for {target.function_name} (hit max_tokens={config.max_tokens}). "
            "Increase max_tokens or reduce max_mutations_per_function.",
            stacklevel=2,
        )

    response_text = "".join(block.text for block in response.content if hasattr(block, "text"))
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


def _compute_backoff(attempt: int, base: float, cap: float = 30.0) -> float:
    """Compute backoff delay: base * 2^attempt + jitter, capped."""
    delay = min(base * (2 ** attempt), cap)
    jitter = random.uniform(0, 0.5)
    return delay + jitter


async def _call_llm_async(
    client,  # anthropic.AsyncAnthropic
    config: LLMConfig,
    target: ScopeTarget,
    max_mutations: int,
    semaphore: TrackedSemaphore,
    cancel_event: asyncio.Event,
) -> GenerationResult:
    """Per-target async wrapper with semaphore, retry, and cancellation."""
    backoff_delay: float | None = None

    for attempt in range(config.max_retries + 1):
        if cancel_event.is_set():
            return GenerationResult(mutations=[])

        if backoff_delay is not None:
            await asyncio.sleep(backoff_delay)
            backoff_delay = None

        if cancel_event.is_set():
            return GenerationResult(mutations=[])

        async with semaphore:
            if cancel_event.is_set():
                return GenerationResult(mutations=[])

            try:
                return await _call_llm_and_validate_async(client, config, target, max_mutations)

            except asyncio.TimeoutError:
                if attempt < config.max_retries:
                    backoff_delay = _compute_backoff(attempt, config.base_backoff_seconds)
                    warnings.warn(
                        f"Timeout for {target.function_name}, retry {attempt + 1}/{config.max_retries} in {backoff_delay:.1f}s",
                        stacklevel=2,
                    )
                else:
                    warnings.warn(f"All retries exhausted for {target.function_name}: timeout", stacklevel=2)
                    return GenerationResult(mutations=[])

            except Exception as exc:
                action = classify_error(exc)

                if action == ErrorAction.STOP:
                    cancel_event.set()
                    raise

                if action == ErrorAction.SKIP:
                    warnings.warn(f"Skipping {target.function_name}: {exc}", stacklevel=2)
                    return GenerationResult(mutations=[])

                # RETRY
                if attempt < config.max_retries:
                    backoff_delay = _compute_backoff(attempt, config.base_backoff_seconds)
                    warnings.warn(
                        f"Retry {attempt + 1}/{config.max_retries} for {target.function_name} in {backoff_delay:.1f}s: {exc}",
                        stacklevel=2,
                    )
                else:
                    warnings.warn(f"All retries exhausted for {target.function_name}: {exc}", stacklevel=2)
                    return GenerationResult(mutations=[])

    return GenerationResult(mutations=[])


async def _generate_mutations_async(
    config: LLMConfig,
    targets: list[ScopeTarget],
    budget_per_target: dict[str, int],
    total_budget: int,
    base_dir: "Path | None",
) -> int:
    """Async orchestrator for parallel mutation generation."""
    import anthropic

    effective_base = base_dir or Path(".")
    clean_stale_temps(effective_base / CACHE_DIR)

    client = anthropic.AsyncAnthropic(api_key=config.api_key)

    cache_kwargs: dict = {"base_dir": base_dir} if base_dir else {}
    cancel_event = asyncio.Event()

    sorted_targets = sorted(targets, key=lambda t: t.file_path)
    work_items: list[tuple[ScopeTarget, str, int]] = []

    for target in sorted_targets:
        if len(work_items) >= total_budget:
            click.echo(f"\nBudget of {total_budget} API calls reached.")
            break

        src_hash = source_hash(target.source)
        cached = read_cache_entry(
            target.file_path, target.function_name, src_hash,
            model=config.model, **cache_kwargs,
        )
        if cached is not None:
            click.echo(f"  {target.file_path}::{target.function_name} \u2014 cached ({len(cached.mutations)} mutations)")
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

    tasks: list[tuple[ScopeTarget, str, asyncio.Task]] = []
    for target, src_hash, max_mut in work_items:
        coro = _call_llm_async(client, config, target, max_mut, semaphore, cancel_event)
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
                pbar.set_postfix(in_flight=semaphore.in_flight, failed=failed, cost=total_cost)

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
                        click.echo("Cancelling remaining tasks. Completed work has been saved.")
                        cancel_event.set()
                        for _, _, t in tasks:
                            t.cancel()
                    failed += 1
                    pbar.update(1)
                    pbar.set_postfix(in_flight=semaphore.in_flight, failed=failed, cost=total_cost)
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
                        CachedMutation(mutated_code=m["mutated_code"], description=m.get("description", ""))
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
                pbar.set_postfix(in_flight=semaphore.in_flight, failed=failed, cost=total_cost)

        except KeyboardInterrupt:
            click.echo("\nForced exit. Cancelling all tasks...")
            for _, _, t in tasks:
                t.cancel()

    pbar.close()

    from mutmut_llm.pricing import format_cost
    cost_str = f" ({format_cost(total_cost)})" if total_cost > 0 else ""
    fail_str = f", {failed} failed" if failed else ""
    click.echo(f"\nDone. {api_calls} API calls, {total_mutations} mutations generated{fail_str}.{cost_str}")

    if total_cache_read > 0:
        total_all_input = total_input + total_cache_read + total_cache_write
        if total_all_input > 0:
            pct = total_cache_read / total_all_input * 100
            click.echo(f"Cache hit rate: {pct:.0f}% ({total_cache_read} tokens read from cache)")

    return api_calls
