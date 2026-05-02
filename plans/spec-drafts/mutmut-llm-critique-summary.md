# mutmut-llm Spec — Adversarial Critique Summary

**Critique file:** `mutmut-llm/SPEC.md.critique`
**Draft reviewed:** `mutmut-llm/SPEC.md.draft`
**Implementation files verified:** `pipeline.py`, `cache.py`, `config.py`,
`validation.py`, `_io.py`, `pricing.py`, `storage.py`

---

## Critical Issues (must fix before spec is trustworthy)

| ID | Location in spec | Issue |
|----|-----------------|-------|
| CFG-1 | Configuration Contract | **BLOCKER — spec factually wrong.** `__post_init__` only validates defaults; `load_config` sets fields after init without re-validation. `min_concurrency`, `max_concurrency`, `max_retries`, `base_backoff_seconds`, `request_timeout_seconds` are all unvalidated when set from pyproject.toml. `temperature` is validated in `load_config` not `__post_init__`. |
| CAN-1 | Cancellation Contract | **Spec wrong.** "In-flight tasks are awaited before return" is FALSE for the KeyboardInterrupt (second Ctrl-C) path. Tasks are cancelled but never awaited; function returns immediately. |
| CC-1 | Cache key scheme | **Spec wrong.** Uniqueness claim relies on model-name sanitization, but `function_name` is never sanitized. Names with `__` (e.g., `__init__`) produce ambiguous keys. Collision example provided. |
| CONTRA-1 | Retry/Backoff Contract | **Undocumented dual code paths.** Sync `_call_llm_and_validate` swallows ALL exceptions silently (no retry, no STOP propagation). Async path classifies and retries. Spec documents only the async contract. |
| CON-1 | Concurrency Contract | **Spec documents unreachable behavior.** `n_targets=0` case never occurs — the function returns 0 before computing concurrency when `work_items` is empty. |

---

## High-Severity Issues

| ID | Issue |
|----|-------|
| CFG-2 | `api_key` is environment-only; pyproject.toml cannot set it. Priority list ("env > pyproject > defaults") is misleading. |
| CT-1 | Cost silently zero when API response has no `usage` field. No warning emitted. Permanent cost undercount in cache entries. |
| CT-2 | Sonnet fallback pricing for unknown models can severely underestimate Opus-class costs. |
| VP-1 | "Valid syntax" means libcst-parseable, not CPython-parseable. These can differ. |
| VP-2 | Pragma guard uses LINE POSITION. Inserting ANY line before a pragma causes rejection. "Corresponding" is ambiguous — must say "same zero-based index." |
| VP-3 | Import guard counts imports at ALL nesting levels, not just top-level. |
| MI-1 | Class method `function_name` format in cache (`"method"` vs `"ClassName.method"`) unspecified. Mismatch between scope and identification logic causes silent failure. |
| CON-2 | Spec conflates task EXECUTION order (non-deterministic) with result AWAITING order (file_path sorted). |
| CC-5 | File locking uses `fcntl.flock` (POSIX only). Windows not supported. Not disclosed. |

---

## Medium-Severity Issues

| ID | Issue |
|----|-------|
| IL-1 | Caching Contract describes mechanism (temp+rename, advisory lock) not behavior (atomic writes, no partial reads). |
| IL-2 | Cache key sanitization rules are filename-encoding detail, not behavioral contract. |
| CC-2 | `read_cache_entry(model=None)` with multiple models returns alphabetically first by filename — indeterminate. |
| CC-3 | `clear_cache()` doesn't remove run history (stored in `runs/` subdirectory). |
| CT-3 | Zero-cost entries from API failures permanently understate cumulative totals. |
| CON-3 | Spec doesn't explicitly state inter-entry isolation guarantee for concurrent writers. |
| CAN-2 | Stale `.lock` files accumulate after unclean termination. Not documented. |
| CAN-3 | Second-SIGINT → KeyboardInterrupt path is asyncio-version and platform-dependent. Presented as guarantee. |
| CFG-3 | `max_mutations_per_function = 0` behavior observable (empty mutations, cache entry written) but left as open question. |
| MI-2 | `generate` CLI defaults to scanning `["src"]` when no paths configured. Undocumented. |
| MI-3 | `budget = 0` behavior (immediate return, 0 API calls) not specified. |

---

## Already Caught by critique1 (no re-escalation needed)

- Implementation details in prompt structure (cache_control block)
- Budget allocation spec vs. implementation gap (`_allocate_budget`)
- LLM ordering assumption framed as MUST vs. open question
- `parse_llm_response` contract missing
- `dry_run` no-API-key invariant missing

---

## Reviser Guidance

The reviser for the final SPEC.md should:

1. **Correct CFG-1**: Replace "`__post_init__` MUST raise ValueError" with accurate
   description of which constraints are enforced in `__post_init__` (called at direct
   construction), which are in `load_config` (`temperature`, `cache_ttl`), and which are
   NOT enforced at all when loading from pyproject.toml.

2. **Correct CAN-1**: Scope the "tasks awaited" invariant to the first-SIGINT path.
   Document the KeyboardInterrupt (forced exit) path as best-effort: "cancellation
   requested but not awaited."

3. **Correct CC-1**: Remove the "unambiguous delimiter" claim or note that function names
   with `__` in them produce non-unique keys (known limitation).

4. **Correct CON-1**: Remove the `n_targets=0` bullet or note it as "returns early before
   computing concurrency."

5. **Add CFG-2**: State explicitly that `api_key` is env-only.

6. **Add CT-1/CT-2 to Known Limitations**: Cost can be zero (missing usage) or
   undercounted (unknown model uses Sonnet fallback).

7. **Tighten VP-1/VP-2**: Specify libcst-parseable; clarify pragma position semantics.
