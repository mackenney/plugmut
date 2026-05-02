# Code Review: Dynamic Exclusion List (agent-a9c42fae)

## Summary

Single-commit feature (f56b75b) on top of a worktree base that predates 18+ async pipeline commits. The prompts.py work is well-structured and tested. The pipeline.py changes are minimal and correct *for the sync path only*, but the branch diverged from main before the async pipeline was merged, making the pipeline integration a no-op on current main. Two of the three known issues are addressed; one remains.

**Files actually changed by this commit (HEAD~1..HEAD):**
- `mutmut-llm/src/mutmut_llm/prompts.py` — adds `build_exclusion_list`, `build_system_prompt`, `_describe_operator`, `_get_registered_operators`, `SYSTEM_PROMPT_TEMPLATE`, `_HARDCODED_EXCLUSIONS`; updates `build_system_with_context` to accept `system_prompt` override
- `mutmut-llm/src/mutmut_llm/pipeline.py` — imports `build_system_prompt`, calls it once at top of `_generate_mutations`, passes result to `_call_llm_and_validate`
- `mutmut-llm/tests/test_prompts.py` — 183 lines of new tests, all passing (67 total)
- `mutmut-extras/src/mutmut_extras/operators/ternary.py` — 1-line docstring addition

Note: the `main..HEAD` diff looks massive (−2543 lines) because the worktree base predates all async pipeline merges. The actual branch contribution is only ~330 net lines.

---

## Known Issues Status

- **H3 (import-time prompt): PARTIALLY RESOLVED**
  The pipeline now calls `build_system_prompt()` at runtime (`pipeline.py:94`), which is correct *for the sync path*. However, `SYSTEM_PROMPT = build_system_prompt()` (prompts.py line 153) still executes at module import time as a "backward-compatible constant." `build_system_with_context()` falls back to this stale constant when called without the `system_prompt=` kwarg. Any caller that doesn't pass `system_prompt=` explicitly (including the async path on current main) gets the import-time snapshot.

- **M2 (broad exception): PRESENT**
  `_get_registered_operators` line 135: `except Exception:` is unchanged. Catches `ImportError`, `AttributeError`, `TypeError`, and any runtime error from any plugin's `mutmut_register_operators`. Genuine plugin bugs are silently swallowed and the log line is `DEBUG`, so they're invisible in normal operation. The fix (catch `ImportError` only for the import step, re-raise plugin errors) was not applied.

- **M7 (format injection): RESOLVED**
  The original concern was about operator descriptions being concatenated into the template before `.format()`. This implementation correctly uses a single `{exclusion_list}` placeholder in `SYSTEM_PROMPT_TEMPLATE` and substitutes via `SYSTEM_PROMPT_TEMPLATE.format(exclusion_list=exclusion_list)`. Python's `str.format()` makes a single pass over the template—`{...}` inside a substituted value is not re-processed. Test `test_template_braces_in_examples_preserved` confirms the `{{...}}` → `{...}` escaping works correctly.

---

## New Issues Found

### BLOCKER

**Feature is a no-op on current main's async execution path**
- Location: `mutmut-llm/src/mutmut_llm/pipeline.py`
- The branch adds `build_system_prompt()` to `_generate_mutations()` and `_call_llm_and_validate()`. On current main, `_generate_mutations()` is a two-line sync wrapper (`asyncio.run(_generate_mutations_async(...))`). The actual generation work runs in `_generate_mutations_async` → `_call_llm_and_validate_async`. Neither of these functions was modified by this branch. `_call_llm_and_validate_async` (main `pipeline.py:277`) still calls `build_system_with_context(context=target.context, ttl=config.cache_ttl)` with no `system_prompt` argument, using the stale import-time `SYSTEM_PROMPT` constant.
- Evidence: `git log --oneline 1fed3b9..main` shows 18+ async pipeline commits merged after the worktree's branch point. `grep "build_system_prompt" mutmut-llm/src/mutmut_llm/pipeline.py` returns no results on current main.
- Impact: After merge conflict resolution, the feature must also be applied to `_call_llm_and_validate_async` (pass `system_prompt` parameter) and `_generate_mutations_async` (call `build_system_prompt()` once before the target loop). Without this, the dynamic exclusion list is built and set up in the sync path but the async path—which is the actual execution path—silently ignores it.

**Inevitable pipeline.py merge conflict**
- Location: `mutmut-llm/src/mutmut_llm/pipeline.py`
- The branch base commit is `1fed3b9`. Current main has 18+ commits rewriting `pipeline.py` with async infrastructure (`TrackedSemaphore`, `ErrorAction`, `classify_error`, `_compute_concurrency`, `_sigint_handler`, `_generate_mutations_async`, `_call_llm_and_validate_async`, tqdm integration). The branch modifies `_generate_mutations` and `_call_llm_and_validate`, both of which have also changed on main. This is not a clean merge—it requires manual conflict resolution.
- Resolution path: take main's async pipeline as the base; apply the three changes from the branch (`build_system_prompt()` import, runtime call before generation loop, `system_prompt=` parameter on both `_call_llm_and_validate` and `_call_llm_and_validate_async`).

### IMPORTANT

**`SYSTEM_PROMPT` module-level constant survives (H3 incomplete)**
- Location: `mutmut-llm/src/mutmut_llm/prompts.py:151–153`
- The comment says "Backward-compatible constant: built once at import time with whatever operators are registered." But this is exactly what H3 identified as the bug. `build_system_with_context()` uses it as default. Any test or production code calling `build_system_with_context()` without explicitly passing `system_prompt=build_system_prompt()` gets the import-time snapshot—possibly with no plugins registered if called early in the process lifecycle.
- The fix: remove `SYSTEM_PROMPT` as a module-level side effect. Callers that need a default should call `build_system_prompt()` themselves (which is cheap; it just queries the plugin manager).

**`except Exception` in `_get_registered_operators` swallows plugin bugs (M2)**
- Location: `mutmut-llm/src/mutmut_llm/prompts.py:130–137`
- The `try` block covers both the `from mutmut.plugin_manager import get_plugin_manager` import and the `pm.hook.mutmut_register_operators()` call. A `TypeError` in any plugin's registered operator (wrong return type, wrong signature), an `AttributeError` on a broken plugin object, or any other runtime error logs at `DEBUG` and silently falls back to hardcoded exclusions. Users see no indication the plugin contributed nothing.
- Fix: wrap only the import in `except ImportError`; let plugin-level errors propagate (or at least log at `WARNING` with a user-visible message).

### SUGGESTION

**`_describe_operator` does not guard against property-raising `__doc__`**
- Location: `mutmut-llm/src/mutmut_llm/prompts.py:87`
- `getattr(fn, "__doc__", None)` is safe for normal callables but if `__doc__` is a descriptor that raises (e.g., a C extension with a broken descriptor), the default is bypassed. Wrapping in `try/except` is low-cost insurance.

**`test_system_prompt_text_used_by_default` is environment-sensitive**
- Location: `mutmut-llm/tests/test_prompts.py`, `TestBuildSystemWithContext`
- The test asserts `blocks[0]["text"] == SYSTEM_PROMPT`. `SYSTEM_PROMPT` is the import-time constant, which differs based on what plugins are installed at test time. In a clean venv this passes; in an environment where `mutmut-extras` is installed (the normal workspace state), `SYSTEM_PROMPT` contains the dynamic 19-operator list. The test passes either way because both sides use the same import-time value. But it doesn't actually test that `build_system_with_context` falls back correctly—it just confirms it uses whatever was built at import time. A more robust test would pass `system_prompt=None` explicitly and assert something stable about the content (e.g., `"mutation testing expert" in blocks[0]["text"]`).

**No coverage for the case where a plugin registers zero operators**
- `build_exclusion_list` with `operator_lists=[[]]` (one plugin returning an empty list) hits `not operator_lists` False (list is non-empty), iterates over the empty inner list, and reaches `return "\n".join(lines) if lines else _HARDCODED_EXCLUSIONS`. This correctly returns `_HARDCODED_EXCLUSIONS`. Not a bug, but the path is not tested. `test_empty_operator_lists_returns_hardcoded` tests `operator_lists=[]`, not `[[]]`.

---

## Test Coverage Assessment

**Strong coverage of the new prompts.py surface:**
- `_describe_operator`: 5 tests covering docstring, multiline, no-doc, empty-doc, whitespace-doc paths
- `build_exclusion_list`: 8 tests covering empty, single operator, multiple, dedup, mixed
- `build_system_prompt`: 4 tests including brace-escaping and template validation
- `_get_registered_operators`: 2 tests for ImportError fallback and happy path

**Missing coverage:**
- No test for `build_system_prompt()` called at runtime in `_generate_mutations` (pipeline-level integration test)
- No test for `operator_lists=[[]]` (empty-plugin-returns-empty-list edge case)
- No test for `_describe_operator` with a property-raising `__doc__`
- No test confirming the async path would use the dynamic prompt (impossible to write against old worktree; important to add post-merge)

All 67 tests pass in the worktree (`uv run --package mutmut-llm pytest mutmut-llm/tests/ -v` → 426 passed, 21 skipped).

---

## Recommendation

**Block merge until the async path is addressed.** The prompts.py work is clean and well-tested. The pipeline integration is correct for the sync path but that path is no longer the execution path on current main. Merging as-is produces a feature that builds the dynamic exclusion list, calls `build_system_prompt()`, and then silently discards the result because the async path ignores it.

Required before merge:
1. **Rebase onto current main** (or cherry-pick prompts.py changes and write new pipeline integration against the async structure)
2. **Pass `system_prompt` through the async path**: add `system_prompt` parameter to `_call_llm_and_validate_async`; call `build_system_prompt()` once in `_generate_mutations_async` before the target loop
3. **Narrow `except Exception` to `except ImportError`** in `_get_registered_operators` (M2)
4. **Remove module-level `SYSTEM_PROMPT = build_system_prompt()`** or demote it to a lazy-initialized helper (H3 incomplete)
