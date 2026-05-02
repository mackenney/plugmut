# Code Review: Mutation Source Tracking (agent-afcf9355)

## Summary

Branch adds a `source` field to `Mutation` objects, threads it through the pipeline, and persists it in `.meta` files. Core feature is implemented correctly and all 12 source-tracking tests pass in the worktree. However, the branch was cut before the async parallel pipeline (`agent-aaf84c48`) was merged to main — merging it now would **delete the entire async pipeline**, making this the most critical issue, far outweighing C2.

**Overall diff**: 14 files, +242/-2529. Net deletion is the signal: this branch removes far more than it adds.

---

## Known Issues Status

### C2 — `mutate_file_contents` returns 3-tuple (RESOLVED in branch, PRESENT as merge risk)

**Status:** Resolved within the worktree. All callers updated:
- `mutmut/src/mutmut/__main__.py:365`: `result, mutant_names, source_by_name = mutate_file_contents(...)` ✅
- All test files in `mutmut/tests/` unpacking `_, _, _` ✅

**But the public API IS broken** relative to current main. Every external caller using `result, names = mutate_file_contents(...)` will get `ValueError: too many values to unpack`. `mutate_file_contents` is a module-level public function — no import guard, no `__all__` restriction. The conflict-resolution guide acknowledges the type change. No deprecation wrapper, no named return type.

Specific 2-tuple unpackers in main that will break on merge:
- `mutmut/src/mutmut/__main__.py:362`: `result, mutant_names = mutate_file_contents(...)` (current main)
- `mutmut/tests/test_mutation.py:29, 584, 881, 904, 930` (current main tests)
- `mutmut/tests/test_mutation regression.py:86`
- `mutmut/tests/test_hookspecs.py:133, 145, 224`
- `mutmut/tests/test_whole_function_mutation.py:195`

The branch's submodule (commit 4891357) has already updated all of these. The issue is purely about external consumers.

### M5 — `__mutmut_source__` attribute stamping (PRESENT, no guard)

`_tag_operators` in `plugin.py:42` does `func.__mutmut_source__ = source` with no `try/except`. For this package (pure Python operators), this is safe. For third-party plugins using `functools.partial` or C-extension callables, this raises `AttributeError` at plugin registration time, silently breaking the entire plugin. No guard exists.

Reading side is safe: `getattr(operator, "__mutmut_source__", "builtin")` at `file_mutation.py:231`.

### L3 — `.meta` backward compatibility (PARTIALLY ADDRESSED)

**New→Old direction (broken):** Old mutmut (`assert not meta` at end of `load()`) crashes when reading a new `.meta` file that contains `source_by_key`. The branch makes NO attempt to fix this. The conflict-resolution guide does not mention it.

**Old→New direction (handled):** New code uses `meta.pop("source_by_key", {})`, so old files load cleanly. Test `test_meta_backward_compat_no_source_by_key` covers this. ✅

**Verdict:** L3 is half-addressed. One direction is fine; the other is a breaking compatibility boundary.

---

## New Issues Found

### BLOCKER — Branch deletes the entire async parallel pipeline

**This is the most critical issue in this review.**

The branch was forked from commit `1fed3b9` (before async pipeline work). After the branch was cut, 7 commits of async work were merged to main:
- `_compute_concurrency()`, `_compute_backoff()`
- `ErrorAction`, `classify_error()` (error routing: STOP/RETRY/SKIP)
- `TrackedSemaphore` (async semaphore with active-count tracking)
- `_sigint_handler()` (SIGINT → graceful cancel)
- `_call_llm_and_validate_async()`
- `_call_llm_async()` (per-target with retry, backoff, cancellation)
- `_generate_mutations_async()` (full orchestrator wiring)

The branch's `mutmut-llm/src/mutmut_llm/pipeline.py` diff: **-392 lines / +91 lines**. Every one of these functions is deleted. The sync `_generate_mutations()` is restored in their place.

Associated deletions:
- `mutmut-llm/tests/test_pipeline.py`: 41 test methods deleted (TestErrorClassifier, TestTrackedSemaphore, TestSigintHandler, TestComputeConcurrency, TestCallLlmAndValidateAsync, TestCallLlmAsync, TestGenerateMutationsAsync)
- `mutmut-llm/tests/conftest.py`: `make_async_mock_client()` deleted
- `mutmut-llm/tests/test_config.py`: 14 test methods for concurrency/retry/backoff config deleted
- `mutmut-llm/pyproject.toml`: `tqdm`, `pytest-asyncio` dependencies removed; `asyncio_mode = "auto"` removed
- `mutmut-llm/src/mutmut_llm/config.py`: `min_concurrency`, `max_concurrency`, `max_retries`, `base_backoff_seconds`, `request_timeout_seconds` fields deleted; all `__post_init__` validation for these fields deleted

Additionally:
- `plans/llm/audit-verbose-mode.md` deleted (715-line plan file)
- `plans/llm/prompt-caching-strategy.md` deleted (503-line plan file)
- `.agent/tools.json` deleted

Merging this branch as-is **reverts the async parallel feature** that PICK_UP_HERE.md lists as already merged and "Clean."

**Required fix before merge:** Rebase onto current main (not the merge-base from `1fed3b9`). The source-tracking changes are confined to `mutmut/` submodule (core data structures + pipeline threading), `mutmut-extras/plugin.py` (+11 lines), and `mutmut-llm/plugin.py` (+2 lines). None of these conflict with the async pipeline changes. A rebase or cherry-pick of just the source-tracking commits would be clean.

### IMPORTANT — `source_by_key` not refreshed on file-unchanged path

`create_mutants_for_file()` in `__main__.py:309-318`: when `source_mtime < mutant_mtime` (file unchanged since last run), the function returns `FileMutationResult(unmodified=True)` without touching `SourceFileMutationData`. This means `source_by_key` is never backfilled for files that were first mutated by old mutmut (which wrote no `source_by_key`). On incremental re-runs, those files silently stay with empty attribution. The only way to get attribution for them is to delete the mutant file and re-run.

No test covers this path.

### IMPORTANT — `Mutation.source` is mutable despite being a data identity field

`@dataclass` without `frozen=True` at `file_mutation.py:86`. `mutation.source = "other"` succeeds at runtime. Source attribution is a property of how the mutation was generated — it is not meaningful to reassign it. Any code that accidentally overwrites `source` produces silently wrong per-operator reporting with no error. Minimum fix: add `frozen=True` to the dataclass. Blocker: `original_node` and `mutated_node` hold CST nodes, which may themselves be mutable; verify CST node hashability before freezing.

### SUGGESTION — `_tag_operators` mutates shared callables permanently

`func.__mutmut_source__ = source` in `_tag_operators` stamps the attribute on the function object itself — permanently for the process lifetime. Since operator functions are module-level objects, this is idempotent in production. In tests, if the same function is returned by two different `mutmut_register_operators` calls (e.g., one with patching), the second call overwrites the first's tag. The fix is to wrap with `functools.wraps` or use a side-channel registry `{id(func): source}`. Low priority for production but relevant for test isolation.

### SUGGESTION — `operator_llm.__mutmut_source__` set inside `mutmut_register_operators`

`mutmut-llm/plugin.py:120`: the attribute is stamped inside the hook implementation, meaning it is set every time pluggy invokes the hook. This is harmless (same value each time) but unusual — the attribute should be set once at module load or in `mutmut_configure`. Marking it inside the hook makes the attribution timing dependent on whether the plugin is enabled.

---

## Attribution Completeness

**mutmut-extras:** All 19 operators receive `source="mutmut-extras"` via `_tag_operators(all_ops, "mutmut-extras")`. Coverage: 100%.

**mutmut-llm:** `operator_llm` tagged with `"mutmut-llm"`. Coverage: 100% (1 operator).

**mutmut core (builtin):** All operators not tagged via plugins default to `source="builtin"` via `getattr(operator, "__mutmut_source__", "builtin")`. Default is applied at mutation-creation time, not at operator registration. Coverage: correct by design.

**Gap:** Operators from third-party plugins that don't tag their functions will be attributed as `"builtin"`, indistinguishable from core operators. There is no way to detect attribution absence. The spec delta critique (from the adversarial review chain) identifies this as the `"builtin"` semantic ambiguity issue.

---

## Test Coverage Assessment

**Source tracking tests (branch-local, all pass in worktree):**
- `test_source_tracking.py`: 12 tests covering `Mutation.source` default, custom, pipeline threading, `combine_mutations_to_source` 3-tuple, `mutate_file_contents` 3-tuple, hook integration, `.meta` roundtrip, backward compat
- `test_adversarial_source.py`: 20 tests covering edge cases (unicode, very long source, empty source, corrupted meta, class method mutations)

**Coverage gaps:**
- No test for `source_by_key` on file-unchanged re-run path
- No test for `_tag_operators` on non-Python callables (M5 path)
- No test for `frozen=True` enforcement (mutation would require dataclass change first)
- No test verifying `source_by_key` written in the `cst.ParserSyntaxError` exception path
- The `test_e2e_type_checking.py` failure in the worktree is a pre-existing environment issue (pyrefly excludes mutants directory under the worktree path), not introduced by this branch. Confirmed same failure on main.

---

## Recommendation

**Do not merge.** Three actions required in this order:

1. **Rebase onto current main.** The deletion of the async pipeline, plan files, and config fields is entirely due to the branch being cut from an old base. The source-tracking changes themselves don't touch any of the async infrastructure. A rebase should be clean for the `mutmut-llm/` and `mutmut-extras/` changes; only the submodule pointer needs manual resolution (take the source-tracking patch on top of the current patched commit).

2. **Fix C2 via NamedTuple or dataclass result.** Return a named result object from `mutate_file_contents` rather than a raw 3-tuple. This makes future additions backward-compatible. The conflict-resolution guide should be updated to reflect the chosen API shape.

3. **Add `frozen=True` to `Mutation` dataclass** (or document why it's deliberately mutable).

Once rebased and C2 is addressed, the actual source-tracking feature is small, well-tested, and conceptually sound.
