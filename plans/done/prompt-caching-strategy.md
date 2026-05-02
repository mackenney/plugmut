# Prompt Caching Strategy for mutmut-llm

## Context

### Current API Call Pattern

The pipeline (`mutmut-llm/src/mutmut_llm/pipeline.py`) iterates over `ScopeTarget` objects (one per function) and makes one API call per uncached function via `_call_llm_and_validate()` (line 152).

Each call uses:

```python
response = client.messages.create(
    model=config.model,
    max_tokens=config.max_tokens,
    system=SYSTEM_PROMPT,            # ~300 tokens, identical across ALL calls
    messages=[{"role": "user", "content": user_prompt}],
)
```

The `user_prompt` is built by `build_user_prompt()` (`mutmut-llm/src/mutmut_llm/prompts.py`, line 43):

```
Function to mutate:
```python
{function_source}
```

File context (imports, class headers):
```python
{context}
```

Generate up to {max_mutations} subtle mutations.
```

### What's Repeated vs What Varies

| Component | Scope | Changes between calls |
|-----------|-------|----------------------|
| `SYSTEM_PROMPT` | Global | Never (identical for every call) |
| File context (imports, class header) | Per-file | Same for all functions in a file |
| Function source | Per-function | Always different |
| `max_mutations` | Per-function | Varies (usually 5) |

For a file with 10 functions, the system prompt + file context are sent 10 times identically.

## Anthropic Prompt Caching

### How It Works

Prompt caching lets the API reuse KV-cache representations of prompt prefixes across calls. Content is cached in order: `tools` -> `system` -> `messages`. A cached prefix must match exactly (byte-identical).

Two modes:
1. **Automatic caching**: Add `cache_control={"type": "ephemeral"}` at the top level of `messages.create()`. The system auto-caches up to the last cacheable block.
2. **Explicit breakpoints**: Place `cache_control` on individual content blocks for fine-grained control. Up to 4 breakpoints per request.

### TTL and Pricing

| TTL | Write cost | Read cost |
|-----|-----------|-----------|
| 5 minutes (default) | 1.25x base input | 0.10x base input |
| 1 hour | 2.00x base input | 0.10x base input |

For Sonnet 4.6 ($3/MTok base input):
- Cache write (5m): $3.75/MTok
- Cache read: $0.30/MTok (90% savings vs uncached)

The 5-minute TTL auto-refreshes on each cache hit at no extra cost.

### Minimum Token Requirements

| Model | Minimum cacheable tokens |
|-------|-------------------------|
| Claude Opus 4.6, Opus 4.5 | 4,096 |
| Claude Sonnet 4.6 | 2,048 |
| Claude Sonnet 4.5, Opus 4.1, Sonnet 4 | 1,024 |
| Claude Haiku 4.5 | 4,096 |

The system prompt alone (~300 tokens) is too short to cache on its own. It needs to be combined with additional content to meet the minimum.

### Response Usage Fields

```python
response.usage.cache_creation_input_tokens  # tokens written to cache
response.usage.cache_read_input_tokens      # tokens read from cache
response.usage.input_tokens                 # tokens after last breakpoint (uncached)
```

### What's Cacheable in mutmut-llm

1. **System prompt** (~300 tokens) -- identical across all calls but too short alone
2. **File context** (imports, class headers) -- identical for all functions in the same file, variable size
3. **System prompt + file context combined** -- this is the cacheable prefix when grouped by file

## Implementation Plan

### Strategy: Group Targets by File + Explicit System Block Caching

Sort targets by `file_path` so all functions from the same file are processed consecutively. Structure the prompt so the system message includes both the static instructions AND the file context, maximizing the cached prefix.

### Step 1: Restructure Prompt to Maximize Cached Prefix

**File: `mutmut-llm/src/mutmut_llm/prompts.py`**

Add a function that builds the system message with file context appended:

```python
def build_system_with_context(context: str = "") -> list[dict]:
    """Build system blocks with cache_control on the last block.

    Combines SYSTEM_PROMPT with file-level context so the entire
    prefix is cached across calls to functions in the same file.
    """
    blocks = [{"type": "text", "text": SYSTEM_PROMPT}]
    if context:
        blocks.append({
            "type": "text",
            "text": f"File context (imports, class headers):\n```python\n{context}\n```",
            "cache_control": {"type": "ephemeral"},
        })
    else:
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks
```

Update `build_user_prompt` to no longer include the context (it moves to the system blocks):

```python
def build_user_prompt(
    function_source: str,
    max_mutations: int = 5,
    context: str = "",  # kept for backward compat but ignored when caching
) -> str:
    parts = [f"Function to mutate:\n```python\n{function_source}\n```"]
    parts.append(f"\nGenerate up to {max_mutations} subtle mutations.")
    return "\n".join(parts)
```

### Step 2: Sort Targets by File Path

**File: `mutmut-llm/src/mutmut_llm/pipeline.py`, `_generate_mutations()` (line 77)**

```python
from itertools import groupby
from operator import attrgetter

# Group targets by file_path so consecutive calls share cached file context
sorted_targets = sorted(targets, key=attrgetter("file_path"))
```

### Step 3: Update the API Call

**File: `mutmut-llm/src/mutmut_llm/pipeline.py`, `_call_llm_and_validate()` (line 152)**

Change the `messages.create()` call to use structured system blocks:

```python
from mutmut_llm.prompts import SYSTEM_PROMPT, build_system_with_context, build_user_prompt, parse_llm_response

# In _call_llm_and_validate:
system_blocks = build_system_with_context(context=target.context)
user_prompt = build_user_prompt(
    function_source=target.source,
    max_mutations=max_mutations,
    # context no longer passed here
)

response = client.messages.create(
    model=config.model,
    max_tokens=config.max_tokens,
    system=system_blocks,
    messages=[{"role": "user", "content": user_prompt}],
)
```

### Step 4: Track Cache Metrics in Pricing

**File: `mutmut-llm/src/mutmut_llm/pricing.py`**

Add cache-aware pricing:

```python
@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float
    cache_write_per_million: float = 0.0  # 1.25x input
    cache_read_per_million: float = 0.0   # 0.10x input

    def __post_init__(self):
        if self.cache_write_per_million == 0.0:
            object.__setattr__(self, "cache_write_per_million", self.input_per_million * 1.25)
        if self.cache_read_per_million == 0.0:
            object.__setattr__(self, "cache_read_per_million", self.input_per_million * 0.10)


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        warnings.warn(f"Unknown model '{model}', using Sonnet pricing", stacklevel=2)
        pricing = MODEL_PRICING[_DEFAULT_PRICING_KEY]
    return (
        input_tokens * pricing.input_per_million
        + output_tokens * pricing.output_per_million
        + cache_creation_tokens * pricing.cache_write_per_million
        + cache_read_tokens * pricing.cache_read_per_million
    ) / 1_000_000
```

### Step 5: Extract Cache Metrics from Response

**File: `mutmut-llm/src/mutmut_llm/pipeline.py`, `_call_llm_and_validate()` (line 178)**

```python
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
```

### Step 6: Add Cache Hit Logging

**File: `mutmut-llm/src/mutmut_llm/pipeline.py`, `_generate_mutations()` loop**

Log cache hit/miss per call and aggregate stats:

```python
total_cache_read = 0
total_cache_write = 0

# After each call:
total_cache_read += result.cache_read_tokens
total_cache_write += result.cache_creation_tokens

# At end:
if total_cache_read > 0:
    pct = total_cache_read / (total_cache_read + total_cache_write + ...) * 100
    click.echo(f"Cache hit rate: {pct:.0f}% ({total_cache_read} tokens read from cache)")
```

### Step 7: Add Config Option for Cache TTL

**File: `mutmut-llm/src/mutmut_llm/config.py`**

```python
@dataclass
class LLMConfig:
    # ... existing fields ...
    cache_ttl: str = "5m"  # "5m" or "1h"
```

Pass through to `build_system_with_context()`:

```python
def build_system_with_context(context: str = "", ttl: str = "5m") -> list[dict]:
    cache_control = {"type": "ephemeral"}
    if ttl == "1h":
        cache_control["ttl"] = "1h"
    # ... rest as above, using cache_control dict ...
```

## Code Surface Impact

| File | Change type | Estimated size |
|------|------------|----------------|
| `mutmut-llm/src/mutmut_llm/prompts.py` | Add `build_system_with_context()`, modify `build_user_prompt()` | ~25 lines |
| `mutmut-llm/src/mutmut_llm/pipeline.py` | Sort targets, update API call, extract cache metrics, add logging | ~40 lines |
| `mutmut-llm/src/mutmut_llm/pricing.py` | Add cache pricing fields and params to `calculate_cost()` | ~20 lines |
| `mutmut-llm/src/mutmut_llm/config.py` | Add `cache_ttl` field | ~5 lines |
| `mutmut-llm/src/mutmut_llm/cache.py` | Add `cache_creation_tokens` / `cache_read_tokens` to `CacheEntry` | ~5 lines |
| `mutmut-llm/tests/test_pipeline.py` | Update mocks for new system block format | ~30 lines |
| `mutmut-llm/tests/test_prompts.py` (new or extend) | Test `build_system_with_context()` | ~40 lines |
| `mutmut-llm/tests/test_pricing.py` | Test cache-aware cost calculation | ~20 lines |

Total: ~185 lines changed/added.

## Testing Plan

### Unit Tests

1. **Prompt construction** (`test_prompts.py`):
   - `build_system_with_context("")` returns single block with `cache_control`
   - `build_system_with_context("import foo")` returns two blocks, second has `cache_control`
   - `build_system_with_context("...", ttl="1h")` includes `"ttl": "1h"` in cache_control
   - `build_user_prompt()` no longer includes context section

2. **Pricing** (`test_pricing.py`):
   - `calculate_cost()` with `cache_creation_tokens` charges 1.25x
   - `calculate_cost()` with `cache_read_tokens` charges 0.10x
   - Combined cache + uncached tokens compute correctly

3. **Pipeline** (`test_pipeline.py`):
   - Targets are sorted by `file_path` before processing
   - API call uses list-of-dicts `system` parameter (not plain string)
   - Cache metrics extracted from response `usage` object
   - `GenerationResult` includes `cache_read_tokens` and `cache_creation_tokens`

### Integration / Verification

4. **Cache hit verification**: After running `mutmut generate` on a multi-function file, check logged output for:
   - First function: `cache_creation_input_tokens > 0`, `cache_read_input_tokens == 0`
   - Second+ functions (same file): `cache_read_input_tokens > 0`

5. **Cost comparison**: Run generation with and without caching on same file, compare total cost logged. Expect 80-90% reduction in input token cost for files with 5+ functions.

### Gotcha: Minimum Token Threshold

The system prompt (~300 tokens) + file context must exceed the model's minimum cacheable token count (1,024 for Sonnet 4.5, 2,048 for Sonnet 4.6). Files with very few imports may fall below this threshold. The implementation should handle this gracefully -- if the combined system blocks are below the minimum, caching is silently skipped by the API (no error, just no cache hit). Log a debug message when this happens.

## Usability / Feature Impact

### Expected Cost Reduction

For a file with N functions:
- Without caching: N * (system_tokens + context_tokens + function_tokens) at full input price
- With caching: 1 cache write + (N-1) cache reads for (system + context), plus N * function_tokens at full price
- Cache reads are 90% cheaper than base input

Example: 10 functions, 1,500 token system+context, 200 token avg function:
- Without caching: 10 * (1500 + 200) * $3/MTok = $0.051
- With caching: 1 write at $3.75/MTok + 9 reads at $0.30/MTok + 10 * 200 at $3/MTok = $0.0143
- **Savings: ~72%** on input costs for this file

Savings increase with more functions per file and larger context blocks.

### Expected Latency Improvement

Cache hits reduce time-to-first-token because the API skips KV-cache computation for the cached prefix. For ~1,500 token prefixes, expect modest improvement (~100-300ms per call). More significant for files with large import sections or class hierarchies.

### UX Changes

- New config option: `cache_ttl = "5m"` (default) or `"1h"` in `[tool.mutmut.llm]`
- New log output: cache hit rate and cached token counts at end of generation
- No breaking changes to existing CLI or config

### Limitations

- Cache only benefits consecutive calls within the TTL window (5 min default). If generation takes >5 min per file, cache misses occur on the next file.
- Files with very few imports may not meet minimum cacheable token threshold.
- First call to any new file always pays the cache write premium (1.25x).
- Cache is org-scoped (workspace-scoped after Feb 2026) -- no cross-org sharing.
