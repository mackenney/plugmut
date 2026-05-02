# Cost Tracking for LLM Mutations

Add per-call and aggregate cost tracking to `mutmut-llm`. Every API call records token usage and USD cost. Costs flow through cache → storage → reporting.

## Current State

- `pipeline.py`: calls Anthropic API via `client.messages.create()`, discards `response.usage`
- `cache.py`: `CacheEntry` has no cost fields
- `storage.py`: `RunResult` / `MutantResult` have no cost fields
- `reporting.py`: shows LLM/builtin counts but no cost metrics
- `config.py`: no pricing table

The old fork (`~/pr/mutmut/`) has all of this implemented — this plan ports the cost tracking with a cleaner design.

## Architecture

Changes across 5 existing files + 1 new file:

```
mutmut-llm/src/mutmut_llm/
├── pricing.py       # NEW: model pricing table + cost calculation
├── pipeline.py      # MODIFIED: capture usage, compute cost, pass to cache
├── cache.py         # MODIFIED: add cost_usd, generated_at, token counts to CacheEntry
├── storage.py       # MODIFIED: add cost fields to RunResult
├── reporting.py     # MODIFIED: show cost in summaries
└── plugin.py        # MODIFIED: aggregate cost in post_run
```

## Public API

```python
# pricing.py

@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float

MODEL_PRICING: dict[str, ModelPricing]

def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD cost. Falls back to Sonnet pricing with warning for unknown models."""

def format_cost(cost_usd: float) -> str:
    """Format cost for display: '$0.0042' or '<$0.001'."""
```

```python
# cache.py — extended CacheEntry

@dataclass
class CacheEntry:
    function_name: str
    file_path: str
    source_hash: str
    mutations: list[dict]
    model: str
    # NEW fields:
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    generated_at: str = ""  # ISO 8601 timestamp
```

```python
# pipeline.py — _call_llm_and_validate returns cost info

@dataclass
class GenerationResult:
    mutations: list[dict]
    cost_usd: float
    input_tokens: int
    output_tokens: int
```

## Steps

### Step 1: Create `pricing.py` with model pricing table

```python
MODEL_PRICING = {
    "claude-sonnet-4-6": ModelPricing(3.0, 15.0),
    "claude-sonnet-4-5-20250514": ModelPricing(3.0, 15.0),
    "claude-haiku-3-5-20241022": ModelPricing(0.80, 4.0),
    "claude-opus-4-6": ModelPricing(15.0, 75.0),
}
```

Include common model ID aliases. `calculate_cost()` does:
```python
def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        warnings.warn(f"Unknown model '{model}', using Sonnet pricing")
        pricing = MODEL_PRICING["claude-sonnet-4-6"]
    return (input_tokens * pricing.input_per_million + output_tokens * pricing.output_per_million) / 1_000_000
```

**Unit tests** (`test_pricing.py`):
1. Known model returns correct cost: `calculate_cost("claude-sonnet-4-6", 1000, 500)` = `(1000 * 3.0 + 500 * 15.0) / 1_000_000`
2. Unknown model falls back to Sonnet pricing and emits warning
3. Zero tokens → zero cost
4. `format_cost(0.0042)` → `"$0.0042"`
5. `format_cost(0.00001)` → `"<$0.001"`
6. `format_cost(1.23)` → `"$1.23"`
7. All models in `MODEL_PRICING` have positive input and output rates

**Smoke test:** `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pricing.py -v`

### Step 2: Extend `CacheEntry` with cost fields

Add `cost_usd`, `input_tokens`, `output_tokens`, `generated_at` to the dataclass. Update `to_dict()` / `from_dict()` serialization.

**Backward compatibility:** `from_dict()` must handle cache files written before this change (missing cost fields). Default to `0.0` / `0` / `""`.

**Unit tests** (`test_cache.py` — extend existing):
1. Round-trip: write cache entry with cost fields, read back, verify all fields match
2. Read old-format cache entry (no cost fields) → defaults to 0.0 / 0 / ""
3. `generated_at` stored as ISO 8601 string
4. Cost fields appear in JSON output

**Smoke test:** `uv run --package mutmut-llm pytest mutmut-llm/tests/test_cache.py -v`

### Step 3: Capture API usage in pipeline

Modify `_call_llm_and_validate()` to:
1. Read `response.usage.input_tokens` and `response.usage.output_tokens` from the Anthropic API response
2. Call `calculate_cost(config.model, input_tokens, output_tokens)`
3. Return a `GenerationResult` dataclass instead of bare `list[dict]`

Update callers (`_generate_mutations`, `run_generation`) to use the new return type.

Pass cost info to `write_cache_entry()` so it's persisted.

**Unit tests** (`test_pipeline.py` — extend existing):
1. Mocked API response with `usage` field → `GenerationResult.cost_usd` is correct
2. Mocked API response without `usage` field → cost defaults to 0.0 (graceful degradation)
3. Cost is passed through to cache entry
4. `generated_at` is set to current time (within 1 second tolerance)

**Smoke test:** `uv run --package mutmut-llm pytest mutmut-llm/tests/test_pipeline.py -v`

### Step 4: Add cost aggregation to storage

Extend `RunResult` with:
```python
@dataclass
class RunResult:
    # existing fields...
    total_llm_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
```

The `mutmut_post_run` hook aggregates cost from cache entries used in the run.

Approach: during `run_generation()`, accumulate total cost. Store in a module-level variable (same pattern as `_source_by_mutant_name`). `mutmut_post_run` reads it and writes to `RunResult`.

**Unit tests** (`test_storage.py` — extend existing):
1. `RunResult` with cost fields serializes/deserializes correctly
2. Old-format run results (no cost) load with defaults
3. Cost aggregation: 3 cache entries with costs → total matches sum

**Smoke test:** `uv run --package mutmut-llm pytest mutmut-llm/tests/test_storage.py -v`

### Step 5: Add cost to reporting

Update `format_run_summary()` to include cost:
```
Mutations: 42 total, 38 killed, 4 survived (90.5% kill rate)
Sources: 35 builtin, 7 LLM ($0.0234)
```

Update `format_run_table()` to show per-function cost if available (from cache entries).

**Unit tests** (`test_reporting.py` — extend existing):
1. Summary with zero cost → no cost shown (or "$0.00")
2. Summary with cost → formatted correctly
3. Summary with cost < $0.001 → shows "<$0.001"

**Smoke test:** `uv run --package mutmut-llm pytest mutmut-llm/tests/test_reporting.py -v`

### Step 6: Add `llm-status` cost summary

Update the `mutmut llm-status` CLI command to show cumulative cost across all cache entries:
```
LLM Plugin Status:
  Model: claude-sonnet-4-6
  API Key: ****...1234
  Cache entries: 12
  Total cached mutations: 47
  Total generation cost: $0.15
  Average cost per function: $0.0125
```

Read all cache entries, sum `cost_usd` fields.

**Unit tests** (`test_plugin.py` — extend existing):
1. `llm-status` output includes "Total generation cost" line
2. Cost is sum of all cache entries' `cost_usd`

**Smoke test:** `uv run --package mutmut-llm pytest mutmut-llm/tests/test_plugin.py -v`

### Step 7: Live API cost verification

Add to `test_e2e_live.py` (from the live API integration tests plan):

15. **`test_live_cost_is_positive`** — After a real API call, verify `GenerationResult.cost_usd > 0`.
16. **`test_live_token_counts_are_positive`** — Verify `input_tokens > 0` and `output_tokens > 0`.
17. **`test_live_cost_matches_calculation`** — Verify `cost_usd == calculate_cost(model, input_tokens, output_tokens)` (exact float match since same calculation).
18. **`test_live_cache_entry_has_cost`** — After pipeline run, read cache entry and verify `cost_usd > 0` and `generated_at` is a valid ISO timestamp.

**Verify:** `MUTMUT_LLM_E2E_LIVE=1 uv run --package mutmut-llm pytest mutmut-llm/tests/e2e/test_e2e_live.py -v -k "cost or token"` — all pass.

### Step 8: Full regression check

```bash
uv run --package mutmut-llm pytest mutmut-llm/tests/ -v --ignore=mutmut-llm/tests/e2e/test_e2e_live.py
uv run --package mutmut pytest mutmut/tests/ -x
uv run --package mutmut-extras pytest -x
```

Verify no existing tests break from the dataclass changes (backward-compatible defaults).

## Pricing Maintenance

Model pricing changes over time. The `MODEL_PRICING` dict is the single source of truth. When Anthropic updates pricing:
1. Update the dict in `pricing.py`
2. No cache migration needed — historical costs reflect what was paid at generation time
3. The `model` field in cache entries documents which model was used

## Dependencies

No new dependencies. Uses only:
- `warnings` (stdlib) — for unknown model fallback
- `datetime` (stdlib) — for `generated_at` timestamp
- Anthropic SDK's `response.usage` — already available from existing API calls
