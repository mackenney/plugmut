# Async Parallel Generation — Step-by-Step Implementation

This plan implements the async parallel LLM mutation generation pipeline as designed in `async-parallel-generation-v2.md`, with dynamic concurrency as specified in the task.

---

## Execution Graph

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           WAVE 1 (parallel)                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │  Step 1      │  │  Step 2      │  │  Step 3      │  │  Step 4      │ │
│  │  Config      │  │  Error       │  │  Tracked     │  │  SIGINT      │ │
│  │  Changes     │  │  Classifier  │  │  Semaphore   │  │  Handler     │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘ │
└─────────┼─────────────────┼─────────────────┼─────────────────┼─────────┘
          │                 │                 │                 │
          ▼                 │                 │                 │
┌─────────────────────────────────────────────────────────────────────────┐
│                           WAVE 2 (parallel)                             │
│  ┌──────────────────────────────┐  ┌──────────────────────────────────┐ │
│  │  Step 5                      │  │  Step 6                          │ │
│  │  _compute_concurrency        │  │  _call_llm_and_validate_async    │ │
│  │  (depends on Step 1)         │  │  + conftest helpers              │ │
│  └──────────────┬───────────────┘  │  (depends on Step 1)             │ │
│                 │                  └──────────────┬───────────────────┘ │
└─────────────────┼────────────────────────────────┼──────────────────────┘
                  │                                │
                  │                                ▼
                  │         ┌─────────────────────────────────────────────┐
                  │         │  Step 7: _call_llm_async                    │
                  │         │  (depends on Steps 2, 3, 6)                 │
                  │         └─────────────────────┬───────────────────────┘
                  │                               │
                  ▼                               ▼
          ┌─────────────────────────────────────────────────────────────┐
          │  Step 8: _generate_mutations_async                          │
          │  (depends on Steps 3, 4, 5, 7)                              │
          └─────────────────────────────────┬───────────────────────────┘
                                            │
                                            ▼
          ┌─────────────────────────────────────────────────────────────┐
          │  Step 9: Wire up run_generation + update tests              │
          │  (depends on Step 8)                                        │
          └─────────────────────────────────────────────────────────────┘
```

---

## Step 1: Config Changes

**Branch**: `feat/async-config`
**Depends on**: none
**Can parallelize with**: Steps 2, 3, 4
**Files changed**:
- `mutmut-llm/src/mutmut_llm/config.py`
- `mutmut-llm/pyproject.toml`
- `mutmut-llm/tests/test_config.py` (new file)

### What to implement

1. **Add new fields to `LLMConfig` dataclass** in `config.py`:
   ```python
   min_concurrency: int = 5
   max_concurrency: int = 20
   max_retries: int = 3
   base_backoff_seconds: float = 1.0
   request_timeout_seconds: int = 120
   ```

2. **Extend `__post_init__` validation**:
   ```python
   if self.min_concurrency < 1:
       raise ValueError(f"min_concurrency must be >= 1, got {self.min_concurrency}")
   if self.max_concurrency < self.min_concurrency:
       raise ValueError(f"max_concurrency must be >= min_concurrency, got max={self.max_concurrency} < min={self.min_concurrency}")
   if self.max_retries < 0:
       raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")
   if self.base_backoff_seconds <= 0:
       raise ValueError(f"base_backoff_seconds must be > 0, got {self.base_backoff_seconds}")
   if self.request_timeout_seconds < 10:
       raise ValueError(f"request_timeout_seconds must be >= 10, got {self.request_timeout_seconds}")
   ```

3. **Update `load_config()` to read new fields from `[tool.mutmut.llm]`**:
   - `min_concurrency` → `config.min_concurrency = int(section["min_concurrency"])`
   - `max_concurrency` → `config.max_concurrency = int(section["max_concurrency"])`
   - `max_retries` → `config.max_retries = int(section["max_retries"])`
   - `base_backoff_seconds` → `config.base_backoff_seconds = float(section["base_backoff_seconds"])`
   - `request_timeout_seconds` → `config.request_timeout_seconds = int(section["request_timeout_seconds"])`

4. **Add `tqdm` dependency** to `pyproject.toml`:
   ```toml
   dependencies = [
       "mutmut>=3.5.0",
       "pluggy>=1.5.0",
       "anthropic>=0.40.0",
       "tomli>=1.1.0; python_version < '3.11'",
       "tqdm>=4.66.0",
   ]
   ```

5. **Create `test_config.py`** with validation tests:
   - Test min_concurrency < 1 raises ValueError
   - Test max_concurrency < min_concurrency raises ValueError
   - Test max_retries < 0 raises ValueError
   - Test base_backoff_seconds <= 0 raises ValueError
   - Test request_timeout_seconds < 10 raises ValueError
   - Test valid config with all new fields works
   - Test load_config reads new fields from pyproject.toml

### Acceptance criteria
- [ ] AC1: `LLMConfig(min_concurrency=0)` raises `ValueError` with message containing "min_concurrency must be >= 1"
  - `uv run --package mutmut-llm python -c "from mutmut_llm.config import LLMConfig; LLMConfig(min_concurrency=0)" 2>&1 | grep -q "min_concurrency must be >= 1"`
- [ ] AC2: `LLMConfig(min_concurrency=10, max_concurrency=5)` raises `ValueError` with message containing "max_concurrency must be >= min_concurrency"
  - `uv run --package mutmut-llm python -c "from mutmut_llm.config import LLMConfig; LLMConfig(min_concurrency=10, max_concurrency=5)" 2>&1 | grep -q "max_concurrency must be >= min_concurrency"`
- [ ] AC3: `LLMConfig(max_retries=-1)` raises `ValueError`
  - `uv run --package mutmut-llm python -c "from mutmut_llm.config import LLMConfig; LLMConfig(max_retries=-1)" 2>&1 | grep -q "max_retries must be >= 0"`
- [ ] AC4: `LLMConfig(base_backoff_seconds=0)` raises `ValueError`
  - `uv run --package mutmut-llm python -c "from mutmut_llm.config import LLMConfig; LLMConfig(base_backoff_seconds=0)" 2>&1 | grep -q "base_backoff_seconds must be > 0"`
- [ ] AC5: `LLMConfig(request_timeout_seconds=5)` raises `ValueError`
  - `uv run --package mutmut-llm python -c "from mutmut_llm.config import LLMConfig; LLMConfig(request_timeout_seconds=5)" 2>&1 | grep -q "request_timeout_seconds must be >= 10"`
- [ ] AC6: Default config has correct new field values (min_concurrency=5, max_concurrency=20, max_retries=3, base_backoff_seconds=1.0, request_timeout_seconds=120)
  - `uv run --package mutmut-llm python -c "from mutmut_llm.config import LLMConfig; c=LLMConfig(); assert c.min_concurrency==5 and c.max_concurrency==20 and c.max_retries==3 and c.base_backoff_seconds==1.0 and c.request_timeout_seconds==120; print('OK')"`
- [ ] AC7: `tqdm` is importable after install
  - `uv run --package mutmut-llm python -c "import tqdm; print('OK')"`
- [ ] AC8: Config tests pass
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_config.py -v`
- [ ] AC9: Full test suite passes
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/ -q --tb=short`

### Reviewer checklist
- Verify all 5 new fields have correct types and defaults in dataclass definition
- Verify __post_init__ validation order is logical (min before max checks)
- Verify load_config uses correct type conversions (int vs float)
- Verify pyproject.toml dependency version constraint is reasonable (>=4.66.0)
- Verify tests cover both valid and invalid edge cases for each field
- Verify existing tests still pass (no regressions from config changes)

---

## Step 2: Error Classification

**Branch**: `feat/async-error-classifier`
**Depends on**: none
**Can parallelize with**: Steps 1, 3, 4
**Files changed**:
- `mutmut-llm/src/mutmut_llm/pipeline.py`
- `mutmut-llm/tests/test_pipeline.py`

### What to implement

1. **Add `ErrorAction` enum** at module level in `pipeline.py`:
   ```python
   import enum

   class ErrorAction(enum.Enum):
       RETRY = "retry"   # Transient error, retry with backoff
       SKIP = "skip"     # Permanent error for this target, move on
       STOP = "stop"     # Fatal error, cancel all remaining work
   ```

2. **Add `_QUOTA_KEYWORDS` constant**:
   ```python
   _QUOTA_KEYWORDS = frozenset({
       "credit",
       "billing",
       "spending limit",
       "payment",
       "insufficient funds",
       "quota exceeded",
   })
   ```

3. **Implement `classify_error()` function**:
   ```python
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

4. **Add `TestErrorClassifier` test class** in `test_pipeline.py`:
   - Test AuthenticationError → STOP
   - Test PermissionDeniedError → STOP
   - Test RateLimitError (no quota keyword) → RETRY
   - Test RateLimitError with "spending limit" → STOP
   - Test RateLimitError with "credit" → STOP
   - Test OverloadedError → RETRY
   - Test InternalServerError → RETRY
   - Test APITimeoutError → RETRY
   - Test APIConnectionError → RETRY
   - Test BadRequestError → SKIP
   - Test RequestTooLargeError → SKIP
   - Test NotFoundError → SKIP
   - Test unknown Exception → SKIP

   Each test should construct the appropriate Anthropic exception. Note: Anthropic exceptions require specific constructor args. Use `MagicMock` for `response` parameter:
   ```python
   from unittest.mock import MagicMock
   exc = anthropic.AuthenticationError(
       message="Invalid API key",
       response=MagicMock(status_code=401),
       body=None,
   )
   ```

### Acceptance criteria
- [ ] AC1: `ErrorAction` enum has exactly three members: RETRY, SKIP, STOP
  - `uv run --package mutmut-llm python -c "from mutmut_llm.pipeline import ErrorAction; assert set(e.value for e in ErrorAction) == {'retry', 'skip', 'stop'}; print('OK')"`
- [ ] AC2: `classify_error(anthropic.AuthenticationError(...))` returns `ErrorAction.STOP`
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestErrorClassifier::test_authentication_error_stops -v`
- [ ] AC3: `classify_error(anthropic.RateLimitError("rate limited", ...))` returns `ErrorAction.RETRY`
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestErrorClassifier::test_rate_limit_retries -v`
- [ ] AC4: `classify_error(anthropic.RateLimitError("spending limit exceeded", ...))` returns `ErrorAction.STOP`
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestErrorClassifier::test_rate_limit_with_quota_keyword_stops -v`
- [ ] AC5: All error classification tests pass
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestErrorClassifier -v`
- [ ] AC6: Full test suite passes
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/ -q --tb=short`

### Reviewer checklist
- Verify `_QUOTA_KEYWORDS` is a frozenset (immutable)
- Verify all Anthropic exception types mentioned in v2 plan are handled
- Verify case-insensitive keyword matching (`.lower()` on message)
- Verify tests create valid exception instances (correct constructor args)
- Verify each exception type has at least one test case
- Verify enum values are lowercase strings matching the action names

---

## Step 3: TrackedSemaphore

**Branch**: `feat/async-tracked-semaphore`
**Depends on**: none
**Can parallelize with**: Steps 1, 2, 4
**Files changed**:
- `mutmut-llm/src/mutmut_llm/pipeline.py`
- `mutmut-llm/tests/test_pipeline.py`

### What to implement

1. **Add `TrackedSemaphore` class** in `pipeline.py`:
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

2. **Add `TestTrackedSemaphore` test class** using `pytest-asyncio`:
   - Test `in_flight` starts at 0
   - Test `in_flight` increments on acquire, decrements on release
   - Test max concurrency is enforced (N+1 acquires with limit N blocks)
   - Test `in_flight` accurate under concurrent access

   Example test structure:
   ```python
   import pytest

   @pytest.mark.asyncio
   async def test_in_flight_tracking():
       from mutmut_llm.pipeline import TrackedSemaphore
       sem = TrackedSemaphore(2)
       assert sem.in_flight == 0

       async with sem:
           assert sem.in_flight == 1
           async with sem:
               assert sem.in_flight == 2
           assert sem.in_flight == 1
       assert sem.in_flight == 0
   ```

3. **Add `pytest-asyncio` to dev dependencies** if not present. Check `pyproject.toml` [dependency-groups] dev section and add if needed:
   ```toml
   [dependency-groups]
   dev = [
       "ruff>=0.15.4",
       "pytest-asyncio>=0.24.0",
   ]
   ```

### Acceptance criteria
- [ ] AC1: `TrackedSemaphore(5).in_flight` returns `0` initially
  - `uv run --package mutmut-llm python -c "import asyncio; from mutmut_llm.pipeline import TrackedSemaphore; s=TrackedSemaphore(5); assert s.in_flight==0; print('OK')"`
- [ ] AC2: `in_flight` correctly tracks acquired slots
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestTrackedSemaphore::test_in_flight_tracking -v`
- [ ] AC3: Semaphore limits concurrent access to specified value
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestTrackedSemaphore::test_max_concurrency_enforced -v`
- [ ] AC4: All TrackedSemaphore tests pass
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestTrackedSemaphore -v`
- [ ] AC5: Full test suite passes
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/ -q --tb=short`

### Reviewer checklist
- Verify `_in_flight` is private (underscore prefix)
- Verify `in_flight` is a read-only property
- Verify `__aenter__` increments AFTER successful acquire
- Verify `__aexit__` decrements BEFORE release
- Verify tests use `pytest.mark.asyncio` decorator
- Verify tests cover both sequential and concurrent access patterns

---

## Step 4: SIGINT Handler

**Branch**: `feat/async-sigint-handler`
**Depends on**: none
**Can parallelize with**: Steps 1, 2, 3
**Files changed**:
- `mutmut-llm/src/mutmut_llm/pipeline.py`
- `mutmut-llm/tests/test_pipeline.py`

### What to implement

1. **Add `_sigint_handler` context manager** in `pipeline.py`:
   ```python
   import signal
   from contextlib import contextmanager

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
   ```

2. **Add `TestSigintHandler` test class**:
   - Test that SIGINT sets the cancel_event
   - Test that old handler is restored after context exit
   - Test that cancel_event can be checked in async code

   Example test:
   ```python
   import os
   import signal
   import asyncio
   import pytest

   class TestSigintHandler:
       def test_sigint_sets_cancel_event(self):
           from mutmut_llm.pipeline import _sigint_handler
           cancel_event = asyncio.Event()

           with _sigint_handler(cancel_event):
               assert not cancel_event.is_set()
               os.kill(os.getpid(), signal.SIGINT)
               assert cancel_event.is_set()

       def test_old_handler_restored(self):
           from mutmut_llm.pipeline import _sigint_handler

           original = signal.getsignal(signal.SIGINT)
           cancel_event = asyncio.Event()

           with _sigint_handler(cancel_event):
               current = signal.getsignal(signal.SIGINT)
               assert current != original

           restored = signal.getsignal(signal.SIGINT)
           assert restored == original
   ```

### Acceptance criteria
- [ ] AC1: `_sigint_handler` context manager is importable from `mutmut_llm.pipeline`
  - `uv run --package mutmut-llm python -c "from mutmut_llm.pipeline import _sigint_handler; print('OK')"`
- [ ] AC2: SIGINT signal sets the cancel_event
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestSigintHandler::test_sigint_sets_cancel_event -v`
- [ ] AC3: Original SIGINT handler is restored after context exits
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestSigintHandler::test_old_handler_restored -v`
- [ ] AC4: All SIGINT handler tests pass
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestSigintHandler -v`
- [ ] AC5: Full test suite passes
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/ -q --tb=short`

### Reviewer checklist
- Verify `@contextmanager` decorator is used
- Verify `signal.signal()` is called with `signal.SIGINT`
- Verify old handler is captured BEFORE installing new handler
- Verify old handler is restored in `finally` block (not just normal exit)
- Verify handler function only sets `cancel_event.set()` (no raise)
- Verify tests don't leave signal handlers in corrupted state on failure

---

## Step 5: _compute_concurrency

**Branch**: `feat/async-compute-concurrency`
**Depends on**: Step 1 (needs min_concurrency/max_concurrency in LLMConfig)
**Can parallelize with**: Step 6 (after Step 1 completes)
**Files changed**:
- `mutmut-llm/src/mutmut_llm/pipeline.py`
- `mutmut-llm/tests/test_pipeline.py`

### What to implement

1. **Add `_compute_concurrency()` function** in `pipeline.py`:
   ```python
   def _compute_concurrency(n_targets: int, config: LLMConfig) -> int:
       """Dynamic concurrency: n_targets // 3, clamped to [min_concurrency, max_concurrency]."""
       return max(config.min_concurrency, min(n_targets // 3, config.max_concurrency))
   ```

2. **Add `TestComputeConcurrency` test class**:
   - Test n=0 → min_concurrency (5)
   - Test n=1 → min_concurrency (5)
   - Test n=3 → min_concurrency (5) (3//3=1 < 5)
   - Test n=6 → min_concurrency (5) (6//3=2 < 5)
   - Test n=15 → 5 (15//3=5, equals min)
   - Test n=30 → 10 (30//3=10, within range)
   - Test n=60 → 20 (60//3=20, equals max)
   - Test n=90 → max_concurrency (20) (90//3=30 > 20)
   - Test n=300 → max_concurrency (20) (300//3=100 > 20)
   - Test custom min/max: n=30, min=1, max=5 → 5 (10 clamped to max)
   - Test custom min/max: n=3, min=10, max=20 → 10 (1 clamped to min)

   Use default config (min=5, max=20) for most tests, custom config for edge cases.

### Acceptance criteria
- [ ] AC1: `_compute_concurrency(0, config)` returns `5` (min_concurrency)
  - `uv run --package mutmut-llm python -c "from mutmut_llm.pipeline import _compute_concurrency; from mutmut_llm.config import LLMConfig; c=LLMConfig(); assert _compute_concurrency(0,c)==5; print('OK')"`
- [ ] AC2: `_compute_concurrency(30, config)` returns `10`
  - `uv run --package mutmut-llm python -c "from mutmut_llm.pipeline import _compute_concurrency; from mutmut_llm.config import LLMConfig; c=LLMConfig(); assert _compute_concurrency(30,c)==10; print('OK')"`
- [ ] AC3: `_compute_concurrency(90, config)` returns `20` (max_concurrency)
  - `uv run --package mutmut-llm python -c "from mutmut_llm.pipeline import _compute_concurrency; from mutmut_llm.config import LLMConfig; c=LLMConfig(); assert _compute_concurrency(90,c)==20; print('OK')"`
- [ ] AC4: All compute_concurrency tests pass
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestComputeConcurrency -v`
- [ ] AC5: Full test suite passes
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/ -q --tb=short`

### Reviewer checklist
- Verify formula matches spec: `max(min_concurrency, min(n_targets // 3, max_concurrency))`
- Verify integer division is used (`//`)
- Verify tests cover all boundary conditions (0, 1, at min, within range, at max, above max)
- Verify tests use both default config and custom min/max values

---

## Step 6: _call_llm_and_validate_async + conftest helpers

**Branch**: `feat/async-call-llm-validate`
**Depends on**: Step 1 (needs request_timeout_seconds in config)
**Can parallelize with**: Step 5 (after Step 1 completes)
**Files changed**:
- `mutmut-llm/src/mutmut_llm/pipeline.py`
- `mutmut-llm/tests/conftest.py`
- `mutmut-llm/tests/test_pipeline.py`

### What to implement

1. **Add `_call_llm_and_validate_async()` function** in `pipeline.py`:
   ```python
   import asyncio

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
   ```

2. **Add async mock helpers to `conftest.py`**:
   ```python
   from unittest.mock import AsyncMock

   def make_async_mock_client(responses: list | None = None) -> AsyncMock:
       """Create a mock AsyncAnthropic client.

       Args:
           responses: List of responses for messages.create. If None, returns empty mutations.
                      Can contain exceptions to simulate failures.
       """
       client = AsyncMock()
       if responses:
           client.messages.create = AsyncMock(side_effect=responses)
       else:
           client.messages.create = AsyncMock(
               return_value=make_mock_response([])
           )
       return client
   ```

3. **Add `TestCallLlmAndValidateAsync` test class**:
   - Test successful call returns mutations with cost data
   - Test truncated response (stop_reason="max_tokens") warns
   - Test syntax error mutations rejected
   - Test timeout raises asyncio.TimeoutError
   - Test API exception propagates

### Acceptance criteria
- [ ] AC1: `_call_llm_and_validate_async` is importable from `mutmut_llm.pipeline`
  - `uv run --package mutmut-llm python -c "from mutmut_llm.pipeline import _call_llm_and_validate_async; print('OK')"`
- [ ] AC2: `make_async_mock_client` is importable from `tests.conftest`
  - `uv run --package mutmut-llm python -c "from tests.conftest import make_async_mock_client; print('OK')"`
- [ ] AC3: Async function returns valid mutations with correct cost data
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestCallLlmAndValidateAsync::test_valid_mutations_returned -v`
- [ ] AC4: Truncated response warns user
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestCallLlmAndValidateAsync::test_truncated_response_warns -v`
- [ ] AC5: Invalid mutations rejected
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestCallLlmAndValidateAsync::test_syntax_errors_rejected -v`
- [ ] AC6: All async validation tests pass
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestCallLlmAndValidateAsync -v`
- [ ] AC7: Full test suite passes
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/ -q --tb=short`

### Reviewer checklist
- Verify `asyncio.wait_for` wraps the API call with `config.request_timeout_seconds`
- Verify `asyncio.TimeoutError` is re-raised (not caught silently)
- Verify warning message on timeout includes function name
- Verify function signature matches sync version except for `async`
- Verify return type is `GenerationResult` (same as sync)
- Verify `make_async_mock_client` uses `AsyncMock` not `MagicMock`
- Verify tests use `pytest.mark.asyncio` decorator

---

## Step 7: _call_llm_async

**Branch**: `feat/async-call-llm`
**Depends on**: Steps 2 (ErrorAction/classify_error), 3 (TrackedSemaphore), 6 (_call_llm_and_validate_async)
**Can parallelize with**: none
**Files changed**:
- `mutmut-llm/src/mutmut_llm/pipeline.py`
- `mutmut-llm/tests/test_pipeline.py`

### What to implement

1. **Add `_compute_backoff()` helper** in `pipeline.py`:
   ```python
   import random

   def _compute_backoff(attempt: int, base: float, cap: float = 30.0) -> float:
       """Compute backoff delay: base * 2^attempt + jitter, capped."""
       delay = min(base * (2 ** attempt), cap)
       jitter = random.uniform(0, 0.5)
       return delay + jitter
   ```

2. **Add `_call_llm_async()` function** in `pipeline.py`:
   ```python
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

3. **Add `TestComputeBackoff` test class**:
   - Test attempt=0 with base=1.0 → delay in [1.0, 1.5]
   - Test attempt=1 with base=1.0 → delay in [2.0, 2.5]
   - Test attempt=2 with base=1.0 → delay in [4.0, 4.5]
   - Test delay capped at 30.0 (attempt=10, base=1.0)

4. **Add `TestCallLlmAsync` test class**:
   - Test successful call returns result
   - Test cancel_event set before acquire returns empty
   - Test cancel_event set during acquire returns empty
   - Test RETRY error triggers retry with backoff
   - Test SKIP error returns empty without retry
   - Test STOP error sets cancel_event and raises
   - Test max_retries exhausted returns empty
   - Test backoff delays increase exponentially

   For backoff timing test, mock `asyncio.sleep` and verify call args:
   ```python
   @pytest.mark.asyncio
   async def test_exponential_backoff_delays(self):
       sleep_calls = []
       async def mock_sleep(delay):
           sleep_calls.append(delay)

       # ... setup mock client that fails 3 times then succeeds ...

       with patch("asyncio.sleep", mock_sleep):
           result = await _call_llm_async(...)

       # Verify exponential increase
       assert 1.0 <= sleep_calls[0] <= 1.5  # base * 2^0
       assert 2.0 <= sleep_calls[1] <= 2.5  # base * 2^1
       assert 4.0 <= sleep_calls[2] <= 4.5  # base * 2^2
   ```

### Acceptance criteria
- [ ] AC1: `_call_llm_async` is importable from `mutmut_llm.pipeline`
  - `uv run --package mutmut-llm python -c "from mutmut_llm.pipeline import _call_llm_async; print('OK')"`
- [ ] AC2: `_compute_backoff(0, 1.0)` returns value in [1.0, 1.5]
  - `uv run --package mutmut-llm python -c "from mutmut_llm.pipeline import _compute_backoff; d=_compute_backoff(0,1.0); assert 1.0<=d<=1.5; print('OK')"`
- [ ] AC3: Cancel event prevents API call
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestCallLlmAsync::test_cancel_event_prevents_call -v`
- [ ] AC4: RETRY error triggers retry
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestCallLlmAsync::test_retry_on_transient_error -v`
- [ ] AC5: SKIP error returns empty without retry
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestCallLlmAsync::test_skip_on_permanent_error -v`
- [ ] AC6: STOP error sets cancel_event and raises
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestCallLlmAsync::test_stop_on_fatal_error -v`
- [ ] AC7: All _call_llm_async tests pass
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestCallLlmAsync -v`
- [ ] AC8: Full test suite passes
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/ -q --tb=short`

### Reviewer checklist
- Verify cancel_event checked BOTH before and after semaphore acquire
- Verify retry loop is `for attempt in range(config.max_retries + 1)` (max_retries+1 total attempts)
- Verify STOP action calls `cancel_event.set()` before `raise`
- Verify backoff happens OUTSIDE the semaphore context (don't hold semaphore during sleep)
- Verify `_compute_backoff` uses `random.uniform(0, 0.5)` for jitter
- Verify tests mock both successful and failing API calls
- Verify tests verify asyncio.sleep was called with expected delays

---

## Step 8: _generate_mutations_async

**Branch**: `feat/async-generate-mutations`
**Depends on**: Steps 3 (TrackedSemaphore), 4 (SIGINT handler), 5 (_compute_concurrency), 7 (_call_llm_async)
**Can parallelize with**: none
**Files changed**:
- `mutmut-llm/src/mutmut_llm/pipeline.py`
- `mutmut-llm/tests/test_pipeline.py`

### What to implement

1. **Add `_generate_mutations_async()` function** in `pipeline.py`:
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

       # Dynamic concurrency
       concurrency = _compute_concurrency(len(work_items), config)
       semaphore = TrackedSemaphore(concurrency)

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

2. **Add `TestGenerateMutationsAsync` test class**:
   - Test all-cached targets returns 0 with "All targets cached" message
   - Test budget enforcement (budget=1 with 2 uncached targets)
   - Test tqdm.update called once per task
   - Test cost accumulation across multiple calls
   - Test failed count incremented on error
   - Test dynamic concurrency used (verify semaphore value based on target count)
   - Test targets processed in sorted file order
   - Test cancel_event cancels remaining tasks

   These tests require careful mocking. Use `make_async_mock_client` from conftest and mock `tqdm.tqdm` to verify calls:
   ```python
   @pytest.mark.asyncio
   async def test_tqdm_update_called_per_task(self, tmp_path):
       mock_client = make_async_mock_client([
           make_mock_response([{"mutated_code": "def f(): pass", "description": ""}])
           for _ in range(3)
       ])

       targets = [ScopeTarget(file_path=f"f{i}.py", ...) for i in range(3)]
       # ... setup ...

       mock_pbar = MagicMock()
       mock_tqdm = MagicMock(return_value=mock_pbar)

       with patch("anthropic.AsyncAnthropic", return_value=mock_client):
           with patch("mutmut_llm.pipeline.tqdm", mock_tqdm):
               await _generate_mutations_async(config, targets, budget, 10, tmp_path)

       assert mock_pbar.update.call_count == 3
   ```

### Acceptance criteria
- [ ] AC1: `_generate_mutations_async` is importable from `mutmut_llm.pipeline`
  - `uv run --package mutmut-llm python -c "from mutmut_llm.pipeline import _generate_mutations_async; print('OK')"`
- [ ] AC2: All-cached targets returns 0
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestGenerateMutationsAsync::test_all_cached_returns_zero -v`
- [ ] AC3: Budget enforcement limits API calls
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestGenerateMutationsAsync::test_budget_enforcement -v`
- [ ] AC4: tqdm progress bar updates correctly
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestGenerateMutationsAsync::test_tqdm_update_called_per_task -v`
- [ ] AC5: Cost accumulates across calls
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestGenerateMutationsAsync::test_cost_accumulation -v`
- [ ] AC6: Dynamic concurrency computed from target count
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestGenerateMutationsAsync::test_dynamic_concurrency -v`
- [ ] AC7: All async generation tests pass
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestGenerateMutationsAsync -v`
- [ ] AC8: Full test suite passes
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/ -q --tb=short`

### Reviewer checklist
- Verify `anthropic.AsyncAnthropic` (not `anthropic.Anthropic`) is used
- Verify `_compute_concurrency` is called with `len(work_items)`
- Verify tasks created with `asyncio.create_task()` before await loop
- Verify cache writes happen AFTER successful task completion (not during)
- Verify tqdm bar_format matches spec: `{desc}: {n}/{total} [▶{postfix[in_flight]}] failed:{postfix[failed]} cost:${postfix[cost]:.4f}`
- Verify `_sigint_handler` wraps the await loop
- Verify failed tasks increment `failed` counter
- Verify FATAL error cancels all tasks and breaks loop

---

## Step 9: Wire up run_generation + update tests

**Branch**: `feat/async-wire-up`
**Depends on**: Step 8 (_generate_mutations_async)
**Can parallelize with**: none
**Files changed**:
- `mutmut-llm/src/mutmut_llm/pipeline.py`
- `mutmut-llm/tests/test_pipeline.py`

### What to implement

1. **Update `run_generation()` to use async**:
   Replace the call to `_generate_mutations()` with `asyncio.run(_generate_mutations_async(...))`:
   ```python
   def run_generation(
       config: LLMConfig,
       paths: list[str],
       budget: int,
       dry_run: bool = False,
       base_dir: Path | None = None,
   ) -> int:
       # ... existing validation unchanged ...

       if dry_run:
           # ... dry run logic unchanged ...
           return 0

       return asyncio.run(
           _generate_mutations_async(
               config, scope.targets, scope.budget_per_target, budget, base_dir
           )
       )
   ```

2. **Keep `_generate_mutations()` as a thin wrapper** for backward compatibility with tests that call it directly:
   ```python
   def _generate_mutations(
       config: LLMConfig,
       targets: list[ScopeTarget],
       budget_per_target: dict[str, int],
       total_budget: int,
       base_dir: Path | None,
   ) -> int:
       """Sync wrapper for backward compatibility. Prefer _generate_mutations_async."""
       return asyncio.run(
           _generate_mutations_async(config, targets, budget_per_target, total_budget, base_dir)
       )
   ```

3. **Update `TestRunGeneration` tests** to patch `anthropic.AsyncAnthropic`:
   Change all `@patch("anthropic.Anthropic")` to `@patch("anthropic.AsyncAnthropic")` and use `AsyncMock`:

   Before:
   ```python
   @patch("anthropic.Anthropic")
   def test_generates_and_caches(self, MockAnthropic, sample_project, capsys):
       mock_client = MagicMock()
       mock_client.messages.create.return_value = _make_mock_response(mutations)
       MockAnthropic.return_value = mock_client
   ```

   After:
   ```python
   @patch("anthropic.AsyncAnthropic")
   def test_generates_and_caches(self, MockAsyncAnthropic, sample_project, capsys):
       mock_client = AsyncMock()
       mock_client.messages.create = AsyncMock(return_value=_make_mock_response(mutations))
       MockAsyncAnthropic.return_value = mock_client
   ```

4. **Update inline patches** in tests that use `with patch("anthropic.Anthropic", ...)`:
   - `test_targets_sorted_by_file_path`
   - `test_no_cache_tokens_no_log`
   - `test_all_cache_read_shows_100_percent`
   - `test_mixed_cache_shows_correct_percentage`

   All must change to:
   ```python
   with patch("anthropic.AsyncAnthropic", return_value=mock_client):
   ```
   where `mock_client = AsyncMock()` with `mock_client.messages.create = AsyncMock(return_value=...)`.

5. **Add import** at top of test file:
   ```python
   from unittest.mock import MagicMock, AsyncMock, patch
   ```

### Acceptance criteria
- [ ] AC1: `run_generation` calls `asyncio.run` internally
  - `uv run --package mutmut-llm python -c "import inspect; from mutmut_llm.pipeline import run_generation; src=inspect.getsource(run_generation); assert 'asyncio.run' in src; print('OK')"`
- [ ] AC2: `_generate_mutations` remains callable (backward compat)
  - `uv run --package mutmut-llm python -c "from mutmut_llm.pipeline import _generate_mutations; print('OK')"`
- [ ] AC3: test_generates_and_caches passes with async mock
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestRunGeneration::test_generates_and_caches -v`
- [ ] AC4: test_skips_cached_functions passes
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestRunGeneration::test_skips_cached_functions -v`
- [ ] AC5: test_budget_limits_api_calls passes
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestRunGeneration::test_budget_limits_api_calls -v`
- [ ] AC6: TestMultiModelGeneration tests pass
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestMultiModelGeneration -v`
- [ ] AC7: TestCostTracking tests pass
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestCostTracking -v`
- [ ] AC8: TestPromptCaching tests pass
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestPromptCaching -v`
- [ ] AC9: TestCacheHitLogging tests pass
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py::TestCacheHitLogging -v`
- [ ] AC10: Full test suite passes
  - `uv run --package mutmut-llm pytest mutmut-llm/tests/ -q --tb=short`

### Reviewer checklist
- Verify `run_generation` signature unchanged (remains sync)
- Verify `_generate_mutations` wrapper calls `asyncio.run(_generate_mutations_async(...))`
- Verify ALL tests patching `anthropic.Anthropic` are updated to `anthropic.AsyncAnthropic`
- Verify `AsyncMock` used for client, not `MagicMock`
- Verify `messages.create` is set as `AsyncMock(return_value=...)` not plain assignment
- Verify no remaining references to sync `anthropic.Anthropic` in tests
- Verify existing test assertions unchanged (same behavior, just async internally)
- Run full test suite and verify all tests pass

---

## Cross-Step Risks and Mitigations

1. **pytest-asyncio configuration**: Ensure `pytest.ini` or `pyproject.toml` has `asyncio_mode = "auto"` or tests use explicit `@pytest.mark.asyncio`.

2. **Import order**: The `import anthropic` inside functions (lazy import) must switch from `anthropic.Anthropic` to `anthropic.AsyncAnthropic` in async functions.

3. **Existing sync tests**: The `TestCallLlmAndValidate` tests that call the sync `_call_llm_and_validate` should remain unchanged. Only `TestRunGeneration` and related integration tests need async mocks.

4. **tqdm import**: Must be at module level in pipeline.py, not inside function, for proper mocking in tests.

5. **Signal handler in tests**: Tests for `_sigint_handler` must not leave signal handlers in corrupted state. Use try/finally or context managers.
