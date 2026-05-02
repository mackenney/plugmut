# Async Parallel Generation

## Context

The pipeline (`mutmut-llm/src/mutmut_llm/pipeline.py`) is fully sequential: one `client.messages.create()` call at a time inside a `for target in targets` loop. Each call takes 2-10 seconds (network + LLM inference). For 50 functions, that is 2-8 minutes of pure I/O wait.

The Anthropic Python SDK provides `AsyncAnthropic` with identical API surface to the synchronous client. All methods return coroutines: `await client.messages.create(...)`. An optional `aiohttp` backend (`pip install anthropic[aiohttp]`) improves concurrency over the default `httpx.AsyncClient`.

The SDK already retries 429, 529, and 5xx errors twice with exponential backoff (base 0.5s, max 60s, jitter 0.75-1.0x), respecting `Retry-After` headers. Our implementation builds on top of this with additional application-level controls.

## Requirements

1. Replace `anthropic.Anthropic` with `anthropic.AsyncAnthropic` for parallel API calls.
2. `asyncio.Semaphore` to cap max concurrent requests (configurable, default 5).
3. Application-level exponential backoff for rate limiting after SDK retries are exhausted.
4. Early stop with prominent warning on authentication/quota/credit errors.
5. Progress bar showing completed/total/failed counts.
6. Graceful shutdown on Ctrl+C: cancel pending tasks, save completed work.
7. Per-request timeout (don't hang forever on slow responses).
8. Cost accumulator updated atomically per completed task.
9. Dry-run mode compatibility (unchanged).
10. Structured logging of retry attempts and error classification.

## Anthropic Error Classification

From the [official error docs](https://platform.claude.com/docs/en/api/errors) and [SDK source](https://deepwiki.com/anthropics/anthropic-sdk-python/4.5-request-lifecycle-and-error-handling):

| HTTP | SDK Exception | Category | Action |
|------|--------------|----------|--------|
| 400 | `BadRequestError` | Permanent | Skip target, log error |
| 401 | `AuthenticationError` | Fatal | Early stop all tasks, big warning |
| 403 | `PermissionDeniedError` | Fatal | Early stop, check API key permissions |
| 404 | `NotFoundError` | Permanent | Skip target (invalid model?) |
| 413 | `RequestTooLargeError` | Permanent | Skip target, warn about function size |
| 429 | `RateLimitError` | Transient | SDK retries first, then app-level backoff |
| 500 | `InternalServerError` | Transient | SDK retries first, then app-level retry (limited) |
| 529 | `OverloadedError` | Transient | SDK retries first, then app-level backoff |

The SDK retries 429/529/5xx automatically (2 retries, exponential backoff with jitter). When those retries are exhausted, the exception propagates to our code.

**Credit exhaustion detection**: Anthropic does not have a dedicated 402 status code for credit exhaustion. Credit/billing issues surface as either:
- `AuthenticationError` (401) with a message mentioning billing or credits
- `PermissionDeniedError` (403) with a message about account status
- `RateLimitError` (429) with a message about spending limits

The error classifier must inspect `error.message` for keywords like "credit", "billing", "spending limit", "payment" to distinguish quota exhaustion from normal rate limiting.

## Standard Features Beyond User Requirements

- **Per-request timeout**: `httpx` timeout on the `AsyncAnthropic` client (default 120s), plus `asyncio.wait_for()` as a safety net.
- **Progress bar**: `tqdm` with format `[completed/total] failed:N cost:$X.XX`. Falls back to click.echo if tqdm unavailable.
- **Graceful Ctrl+C**: Register a signal handler that sets a cancellation flag. Pending `asyncio.gather()` tasks check this flag before starting new API calls. Already-in-flight calls complete and their results are cached.
- **Cost accumulator**: A simple float updated in the main coroutine after each task completes (asyncio is single-threaded, no lock needed). Total is displayed in the progress bar.
- **File-grouping preservation**: Sort targets by `file_path` before dispatching, and use a per-file semaphore ordering hint so functions from the same file tend to execute consecutively. This maximizes prompt cache hits (see [prompt-caching-strategy.md](prompt-caching-strategy.md)).
- **Dry-run unchanged**: The async path is only entered when actually calling the API.
- **Retry budget**: Max 3 application-level retries per target (on top of SDK's 2 internal retries). After that, the target is marked failed and skipped.

## Implementation Plan

### Step 1: Error classifier function

**New function in `pipeline.py`**

```python
import anthropic

class ErrorAction(enum.Enum):
    RETRY = "retry"
    SKIP = "skip"
    STOP = "stop"

_QUOTA_KEYWORDS = {"credit", "billing", "spending limit", "payment", "insufficient"}

def classify_error(exc: Exception) -> ErrorAction:
    if isinstance(exc, anthropic.AuthenticationError):
        return ErrorAction.STOP
    if isinstance(exc, anthropic.PermissionDeniedError):
        msg = str(exc).lower()
        if any(kw in msg for kw in _QUOTA_KEYWORDS):
            return ErrorAction.STOP
        return ErrorAction.STOP
    if isinstance(exc, (anthropic.RateLimitError, anthropic.OverloadedError)):
        msg = str(exc).lower()
        if any(kw in msg for kw in _QUOTA_KEYWORDS):
            return ErrorAction.STOP
        return ErrorAction.RETRY
    if isinstance(exc, anthropic.InternalServerError):
        return ErrorAction.RETRY
    if isinstance(exc, (anthropic.BadRequestError, anthropic.RequestTooLargeError)):
        return ErrorAction.SKIP
    if isinstance(exc, (anthropic.APITimeoutError, anthropic.APIConnectionError)):
        return ErrorAction.RETRY
    return ErrorAction.SKIP
```

### Step 2: Async LLM call wrapper with semaphore and backoff

**New function in `pipeline.py`**

```python
async def _call_llm_async(
    client: anthropic.AsyncAnthropic,
    config: LLMConfig,
    target: ScopeTarget,
    max_mutations: int,
    semaphore: asyncio.Semaphore,
    cancel_event: asyncio.Event,
    max_retries: int = 3,
    base_backoff: float = 1.0,
) -> GenerationResult:
    for attempt in range(max_retries + 1):
        if cancel_event.is_set():
            return GenerationResult(mutations=[])

        async with semaphore:
            if cancel_event.is_set():
                return GenerationResult(mutations=[])
            try:
                return await _call_llm_and_validate_async(
                    client, config, target, max_mutations
                )
            except Exception as exc:
                action = classify_error(exc)
                if action == ErrorAction.STOP:
                    cancel_event.set()
                    raise
                if action == ErrorAction.SKIP:
                    warnings.warn(
                        f"Skipping {target.function_name}: {exc}",
                        stacklevel=2,
                    )
                    return GenerationResult(mutations=[])
                if attempt < max_retries:
                    delay = base_backoff * (2 ** attempt) + random.uniform(0, 0.5)
                    warnings.warn(
                        f"Retry {attempt+1}/{max_retries} for "
                        f"{target.function_name} after {delay:.1f}s: {exc}",
                        stacklevel=2,
                    )
                    await asyncio.sleep(delay)
                else:
                    warnings.warn(
                        f"All retries exhausted for {target.function_name}: {exc}",
                        stacklevel=2,
                    )
                    return GenerationResult(mutations=[])
    return GenerationResult(mutations=[])
```

### Step 3: Async version of `_call_llm_and_validate`

**New function in `pipeline.py`**. Nearly identical to the sync version but uses `await client.messages.create(...)`.

```python
async def _call_llm_and_validate_async(
    client: anthropic.AsyncAnthropic,
    config: LLMConfig,
    target: ScopeTarget,
    max_mutations: int,
) -> GenerationResult:
    user_prompt = build_user_prompt(
        function_source=target.source,
        max_mutations=max_mutations,
        context=target.context,
    )
    response = await client.messages.create(
        model=config.model,
        max_tokens=config.max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    # ... identical parsing/validation as sync version ...
```

The sync `_call_llm_and_validate` is kept for backward compatibility (tests, potential sync callers). The async version delegates to the same `parse_llm_response` and `validate_mutation` functions (both are pure CPU, no I/O).

### Step 4: Async generation orchestrator

**Replaces `_generate_mutations()` with `_generate_mutations_async()`**

```python
async def _generate_mutations_async(
    config: LLMConfig,
    targets: list[ScopeTarget],
    budget_per_target: dict[str, int],
    total_budget: int,
    base_dir: Path | None,
) -> int:
    client = anthropic.AsyncAnthropic(api_key=config.api_key)
    semaphore = asyncio.Semaphore(config.max_concurrency)
    cancel_event = asyncio.Event()
    cache_kwargs = {"base_dir": base_dir} if base_dir else {}

    # Filter to uncached targets, respecting budget
    work_items: list[tuple[ScopeTarget, str, int]] = []
    for target in sorted(targets, key=lambda t: t.file_path):
        if len(work_items) >= total_budget:
            break
        src_hash = source_hash(target.source)
        cached = read_cache_entry(
            target.file_path, target.function_name, src_hash, **cache_kwargs
        )
        if cached is not None:
            click.echo(f"  {target.file_path}::{target.function_name} — cached")
            continue
        max_mut = budget_per_target.get(
            f"{target.file_path}::{target.function_name}",
            config.max_mutations_per_function,
        )
        work_items.append((target, src_hash, max_mut))

    if not work_items:
        click.echo("All targets cached. Nothing to generate.")
        return 0

    # Create tasks
    tasks = []
    for target, src_hash, max_mut in work_items:
        coro = _call_llm_async(
            client, config, target, max_mut,
            semaphore, cancel_event,
            max_retries=config.max_retries,
            base_backoff=config.base_backoff_seconds,
        )
        tasks.append((target, src_hash, asyncio.create_task(coro)))

    # Progress tracking
    api_calls = 0
    total_mutations = 0
    total_cost = 0.0
    failed = 0

    try:
        for target, src_hash, task in tasks:
            try:
                result = await task
            except Exception as exc:
                # ErrorAction.STOP exceptions propagate here
                action = classify_error(exc)
                if action == ErrorAction.STOP:
                    click.echo(
                        f"\n*** FATAL: {exc} ***\n"
                        "Cancelling remaining tasks. Completed work has been saved."
                    )
                    for _, _, t in tasks:
                        t.cancel()
                    break
                failed += 1
                continue

            api_calls += 1
            total_mutations += len(result.mutations)
            total_cost += result.cost_usd

            if result.mutations or result.cost_usd > 0:
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
                    generated_at=datetime.now(timezone.utc).isoformat(),
                )
                write_cache_entry(entry, **cache_kwargs)
    except KeyboardInterrupt:
        click.echo("\nInterrupted. Cancelling pending tasks...")
        for _, _, t in tasks:
            t.cancel()

    cost_str = f" ({format_cost(total_cost)})" if total_cost > 0 else ""
    fail_str = f", {failed} failed" if failed else ""
    click.echo(
        f"\nDone. {api_calls} API calls, {total_mutations} mutations generated"
        f"{fail_str}.{cost_str}"
    )
    return api_calls
```

**Key design decisions:**
- Tasks are created upfront but semaphore-controlled, so at most `max_concurrency` are in-flight.
- Cache reads happen synchronously before dispatching (they are fast local file reads).
- Cache writes happen synchronously after each task completes (sequential in the await loop). This avoids concurrent writes to the same file and sidesteps the need for atomic writes until that plan is implemented.
- `cancel_event` propagates early stop: when a fatal error occurs, all tasks check the flag before acquiring the semaphore.

### Step 5: Entry point wrapper

**Modified `run_generation()` in `pipeline.py`**

```python
def run_generation(
    config: LLMConfig,
    paths: list[str],
    budget: int,
    dry_run: bool = False,
    base_dir: Path | None = None,
) -> int:
    # ... existing validation (enabled check, API key check, scope resolution) ...

    if dry_run:
        # ... existing dry run output ...
        return 0

    return asyncio.run(
        _generate_mutations_async(
            config, scope.targets, scope.budget_per_target, budget, base_dir
        )
    )
```

The public `run_generation()` stays synchronous. `asyncio.run()` creates and tears down the event loop. This keeps the CLI integration unchanged.

### Step 6: Config additions

**Modified `config.py`**

Add to `LLMConfig`:

```python
@dataclass
class LLMConfig:
    # ... existing fields ...
    max_concurrency: int = 5
    max_retries: int = 3
    base_backoff_seconds: float = 1.0
    request_timeout: int = 120
```

Add to `load_config()`:

```python
if "max_concurrency" in section:
    config.max_concurrency = int(section["max_concurrency"])
if "max_retries" in section:
    config.max_retries = int(section["max_retries"])
if "base_backoff_seconds" in section:
    config.base_backoff_seconds = float(section["base_backoff_seconds"])
if "request_timeout" in section:
    config.request_timeout = int(section["request_timeout"])
```

Corresponding pyproject.toml:

```toml
[tool.mutmut.llm]
max_concurrency = 5       # max parallel API calls
max_retries = 3            # app-level retries per target (after SDK retries)
base_backoff_seconds = 1.0 # initial backoff for app-level retries
request_timeout = 120      # seconds per API call
```

### Step 7: Progress display

Use `tqdm` if available, otherwise fall back to periodic `click.echo`.

```python
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
```

Progress bar format: `Generating mutations: 12/50 [failed:2 $0.0341]`

`tqdm` is an optional dependency (added to `[project.optional-dependencies]`). The pipeline works without it.

### Step 8: Graceful Ctrl+C handling

```python
import signal

async def _generate_mutations_async(...):
    cancel_event = asyncio.Event()

    def _signal_handler(sig, frame):
        cancel_event.set()

    old_handler = signal.signal(signal.SIGINT, _signal_handler)
    try:
        # ... task creation and await loop ...
    finally:
        signal.signal(signal.SIGINT, old_handler)
```

When `cancel_event` is set:
1. Tasks waiting for the semaphore return immediately with empty results.
2. Tasks already in-flight complete normally (their results are cached).
3. The await loop breaks after completing in-flight tasks.
4. Summary is printed with partial results.

## Code Surface Impact

| File | Change | Est. diff |
|------|--------|-----------|
| `mutmut-llm/src/mutmut_llm/pipeline.py` | Add async orchestrator, async LLM call, error classifier, progress display, signal handling. Keep sync `_call_llm_and_validate` for tests. | +180 lines |
| `mutmut-llm/src/mutmut_llm/config.py` | Add 4 new config fields + loading | +20 lines |
| `mutmut-llm/src/mutmut_llm/plugin.py` | No changes needed (calls `run_generation()` which stays sync) | 0 lines |
| `mutmut-llm/src/mutmut_llm/cache.py` | No changes | 0 lines |
| `mutmut-llm/src/mutmut_llm/storage.py` | No changes | 0 lines |
| `mutmut-llm/src/mutmut_llm/pricing.py` | No changes | 0 lines |
| `mutmut-llm/tests/test_pipeline.py` | New async test class, update existing tests | +150 lines |
| `mutmut-llm/pyproject.toml` | Add `tqdm` to optional-dependencies | +2 lines |

**Total: ~350 lines added/changed.**

### Dependencies

- `anthropic` already includes async support. No extra install needed.
- `anthropic[aiohttp]` is optional for better async performance. Not required.
- `tqdm` added as optional dependency: `pip install mutmut-llm[progress]`.
- No other new dependencies. `asyncio`, `signal`, `random`, `enum` are all stdlib.

## Testing Plan

### Unit tests (mocked)

1. **Error classifier**: Feed each SDK exception type into `classify_error()`, assert correct `ErrorAction`. Test quota-keyword detection in `RateLimitError` messages.

2. **Semaphore concurrency limit**: Create 10 mock tasks with a semaphore of 3. Track max concurrent execution count. Assert never exceeds 3.

   ```python
   async def test_semaphore_limits_concurrency():
       concurrent = 0
       max_concurrent = 0
       sem = asyncio.Semaphore(3)

       async def fake_call(*args, **kwargs):
           nonlocal concurrent, max_concurrent
           concurrent += 1
           max_concurrent = max(max_concurrent, concurrent)
           await asyncio.sleep(0.01)
           concurrent -= 1
           return mock_response

       # ... dispatch 10 tasks with semaphore ...
       assert max_concurrent <= 3
   ```

3. **Backoff on 429**: Mock `client.messages.create` to raise `RateLimitError` twice then succeed. Assert `asyncio.sleep` was called with increasing delays (1.0, 2.0 + jitter).

4. **Early stop on quota error**: Mock one task to raise `AuthenticationError`. Assert `cancel_event` is set. Assert remaining tasks return empty results.

5. **Graceful shutdown**: Simulate `cancel_event.set()` during task execution. Assert in-flight tasks complete and are cached. Assert pending tasks are skipped.

6. **Progress tracking**: Assert final output includes correct counts for completed, failed, and cost.

7. **Cache skip**: Pre-populate cache for some targets. Assert those targets are not dispatched as tasks.

### Existing tests (backward compat)

All existing `TestRunGeneration` and `TestCallLlmAndValidate` tests must pass. The sync `_call_llm_and_validate` is preserved. `run_generation` behavior is identical for dry-run and validation-error paths.

`@patch("anthropic.Anthropic")` tests in `TestRunGeneration` need updating to also patch `anthropic.AsyncAnthropic` since `run_generation` now uses the async path. Approach: patch `AsyncAnthropic` to return a mock whose `messages.create` is an async mock (`AsyncMock`).

### Integration test (optional, env-gated)

```python
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="Requires ANTHROPIC_API_KEY"
)
async def test_real_parallel_generation(tmp_path):
    # Generate for 5 functions, verify all cached, cost > 0
```

## Interaction with Other Plans

### Atomic writes ([atomic-cache-writes.md](atomic-cache-writes.md))

Parallel generation is the primary motivation for atomic writes. In this plan, cache writes happen sequentially in the main coroutine's await loop (after each task completes), so concurrent write corruption is not possible. However, if a user runs two `mutmut generate` processes simultaneously, both could write to the same cache key. **Atomic writes should be implemented before or alongside this plan.**

### Prompt caching ([prompt-caching-strategy.md](prompt-caching-strategy.md))

Prompt caching and async parallelism interact in an important way: prompt cache hits require consecutive calls with identical prefixes, which means functions from the same file should be processed together. The implementation sorts targets by `file_path` and dispatches them in order, but with a concurrency limit of 5, up to 5 different files could be in-flight simultaneously.

Mitigation: The semaphore + sorted dispatch means the first N tasks are all from the first files. As each completes, the next task (same or next file) is released. With typical workloads (2-5 functions per file, 5 concurrency), most consecutive calls within a file will hit the prompt cache. For maximum cache efficiency, users can set `max_concurrency = 1` (sequential, like today).

### Other plans

- **Composite cache keys** ([composite-cache-keys.md](composite-cache-keys.md)): No interaction. Cache key format is orthogonal to parallelism.
- **Model validation on read** ([model-validation-on-read.md](model-validation-on-read.md)): No interaction.
- **Cache garbage collection** ([cache-garbage-collection.md](cache-garbage-collection.md)): No interaction.
- **Adaptive budget** ([adaptive-budget.md](adaptive-budget.md)): Compatible. Budget calculation happens before async dispatch.

## Usability / Feature Impact

### Expected speedup

With `max_concurrency = 5` (default), speedup is bounded by `min(N, 5)` where N is the number of uncached targets:

| Targets | Sequential (est.) | Parallel (est.) | Speedup |
|---------|-------------------|-----------------|---------|
| 5 | 25s | 7s | 3.5x |
| 20 | 100s | 25s | 4x |
| 50 | 250s | 55s | 4.5x |
| 100 | 500s | 105s | 4.8x |

Assumes 5s avg per API call. Real speedup depends on rate limits — at high concurrency, 429s reduce effective parallelism. The default of 5 is conservative; users on higher API tiers can increase it.

### New config options

| Option | Default | Description |
|--------|---------|-------------|
| `max_concurrency` | 5 | Max parallel API calls |
| `max_retries` | 3 | App-level retries per target |
| `base_backoff_seconds` | 1.0 | Initial backoff delay |
| `request_timeout` | 120 | Per-request timeout in seconds |

### CLI output changes

**Before (sequential):**
```
Found 20 functions in scope (deep mode).
  src/app.py::greet — generating...
  src/app.py::add — generating...
  ...
Done. 20 API calls, 45 mutations generated. ($0.0512)
```

**After (parallel):**
```
Found 20 functions in scope (deep mode).
  src/app.py::greet — cached
Generating mutations: 18/18 [failed:0 $0.0480]
Done. 18 API calls, 42 mutations generated. ($0.0480)
```

With tqdm absent, falls back to periodic status lines every 5 completions.

### Ctrl+C behavior

```
Generating mutations: 7/18 [failed:0 $0.0195]
^C
Interrupted. Waiting for 3 in-flight tasks to complete...
Done. 10 API calls, 23 mutations generated, 8 skipped. ($0.0280)
```

In-flight tasks complete and cache. Pending tasks are cancelled. No work is lost.

### Error messages

**Rate limiting (transient):**
```
  Warning: Retry 1/3 for greet after 1.3s: rate_limit_error (429)
```

**Quota exhaustion (fatal):**
```
*** FATAL: AuthenticationError: Your account has insufficient credits. ***
Cancelling remaining tasks. Completed work has been saved.
Done. 5 API calls, 12 mutations generated, 15 cancelled. ($0.0140)
```

**Bad request (permanent, per-target):**
```
  Warning: Skipping enormous_function: request_too_large (413)
```
