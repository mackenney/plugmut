# Merging feat/prompt-caching and feat/multi-model-cache

## Branch summary

Both branches fork from the same point on main and modify overlapping files in `plugmut-llm/`.

**feat/prompt-caching** — Adds Anthropic prompt caching to reduce API costs.
- Restructures system prompt into content blocks with `cache_control`
- Moves file context from user prompt to system prompt (cacheable)
- Adds `cache_ttl` config field, cache token tracking, cache hit rate logging
- Adds `cache_creation_tokens` / `cache_read_tokens` to `GenerationResult`
- Extends `ModelPricing` with `cache_write_per_million` / `cache_read_per_million`
- Sorts targets by `file_path` for deterministic cache-friendly ordering

**feat/multi-model-cache** — Adds multi-model cache accumulation.
- Extends cache key format from 3-segment to 4-segment (appends model name)
- Adds `model` field to `CacheEntry`
- Changes cache index from `dict[str, CacheEntry]` to `dict[str, list[CacheEntry]]`
- Adds cross-model mutation deduplication in `operator_llm()` and counting in `plugin.py`
- Backward-compatible glob scanning for old 3-segment filenames

## Recommended merge order

Merge **feat/prompt-caching into main first**, then rebase feat/multi-model-cache on top.

Rationale: prompt-caching makes deeper changes to the prompt/pipeline interface (system blocks, user prompt signature, pricing fields) that multi-model-cache doesn't touch. Multi-model-cache's changes are more localized to cache.py/operators.py/plugin.py. Rebasing multi-model on top of prompt-caching requires fewer semantic decisions.

## File-by-file conflict resolution

### pipeline.py — CONFLICT EXPECTED

**prompt-caching changes:**
- `GenerationResult` gains `cache_creation_tokens`, `cache_read_tokens` fields
- `_call_llm_and_validate()` passes system as list-of-dicts via `build_system_with_context()`, extracts cache metrics from response, removes `context` param from `build_user_prompt()`
- `_generate_mutations()` sorts targets by `file_path`, accumulates cache metrics, logs cache hit rate

**multi-model-cache changes:**
- `_generate_mutations()` passes `model=config.model` to `read_cache_entry()`

**Resolution:** Keep all prompt-caching changes. Apply multi-model's `model=config.model` parameter addition to `read_cache_entry()` within the prompt-caching version of `_generate_mutations()`. The two changes are orthogonal — one adds caching metrics, the other adds model-specific cache lookup.

```python
# In _generate_mutations(), the read_cache_entry call should have both:
cached = read_cache_entry(
    ...,
    model=config.model,  # from multi-model-cache
    base_dir=base_dir,
)
# Plus prompt-caching's cache metric accumulation and target sorting
```

### config.py — CONFLICT UNLIKELY

**prompt-caching changes:** Adds `cache_ttl` field, `__post_init__` validation, `load_config` reads `cache_ttl`.
**multi-model-cache changes:** None.

**Resolution:** Take prompt-caching version as-is.

### prompts.py — CONFLICT UNLIKELY

**prompt-caching changes:** Adds `build_system_with_context()`, removes `context` from `build_user_prompt()`.
**multi-model-cache changes:** None.

**Resolution:** Take prompt-caching version as-is.

### pricing.py — CONFLICT UNLIKELY

**prompt-caching changes:** Adds cache pricing fields to `ModelPricing`, extends `calculate_cost()`.
**multi-model-cache changes:** None.

**Resolution:** Take prompt-caching version as-is.

### cache.py — CONFLICT UNLIKELY

**prompt-caching changes:** None.
**multi-model-cache changes:** Adds `model` field to `CacheEntry`, 4-segment cache keys, `_read_any_matching_entry()`, model name sanitization.

**Resolution:** Take multi-model-cache version as-is.

### operators.py — CONFLICT UNLIKELY

**prompt-caching changes:** None.
**multi-model-cache changes:** Changes index type to `dict[str, list[CacheEntry]]`, adds deduplication in `operator_llm()`.

**Resolution:** Take multi-model-cache version as-is.

### plugin.py — CONFLICT UNLIKELY

**prompt-caching changes:** None.
**multi-model-cache changes:** Rewrites `_llm_mutation_count_by_function()` for dedup, updates cost aggregation.

**Resolution:** Take multi-model-cache version as-is.

### tests/conftest.py — CONFLICT EXPECTED

**prompt-caching changes:** Extracts `make_mock_response()` helper into conftest.
**multi-model-cache changes:** None, but the branch's test_pipeline.py may reference a local helper.

**Resolution:** Keep prompt-caching's `make_mock_response()` in conftest. Ensure multi-model's test files import from conftest rather than defining their own. The helper needs these parameters (from prompt-caching):
- `cache_creation_input_tokens=0`
- `cache_read_input_tokens=0`

### tests/test_pipeline.py — CONFLICT EXPECTED

**prompt-caching changes:** Removes local `_make_mock_response()`, adds `TestPromptCaching` (6 tests), `TestUsageFieldExtraction` (3 tests), `TestCacheHitLogging` (3 tests).
**multi-model-cache changes:** Adds `TestMultiModelGeneration` (2 tests).

**Resolution:** Keep all test classes from both branches. Ensure `TestMultiModelGeneration` uses `make_mock_response` from conftest (not a local copy). The mock responses in multi-model tests need the cache token fields (default to 0).

### tests/test_e2e_live.py — CONFLICT EXPECTED (minor)

Both branches independently applied the same fix: `list` → `GenerationResult`. The linter reformatted `test_live_mutation_count_within_budget` slightly differently on each branch.

**Resolution:** Take either version — they're functionally identical. Reformat if linter complains.

### tests/test_cache.py — CONFLICT UNLIKELY

**prompt-caching changes:** None.
**multi-model-cache changes:** Adds 5 test classes (~300 lines) for multi-model cache.

**Resolution:** Take multi-model-cache version as-is.

### tests/test_plugin.py — NEW FILE (multi-model-cache only)

**Resolution:** Take as-is. No conflict possible.

### tests/test_prompts.py — CONFLICT UNLIKELY

**prompt-caching changes:** Rewrites to test `build_system_with_context()`, removes old context-in-user-prompt tests.
**multi-model-cache changes:** None.

**Resolution:** Take prompt-caching version as-is.

### tests/test_config.py — CONFLICT UNLIKELY

**prompt-caching changes:** Adds `TestTTLValidation` (5 tests).
**multi-model-cache changes:** None.

**Resolution:** Take prompt-caching version as-is.

### tests/test_pricing.py — CONFLICT UNLIKELY

**prompt-caching changes:** Adds 8 cache pricing tests.
**multi-model-cache changes:** None.

**Resolution:** Take prompt-caching version as-is.

### tests/test_operators.py — CONFLICT UNLIKELY

**prompt-caching changes:** None.
**multi-model-cache changes:** Adds `TestDeduplicationEdgeCases`.

**Resolution:** Take multi-model-cache version as-is.

## Semantic integration concerns

These are issues that won't show up as git conflicts but can cause runtime failures.

### 1. GenerationResult field alignment

prompt-caching adds `cache_creation_tokens` and `cache_read_tokens` to `GenerationResult`. Multi-model-cache's pipeline code creates `GenerationResult` instances — ensure those callsites include the new fields (default 0).

### 2. build_user_prompt signature change

prompt-caching removes the `context` parameter from `build_user_prompt()`. If multi-model-cache's tests or code call `build_user_prompt(context=...)`, those calls will fail. Search for `build_user_prompt.*context` in multi-model-cache and remove the parameter.

### 3. System prompt format in mock tests

prompt-caching changes the API call to pass `system=` as a list-of-dicts (content blocks) instead of a plain string. Multi-model tests that mock the Anthropic client and assert on the `system` parameter need to expect the new format.

### 4. make_mock_response helper location

prompt-caching moves `_make_mock_response` to `tests/conftest.py` with cache token fields. Multi-model tests that build mock responses need to use this shared helper (or at minimum include `cache_creation_input_tokens` and `cache_read_input_tokens` in their mock usage objects).

### 5. Cache read in _generate_mutations

After merge, `_generate_mutations` must both:
- Pass `model=config.model` to `read_cache_entry()` (from multi-model)
- Sort targets by `file_path` and track cache metrics (from prompt-caching)

These are orthogonal but live in the same function body.

## Verification

```bash
# After merge, run all plugmut-llm tests
uv run --package plugmut-llm pytest plugmut-llm/tests/ -v

# Run live e2e tests if API key available
PLUGMUT_LLM_E2E_LIVE=1 uv run --package plugmut-llm pytest plugmut-llm/tests/e2e/test_e2e_live.py -v

# Ensure core mutmut tests unaffected
uv run --package plugmut pytest mutmut/tests/ --ignore=mutmut/tests/e2e -x
```
