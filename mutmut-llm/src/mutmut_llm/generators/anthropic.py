"""Anthropic Claude generator for mutation generation."""
from __future__ import annotations

import asyncio
import random
import signal
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import click
from tqdm import tqdm

from mutmut_llm.config import LLMConfig
from mutmut_llm.discovery import GenerationTarget
from mutmut_llm.generators.base import GenerationStats
from mutmut_llm.library import source_hash as compute_source_hash
from mutmut_llm.pricing import calculate_cost, format_cost
from mutmut_llm.prompts import build_system_prompt, build_system_with_context, build_user_prompt, parse_llm_response
from mutmut_llm.validation import validate_mutation

if TYPE_CHECKING:
    from mutmut_llm.library import Library


class ErrorAction(Enum):
    RETRY = "retry"
    SKIP = "skip"
    STOP = "stop"


_QUOTA_KEYWORDS = frozenset(
    {
        "credit",
        "billing",
        "spending limit",
        "payment",
        "insufficient funds",
        "quota exceeded",
    }
)


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
def _sigint_handler(cancel_event: asyncio.Event):
    """Context manager that installs a SIGINT handler setting cancel_event."""

    def handler(signum, frame):
        cancel_event.set()

    old_handler = signal.signal(signal.SIGINT, handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, old_handler)


def _compute_concurrency(n_targets: int, config: LLMConfig) -> int:
    """Dynamic concurrency: n_targets // 3, clamped to [min_concurrency, max_concurrency]."""
    return max(config.min_concurrency, min(n_targets // 3, config.max_concurrency))


def _compute_backoff(attempt: int, base: float, cap: float = 30.0) -> float:
    """Compute backoff delay: base * 2^attempt + jitter, capped."""
    delay = min(base * (2**attempt), cap)
    jitter = random.uniform(0, 0.5)
    return delay + jitter


@dataclass
class GenerationResult:
    mutations: list[dict]
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


async def _call_llm_and_validate_async(
    client,
    config: LLMConfig,
    target: GenerationTarget,
    max_mutations: int,
    system_prompt: str | None = None,
) -> GenerationResult:
    """Async LLM call: build prompt, call API, parse response, validate mutations."""
    system_blocks = build_system_with_context(
        context=target.context, ttl=config.cache_ttl, system_prompt=system_prompt
    )
    user_prompt = build_user_prompt(
        function_source=target.source, max_mutations=max_mutations
    )

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


async def _call_llm_async(
    client,
    config: LLMConfig,
    target: GenerationTarget,
    max_mutations: int,
    semaphore: TrackedSemaphore,
    cancel_event: asyncio.Event,
    system_prompt: str | None = None,
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
                return await _call_llm_and_validate_async(
                    client, config, target, max_mutations, system_prompt=system_prompt
                )

            except asyncio.TimeoutError:
                if attempt < config.max_retries:
                    backoff_delay = _compute_backoff(
                        attempt, config.base_backoff_seconds
                    )
                    warnings.warn(
                        f"Timeout for {target.function_name}, retry {attempt + 1}/{config.max_retries} in {backoff_delay:.1f}s",
                        stacklevel=2,
                    )
                else:
                    warnings.warn(
                        f"All retries exhausted for {target.function_name}: timeout",
                        stacklevel=2,
                    )
                    return GenerationResult(mutations=[])

            except Exception as exc:
                action = classify_error(exc)

                if action == ErrorAction.STOP:
                    cancel_event.set()
                    raise

                if action == ErrorAction.SKIP:
                    warnings.warn(
                        f"Skipping {target.function_name}: {exc}", stacklevel=2
                    )
                    return GenerationResult(mutations=[])

                if attempt < config.max_retries:
                    backoff_delay = _compute_backoff(
                        attempt, config.base_backoff_seconds
                    )
                    warnings.warn(
                        f"Retry {attempt + 1}/{config.max_retries} for {target.function_name} in {backoff_delay:.1f}s: {exc}",
                        stacklevel=2,
                    )
                else:
                    warnings.warn(
                        f"All retries exhausted for {target.function_name}: {exc}",
                        stacklevel=2,
                    )
                    return GenerationResult(mutations=[])

    return GenerationResult(mutations=[])


class AnthropicGenerator:
    """Anthropic Claude generator implementing the Generator protocol."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self._config = config if config is not None else LLMConfig()

    def run(
        self,
        targets: list,
        budget_per_target: dict[str, int],
        library: "Library",
        total_budget: int,
    ) -> GenerationStats:
        """Generate mutations using Anthropic Claude API."""
        if total_budget == 0:
            return GenerationStats()

        return asyncio.run(
            self._run_async(targets, budget_per_target, library, total_budget)
        )

    async def _run_async(
        self,
        targets: list,
        budget_per_target: dict[str, int],
        library: "Library",
        total_budget: int,
    ) -> GenerationStats:
        """Async orchestration loop: check library cache, call API, persist via library.add()."""
        import anthropic

        config = self._config
        system_prompt = build_system_prompt()
        client = anthropic.AsyncAnthropic(api_key=config.api_key)
        cancel_event = asyncio.Event()

        sorted_targets = sorted(targets, key=lambda t: t.file_path)
        work_items: list[tuple[GenerationTarget, int]] = []

        for target in sorted_targets:
            if len(work_items) >= total_budget:
                click.echo(f"\nBudget of {total_budget} API calls reached.")
                break

            src_hash = compute_source_hash(target.source)
            cached = [
                e
                for e in library.query(src_hash)
                if e.function_name == target.function_name
                and e.file_path == target.file_path
                and e.model == config.model
            ]
            if cached:
                click.echo(
                    f"  {target.file_path}::{target.function_name} \u2014 cached ({len(cached[0].mutations)} mutations)"
                )
                continue

            max_mut = budget_per_target.get(
                f"{target.file_path}::{target.function_name}",
                config.max_mutations_per_function,
            )
            work_items.append((target, max_mut))

        if not work_items:
            click.echo("All targets cached. Nothing to generate.")
            return GenerationStats()

        concurrency = _compute_concurrency(len(work_items), config)
        semaphore = TrackedSemaphore(concurrency)

        tasks: list[tuple[GenerationTarget, asyncio.Task]] = []
        for target, max_mut in work_items:
            coro = _call_llm_async(
                client, config, target, max_mut, semaphore, cancel_event, system_prompt
            )
            tasks.append((target, asyncio.create_task(coro)))

        stats = GenerationStats()
        failed = 0

        pbar = tqdm(total=len(tasks), desc="Generating", unit="target")

        with _sigint_handler(cancel_event):
            try:
                for target, task in tasks:
                    pbar.set_postfix(
                        in_flight=semaphore.in_flight, failed=failed, cost=stats.cost_usd
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
                            for _, t in tasks:
                                t.cancel()
                        failed += 1
                        pbar.update(1)
                        pbar.set_postfix(
                            in_flight=semaphore.in_flight, failed=failed, cost=stats.cost_usd
                        )
                        continue

                    stats.api_calls += 1
                    stats.cost_usd += result.cost_usd

                    entries = library.add(
                        function_name=target.function_name,
                        file_path=target.file_path,
                        source=target.source,
                        mutations=result.mutations,
                        model=config.model,
                    )
                    mutations_stored = sum(len(e.mutations) for e in entries)
                    stats.mutations_generated += mutations_stored
                    stats.mutations_rejected += len(result.mutations) - mutations_stored

                    pbar.update(1)
                    pbar.set_postfix(
                        in_flight=semaphore.in_flight, failed=failed, cost=stats.cost_usd
                    )

            except KeyboardInterrupt:
                click.echo("\nForced exit. Cancelling all tasks...")
                for _, t in tasks:
                    t.cancel()

        pbar.close()

        cost_str = f" ({format_cost(stats.cost_usd)})" if stats.cost_usd > 0 else ""
        fail_str = f", {failed} failed" if failed else ""
        click.echo(
            f"\nDone. {stats.api_calls} API calls, {stats.mutations_generated} mutations generated{fail_str}.{cost_str}"
        )

        return stats
