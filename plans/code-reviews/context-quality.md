# Code Review: Context Quality (agent-a28bdd9d)

## Summary

The scope.py changes are technically solid and the new test suite for scope functions is comprehensive. However the branch carries a **new critical blocker not in the wave2 findings**: it was developed against an old main snapshot predating the async pipeline merge, and merging it as-is would silently delete the entire async generation architecture (392 deleted lines from pipeline.py, async config fields, 655+ lines of async tests, two plan files, and tqdm/pytest-asyncio dependencies). The fix is a targeted cherry-pick or rebase — the actual feature lives entirely in scope.py and test_scope.py additions.

Of the six known issues from the wave2 review: C3 is resolved, H2 is not applicable to this branch, and H1/H4/M3/M4 remain present.

---

## Known Issues Status

- **C3 (submodule pointer):** RESOLVED — committed pointer is `0431bc7` (local patched commit with decorator support and all 7 local patches). Working tree shows `+56fc6a7` in `submodule status` (stale checkout) but the committed tree entry is correct and would merge cleanly.

- **H1 (regex import filter):** PRESENT — `scope.py:104`: `func_names = set(re.findall(r"\b(\w+)\b", function_source))` applies a regex to raw function source text. String literals and comments in the function body contribute false word matches. Example: `def f(): return "using os"` → `import os` incorrectly included because `"os"` appears in the string. Import-name extraction (`_extract_imported_names`) correctly uses libcst, but the *matching side* (what names exist in the function) still uses raw-text regex.

- **H2 (regex branch count):** NOT APPLICABLE to this branch — no branch counting code exists anywhere in the diff. The listing in PICK_UP_HERE.md appears to be a forward-looking note about a merge conflict that will arise when combining this branch with `agent-a225536b` (which adds branch counting in scope.py).

- **H4 (target method duplicate):** PRESENT — `_build_class_context` (scope.py:190–196) iterates all `FunctionDef` nodes in the class body and adds each signature via `_extract_signature`. The target method is never excluded. When the LLM receives a class method context, it sees the method signature stub (`def foo(self): ...`) in the class block AND the full function source separately — the same function twice. Fix requires passing the target function name into `_build_class_context` and skipping it in the signature loop.

- **M3 (O(n×m) recomputation):** PRESENT — `_extract_functions` (scope.py:71–98): for each method in a class, `_build_module_context(module, func_source)` rescans the entire module body and `_build_class_context(module, stmt, module_context)` reiterates the class body. A class with m methods in a file with n module-level statements costs O(n×m) import/constant scanning plus O(m²) for class context (since class context generation is O(m) and called m times). For files with large classes this is noticeable; for a 50-method class in a 200-line module the import scan alone is 10,000 iterations per file.

- **M4 (wildcard imports):** PRESENT, intentional — `_extract_imported_names` returns `set()` for `from x import *` because `node.names` is `cst.ImportStar`, not a list. `test_star_import_returns_empty` explicitly validates this with the docstring "from x import * -> can't determine names statically." The conservative approach (always include wildcard imports) recommended in the wave2 review was not implemented. This is a known gap: code using wildcard imports will receive empty context for those modules.

---

## New Issues Found

### BLOCKER

**C4 — Branch regresses the entire async pipeline**

The branch diverged from main at `1fed3b9`, which is **before** the entire async pipeline was merged. Main has since received 20+ commits adding the async architecture. The branch's pipeline.py is the pre-async version and deletes (relative to current main):

From `pipeline.py` (392 lines removed, 91 added):
- `ErrorAction` enum (`RETRY` / `SKIP` / `STOP`)
- `classify_error()` — API error classification (auth, rate limit with quota keywords, server errors, connection errors)
- `TrackedSemaphore` — concurrency tracking with in-flight counter
- `_sigint_handler()` — graceful cancellation on SIGINT
- `_compute_concurrency()` — dynamic concurrency formula
- `_compute_backoff()` — exponential retry backoff
- `_call_llm_async()` — async LLM API call with retry/cancel
- `_call_llm_and_validate_async()` — async validation wrapper
- `_generate_mutations_async()` — async parallel generation orchestrator with tqdm

From `config.py` (23 lines removed):
- `min_concurrency`, `max_concurrency` fields and validation
- `max_retries`, `base_backoff_seconds`, `request_timeout_seconds` fields and validation
- TOML loading for all five fields

From `tests/test_pipeline.py` (655 lines removed):
- `TestErrorClassifier`, `TestTrackedSemaphore`, `TestSigintHandler`, `TestComputeConcurrency`, `TestCallLlmAndValidateAsync`, `TestComputeBackoff`, `TestCallLlmAsync`, `TestGenerateMutationsAsync`

From `tests/conftest.py`:
- `make_async_mock_client()` helper

From `pyproject.toml`:
- `tqdm>=4.66.0` dependency
- `pytest-asyncio>=0.24.0` dev dependency
- `asyncio_mode = "auto"` pytest config

From `plans/`:
- `plans/llm/audit-verbose-mode.md` (715-line implementation plan)
- `plans/llm/prompt-caching-strategy.md` (503-line plan)

The branch's own tests all pass (441 passed) because they test only the synchronous pipeline. The deleted async tests no longer exist in the worktree, so no failures surface.

**Fix:** Do not merge pipeline.py, config.py, conftest.py, pyproject.toml, or the deleted plan files from this branch. The feature's real contribution is in scope.py and test_scope.py only. Cherry-pick or rebase to extract those changes onto current main.

Evidence: `git -C .claude/worktrees/agent-a28bdd9d diff main..HEAD -- mutmut-llm/src/mutmut_llm/pipeline.py` shows `-392 +91`; `grep -E "^class|^async def|^def" pipeline.py` on main shows 13 functions/classes vs 4 in the branch.

### SUGGESTION

**S1 — `break` after first item drops subsequent statements on compound lines**

`_build_module_context` (scope.py:109–119) breaks out of the inner `for item in stmt.body` loop after the FIRST item regardless of whether it matched:

```python
for item in stmt.body:
    if isinstance(item, (cst.Import, cst.ImportFrom)):
        ...
        break  # unconditional — even if the import didn't match
    elif isinstance(item, (cst.Assign, cst.AnnAssign)):
        ...
        break  # unconditional
```

For `import os; import sys` (a single `SimpleStatementLine` with two `Import` nodes in `.body`), only `import os` is evaluated; `import sys` is never checked. If the function uses `sys` but not `os`, the import is silently excluded from context.

In practice, multi-statement lines are uncommon (PEP 8 discourages them), but the behavior is surprising. The fix is trivial: remove the second `break` so the loop continues after a non-matching import. Or, since each module-level simple statement is almost always a single statement, document this as a known limitation.

---

## Import Filtering Correctness

The core import-name extraction (what names an import binds) is correct and uses libcst throughout:

- `from pathlib import Path` → `{"Path"}` ✓
- `import numpy as np` → `{"np"}` ✓  
- `from os.path import join, exists` → `{"join", "exists"}` ✓
- `import os.path` → `{"os"}` (Python binds the top-level name) ✓
- `from x import a.b` → `{"b"}` (rightmost segment) ✓

The weakness is on the matching side: which names *the function uses* is determined by `re.findall(r"\b(\w+)\b", function_source)`. This produces false positives for any import name that appears as a word in the function's string literals, docstrings, or comments. For example:

```python
def f():
    """Use os.path for path manipulation."""  # "os" matches here
    return 42
```

would include `import os` in context even though it is never actually referenced. The fix (H1) is to replace the regex with a libcst `Name` node visitor that only collects identifiers from actual AST nodes.

---

## Test Coverage Assessment

**scope.py:** Excellent — 35 new test methods covering `_build_module_context`, `_extract_imported_names`, `_extract_assign_targets`, `_extract_signature`, `_build_class_context`, and integration tests in `TestExtractFunctions`. The test for star imports explicitly documents the empty-set behavior.

**Pipeline regression coverage gap:** The deletion of `TestErrorClassifier`, `TestTrackedSemaphore`, `TestSigintHandler`, `TestComputeConcurrency`, `TestCallLlmAndValidateAsync`, `TestComputeBackoff`, `TestCallLlmAsync`, and `TestGenerateMutationsAsync` leaves the async pipeline entirely uncovered if this branch were merged as-is.

---

## Recommendation

**DO NOT MERGE as-is.**

The feature itself (scope.py context improvements) is valuable and well-tested. But the branch must be cherry-picked onto current main rather than merged directly. Only these files contain the intentional feature changes:

- `mutmut-llm/src/mutmut_llm/scope.py` — the full rewrite of `_build_module_context` + 5 new helper functions
- `mutmut-llm/tests/test_scope.py` — the new test suite (+420 lines)

All other diffs (pipeline.py, config.py, conftest.py, pyproject.toml, PROGRESS.md, deleted plan files) are regressions from the stale base and must be discarded.

After rebasing, the remaining open issues are H1 (regex on function source), H4 (target method in class context), M3 (O(n×m) recomputation), and M4 (wildcard imports excluded). Of these, H1 and H4 are the highest priority to fix before merge.
