# Async Parallel Generation — Progress

## Status: COMPLETE ✅

## Steps

| Step | Name | Status | Branch | Reviewer verdict |
|------|------|--------|--------|-----------------|
| 1 | Config Changes | ✅ Done | `feat/async-config` | — |
| 2 | Error Classification | ✅ Done | `feat/async-error-classifier` | — |
| 3 | TrackedSemaphore | ✅ Done | `feat/async-tracked-semaphore` | — |
| 4 | SIGINT Handler | ✅ Done | `feat/async-sigint-handler` | — |
| 5 | _compute_concurrency | ✅ Done | `feat/async-compute-concurrency` | — |
| 6 | _call_llm_and_validate_async | ✅ Done | `feat/async-call-llm-validate` | — |
| 7 | _call_llm_async | ✅ Done | `feat/async-call-llm` | — |
| 8 | _generate_mutations_async | ✅ Done | `feat/async-generate-mutations` | — |
| 9 | Wire up run_generation | ✅ Done | `feat/async-wire-up` | — |

## Execution Graph

```
WAVE 1 (parallel - no dependencies) ✅
├── Step 1: Config Changes
├── Step 2: Error Classification
├── Step 3: TrackedSemaphore
└── Step 4: SIGINT Handler

WAVE 2 (parallel - depends on Step 1) ✅
├── Step 5: _compute_concurrency
└── Step 6: _call_llm_and_validate_async + conftest helpers

WAVE 3 (sequential - depends on Steps 2, 3, 6) ✅
└── Step 7: _call_llm_async

WAVE 4 (sequential - depends on Steps 3, 4, 5, 7) ✅
└── Step 8: _generate_mutations_async

WAVE 5 (sequential - depends on Step 8) ✅
└── Step 9: Wire up run_generation + update tests
```

## Final validation

```
448 passed, 21 skipped
```

## Key Design Decisions (implemented)
1. `_generate_mutations()` kept as sync wrapper for backward compat — now delegates to `asyncio.run(_generate_mutations_async(...))`
2. `pytest-asyncio` added with `asyncio_mode = "auto"`
3. `tqdm` imported at module level in pipeline.py for mockability
4. SIGINT handler sets cancel_event, doesn't raise
5. Backoff sleeps OUTSIDE semaphore (don't hold slot during backoff) — uses `backoff_delay` variable pattern
6. `anthropic.AsyncAnthropic` used throughout async pipeline
7. All existing tests migrated from sync `anthropic.Anthropic` to `anthropic.AsyncAnthropic` with `AsyncMock`
