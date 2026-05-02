# Async Parallel Generation v2 — Implementation Plan

## Overview

Replace the sequential `for target in targets` loop with async parallel dispatch using `asyncio.Semaphore` to cap concurrency. This reduces wall-clock time for mutation generation by ~4x (5 concurrent requests, 5s avg per call).

---

## 1. Prompt Caching Analysis Under Async Parallelism

### How Anthropic prompt caching works

The Anthropic API caches system prompt blocks marked with `cache_control: {type: "ephemeral"}`. The cache key is derived from the content hash of those blocks. Consecutive API calls with identical system blocks hit the cache for 5 minutes (TTL).

In the sync pipeline, `sorted(targets, key=lambda t: t.file_path)` ensures functions from the same file are processed consecutively. Since they share the same `target.context` (file-level imports/classes), consecutive calls reuse the cached system prompt.

### Async parallelism impact

With `max_concurrency=5`, up to 5 requests can be in-flight simultaneously. If those 5 requests come from 5 different files, each creates its own cache entry on the first call (5 cache misses). However:

1. **Subsequent calls within the same file still hit.** After the first request from `a.py` completes, any remaining functions in `a.py` that are dispatched will hit the cache (assuming the 5-minute TTL hasn't expired).

2. **Sorted dispatch order mitigates the problem.** Targets are sorted by `file_path` before dispatch. The semaphore releases tasks in FIFO order. So tasks for `a.py` functions 1-5 are dispatched before `b.py` function 1.

3. **Real-world distribution is favorable.** Most files have 1-5 functions. With 5 concurrency and sorted dispatch, the worst case is the first batch of 5 calls hitting 5 different files (5 cache misses). All subsequent calls within those files hit.

### Worst-case cache efficiency loss

**Scenario**: 25 functions across 5 files (5 functions each), `max_concurrency=5`.

- **Sequential**: 5 cache misses (first function per file), 20 cache hits. Hit rate: 80%.
- **Async (worst case)**: First batch sends 1 function from each of 5 files → 5 misses. Remaining 4 functions per file hit → 20 hits. Hit rate: 80%.

The worst case is **identical to sequential** because functions are dispatched in sorted order.

**Pathological scenario**: 100 functions across 100 files (1 function each), `max_concurrency=5`.

- Both sequential and async have 0% hit rate (every function is from a different file).
- No loss from parallelism.

### Recommendation: Sorted dispatch + semaphore is sufficient

No special "drain one file before starting the next" strategy is needed. The sorted dispatch order combined with FIFO semaphore scheduling naturally groups same-file functions together. The overhead of implementing file-level batching would add complexity without measurable benefit.

**Action**: Keep the existing `sorted(targets, key=lambda t: t.file_path)` and dispatch all tasks upfront with semaphore control.

---

## 2. Error Classification and Retry/Backoff

### SDK internal retry behavior

The Anthropic SDK automatically retries on:
- 429 (RateLimitError) — 2 retries
- 529 (OverloadedError) — 2 retries
- 5xx (InternalServerError) — 2 retries

Backoff formula: `min(0.5 * 2^attempt, 60)` with jitter factor 0.75-1.0.

SDK respects `Retry-After` headers when present.

Our app-level retries sit **on top of** SDK retries. By the time an exception reaches our code, the SDK has already tried 3 times (initial + 2 retries).

### ErrorAction enum and classify_error

```python
import enum
import anthropic


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
    """Classify an exception into an action for the retry loop."""
    # Fatal: authentication failures always stop
    if isinstance(exc, anthropic.AuthenticationError):
        return ErrorAction.STOP

    # Permission denied: check for quota keywords, otherwise stop
    if isinstance(exc, anthropic.PermissionDeniedError):
        msg = str(exc).lower()
        if any(kw in msg for kw in _QUOTA_KEYWORDS):
            return ErrorAction.STOP
        return ErrorAction.STOP

    # Rate limit: check for quota exhaustion vs temporary limit
    if isinstance(exc, anthropic.RateLimitError):
        msg = str(exc).lower()
        if any(kw in msg for kw in _QUOTA_KEYWORDS):
            return ErrorAction.STOP
        return ErrorAction.RETRY

    # Overloaded: Anthropic is busy, retry
    if isinstance(exc, anthropic.OverloadedError):
        return ErrorAction.RETRY

    # Internal server error: transient, retry
    if isinstance(exc, anthropic.InternalServerError):
        return ErrorAction.RETRY

    # Timeout / connection errors: transient, retry
    if isinstance(exc, (anthropic.APITimeoutError, anthropic.APIConnectionError)):
        return ErrorAction.RETRY

    # Bad request: malformed prompt, skip this target
    if isinstance(exc, anthropic.BadRequestError):
        return ErrorAction.SKIP

    # Request too large: function too big, skip
    if isinstance(exc, anthropic.RequestTooLargeError):
        return ErrorAction.SKIP

    # Not found: invalid model name or endpoint, skip
    if isinstance(exc, anthropic.NotFoundError):
        return ErrorAction.SKIP

    # Unknown exception: skip to be safe
    return ErrorAction.SKIP
```

### App-level retry configuration

- **Max retries**: 3 (configurable via `max_retries`)
- **Backoff formula**: `base_backoff * 2^attempt + jitter`, capped at 30s
- **Jitter**: uniform random in `[0, 0.5]` seconds

```python
import random

def compute_backoff(attempt: int, base: float, cap: float = 30.0) -> float:
    """Compute backoff delay for retry attempt (0-indexed)."""
    delay = min(base * (2 ** attempt), cap)
    jitter = random.uniform(0, 0.5)
    return delay + jitter
```

**Validation**: 3 app-level retries is appropriate. Combined with SDK's 2 internal retries, each target gets up to 12 attempts total (3 app retries × (1 initial + 2 SDK retries) + 3 SDK attempts for the initial app call). This is aggressive enough to weather transient issues while avoiding infinite loops.

---

## 3. tqdm Progress Bar (Required Dependency)

### Rationale

Long generation jobs (2-8 minutes for 50+ functions) need visual progress feedback. `tqdm` is the standard Python progress bar library. Since `mutmut-llm` is a developer tool (not a library), adding `tqdm` as a required dependency is appropriate.

### pyproject.toml change

```toml
[project]
dependencies = [
    "mutmut>=3.5.0",
    "pluggy>=1.5.0",
    "anthropic>=0.40.0",
    "tomli>=1.1.0; python_version < '3.11'",
    "tqdm>=4.66.0",
]
```

### Progress bar format

```
Generating: 12/50 [▶ 3] failed:2 cost:$0.0341
```

- `12/50` — completed / total (uncached targets only)
- `▶ 3` — currently in-flight requests
- `failed:2` — targets that errored out (after retries exhausted)
- `cost:$0.0341` — cumulative USD cost

### Integration with async orchestrator

```python
from tqdm import tqdm

async def _generate_mutations_async(...) -> int:
    # ... filter to uncached work_items ...
    
    total = len(work_items)
    in_flight = 0
    failed = 0
    total_cost = 0.0
    
    pbar = tqdm(
        total=total,
        desc="Generating",
        bar_format="{desc}: {n}/{total} [▶ {postfix[in_flight]}] failed:{postfix[failed]} cost:${postfix[cost]:.4f}",
        postfix={"in_flight": 0, "failed": 0, "cost": 0.0},
    )
    
    try:
        # ... dispatch tasks ...
        for target, src_hash, task in tasks:
            in_flight += 1
            pbar.set_postfix(in_flight=in_flight, failed=failed, cost=total_cost)
            
            try:
                result = await task
                total_cost += result.cost_usd
            except Exception:
                failed += 1
            finally:
                in_flight -= 1
                pbar.update(1)
                pbar.set_postfix(in_flight=in_flight, failed=failed, cost=total_cost)
    finally:
        pbar.close()
```

### In-flight tracking

The in-flight counter is incremented before awaiting a task and decremented in the `finally` block. Since the orchestrator awaits tasks one-by-one (even though multiple are running concurrently via the semaphore), the counter reflects "tasks we've started awaiting but haven't finished yet."

More accurate approach: track in-flight at the semaphore level:

```python
class TrackedSemaphore:
    def __init__(self, value: int):
        self._sem = asyncio.Semaphore(value)
        self.in_flight = 0
    
    async def __aenter__(self):
        await self._sem.acquire()
        self.in_flight += 1
        return self
    
    async def __aexit__(self, *args):
        self.in_flight -= 1
        self._sem.release()
```

This counts requests actually holding the semaphore (truly in-flight).

---

## 4. Concurrency Architecture

### Pattern comparison

**Pattern A: `asyncio.gather(*tasks)`**
- All tasks created upfront
- Semaphore inside each task controls concurrency
- Simple: one `await gather(...)` call
- Budget enforcement: filter cached targets before creating tasks
- Early stop: set `cancel_event`, tasks check before semaphore acquire

**Pattern B: `asyncio.as_completed()` over running set**
- Tasks dispatched incrementally
- More control over when new tasks start
- Budget enforcement: stop dispatching after N completions
- More complex state management

### Recommendation: Pattern A with pre-filtered dispatch

**Justification:**

1. **Budget enforcement is simple.** Cached targets are filtered BEFORE dispatch. We only create tasks for uncached targets. The total budget limits how many uncached targets we process, which equals the number of tasks created.

2. **Early stop works cleanly.** A `cancel_event: asyncio.Event` is checked before acquiring the semaphore. When a fatal error occurs, set the event; all pending tasks return empty immediately.

3. **tqdm integration is straightforward.** `gather()` with `return_exceptions=True` followed by iteration, or create tasks and `await` them individually in the order they were created.

4. **Simplicity.** Fewer moving parts, easier to reason about, easier to test.

### Chosen pattern: individual task awaits with early-exit

Instead of `gather()`, create all tasks upfront but `await` them one by one in a loop. This allows:
- Immediate response to fatal errors (break the loop)
- Per-task progress updates
- Cache writes after each completion (sequential, no concurrent writes)

```python
# Create all tasks
tasks: list[tuple[ScopeTarget, str, asyncio.Task]] = []
for target, src_hash, max_mut in work_items:
    coro = _call_llm_async(client, config, target, max_mut, tracked_sem, cancel_event)
    tasks.append((target, src_hash, asyncio.create_task(coro)))

# Await in order (tasks run concurrently via semaphore)
for target, src_hash, task in tasks:
    if cancel_event.is_set():
        task.cancel()
        continue
    
    try:
        result = await task
    except asyncio.CancelledError:
        continue
    except Exception as exc:
        if classify_error(exc) == ErrorAction.STOP:
            cancel_event.set()
            # Cancel remaining tasks
            for _, _, t in tasks:
                t.cancel()
            break
        continue
    
    # Cache write (sequential, safe)
    write_cache_entry(...)
    pbar.update(1)
```

---

## 5. Graceful Ctrl+C / Cancellation

### Recommendation: Option B — SIGINT handler with cancel_event

**Justification:**

Option A (catch `KeyboardInterrupt` after `asyncio.run()`) is simpler but has a critical flaw: cache writes may be interrupted mid-write, leaving corrupt files. With atomicwrites (from the atomic writes plan), this is mitigated, but we don't want to rely on that.

Option B (SIGINT handler + cancel_event) gives clean shutdown:
1. SIGINT sets `cancel_event`
2. Tasks waiting for semaphore see the event and return immediately
3. Tasks already past the semaphore (in-flight API calls) complete
4. Cache writes for completed tasks execute normally
5. Event loop exits cleanly

### Implementation

```python
import signal
import asyncio
from contextlib import contextmanager


@contextmanager
def _sigint_handler(cancel_event: asyncio.Event):
    """Install a SIGINT handler that sets cancel_event."""
    def handler(signum, frame):
        cancel_event.set()
    
    old_handler = signal.signal(signal.SIGINT, handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, old_handler)


async def _generate_mutations_async(...) -> int:
    cancel_event = asyncio.Event()
    
    with _sigint_handler(cancel_event):
        # ... task creation and await loop ...
        pass
```

### What gets shielded

Cache writes are NOT shielded with `asyncio.shield()`. They execute in the main await loop, which continues until all in-flight tasks complete. The SIGINT handler only sets the event; it doesn't raise an exception. The await loop checks the event and skips remaining tasks, but completes writes for already-awaited results.

However, if the user hits Ctrl+C repeatedly, Python's default handler may eventually raise `KeyboardInterrupt`. To handle this:

```python
async def _generate_mutations_async(...) -> int:
    cancel_event = asyncio.Event()
    
    with _sigint_handler(cancel_event):
        try:
            # ... await loop ...
            for target, src_hash, task in tasks:
                if cancel_event.is_set():
                    task.cancel()
                    continue
                result = await task
                # ... cache write ...
        except KeyboardInterrupt:
            # Second Ctrl+C forces immediate exit
            click.echo("\nForced exit. Some results may not be cached.")
            for _, _, t in tasks:
                t.cancel()
```

### Signal handler lifecycle

- Installed: at the start of `_generate_mutations_async`
- Restored: in the `finally` block of the context manager
- `asyncio.run()` handles its own SIGINT cleanup; our handler is layered on top

---

## 6. Config Additions

### New LLMConfig fields

```python
@dataclass
class LLMConfig:
    api_key: str = field(default="", repr=False)
    model: str = "claude-sonnet-4-6"
    max_mutations_per_function: int = 5
    max_tokens: int = 4096
    temperature: float = 0.6
    enabled: bool = True
    cache_ttl: str = "5m"
    # New fields for async parallelism
    max_concurrency: int = 5
    max_retries: int = 3
    base_backoff_seconds: float = 1.0
    request_timeout_seconds: int = 120

    def __post_init__(self) -> None:
        if self.cache_ttl not in _VALID_CACHE_TTLS:
            raise ValueError(
                f"Invalid cache_ttl={self.cache_ttl!r}. Must be one of: {', '.join(sorted(_VALID_CACHE_TTLS))}"
            )
        if self.max_concurrency < 1:
            raise ValueError(f"max_concurrency must be >= 1, got {self.max_concurrency}")
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")
        if self.base_backoff_seconds <= 0:
            raise ValueError(f"base_backoff_seconds must be > 0, got {self.base_backoff_seconds}")
        if self.request_timeout_seconds < 10:
            raise ValueError(f"request_timeout_seconds must be >= 10, got {self.request_timeout_seconds}")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)
```

### load_config additions

```python
def load_config(
    *,
    pyproject_path: Path | None = None,
    env: dict[str, str] | None = None,
) -> LLMConfig:
    # ... existing loading ...
    
    if "max_concurrency" in section:
        config.max_concurrency = int(section["max_concurrency"])
    if "max_retries" in section:
        config.max_retries = int(section["max_retries"])
    if "base_backoff_seconds" in section:
        config.base_backoff_seconds = float(section["base_backoff_seconds"])
    if "request_timeout_seconds" in section:
        config.request_timeout_seconds = int(section["request_timeout_seconds"])
    
    # ... existing validation ...
    return config
```

### pyproject.toml example

```toml
[tool.mutmut.llm]
model = "claude-sonnet-4-6"
max_mutations_per_function = 5
max_concurrency = 5
max_retries = 3
base_backoff_seconds = 1.0
request_timeout_seconds = 120
```

---

## 7. Code Surface / File-by-File Changes

| File | Changes | Est. delta |
|------|---------|------------|
| `mutmut-llm/pyproject.toml` | Add `tqdm>=4.66.0` to dependencies | +1 line |
| `mutmut-llm/src/mutmut_llm/config.py` | Add 4 new fields to `LLMConfig`, update `__post_init__` validation, update `load_config` | +30 lines |
| `mutmut-llm/src/mutmut_llm/pipeline.py` | Add `ErrorAction` enum, `classify_error()`, `compute_backoff()`, `TrackedSemaphore`, `_sigint_handler()`, `_call_llm_async()`, `_call_llm_and_validate_async()`, `_generate_mutations_async()`. Modify `run_generation()` to call `asyncio.run()`. Keep sync `_call_llm_and_validate` for backward compat. | +200 lines |
| `mutmut-llm/tests/test_pipeline.py` | Add `TestErrorClassifier` class (10 test cases), `TestAsyncGeneration` class (semaphore, backoff, early stop, progress, cancellation tests). Update existing tests to work with async path. | +200 lines |
| `mutmut-llm/tests/conftest.py` | Add `make_async_mock_client()` helper for async tests | +15 lines |

**Total estimated change: ~450 lines**

---

## 8. Test Plan

### 8.1 `classify_error` tests

**File**: `test_pipeline.py`, class `TestErrorClassifier`

```python
import anthropic
from mutmut_llm.pipeline import ErrorAction, classify_error


class TestErrorClassifier:
    def test_authentication_error_stops(self):
        exc = anthropic.AuthenticationError(
            message="Invalid API key",
            response=MagicMock(status_code=401),
            body=None,
        )
        assert classify_error(exc) == ErrorAction.STOP

    def test_permission_denied_stops(self):
        exc = anthropic.PermissionDeniedError(
            message="Access denied",
            response=MagicMock(status_code=403),
            body=None,
        )
        assert classify_error(exc) == ErrorAction.STOP

    def test_rate_limit_retries(self):
        exc = anthropic.RateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(status_code=429),
            body=None,
        )
        assert classify_error(exc) == ErrorAction.RETRY

    def test_rate_limit_with_quota_keyword_stops(self):
        exc = anthropic.RateLimitError(
            message="spending limit exceeded for this billing period",
            response=MagicMock(status_code=429),
            body=None,
        )
        assert classify_error(exc) == ErrorAction.STOP

    def test_overloaded_retries(self):
        exc = anthropic.OverloadedError(
            message="API overloaded",
            response=MagicMock(status_code=529),
            body=None,
        )
        assert classify_error(exc) == ErrorAction.RETRY

    def test_internal_server_error_retries(self):
        exc = anthropic.InternalServerError(
            message="Internal error",
            response=MagicMock(status_code=500),
            body=None,
        )
        assert classify_error(exc) == ErrorAction.RETRY

    def test_bad_request_skips(self):
        exc = anthropic.BadRequestError(
            message="Invalid request",
            response=MagicMock(status_code=400),
            body=None,
        )
        assert classify_error(exc) == ErrorAction.SKIP

    def test_request_too_large_skips(self):
        exc = anthropic.RequestTooLargeError(
            message="Request too large",
            response=MagicMock(status_code=413),
            body=None,
        )
        assert classify_error(exc) == ErrorAction.SKIP

    def test_timeout_retries(self):
        exc = anthropic.APITimeoutError(request=MagicMock())
        assert classify_error(exc) == ErrorAction.RETRY

    def test_connection_error_retries(self):
        exc = anthropic.APIConnectionError(request=MagicMock())
        assert classify_error(exc) == ErrorAction.RETRY

    def test_unknown_exception_skips(self):
        exc = ValueError("something unexpected")
        assert classify_error(exc) == ErrorAction.SKIP
```

### 8.2 Semaphore concurrency limit test

**Goal**: Verify at most `max_concurrency` requests are in-flight simultaneously.

```python
import asyncio
from unittest.mock import AsyncMock, patch

class TestAsyncConcurrency:
    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_requests(self, tmp_path):
        """Max concurrent API calls never exceeds max_concurrency."""
        concurrent = 0
        max_observed = 0
        call_count = 0

        async def mock_create(*args, **kwargs):
            nonlocal concurrent, max_observed, call_count
            concurrent += 1
            max_observed = max(max_observed, concurrent)
            call_count += 1
            await asyncio.sleep(0.05)  # Simulate API latency
            concurrent -= 1
            return make_async_mock_response([{"mutated_code": "def f(): pass", "description": ""}])

        mock_client = AsyncMock()
        mock_client.messages.create = mock_create

        # Create 10 targets
        targets = [
            ScopeTarget(file_path=f"f{i}.py", function_name=f"f{i}", source=f"def f{i}(): pass\n")
            for i in range(10)
        ]
        budget_per_target = {f"f{i}.py::f{i}": 3 for i in range(10)}

        config = LLMConfig(api_key="test", max_concurrency=3, max_retries=0)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            from mutmut_llm.pipeline import _generate_mutations_async
            await _generate_mutations_async(config, targets, budget_per_target, 10, tmp_path)

        assert max_observed <= 3
        assert call_count == 10
```

### 8.3 Backoff timing test

**Goal**: Verify exponential backoff with increasing delays.

```python
class TestBackoffTiming:
    @pytest.mark.asyncio
    async def test_exponential_backoff_on_retry(self, tmp_path):
        """Retry delays follow exponential backoff formula."""
        sleep_calls = []

        async def mock_sleep(delay):
            sleep_calls.append(delay)

        call_count = 0
        async def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 4:  # Fail first 3 attempts
                raise anthropic.RateLimitError(
                    message="rate limited",
                    response=MagicMock(status_code=429),
                    body=None,
                )
            return make_async_mock_response([{"mutated_code": "def f(): pass", "description": ""}])

        mock_client = AsyncMock()
        mock_client.messages.create = mock_create

        target = ScopeTarget(file_path="f.py", function_name="f", source="def f(): pass\n")
        config = LLMConfig(api_key="test", max_retries=3, base_backoff_seconds=1.0)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            with patch("asyncio.sleep", mock_sleep):
                from mutmut_llm.pipeline import _call_llm_async
                semaphore = asyncio.Semaphore(5)
                cancel_event = asyncio.Event()
                await _call_llm_async(mock_client, config, target, 3, semaphore, cancel_event)

        # Expected: base * 2^0, base * 2^1, base * 2^2 (plus jitter 0-0.5)
        assert len(sleep_calls) == 3
        assert 1.0 <= sleep_calls[0] <= 1.5  # 1.0 + jitter
        assert 2.0 <= sleep_calls[1] <= 2.5  # 2.0 + jitter
        assert 4.0 <= sleep_calls[2] <= 4.5  # 4.0 + jitter
```

### 8.4 Early stop on fatal error

**Goal**: Fatal error cancels remaining tasks, partial results cached.

```python
class TestEarlyStop:
    @pytest.mark.asyncio
    async def test_fatal_error_cancels_remaining(self, tmp_path):
        """AuthenticationError stops all work immediately."""
        call_count = 0

        async def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise anthropic.AuthenticationError(
                    message="Invalid key",
                    response=MagicMock(status_code=401),
                    body=None,
                )
            await asyncio.sleep(0.01)
            return make_async_mock_response([{"mutated_code": "def f(): pass", "description": ""}])

        mock_client = AsyncMock()
        mock_client.messages.create = mock_create

        targets = [
            ScopeTarget(file_path=f"f{i}.py", function_name=f"f{i}", source=f"def f{i}(): pass\n")
            for i in range(5)
        ]
        budget = {f"f{i}.py::f{i}": 3 for i in range(5)}

        config = LLMConfig(api_key="test", max_concurrency=1, max_retries=0)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            from mutmut_llm.pipeline import _generate_mutations_async
            result = await _generate_mutations_async(config, targets, budget, 10, tmp_path)

        # First call succeeds, second fails fatally, remaining cancelled
        assert result == 1  # Only 1 successful API call
        # Verify first target was cached
        from mutmut_llm.cache import list_cache_entries
        entries = list_cache_entries(base_dir=tmp_path)
        assert len(entries) == 1
```

### 8.5 tqdm integration test

**Goal**: Verify `update()` call count and `set_postfix` args.

```python
class TestProgressBar:
    @pytest.mark.asyncio
    async def test_tqdm_update_called_per_task(self, tmp_path):
        """Progress bar updates once per completed task."""
        async def mock_create(*args, **kwargs):
            await asyncio.sleep(0.01)
            return make_async_mock_response([{"mutated_code": "def f(): pass", "description": ""}])

        mock_client = AsyncMock()
        mock_client.messages.create = mock_create

        targets = [
            ScopeTarget(file_path=f"f{i}.py", function_name=f"f{i}", source=f"def f{i}(): pass\n")
            for i in range(3)
        ]
        budget = {f"f{i}.py::f{i}": 3 for i in range(3)}

        config = LLMConfig(api_key="test", max_concurrency=5)

        mock_tqdm = MagicMock()
        mock_pbar = MagicMock()
        mock_tqdm.return_value.__enter__ = MagicMock(return_value=mock_pbar)
        mock_tqdm.return_value.__exit__ = MagicMock(return_value=False)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            with patch("tqdm.tqdm", mock_tqdm):
                from mutmut_llm.pipeline import _generate_mutations_async
                await _generate_mutations_async(config, targets, budget, 10, tmp_path)

        assert mock_pbar.update.call_count == 3
        # Verify set_postfix was called with cost tracking
        assert mock_pbar.set_postfix.call_count >= 3
```

### 8.6 Ctrl+C handling test

**Goal**: In-flight writes complete, pending tasks skip.

```python
class TestCancellation:
    @pytest.mark.asyncio
    async def test_cancel_event_skips_pending(self, tmp_path):
        """Setting cancel_event prevents new tasks from starting."""
        started = []
        
        async def mock_create(*args, **kwargs):
            started.append(1)
            await asyncio.sleep(0.1)
            return make_async_mock_response([{"mutated_code": "def f(): pass", "description": ""}])

        mock_client = AsyncMock()
        mock_client.messages.create = mock_create

        targets = [
            ScopeTarget(file_path=f"f{i}.py", function_name=f"f{i}", source=f"def f{i}(): pass\n")
            for i in range(5)
        ]
        budget = {f"f{i}.py::f{i}": 3 for i in range(5)}

        config = LLMConfig(api_key="test", max_concurrency=1)
        cancel_event = asyncio.Event()

        # Set cancel after first task starts
        async def set_cancel_soon():
            await asyncio.sleep(0.05)
            cancel_event.set()

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            from mutmut_llm.pipeline import _generate_mutations_async
            asyncio.create_task(set_cancel_soon())
            # Need to inject cancel_event into the function for this test
            # This may require refactoring to accept cancel_event as parameter
            result = await _generate_mutations_async(config, targets, budget, 10, tmp_path)

        # Only 1-2 tasks should have started before cancellation
        assert len(started) <= 2
```

### 8.7 Existing test updates

**Tests that patch `anthropic.Anthropic`** need updates:

```python
# Before
@patch("anthropic.Anthropic")
def test_foo(self, MockAnthropic, ...):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_response(...)
    MockAnthropic.return_value = mock_client

# After: also patch AsyncAnthropic
@patch("anthropic.AsyncAnthropic")
def test_foo(self, MockAsyncAnthropic, ...):
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=_make_mock_response(...))
    MockAsyncAnthropic.return_value = mock_client
```

**Helper in conftest.py:**

```python
from unittest.mock import AsyncMock

def make_async_mock_response(
    mutations: list[dict],
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 200,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> MagicMock:
    """Create a mock Anthropic API response for async client."""
    # Same as make_mock_response - the response object is synchronous
    return make_mock_response(
        mutations, stop_reason, input_tokens, output_tokens,
        cache_creation_input_tokens, cache_read_input_tokens,
    )


def make_async_mock_client(responses: list | None = None) -> AsyncMock:
    """Create a mock AsyncAnthropic client."""
    client = AsyncMock()
    if responses:
        client.messages.create = AsyncMock(side_effect=responses)
    else:
        client.messages.create = AsyncMock(
            return_value=make_async_mock_response([])
        )
    return client
```

---

## 9. Interaction with Existing Features

### Prompt caching

Analyzed in §1. Sorted dispatch + semaphore preserves cache efficiency. No code changes needed beyond what's already in `build_system_with_context()`.

### Atomic cache writes

Cache writes in the async orchestrator's await loop are sequential (one write completes before the next task is awaited). Within a single process, no concurrent writes occur.

For multi-process scenarios (two `mutmut generate` commands running simultaneously), the existing atomic write mechanism (write to temp file, rename) handles conflicts safely.

### Adaptive budget

The `resolve_scope_deep()` function computes `budget_per_target` before dispatch. The async orchestrator uses this dict unchanged. No interaction issues.

### Source tracking / GenerationResult

`GenerationResult` dataclass is unchanged. The async `_call_llm_and_validate_async` returns the same type as the sync version.

---

## 10. Migration / Backward Compatibility

### `run_generation()` stays sync

The public API `run_generation()` remains a synchronous function. Internally it calls `asyncio.run(_generate_mutations_async(...))`. Callers (CLI, tests) don't need to change.

```python
def run_generation(
    config: LLMConfig,
    paths: list[str],
    budget: int,
    dry_run: bool = False,
    base_dir: Path | None = None,
) -> int:
    # ... existing validation ...
    if dry_run:
        # ... existing dry run logic ...
        return 0
    
    return asyncio.run(
        _generate_mutations_async(
            config, scope.targets, scope.budget_per_target, budget, base_dir
        )
    )
```

### `_call_llm_and_validate` preserved

The sync function `_call_llm_and_validate(client, config, target, max_mutations)` is kept for:
1. Backward compatibility with any external callers
2. Existing sync unit tests that are easier to write without async mocking
3. Potential future use in contexts where async isn't available

The async version `_call_llm_and_validate_async` is nearly identical but uses `await client.messages.create(...)`.

### Test compatibility

Existing tests in `TestCallLlmAndValidate` test the sync function directly and don't need changes.

`TestRunGeneration` tests exercise the full pipeline via `run_generation()`. These need their mock patches updated from `anthropic.Anthropic` to `anthropic.AsyncAnthropic`.

---

## Full Code Sketches

### ErrorAction and classify_error (pipeline.py)

```python
import enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import anthropic


class ErrorAction(enum.Enum):
    RETRY = "retry"
    SKIP = "skip"
    STOP = "stop"


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

    if isinstance(exc, anthropic.OverloadedError):
        return ErrorAction.RETRY

    if isinstance(exc, anthropic.InternalServerError):
        return ErrorAction.RETRY

    if isinstance(exc, (anthropic.APITimeoutError, anthropic.APIConnectionError)):
        return ErrorAction.RETRY

    if isinstance(exc, (anthropic.BadRequestError, anthropic.RequestTooLargeError, anthropic.NotFoundError)):
        return ErrorAction.SKIP

    return ErrorAction.SKIP
```

### TrackedSemaphore (pipeline.py)

```python
import asyncio


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
```

### _call_llm_and_validate_async (pipeline.py)

```python
async def _call_llm_and_validate_async(
    client,  # anthropic.AsyncAnthropic
    config: LLMConfig,
    target: ScopeTarget,
    max_mutations: int,
) -> GenerationResult:
    """Async version of _call_llm_and_validate."""
    system_blocks = build_system_with_context(context=target.context, ttl=config.cache_ttl)
    user_prompt = build_user_prompt(function_source=target.source, max_mutations=max_mutations)

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
        warnings.warn(f"Response truncated for {target.function_name}", stacklevel=2)

    response_text = "".join(block.text for block in response.content if hasattr(block, "text"))
    mutations = parse_llm_response(response_text)

    valid = []
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
```

### _call_llm_async (per-target wrapper with retry) (pipeline.py)

```python
import random


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
    for attempt in range(config.max_retries + 1):
        if cancel_event.is_set():
            return GenerationResult(mutations=[])

        async with semaphore:
            if cancel_event.is_set():
                return GenerationResult(mutations=[])

            try:
                return await _call_llm_and_validate_async(client, config, target, max_mutations)

            except asyncio.TimeoutError:
                if attempt < config.max_retries:
                    delay = _compute_backoff(attempt, config.base_backoff_seconds)
                    warnings.warn(
                        f"Timeout for {target.function_name}, retry {attempt + 1}/{config.max_retries} in {delay:.1f}s",
                        stacklevel=2,
                    )
                    await asyncio.sleep(delay)
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
                    delay = _compute_backoff(attempt, config.base_backoff_seconds)
                    warnings.warn(
                        f"Retry {attempt + 1}/{config.max_retries} for {target.function_name} in {delay:.1f}s: {exc}",
                        stacklevel=2,
                    )
                    await asyncio.sleep(delay)
                else:
                    warnings.warn(f"All retries exhausted for {target.function_name}: {exc}", stacklevel=2)
                    return GenerationResult(mutations=[])

    return GenerationResult(mutations=[])
```

### _sigint_handler context manager (pipeline.py)

```python
import signal
from contextlib import contextmanager


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
```

### _generate_mutations_async (orchestrator) (pipeline.py)

```python
from tqdm import tqdm


async def _generate_mutations_async(
    config: LLMConfig,
    targets: list[ScopeTarget],
    budget_per_target: dict[str, int],
    total_budget: int,
    base_dir: Path | None,
) -> int:
    """Async orchestrator for parallel mutation generation."""
    effective_base = base_dir or Path(".")
    clean_stale_temps(effective_base / CACHE_DIR)

    import anthropic
    client = anthropic.AsyncAnthropic(api_key=config.api_key)

    cache_kwargs = {"base_dir": base_dir} if base_dir else {}
    cancel_event = asyncio.Event()
    semaphore = TrackedSemaphore(config.max_concurrency)

    # Filter to uncached targets, respecting budget
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
            click.echo(f"  {target.file_path}::{target.function_name} — cached ({len(cached.mutations)} mutations)")
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
    tasks: list[tuple[ScopeTarget, str, asyncio.Task]] = []
    for target, src_hash, max_mut in work_items:
        coro = _call_llm_async(client, config, target, max_mut, semaphore, cancel_event)
        tasks.append((target, src_hash, asyncio.create_task(coro)))

    # Tracking
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
        bar_format="{desc}: {n}/{total} [▶{postfix[in_flight]}] failed:{postfix[failed]} cost:${postfix[cost]:.4f}",
        postfix={"in_flight": 0, "failed": 0, "cost": 0.0},
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

                # Write to cache
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

    # Summary
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
```

### Updated run_generation (pipeline.py)

```python
def run_generation(
    config: LLMConfig,
    paths: list[str],
    budget: int,
    dry_run: bool = False,
    base_dir: Path | None = None,
) -> int:
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

    return asyncio.run(
        _generate_mutations_async(
            config, scope.targets, scope.budget_per_target, budget, base_dir
        )
    )
```

### Updated LLMConfig (config.py)

```python
_VALID_CACHE_TTLS = {"5m", "1h"}


@dataclass
class LLMConfig:
    api_key: str = field(default="", repr=False)
    model: str = "claude-sonnet-4-6"
    max_mutations_per_function: int = 5
    max_tokens: int = 4096
    temperature: float = 0.6
    enabled: bool = True
    cache_ttl: str = "5m"
    # Async parallelism settings
    max_concurrency: int = 5
    max_retries: int = 3
    base_backoff_seconds: float = 1.0
    request_timeout_seconds: int = 120

    def __post_init__(self) -> None:
        if self.cache_ttl not in _VALID_CACHE_TTLS:
            raise ValueError(
                f"Invalid cache_ttl={self.cache_ttl!r}. Must be one of: {', '.join(sorted(_VALID_CACHE_TTLS))}"
            )
        if self.max_concurrency < 1:
            raise ValueError(f"max_concurrency must be >= 1, got {self.max_concurrency}")
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")
        if self.base_backoff_seconds <= 0:
            raise ValueError(f"base_backoff_seconds must be > 0, got {self.base_backoff_seconds}")
        if self.request_timeout_seconds < 10:
            raise ValueError(f"request_timeout_seconds must be >= 10, got {self.request_timeout_seconds}")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)
```

---

## Summary

This plan provides a complete, implementation-ready design for async parallel LLM generation:

1. **Cache efficiency is preserved** — sorted dispatch + semaphore matches sequential hit rates
2. **Error handling is comprehensive** — every SDK exception mapped to RETRY/SKIP/STOP
3. **tqdm is required** — provides essential progress feedback for 2-8 minute jobs
4. **Pattern A (gather-style with individual awaits)** — simple, budget-aware, early-exit capable
5. **SIGINT handler + cancel_event** — clean shutdown, no interrupted writes
6. **Four new config fields** — max_concurrency, max_retries, base_backoff_seconds, request_timeout_seconds
7. **~450 lines of changes** — mostly additive, existing sync code preserved
8. **Comprehensive test plan** — 7 test categories with concrete implementation sketches
9. **Full backward compatibility** — `run_generation()` stays sync, existing tests work with patch updates
