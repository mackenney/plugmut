# P1: Code Review Findings — mutmut-llm

Consolidated from three independent reviews (R1=Architecture, R2=Implementation, R3=Testing/Security).

---

## Deduplicated findings

| ID | Severity | Issue | Reviewers | Verified |
|----|----------|-------|-----------|----------|
| F1 | **MAJOR** | `_llm_mutation_count_by_function()` uses bare names from cache (`Foo.bar`), but `_extract_function_name()` returns bare (`bar`). Class method LLM mutations never matched. | R2 | Yes — `_extract_function_name("xǁFooǁbar__mutmut_1")` returns `"bar"`, but cache stores `function_name="Foo.bar"`. Key mismatch. |
| F2 | **MAJOR** | `mutmut_mutations_created` tail-slicing assumes LLM operator runs last. If another FunctionDef operator registers after LLM, the wrong mutants get tagged. No source-based matching. | R1 | Yes — fragile, order-dependent. Works today with current operator set. |
| F3 | **MAJOR** | `_allocate_budget` can allocate `per_function * len(targets)` > `total_budget`. Example: 3 functions, budget=5, max_per_function=5 → per_function=1, total=3, fine. But 2 functions, budget=5, max_per_function=5 → per_function=2, total=4, fine. Actually: `min(5, max(1, 5//2))=2`, total=4 < 5. Re-check: 3 functions budget=2 max_per=5 → `min(5, max(1, 0))=1`, total=3 > 2. Yes, over-allocates when `total_budget < len(targets)`. | R1, R2, R3 | Yes — edge case when budget < function count. Dry-run output becomes misleading. |
| F4 | **MAJOR** | `_allocate_budget` and `budget_per_target` keyed by bare `function_name` — not unique across files. Two files with `def helper()` collide. | R1 | Yes — `ScopeTarget.function_name` is just `"helper"` for top-level, `"Foo.helper"` for methods. Cross-file collisions real for common names. |
| F5 | **MINOR** | `_llm_mutant_names` (module global) accumulates across `mutmut_mutations_created` calls per file. Never reset between runs within a single process. | R1, R2, R3 | Overstated — mutmut runs once per process invocation. Module globals reset on process restart. The autouse fixture in tests already handles this. Not a production bug, but `mutmut_configure` should reset it for hygiene. |
| F6 | **MINOR** | `operators.py` `_cache_index` never invalidated. If `generate` then `run` in same process, operator uses stale index. | R2, R3 | Overstated — `generate` and `run` are separate CLI invocations (separate processes). Reset function exists but only tests call it. Add reset in `mutmut_configure` for safety. |
| F7 | **MINOR** | `list_cache_entries()` default `base_dir=Path(".")` — CWD-dependent. `operators.py` calls it without `base_dir`. | R1, R2 | Technically true, but mutmut always runs from project root. Low risk in practice. Fix is trivial (pass base_dir through). |
| F8 | **MINOR** | `save_run()` in `plugin.py:mutmut_post_run` calls `save_run(_current_run)` with no `cache_root`. Writes to CWD. Consistent with F7. | R1 | Same as F7 — CWD is project root during mutmut runs. |
| F9 | **MINOR** | `_extract_imports` only checks top-level `SimpleStatementLine` imports. Misses `if TYPE_CHECKING:` blocks, conditional imports, function-level imports. | R1, R3 | True, but this is the import *guard* for LLM output. LLM mutations replace function bodies, not module-level code. Function-level imports in mutations are the real gap — an LLM could add `import os` inside the function body. |
| F10 | **MINOR** | `_cache_key` path sanitization: `a/b.py` → `a_b.py__...` collides with `a_b.py` → `a_b.py__...`. | R2 | True but astronomically unlikely in practice (requires two files differing only by `/` vs `_`). |
| F11 | **MINOR** | `_KNOWN_KEYS` in config.py defined but never used. | R1, R3 | Yes — dead code. Was intended for unknown-key warnings (deferred feature). |
| F12 | **MINOR** | `_extract_functions` in scope.py only handles one level of class nesting. Nested classes' methods are invisible. | R2 | True. Uncommon pattern, low impact. |
| F13 | **MINOR** | `parse_llm_response` fallback regex `\[.*]` is greedy — grabs from first `[` to last `]` in entire response. Could merge unrelated brackets. | R2, R3 | True but this is already a last-resort fallback after JSON parse and code-block extraction both fail. Edge case of an edge case. |
| F14 | **MINOR** | Pipeline catches `except Exception` broadly on API calls. | R3 | Reasonable for network errors. Already emits a warning. Could narrow to `anthropic.APIError` but risks missing `httpx` transport errors. |
| F15 | **MINOR** | tomli fallback for Python 3.10 but tomli not in dependencies. | R1, R2 | Real gap if anyone runs on 3.10. pyproject.toml should add `tomli; python_version < "3.11"`. |
| F16 | **MINOR** | No `conftest.py` — no shared fixtures across test modules. | R3 | Partially addressed: `test_plugin.py` has autouse fixture. Other test files use `tmp_path` directly. A shared conftest would reduce duplication. |
| F17 | **MINOR** | `validate_imports` returns empty set on parse failure (asymmetric — original failing = no guard). | R2 | True but benign — if original code doesn't parse, mutmut wouldn't process it. LLM mutations that don't parse are caught by `validate_syntax` first. |
| F18 | **MINOR** | No `encoding="utf-8"` on file I/O calls. | R2 | Platform-dependent. Linux defaults to UTF-8. Add for Windows compatibility if needed. |

**Dismissed findings:**
- "Prompt injection from malicious docstrings" (R3-P1): Theoretical. Requires attacker-controlled codebase that the developer is also running tests on. If you run `mutmut` on malicious code, the test suite itself is already executing that code.
- "Cache file path traversal" (R3-P3): `_cache_key` replaces `/` and `\` — traversal not possible.
- "source_hash truncated to 64 bits — collision-prone" (R3-P9): 64-bit hash for a local file cache is fine. This isn't a security boundary.
- "Thread safety of globals" (R1, R2): mutmut is single-threaded. Not a real concern.
- "Anthropic SDK `stop_reason` attribute may change" (R2-P13): Speculative. SDK has stable API.
- "E2E tests write to source tree" (R3-P15): No E2E tests exist in mutmut-llm yet.
- "`__import__()`, `exec()`, `eval()`, `importlib` bypass" (R3-P1): Prompt constraint + the fact that these constructs would need to already exist in the original imports. Deferred to "regex scanner" (already in incremental plan's deferred list).

---

## Prioritized work items

### WI-1: Fix class method LLM identification (F1)

**Impact:** Class method LLM mutations are silently never tagged as LLM. Reporting shows them all as "builtin".

**What to change:**
- `plugin.py:_llm_mutation_count_by_function()` — match against bare function name (strip class prefix from cache's `function_name`)
- OR `plugin.py:_extract_function_name()` — return qualified name matching cache format
- Best approach: make `_extract_function_name` return the qualified name (`Foo.bar`) to match the cache's `function_name` field. This is the more correct direction — the function name in the cache comes from `ScopeTarget.function_name` which uses `Class.method` format.

**Files:** `plugin.py`, `test_plugin.py`
**LOC:** ~5 changed, ~10 new test lines
**Approach:**
```python
# In _extract_function_name, return "Class.method" not just "method"
if CLASS_NAME_SEPARATOR in base:
    parts = base.split(CLASS_NAME_SEPARATOR)
    # parts[0] is "x", parts[1] is class, parts[2] is method
    return f"{parts[1]}.{parts[2]}"
```
Update `test_with_class` and `test_with_class_and_module` assertions to expect `"MyClass.method"` and `"Cls.do_thing"`.

---

### WI-2: Fix budget over-allocation (F3)

**Impact:** When `total_budget < len(targets)`, total allocated mutations exceed budget. Dry-run displays wrong numbers.

**What to change:** `scope.py:_allocate_budget` — cap total allocation at `total_budget`.

**Files:** `scope.py`, existing scope tests
**LOC:** ~8 changed
**Approach:**
```python
def _allocate_budget(targets, total_budget, max_per_function):
    if not targets or total_budget <= 0:
        return {}
    per_function = min(max_per_function, max(1, total_budget // len(targets)))
    alloc = {}
    remaining = total_budget
    for t in targets:
        n = min(per_function, remaining)
        if n <= 0:
            break
        alloc[t.function_name] = n
        remaining -= n
    return alloc
```

---

### WI-3: Use file-qualified keys for budget allocation (F4)

**Impact:** Two files with identically-named functions get one budget entry instead of two.

**What to change:** Key `budget_per_target` by `(file_path, function_name)` tuple or a composite string like `file_path::function_name`. Also update `pipeline.py` lookup.

**Files:** `scope.py`, `pipeline.py`
**LOC:** ~15 changed
**Approach:** Use `f"{t.file_path}::{t.function_name}"` as key in `_allocate_budget`. Update `_generate_mutations` and `run_generation` dry-run display to use same composite key.

---

### WI-4: Reset global state in `mutmut_configure` (F5, F6)

**Impact:** Hygiene fix. Ensures clean state if configure is called multiple times (unlikely but defensive).

**What to change:** `plugin.py:mutmut_configure` — clear `_llm_mutant_names`, call `_reset_cache_index()`.

**Files:** `plugin.py`
**LOC:** ~4 added
**Approach:**
```python
@hookimpl
def mutmut_configure(config):
    global _llm_config, _mutmut_paths, _current_run
    _llm_mutant_names.clear()
    _reset_cache_index()  # import from operators
    # ... rest unchanged
```

---

### WI-5: Wire `_KNOWN_KEYS` or delete (F11)

**Impact:** Dead code cleanup.

**What to change:** Delete `_KNOWN_KEYS` from `config.py`. The unknown-key warning feature was explicitly deferred.

**Files:** `config.py`
**LOC:** ~1 deleted

---

### WI-6: Add `tomli` conditional dependency (F15)

**Impact:** Package fails on Python 3.10 if `tomli` not installed.

**What to change:** `mutmut-llm/pyproject.toml` — add `tomli; python_version < "3.11"` to dependencies.

**Files:** `pyproject.toml`
**LOC:** ~1 added

---

### WI-7: Add `conftest.py` with shared fixtures (F16)

**Impact:** Reduces test duplication, prevents future state-leak issues as test count grows.

**What to change:** Create `mutmut-llm/tests/conftest.py` with:
- The existing `_reset_plugin_state` fixture (move from test_plugin.py)
- The `_reset_cache_index` call (operator state)
- A shared `cache_root` fixture

**Files:** `tests/conftest.py` (new), `tests/test_plugin.py`, `tests/test_storage.py`
**LOC:** ~20 new, ~10 removed from test_plugin.py

---

### WI-8: Extend import guard to function-level imports (F9)

**Impact:** LLM mutations can sneak in `import os` inside the function body, bypassing the top-level-only guard.

**What to change:** `validation.py:_extract_imports` — walk all `SimpleStatementLine` nodes recursively (inside `If`, `FunctionDef`, etc.), not just `module.body`.

**Files:** `validation.py`, `tests/test_validation.py`
**LOC:** ~15 changed
**Approach:** Use a simple libcst `CSTVisitor` that collects all `Import` and `ImportFrom` nodes at any depth:
```python
class _ImportCollector(cst.CSTVisitor):
    def __init__(self):
        self.imports: set[str] = set()
    def visit_Import(self, node):
        # extract names
    def visit_ImportFrom(self, node):
        # extract module name

def _extract_imports(code: str) -> set[str]:
    module = cst.parse_module(code)
    collector = _ImportCollector()
    module.walk(collector)
    return collector.imports
```

---

## Deferred items

| Finding | Why defer |
|---------|-----------|
| F2 (tail-slicing fragility) | Works correctly with current operator set. Proper fix requires source-matching (compare mutated code against cache), which is a larger refactor touching the hook interface. Revisit when adding more FunctionDef operators. |
| F7/F8 (CWD-dependent paths) | Mutmut always runs from project root. No user-reported issues. Fix when adding `--project-root` CLI flag (Step 7 scope). |
| F10 (cache key collision) | Requires pathological file naming. Not worth the complexity of a different sanitization scheme. |
| F12 (nested class nesting) | Uncommon Python pattern. Add when a user requests it. |
| F13 (greedy regex fallback) | Last-resort parse path. JSON fast-path and code-block extraction handle >99% of responses. |
| F14 (broad exception catch) | Narrowing risks missing transport-layer errors. Current warning is sufficient. |
| F17 (asymmetric parse failure) | Benign — validate_syntax runs first. |
| F18 (encoding kwarg) | Add when Windows support becomes a goal. |

---

## Execution order

1. **WI-1** (class method key mismatch) — highest impact, 15 min
2. **WI-2** (budget over-allocation) — correctness fix, 15 min
3. **WI-3** (file-qualified budget keys) — depends on WI-2, 20 min
4. **WI-4** (reset globals in configure) — trivial, 5 min
5. **WI-5** (delete dead code) — trivial, 2 min
6. **WI-6** (tomli dep) — trivial, 2 min
7. **WI-7** (conftest.py) — cleanup, 15 min
8. **WI-8** (function-level import guard) — security improvement, 20 min

WI-1 through WI-6 can ship as one commit. WI-7 and WI-8 are independent follow-ups.

Total estimated effort: ~1.5 hours.
