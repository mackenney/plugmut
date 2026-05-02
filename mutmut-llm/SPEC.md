# mutmut-llm Specification

> The key words MUST, MUST NOT, SHOULD, SHOULD NOT, MAY are used per RFC 2119.

## Purpose

mutmut-llm is a mutmut plugin that generates semantically sophisticated code mutations using a
large language model. It operates in two independent phases: a generation phase (run explicitly
by the user) that calls the LLM API and writes results to a local cache, and an operator phase
(run automatically during mutmut's mutation pass) that reads pre-generated mutations from that
cache. The cache is the only interface between the two phases. LLM API costs are incurred only
during generation, not during test execution.

## Non-Goals

- Does NOT run tests, judge mutation survival, or affect how mutmut executes tests.
- Does NOT expire or clean stale cache entries. Entries for renamed, deleted, or refactored
  functions accumulate indefinitely until manually cleared.
- Does NOT provide per-run cost isolation. Reported cost totals are cumulative across all
  cached entries, not scoped to the current run.
- Does NOT deduplicate semantically equivalent mutations — only textually identical ones
  (`mutated_code` string equality).
- Does NOT support targeted mutation (single function or diff-scoped subset). Only
  "all functions under given paths" mode is implemented.
- Does NOT support PR-diff-aware mutation scoping.

## Core Mental Model

**Two-phase design.** Generation and mutation testing are independent operations separated by
the cache. If no cache entry exists for a function, the LLM operator silently yields no
mutations for it; generation is not triggered implicitly.

**Source hash as identity.** A function's cache identity is the SHA-256 hash (16-hex-character
prefix) of its stripped source text. Two functions with identical bodies in different files
share cache entries and receive identical mutations. File path and function name are part of the
filename key but not part of the content identity check.

**Per-model entries.** Each `(function_identity, model_name)` pair has its own independent cache
entry. Running generation with model A does not affect model B's entries for the same function.
During mutation testing, all cached mutations for a function's source hash across all models are
merged and deduplicated by `mutated_code`.

**Validation gate.** Every LLM-generated mutation passes a three-stage pipeline (syntax →
imports → pragmas) before being written to cache. Mutations that fail any stage are discarded
at generation time and never appear in cache.

**Plugin integration.** mutmut-llm registers as a mutmut plugin and implements hooks for the
full run lifecycle: configuration, operator registration, mutation identification, per-test
tracking, and post-run reporting.

## LLM Mutation Generation Contract

### Inputs

`run_generation` accepts:
- `config`: an `LLMConfig` (see Configuration Contract)
- `paths`: a list of file paths or directory paths to scan for Python functions
- `budget`: an integer maximum number of API calls to make in this run
- `dry_run`: when true, discovers scope and reports coverage without making API calls

### Postconditions

- MUST return the count of API calls made in this run.
- For each in-scope function without a valid cache entry for the active model, MUST attempt
  generation and write a cache entry on success.
- Generated mutations MUST pass the validation pipeline before being cached.
- Mutations that fail validation MUST NOT be written to cache.
- Successfully cached entries MUST contain at least: `function_name`, `file_path`,
  `source_hash`, `mutations`, `model`, `cost_usd`, `input_tokens`, `output_tokens`,
  `generated_at`.
- Functions already cached for the active model MUST be skipped (no API call made).
- When `enabled = false`, MUST return 0 and make no API calls.
- When `api_key` is empty and `dry_run` is false, MUST return 0 and report the missing key.
- When `budget = 0`, MUST return 0 immediately and make no API calls.
- When `dry_run = true`, the cache is checked for existing entries (to report which functions
  are already covered) but no API calls are made. The cache is checked at the default location
  regardless of any `base_dir` configuration.

### Default scan path

When no paths are provided, `run_generation` defaults to scanning `["src"]`. Projects where
source code is not under `./src/` will receive no mutations unless paths are provided
explicitly.

### Scope discovery

- Directories are expanded recursively: all `.py` files, sorted alphabetically.
- Top-level function definitions and methods of top-level classes are in scope.
- Functions nested inside other functions are NOT in scope.
- Non-method class members and abstract class bodies are NOT in scope.

### Budget

- `run_generation` processes at most `budget` functions requiring API calls.
- In-scope functions are processed in ascending file path order.
- Already-cached functions do not consume budget.
- When budget is exhausted, remaining uncached functions are skipped for this run without
  error. No warning is emitted for skipped functions.

### Mutation count per function

- Each function receives at most `max_mutations_per_function` mutations from the LLM. This is
  an upper bound; the LLM MAY return fewer.
- Total budget is allocated uniformly across uncached functions, capped per function by
  `max_mutations_per_function`.

### Operator integration

- `operator_llm` is a FunctionDef mutation operator that yields pre-generated mutations from
  the cache. It MUST NOT make API calls or write to cache.
- MUST look up mutations by the source hash of the function's source text.
- MUST merge mutations from all cached models for the same source hash, deduplicating by
  `mutated_code` (string equality).
- MUST skip cached mutations whose `mutated_code` does not parse, or does not contain a
  function definition with the expected name. Each skipped mutation MUST cause a warning to be
  written to stdout.
- The full cache index (all cached mutations for all functions) MUST be loaded at most once per
  mutmut run, lazily on the first operator call. It is reset at the start of each run.

## Caching Contract

### Cache structure

- Cache entries are stored as JSON files under `.mutmut-cache/llm/` relative to the project
  root (or a configurable `base_dir`).
- Run history files are stored under `.mutmut-cache/llm/runs/`. These are a separate namespace.
- `clear_cache()` removes all cache entry JSON files. It does NOT remove run history files.

### Write safety

- A reader MUST never observe a partial cache write.
- Concurrent writers to the same cache entry MUST NOT corrupt each other.
- **Known limitation:** write safety requires a POSIX filesystem with advisory locking support.
  On Windows, write safety is not guaranteed.
- Stale lock sidecar files may persist after unclean process termination (kill signal, power
  loss). They do not prevent subsequent runs but accumulate until manually removed.

### Cache key scheme

- A cache entry filename is deterministic from `(file_path, function_name, source_hash, model)`.
- Model-specific entries use 4 segments separated by `__`.
- Legacy (no-model) entries use 3 segments.
- `file_path` path separators are normalized in the filename.
- Model names are encoded such that the `__` segment delimiter is unambiguous. The encoding is
  stable and deterministic.
- **Known bug:** `function_name` is NOT encoded. A function name containing `__` (including
  `__init__`) produces a key with an ambiguous delimiter. Two different `(file_path,
  function_name)` pairs can produce identical filenames. Example: `file_path="a"`,
  `function_name="b__c"` and `file_path="a__b"`, `function_name="c"` yield the same key.

### Class method naming

Cache entries for class methods MUST use the function name in the format
`"ClassName.method_name"`, consistent with mutmut's mutant name extraction. A mismatch in this
format causes `mutmut_mutations_created` to silently fail to identify LLM mutations for all
class methods.

### Cache hit/miss semantics

- A cache hit requires an exact match on `source_hash` AND `model`.
- A lookup with `model=None` matches any entry for `(file_path, function_name, source_hash)`.
  If multiple model entries exist, the entry with the alphabetically-first model name (after
  encoding) is returned. Callers SHOULD NOT rely on which model entry is returned when multiple
  exist.
- A lookup that finds an entry whose stored `source_hash` differs from the requested hash MUST
  return a miss. The stored entry MUST NOT be returned.
- Corrupt or unparseable cache files MUST be silently skipped; they MUST NOT cause an error.
- If a cache file is deleted between discovery and read, the entry MUST be treated as a miss.

### Multi-model coexistence

- Entries for different models for the same function MUST coexist as separate files.
- Writing an entry for model A MUST NOT affect model B's entry for the same function.
- Legacy (no-model) entries and model-specific entries MAY coexist.

### Backwards compatibility

- Entries written without a model field (3-segment filename) MUST be readable by
  `list_cache_entries` and `read_cache_entry(model=None)`.
- `read_cache_entry(model="some-model")` MUST NOT match legacy 3-segment files.
- `CacheEntry.from_dict` MUST tolerate missing optional fields (`model`, `cost_usd`,
  `input_tokens`, `output_tokens`, `cache_creation_tokens`, `cache_read_tokens`,
  `generated_at`) by substituting zero/empty defaults.

### Source hash computation

- The source hash MUST be the first 16 hex characters of the SHA-256 hash of the
  stripped (leading/trailing whitespace removed) UTF-8 source text of the function.
- The hash MUST be deterministic: identical source text always produces the same hash.

## Validation Pipeline

Validation is applied to each candidate mutation. Three stages run in order; the first failure
causes immediate rejection without running subsequent stages.

1. **Syntax check**: the `mutated_code` MUST be parseable as a complete Python module by
   libcst's module parser. Mutations accepted by CPython but rejected by libcst are rejected
   here; mutations accepted by libcst but not CPython pass this stage.

2. **Import guard**: all module names imported anywhere in `mutated_code` (at any nesting
   level, including inside functions, classes, and conditionals) are compared against all
   module names imported anywhere in `original_code`. If `mutated_code` imports any top-level
   module name not present in `original_code`, the mutation is rejected. Top-level name
   extraction: `import os.path` → `"os"`, `from os import path` → `"os"`. If `original_code`
   fails to parse, its import set is treated as empty, causing any mutation that contains
   imports to be rejected.

3. **Pragma guard**: for every line in `original_code` containing `# pragma: no mutate`
   (case-insensitive, whitespace-normalized), the line at the SAME ZERO-BASED INDEX position
   in `mutated_code` MUST be identical. If that index is out of bounds or the line content
   differs, the mutation is rejected. Note: inserting any line before a pragma-protected line
   shifts that line's position, causing rejection even if the pragma line itself is present
   elsewhere in the mutation.

Pipeline invariants:
- A rejection MUST be accompanied by a message written to stdout indicating the reason.
- A rejection MUST NOT fail the generation attempt; remaining candidate mutations continue.
- A mutation that adds no new imports MUST pass the import guard.
- A mutation that does not change any pragma-protected line at its original position MUST pass
  the pragma guard.
- An empty `mutated_code` passes syntax check, passes the import guard (no imports added), and
  passes the pragma guard only if `original_code` contains no pragma lines.

## Cost Tracking Contract

### Per-generation tracking

- For each API call, MUST record: `input_tokens`, `output_tokens`, `cache_creation_tokens`,
  `cache_read_tokens`, `cost_usd`.
- Token counts come from the API response's usage data. If a field is absent, its count
  defaults to 0. No warning is emitted for absent fields.
- `cache_creation_tokens` and `cache_read_tokens` are stored independently and are NOT
  subtracted from `input_tokens`.
- `cost_usd` is calculated from a hardcoded pricing table keyed on model name. For unrecognized
  model names, the system falls back to Sonnet-tier pricing and MUST emit a warning. Using an
  Opus-class model with an unrecognized name will result in significant cost underestimation
  under this fallback.
- If the API response lacks usage data entirely, `cost_usd` is recorded as 0 with no warning.
  This is a known source of silent cost undercount in historical totals.
- If the API call fails, recorded cost and token counts MUST be zero.
- Per-call cost and token counts are stored in the cache entry at write time and reflect only
  the cost of the generation call that produced that entry.

### Run-level tracking

- `RunResult.total_llm_cost_usd` is the sum of `cost_usd` across ALL entries currently in the
  cache, including entries written by previous generation runs. It is NOT scoped to the current
  run and grows monotonically.
- `total_input_tokens` and `total_output_tokens` reflect cumulative cache totals by the same
  logic.
- Per-model cost breakdown is NOT provided.

### Cache hit rate reporting

- After generation, if any API call produced non-zero cache read tokens, a cache hit rate MUST
  be reported.
- Cache hit rate: `sum(cache_read_tokens) / sum(input_tokens + cache_read_tokens +
  cache_creation_tokens)` across all API calls in this generation run.
- If no cache tokens were used, the cache hit rate line MUST NOT be printed.

## Retry and Backoff Contract

### Error classification

LLM API errors are classified into three actions:
- **RETRY**: transient; retry after backoff. Includes: rate limit (non-quota), server overload,
  internal server error, timeout, connection error.
- **SKIP**: permanent for this target; move on. Includes: bad request, not found, request too
  large, unrecognized exception types.
- **STOP**: fatal; cancel remaining work. Includes: authentication error, permission denied,
  rate limit with quota/billing/credit/spending-limit indicators.

### Retry behavior (async generation path)

- Maximum attempts per target: `max_retries + 1`.
- After a retryable failure, MUST wait: `min(base_backoff_seconds × 2^attempt, 30.0)` seconds
  plus uniform jitter in `[0.0, 0.5)` seconds.
- On STOP error: the cancel event MUST be set and the error propagated. In-flight tasks are
  cancelled; already-written cache entries are preserved.
- On retry exhaustion: target produces empty result (zero mutations, zero cost); a warning MUST
  be emitted.
- When the cancel event is set before a call begins, MUST return an empty result without making
  an API call.

### Sync generation path (backward compatibility)

A synchronous generation path exists alongside the async path. It catches ALL exceptions and
returns an empty result with a warning. It does NOT classify errors, does NOT retry, and does
NOT propagate STOP signals. A quota-exceeded error on the sync path is silently treated as a
per-target miss. This divergence is a known bug; see Bugs / Inconsistencies Observed.

## Concurrency Contract

### Concurrency level

- The concurrency level is computed when generation begins, from the count of uncached targets
  `n`: `max(min_concurrency, min(n // 3, max_concurrency))`.
- When `n = 0`, generation returns immediately with 0 API calls; the concurrency formula is not
  evaluated.
- The concurrency level, when evaluated, MUST fall within `[min_concurrency, max_concurrency]`.

### Execution ordering and isolation

- Uncached targets are processed in ascending file path order.
- Actual execution order within the concurrent window is non-deterministic; tasks may complete
  in any order.
- Cache writes happen in file path order (result-collection order), not task-completion order.
- A failure on one target MUST NOT prevent other targets from completing, unless the error
  action is STOP.
- Concurrent tasks writing to DIFFERENT cache entries MUST NOT interfere with each other.

## Configuration Contract

### Sources and priority

- `api_key`: sourced from the `ANTHROPIC_API_KEY` environment variable ONLY. It CANNOT be set
  via config file; any `api_key` value in `[tool.mutmut.llm]` is silently ignored.
- All other fields: sourced from the `[tool.mutmut.llm]` section of `pyproject.toml` (located
  by walking up from cwd), falling back to dataclass defaults.

### Config fields

| Field | Default | Constraint |
|---|---|---|
| `model` | `"claude-sonnet-4-6"` | Any string; affects cache key and cost calculation |
| `max_mutations_per_function` | `5` | No range validation (see Bugs) |
| `max_tokens` | `4096` | No minimum enforced |
| `temperature` | `0.6` | `[0.0, 1.0]` — validated by `load_config` |
| `enabled` | `True` | — |
| `cache_ttl` | `"5m"` | Must be `"5m"` or `"1h"` — validated by `load_config` |
| `min_concurrency` | `5` | Must be ≥ 1 |
| `max_concurrency` | `20` | Must be ≥ `min_concurrency` |
| `max_retries` | `3` | Must be ≥ 0 |
| `base_backoff_seconds` | `1.0` | Must be > 0 |
| `request_timeout_seconds` | `120` | Must be ≥ 10 |

**Validation gap:** `temperature` and `cache_ttl` are validated when loaded from `pyproject.toml`.
The remaining constrained fields (`min_concurrency`, `max_concurrency`, `max_retries`,
`base_backoff_seconds`, `request_timeout_seconds`) are validated at direct construction time
only. When `load_config` reads these from `pyproject.toml`, it sets fields directly without
re-running construction-time validation. Invalid values from config file (e.g.,
`min_concurrency = -1`) are silently accepted.

- `is_configured` returns `True` if and only if `api_key` is non-empty.

### Prompt caching

- The system prompt MUST be structured to enable provider-level prompt caching using the TTL
  specified by `cache_ttl`. `"5m"` uses the provider's default ephemeral TTL; `"1h"` requests
  a one-hour TTL.
- File-level context (imports, class headers) is passed as a separate cacheable prompt block
  so it may be reused across calls to functions in the same file.

## Plugin Integration Contract

mutmut-llm registers the following hooks:

- **`mutmut_configure(config)`**: loads `LLMConfig`, initializes the current run, resets the
  in-memory cache index and LLM mutant name tracking.
- **`mutmut_register_operators()`**: returns `[(cst.FunctionDef, operator_llm)]` if `enabled`;
  returns `[]` if disabled.
- **`mutmut_mutations_created(filename, source_by_mutant_name)`**: identifies which newly
  created mutants belong to the LLM operator. Assumes LLM mutations are the last `n` mutants
  added per function, where `n` is the count of cached LLM mutations for that function. If any
  operator registered AFTER `operator_llm` adds mutations for the same function, identification
  is incorrect.
- **`mutmut_post_test(mutant_name, exit_code, status, duration)`**: records a mutant result,
  marking it `is_llm` if previously identified as LLM-generated.
- **`mutmut_post_run(source_file_mutation_data)`**: writes the completed run to disk with
  cumulative cost and token totals.
- **`mutmut_register_commands(cli_group)`**: registers `generate` and `llm-status` subcommands.

### Run storage

- Each mutmut run MUST generate a unique run identifier — a fixed-length pseudo-random hex
  string with sufficient entropy for practical uniqueness within a single project.
- Runs are stored as JSON files under `.mutmut-cache/llm/runs/`.
- `load_latest_run` returns the run with the lexicographically greatest `started_at` value.
  If `started_at` formats are inconsistent across entries, sort order is undefined.
- Run files MUST be written with the same write-safety guarantee as cache entries.

## Cancellation Contract

- First SIGINT during `run_generation` MUST set a cancel event without immediately terminating
  the process.
- Once the cancel event is set, pending tasks MUST NOT make new API calls; they MUST return
  empty results.
- After the cancel event is set, in-flight tasks run to natural completion (or are awaited
  until they complete or are cancelled). Cache writes that complete before cancellation are
  preserved.
- A forced interrupt (second SIGINT or `KeyboardInterrupt` propagated into the async loop):
  outstanding tasks are cancelled but NOT awaited. The function returns immediately. Already-
  written cache entries are preserved; in-flight tasks may not have completed their cache
  writes.
- The original SIGINT handler MUST be restored when `run_generation` returns, including on
  exception.

## Known Limitations / Accepted Trade-offs

1. **Cache never expires.** Entries for renamed, deleted, or refactored functions accumulate
   indefinitely. Manual `clear_cache()` removes cache entries but not run history.
2. **Cost totals are cumulative, not per-run.** `RunResult.total_llm_cost_usd` sums all cache
   entries ever written; it grows monotonically across generation runs.
3. **Source hash collisions not detected.** Two semantically different functions whose source
   text produces the same 64-bit hash prefix share cache entries. No collision detection is
   performed.
4. **Deep mode only.** Targeting a specific function or diff-scoped subset is not supported.
5. **Import guard does not detect namespace changes.** `from os import path` and `import os`
   both normalize to `"os"`. A mutation substituting one for the other passes the import guard.
6. **POSIX-only write safety.** The write-safety guarantee requires a POSIX filesystem with
   advisory locking support. Windows is unsupported.
7. **Stale lock sidecar files.** After unclean process termination, lock sidecar files persist
   until manually removed.
8. **`base_dir` ignored by `mutmut_mutations_created`.** This hook always reads cache entries
   from the default location. If generation ran with a non-default `base_dir`, no LLM mutations
   are identified during testing.
9. **Pricing table becomes stale.** For unrecognized model names, cost falls back to Sonnet-
   tier pricing. Using an Opus-class model under an unrecognized name severely underestimates
   cost. The fallback MUST emit a warning.

## Open Questions

1. **Should `max_mutations_per_function` be validated?** Currently 0 is accepted; the API is
   called and returns an empty mutations list, which is cached. A value of 0 silently produces
   no mutations.
2. **Should run-level cost reflect only the current run's entries?** The cumulative total makes
   `RunResult.total_llm_cost_usd` semantically misleading on incremental runs.
3. **Should `operator_llm` merge across models or keep them separate?** Current behavior merges
   all models' mutations for a source hash. Using multiple models sequentially may produce
   unexpected results.
4. **Hash collision handling.** No specified behavior when two genuinely different functions
   share a source hash.
5. **LLM mutant ordering assumption is unenforced.** The assumption that LLM mutations are
   always appended last per function has no hook-level enforcement. A future operator registered
   after `operator_llm` breaks identification silently.

## Bugs / Inconsistencies Observed

1. **`mutmut_mutations_created` ignores `base_dir`** (`plugin.py`). Always reads cache from
   `cwd/.mutmut-cache/llm/`. If generation used a custom `base_dir`, no LLM mutations are
   identified during testing.

2. **`RunResult.total_llm_cost_usd` is cumulative, not per-run.** The field is on a per-run
   object but sums all cache entries ever written, not entries from the current run only.

3. **Import guard does not distinguish access patterns.** `from os import path` and `import os`
   both normalize to `"os"`. A mutation substituting one for the other passes the guard despite
   changing how identifiers are accessed.

4. **Sync generation path has divergent error handling.** The synchronous generation path
   catches all exceptions and returns empty results — no error classification, no retry, no STOP
   propagation. A quota-exceeded error on the sync path is silently treated as a per-target
   miss. The async path classifies, retries, and propagates STOP correctly. Both paths exist and
   are tested independently.

5. **`generated_at` has no format contract.** Stored as a raw string. `load_latest_run` sorts
   by `started_at` lexicographically; mixed timestamp formats across entries produce undefined
   sort order.

6. **Cache key collision via unsanitized function names.** Function names containing `__`
   (including `__init__`) produce cache keys with ambiguous delimiters. `file_path="a"`,
   `function_name="b__c"` and `file_path="a__b"`, `function_name="c"` produce identical keys.

7. **Most constrained config fields not validated when loaded from pyproject.toml.**
   `min_concurrency`, `max_concurrency`, `max_retries`, `base_backoff_seconds`, and
   `request_timeout_seconds` constraints are only enforced at direct construction time. Invalid
   values in `pyproject.toml` are silently accepted.

8. **`list_cache_entries` is not filtered by filename pattern.** Any `.json` file in the cache
   root directory is attempted to be deserialized. Non-entry files silently fail and are
   skipped, but the cache directory is not treated as private.
