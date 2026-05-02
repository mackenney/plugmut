# Code Review: Adaptive Budget (agent-a225536b)

## Summary

**Branch commit:** `bfeccd4 Implement adaptive mutation budget based on function complexity`
**Files changed:** 13 files, +406/-2556 (net deletion due to async pipeline removal)
**Functional changes:** `scope.py`, `config.py`, `pipeline.py`, `test_scope.py`, `test_config.py`, `test_pipeline.py`
**Infrastructure changes:** `pyproject.toml` (removes `tqdm`, `pytest-asyncio`), plan files removed

---

## Known Issues Status

- **H2 (regex branch count): PRESENT — unfixed**
  `_branch_count` uses `re.compile(r"\b(if|elif|else|for|while|try|except|with)\b")` on raw source text.
  Confirmed: `_branch_count('def f():\n    """for all elements"""\n    return 1\n')` returns 1 (no real branches).
  `_branch_count('x = "if you need help"')` returns 1.
  No tests verify keywords-in-strings are excluded.

- **M1 (min > max silently misbehaves): PRESENT — unfixed**
  `load_config` with `min_mutations_per_function=10, max_mutations_per_function=3` creates a config
  with min=10, max=3 — no `ValueError` raised. `compute_mutation_budget` then clamps to
  `max(min_budget=10, ...) = 10`, then `min(max_budget=3, 10) = 3`, silently returning 3.
  No test covers this case.

- **M6 (default max doubled): PRESENT — unfixed**
  `LLMConfig.max_mutations_per_function` default changed from 5 to 10 with no migration note,
  no deprecation warning, no changelog entry. Existing users upgrading silently double API spend.

---

## New Issues Found

### BLOCKER

**`pipeline.py:1-350` — Branch reverts the already-merged async parallel pipeline**

The branch was forked at commit `1fed3b9` (Merge feat/bytecode-tce-phase2), before commit
`ddb5c18` (Merge feat/async-wire-up) landed on main. The branch's single implementation commit
then replaces `_generate_mutations_async` + `asyncio.run(...)` with a new synchronous
`_generate_mutations`. This removes from main:
- `ErrorAction` enum and `classify_error` function (error triage: RETRY/SKIP/STOP)
- `TrackedSemaphore` (concurrent slot tracking)
- `_sigint_handler` (SIGINT → graceful cancel)
- `_compute_concurrency` (dynamic concurrency scaling)
- `_generate_mutations_async` (the entire parallel async orchestrator)
- `tqdm` progress bar
- `pytest-asyncio` dev dependency
- `min_concurrency`, `max_concurrency`, `max_retries`, `base_backoff_seconds`,
  `request_timeout_seconds` config fields (and their validation)
- Retry/backoff logic

The submodule pointer also regresses: branch points to `0431bc7`, main points to `22e26fb`
(set by the async wire-up commit). Merging as-is rolls back the submodule.

**The branch must be rebased onto current main before any adaptive budget work can be merged.**
The budget feature (scope.py changes) is purely additive and can be cleanly rebased; the
pipeline.py changes need to be reworked to add `min_per_function` passthrough on top of the
async version rather than replacing it.

---

**`pipeline.py:142` — `api_calls` incremented unconditionally on API failure**

`_call_llm_and_validate` catches all exceptions internally (via `except Exception as e:`) and
returns `GenerationResult(mutations=[])` with a `warnings.warn`. The caller in `_generate_mutations`
then unconditionally does `api_calls += 1`. Result: if the API key is invalid or the service
returns errors, all budget slots are consumed without generating any mutations. No STOP condition
exists (the old `classify_error` STOP path for `AuthenticationError` / `PermissionDeniedError` is
gone). The run appears to "succeed" with 0 mutations and the full budget "spent."

Fix: only increment `api_calls` when `result.mutations` is non-empty or the call genuinely
reached the API (check `result.input_tokens > 0`). Restore STOP condition for fatal auth errors.

---

### IMPORTANT

**`scope.py:131-148` — Scale-down ignores `min_per_function`; goes to floor=1**

When `total_raw > total_budget`, proportional scaling uses `max(1, int(v * scale))` — the floor
is hardcoded at 1, not at `min_per_function`. With 20 complex functions and budget=5:
```
alloc values: [1, 1, 1, ...]  # all at 1, below min_per_function=2
```
Confirmed empirically. The `min_per_function` contract is violated under budget pressure.

Fix: Use `max(min_per_function, int(v * scale))` in the scale-down path, or document explicitly
that the minimum guarantee does not apply when budget is insufficient.

---

**`scope.py:145-147` — Budget underuse when total_raw ≤ total_budget**

When all raw budgets sum to less than total_budget, the function returns the raw budgets as-is,
leaving capacity unused. Example: 3 simple functions each compute to budget=2 (total=6) with
budget=100 → only 6 API slots allocated, 94 wasted. The remaining capacity is never redistributed
to allow more mutations from complex functions.

Confirmed: `_allocate_budget([3 simple targets], 100, 10, 2)` → sum=6, budget=100.

Fix: When `total_raw < total_budget`, proportionally redistribute surplus using complexity weights
(or at minimum document that unused capacity is intentional).

---

**`config.py:76` — `env` parameter type narrowed from `Mapping` to `dict`**

`load_config`'s `env` parameter was `Mapping[str, str]` (accepting `os.environ`, `MappingProxy`,
any immutable mapping) and is now `dict[str, str]`. Callers passing `os.environ` directly get a
mypy/type-check failure. This is a breaking type change with no deprecation path.

Fix: Restore `Mapping[str, str]` (re-add `from collections.abc import Mapping`).

---

**`test_scope.py` — H2 not tested; M1 not tested**

No test verifies that `_branch_count` ignores keywords in string literals, comments, or
docstrings. No test verifies that `load_config` raises `ValueError` (or any error) when
`min_mutations_per_function > max_mutations_per_function`. Both gaps mean the unfixed bugs could
pass CI indefinitely.

---

**`scope.py:155` / `pipeline.py:137` — Budget sum can undershoot total_budget after rounding**

Confirmed: `_allocate_budget([3 medium targets], 7, 5, 2)` → sum=6, budget=7 (1 slot lost to
floor). The trim loop only removes excess; nothing adds back when rounding creates a deficit.
This is minor but means the stated budget is not fully utilized in every case.

---

### SUGGESTION

**`scope.py:160` — `::` key format undocumented; collision impossible but fragile**

Keys are `f"{file_path}::{function_name}"`. `::` cannot appear in Python function names
(illegal identifier character) or class-qualified names (`ClassName.method_name` uses `.`).
The format is safe in practice but undocumented. A comment noting the separator choice and its
collision-safety assumption would prevent future regressions.

---

**`scope.py:137` — `else` counted as a branch keyword**

`else` on an `if/else` pair is counted as a separate branch, making every `if/else` count as 2
(not 1). This overcounts relative to standard cyclomatic complexity (McCabe), where `if/else`
counts as 1 branch. The spec draft identified this; confirming it is present in code and
untested.

---

## Test Coverage Assessment

**Covered:**
- `_branch_count`: basic keyword detection (if/elif/else/for/while/try/except/with) — 5 cases
- `compute_mutation_budget`: min/max clamping, comment exclusion, blank line exclusion, branch bonus
- `_allocate_budget`: empty, zero budget, simple vs complex, total cap, key collision (same
  function name different files), min_per_function passthrough, scale order preservation
- `load_config`: new `min_mutations_per_function` field read from TOML

**Missing:**
- `_branch_count` false positives: keywords in string literals, comments, docstrings (H2)
- `_allocate_budget` scale-down floor relative to `min_per_function`
- `load_config` validation: `min > max` raises error (M1)
- `_generate_mutations` error handling: failed API call does not consume budget slot
- `_generate_mutations` total_budget enforcement when all calls fail

---

## Recommendation

**MAJOR-REWORK**

The adaptive budget algorithm in `scope.py` is sound and the tests are well-structured. However,
the branch cannot be merged as-is because it reverts the async parallel pipeline already in main.

Required steps before merge:
1. **Rebase onto current main** — conflicts will be in `pipeline.py` (async vs sync)
2. **Preserve async pipeline** — pass `min_per_function` through to `resolve_scope_deep` and
   `_allocate_budget` inside the existing async orchestrator, not by replacing it
3. **Fix H2** — replace `_branch_count` regex with `ast.parse` AST node counting
4. **Fix M1** — add `min > max` validation in `load_config` (or `__post_init__`)
5. **Address M6** — revert default to 5 or add upgrade notice
6. **Fix `api_calls` increment on failure**
7. **Restore `Mapping` type for `env` param**
8. **Add tests** for H2 false positives and M1 validation
