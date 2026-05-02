# Wave 2 Review Findings

**Date:** 2026-03-21
**Features reviewed:** 7 implementations (5 from wave 1, 2 from wave 2)
**Review method:** 3 competing code quality reviewers + 3 competing adversarial testers, all parallel

## Implementations

| # | Feature | Branch | Worktree | Tests | Status |
|---|---------|--------|----------|-------|--------|
| 1 | Context quality improvement | `worktree-agent-a28bdd9d` | `.claude/worktrees/agent-a28bdd9d` | 422 pass | Needs fixes |
| 2 | Adaptive budget per function | `worktree-agent-a225536b` | `.claude/worktrees/agent-a225536b` | 404 pass | Needs fixes |
| 3 | Hook filter composition | `worktree-agent-a8b9d9a9` | `.claude/worktrees/agent-a8b9d9a9` | 192 pass | Needs fixes |
| 4 | Dynamic exclusion list | `worktree-agent-a9c42fae` | `.claude/worktrees/agent-a9c42fae` | 402 pass | Needs fixes |
| 5 | Mutation source tracking | `worktree-agent-afcf9355` | `.claude/worktrees/agent-afcf9355` | 214 pass | Needs fixes |
| 6 | Cache garbage collection | `worktree-agent-a58ce4a1` | `.claude/worktrees/agent-a58ce4a1` | 403+188 pass | Clean |
| 7 | Async parallel generation | `worktree-agent-aaf84c48` | `.claude/worktrees/agent-aaf84c48` | 405+21skip | Clean |

## CRITICAL (must fix before merge)

### C1. Hook filter bypasses pluggy argument subsetting

**Feature:** 3 (hook filter composition)
**File:** `mutmut/src/mutmut/file_mutation.py:141`
**Found by:** Reviewers A, B

The implementation calls `impl.function(filename=filename, mutations=mutations)` directly, bypassing pluggy's argument normalization. Pluggy allows hook implementations to declare a subset of the hookspec's parameters. Any plugin that doesn't accept `filename` will crash with `TypeError: got an unexpected keyword argument 'filename'`.

**Root cause:** Manual `get_hookimpls()` iteration trades pluggy's fan-out (which handles arg subsetting) for chaining semantics, but loses the argument filtering.

**Fix:** Inspect each `impl.function`'s signature and only pass accepted kwargs:
```python
import inspect
for impl in hook_impls:
    sig = inspect.signature(impl.function)
    kwargs = {"filename": filename, "mutations": mutations}
    accepted = {k: v for k, v in kwargs.items() if k in sig.parameters}
    result = impl.function(**accepted)
```

### C2. Breaking API: `mutate_file_contents` returns 3-tuple

**Feature:** 5 (mutation source tracking)
**File:** `mutmut/src/mutmut/file_mutation.py:95`
**Found by:** Reviewers A, C

`mutate_file_contents` return type changed from `tuple[str, Sequence[str]]` to `tuple[str, Sequence[str], dict[str, str]]`. Every external caller unpacking `result, names = mutate_file_contents(...)` breaks with `ValueError: too many values to unpack`.

**Root cause:** Adding source mapping to the return value without backward-compatible wrapping.

**Fix options:**
- (a) Return a `NamedTuple` or `@dataclass` result object (preferred — extensible without future breaks)
- (b) Keep 2-tuple, add source mapping as attribute on a result object or side-channel

### C3. Submodule pointer regression in context quality worktree

**Feature:** 1 (context quality)
**File:** `mutmut/` submodule pointer
**Found by:** Reviewer A, Tester B

Submodule advanced to upstream `56fc6a7` which is on `origin/master` and **lacks all 7 local patches** (pluggy hooks, whole function mutation, decorator support, etc.). The working tree has the right files (tests pass) but the recorded commit pointer is wrong.

**Root cause:** Agent ran `git submodule update --init` which checked out upstream instead of the local patched commit.

**Fix:** Reset submodule pointer to `0431bc7` before merging. Feature 1 changes are entirely in `mutmut-llm/`.

## HIGH (should fix before merge)

### H1. Regex import filtering matches words in strings/comments

**Feature:** 1 (context quality)
**File:** `mutmut-llm/src/mutmut_llm/scope.py:102`
**Found by:** All 3 reviewers

`re.findall(r"\b(\w+)\b", function_source)` captures every word including string literals, comments, and variable names that coincidentally match import names. `x = "os"` → `import os` incorrectly included.

**Root cause:** Text-level matching instead of AST-level identifier extraction.

**Fix:** Use libcst `Name` node visitor to extract only actual identifier references, excluding strings and comments.

### H2. Regex branch counting matches keywords in strings/comments

**Feature:** 2 (adaptive budget)
**File:** `mutmut-llm/src/mutmut_llm/scope.py:130`
**Found by:** All 3 reviewers

`_BRANCH_RE = re.compile(r"\b(if|elif|else|for|while|try|except|with)\b")` applied to raw source text. `msg = "if you need help"` counts as a branch.

**Root cause:** Same as H1 — text-level matching instead of AST counting.

**Fix:** Use `ast.parse` or libcst to count actual `If`/`For`/`While`/`Try` nodes. libcst already imported.

### H3. `SYSTEM_PROMPT` built at import time

**Feature:** 4 (dynamic exclusion)
**File:** `mutmut-llm/src/mutmut_llm/prompts.py:78`
**Found by:** Reviewers A, C; Tester B

`SYSTEM_PROMPT = build_system_prompt()` at module level calls `get_plugin_manager()`. If imported before plugins registered, falls back to hardcoded exclusions. The pipeline correctly calls `build_system_prompt()` at runtime, but `build_system_with_context`'s fallback uses the stale constant.

**Root cause:** Module-level execution of dynamic content.

**Fix:** Remove module-level `SYSTEM_PROMPT` constant. Always call `build_system_prompt()` dynamically.

### H4. Target method signature included in class context

**Feature:** 1 (context quality)
**File:** `mutmut-llm/src/mutmut_llm/scope.py:190-196`
**Found by:** Reviewer B

`_build_class_context` includes ALL method signatures, including the target method being mutated. The LLM sees the same function twice (signature stub + full source).

**Root cause:** No filtering of the target function when building sibling context.

**Fix:** Pass target function name to `_build_class_context`, skip it when generating signatures.

### H5. Merge conflict: features 3+5 in `file_mutation.py`

**Features:** 3 (hook filter) + 5 (source tracking)
**File:** `mutmut/src/mutmut/file_mutation.py`
**Found by:** Testers B, C

Both modify `mutate_file_contents`, `create_mutations`, `combine_mutations_to_source`, `function_trampoline_arrangement`. Feature 5 changes return types; feature 3 changes filter logic. Also overlapping formatting changes. Submodule pointers diverge (`f644cda` vs `4891357`).

**Resolution:** Merge inside submodule. Take feature 5's `source_by_name` for the conflicted line (functional change > refactor).

### H6. Merge conflict: features 1+2 in `test_scope.py`

**Features:** 1 (context quality) + 2 (adaptive budget)
**File:** `mutmut-llm/tests/test_scope.py`
**Found by:** Tester B

3 textual conflicts in import blocks and `TestAllocateBudget`. `scope.py` auto-merges cleanly.

**Resolution:** Combine imports; keep feature 2's rewritten `TestAllocateBudget`; keep feature 1's new test classes.

## MEDIUM (fix recommended)

### M1. `min > max` budget config silently misbehaves

**Feature:** 2 (adaptive budget)
**File:** `config.py` + `scope.py:149`
**Found by:** Reviewers A, B; Tester C

`min_mutations_per_function = 10, max_mutations_per_function = 3` → silently returns 3.

**Fix:** Add validation in `load_config` or `LLMConfig.__post_init__`: `raise ValueError` if `min > max`.

### M2. Bare `except Exception` swallows real plugin errors

**Feature:** 4 (dynamic exclusion)
**File:** `prompts.py:107`
**Found by:** Reviewers A, C

`_get_registered_operators` catches `Exception` broadly. Plugin `TypeError` silently swallowed.

**Fix:** Catch `ImportError` only for plugin manager import; let plugin errors propagate. Log at `WARNING` not `DEBUG`.

### M3. O(n×m) context recomputation per class method

**Feature:** 1 (context quality)
**File:** `scope.py:81-86`
**Found by:** Reviewers A, C

For every method in a class, `_build_module_context` + `_build_class_context` re-parse all module/class statements.

**Fix:** Cache module-level import/constant extraction; filter per function from cached set.

### M4. Wildcard imports silently dropped

**Feature:** 1 (context quality)
**File:** `scope.py:127`
**Found by:** Reviewer B

`from x import *` → `ImportStar` not a list/tuple → empty set → import excluded.

**Fix:** When `isinstance(node.names, cst.ImportStar)`, always include the import (conservative).

### M5. `__mutmut_source__` attribute stamping fragile

**Feature:** 5 (source tracking)
**File:** `mutmut-extras/plugin.py:39`
**Found by:** Reviewers A, B

Setting attributes on arbitrary callables can fail (C extensions, `functools.partial`).

**Fix:** Wrap in try/except, or use a separate registry dict `{id(func): source}`.

### M6. Default `max_mutations_per_function` doubled silently

**Feature:** 2 (adaptive budget)
**File:** `config.py:40`
**Found by:** Reviewer C

Default changed from 5 to 10. Users upgrading see doubled API costs without config change.

**Fix:** Keep default at 5, or document prominently.

### M7. `.format()` on template vulnerable to docstring braces

**Feature:** 4 (dynamic exclusion)
**File:** `prompts.py:72`
**Found by:** Reviewer C

If operator docstring contains `{foo}`, `.format()` raises `KeyError`.

**Fix:** Use `.replace("{exclusion_list}", exclusion_list)` instead of `.format()`.

## LOW (cosmetic / unlikely)

### L1. `_describe_operator` crashes on property-raising callables

**Feature:** 4 — Wrap `getattr(fn, "__doc__")` in try/except.

### L2. Inconsistent operator docstrings (1/20 has docstring)

**Feature:** 4 — Add docstrings to all 20 operators or rely entirely on name-based fallback.

### L3. `.meta` backward compat is one-way

**Feature:** 5 — Old mutmut's `assert not meta` crashes on new `.meta` files with `source_by_key`.

## Merge Order

```
1. Feature 2 (adaptive budget)     — clean, no submodule changes
2. Feature 4 (dynamic exclusion)   — clean, auto-merges with Feature 2
3. Features 3+5 submodule merge    — merge inside submodule, resolve 1-line conflict
4. Feature 3 (hook filter, outer)
5. Feature 5 (source tracking, outer)
6. Feature 1 (context quality)     — discard submodule pointer, resolve test_scope.py conflict
7. Feature 6 (cache GC)            — independent of above
8. Feature 7 (async parallel)      — independent of above
```

## Fix Priority

**Before any merge:**
- C1 (hook filter arg subsetting)
- C2 (source tracking API break)
- C3 (submodule pointer reset)

**Before merge of affected feature:**
- H1 (regex import filtering → libcst)
- H2 (regex branch counting → AST)
- H3 (remove import-time SYSTEM_PROMPT)
- H4 (skip target method in class context)
- M1 (min/max validation)
- M2 (narrow exception catch)
- M7 (format injection)
