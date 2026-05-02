# Spec Delta: Context Quality Improvement (mutmut-llm)

> Describes behavioral contracts that would be added to `mutmut-llm/SPEC.md` if branch
> `worktree-agent-a28bdd9d` were merged. RFC 2119 keywords apply.

## Summary of Changes

**Before (main):** `ScopeTarget.context` contains all module import statements verbatim,
and `class Name: ...` as a placeholder for methods inside a class.

**After (branch):** Context is per-function: only imports and module-level constants
whose names appear in the function source are included, plus rich class context
(full method signature list with decorators and return types, class attributes).

---

## Context Assembly Contract

- Each `ScopeTarget` MUST carry a `context` string assembled at extraction time, scoped
  to the specific function being targeted (not shared across all functions in a file).

- For top-level functions, `context` MUST contain only imports and module-level constants
  determined relevant to that function. It MUST NOT contain imports irrelevant to the
  function.

- For methods inside a class, `context` MUST additionally include the enclosing class's
  structural summary (see Class Context Contract below).

- `context` MAY be the empty string when no relevant context can be determined.

- `context` MUST NOT contain the full source body of the target function. The target
  function's source is provided separately as `ScopeTarget.source`.

---

## Import Filtering Contract

- The filtering unit is the **locally-bound name**: the name introduced into the local
  scope by the import statement. For `import os`, the bound name is `os`. For
  `from pathlib import Path`, the bound name is `Path`. For
  `import a.b.c` (no asname), the bound name is `a` (the leftmost segment). For
  `from x import a as b`, the bound name is `b`.

- An import statement MUST be included if any of its locally-bound names appears as a
  word-boundary token in the function source text.

- An import statement MUST NOT be included if none of its locally-bound names appears
  in the function source text.

- The presence check is **text-level** (word-boundary regex over the raw function
  source). This is intentionally conservative: the function body text, including string
  literals and comments, is searched. This causes false positives (see Open Questions /
  Bugs).

- `from x import *` (wildcard imports) MUST NOT be included. Wildcard imports cannot be
  statically resolved to bound names, so they cannot be filtered. Omitting them is a
  known false negative; the contract accepts this trade-off to avoid always including
  potentially large wildcard scopes.

---

## Constants Contract

- A module-level simple assignment (`NAME = value` or `NAME: type = value`) MUST be
  included if its target name appears as a word-boundary token in the function source.

- Only simple name targets are matched. Tuple unpacking and attribute assignment targets
  MUST NOT be included (they cannot be reliably identified via name matching).

- Multi-target assignments (e.g., `a = b = value`) MUST include the line if any target
  name matches.

- Included constants appear in the same output string as imports, in the order they
  appear in the module source.

---

## Class Context Contract

- For a method `ClassName.method_name`, the context MUST include the class header
  (`class ClassName(Bases):`) and MUST NOT reduce the class to `class ClassName: ...`.

- The context MUST include the **signature** (not body) of every method defined directly
  in the class. A signature is `[decorators] def name(params) -> return_type: ...`
  where decorators are rendered with their full syntax and `...` is a literal ellipsis.

- The context MUST include class-level attribute assignments and annotated assignments
  (e.g., `MAX = 100`, `x: int = 5`) as they appear in the class body.

- Base classes MUST appear in the class header. Each base is rendered as the
  module-level code for that expression (e.g., `Parent`, `Mixin`, `Generic[T]`).

- Nested classes inside the target class are NOT specified (behavior is currently
  undefined for deeply nested structures).

---

## Target-Function Deduplication Contract

- The target function's **full source** is provided as `ScopeTarget.source`.

- The class context MUST NOT include the target function's signature as a sibling
  method stub. Including it causes the same function to appear twice in the LLM
  prompt (once as a stub, once as full source).

  > **BUG (H4):** The branch implementation does not implement this exclusion.
  > `_build_class_context` includes ALL method signatures unconditionally, including
  > the target method. The LLM receives the target function's signature in `context`
  > AND its full body in `source`. This must be fixed before merge (pass target
  > function name to `_build_class_context` and skip it).

---

## Correctness Guarantee (False Negative vs False Positive)

- **False negatives** (an import the function actually uses is excluded) are preferred
  over **false positives** (an irrelevant import is included).

- The spec accepts false negatives in three cases:
  1. Star imports (cannot determine bound names statically).
  2. Dynamic attribute access (`getattr(module, name)`) — not detectable by name matching.
  3. Names injected via exec/eval — explicitly out of scope.

- The spec does NOT guarantee false negatives are impossible via text-level matching.
  An import may be included if its bound name appears in a string literal or comment
  in the function source.

---

## Context Per-Function Isolation

- The context for function `A` MUST be computed independently from function `B` even
  when `A` and `B` are in the same file. Two top-level functions with different import
  usage MUST receive different contexts.

- For class methods: each method MUST have its context computed against its own source.
  The module context for `ClassName.method_a` and `ClassName.method_b` MAY differ if
  they reference different imports.

  > **BUG (M3):** The branch calls `_build_module_context` and `_build_class_context`
  > once per method in a class, re-traversing the full module AST for each method.
  > For a class with N methods, this is O(N) module traversals and O(N) class
  > traversals. The correct approach: compute module-level context once per module,
  > then intersect with per-function name sets. This is a performance issue, not a
  > correctness issue—output is identical—but it is observable for large files.

---

## Open Questions

1. **Target exclusion scope:** Should the target function be excluded only from its
   *own* class context, or also from any nested-class or function-in-function
   context? The plan only discusses the top-level class case.

2. **Wildcard import policy:** The current contract silently omits `from x import *`.
   Should the implementation warn? Should it include the statement unconditionally
   (conservative inclusion) rather than unconditionally excluding it?

3. **Per-function context granularity vs token budget:** Per-function context increases
   prompt size for large classes (N method signatures). The plan mentions "consider
   truncating to 10 closest methods" but does not specify a contract. Is proximity
   truncation in scope? If so, what is the proximity metric?

4. **Constants from nested scopes:** Should constants defined inside `if __name__ ==
   '__main__'` blocks or other top-level conditionals be included? Currently excluded
   (only `SimpleStatementLine` at module body level is processed).

5. **Chained/complex assignments:** `a = b = CONSTANT` — does the contract require
   both `a` and `b` to be extractable as targets? Current implementation extracts
   all `Name` targets from `cst.Assign.targets`.

---

## Bugs / Inconsistencies in Branch Implementation

### H1 — Regex name extraction includes string literals and comments (HIGH)

**Location:** `scope.py`, `_build_module_context`, line computing `func_names`.

**Problem:** `re.findall(r"\b(\w+)\b", function_source)` operates on the raw source
text of the function. This captures every word token, including those inside string
literals and comments. A function containing `x = "os"` will include `import os` in
its context even if `os` is never actually used as an identifier.

**Contract implication:** The import filtering contract as stated above describes the
*intended* behavior (filter to used identifiers). The implementation violates this
contract by using text-level matching instead of AST-level identifier extraction.

**Required fix before this spec clause can be ratified:** Use a libcst `Name` node
visitor to collect only actual identifier references (not tokens inside strings/comments).

---

### H4 — Target method appears twice in class context (HIGH)

**Location:** `scope.py`, `_build_class_context` (no target filtering).

**Problem:** Every method's signature is included in the class context, including the
target method being mutated. The LLM therefore receives the target function's signature
in `context` and its full body in `source`.

**Contract implication:** Violates the Deduplication Contract above.

---

### M3 — O(N) module re-traversal per class method (MEDIUM)

**Location:** `scope.py`, `_extract_functions`, inner class-method loop.

**Problem:** `_build_module_context` and `_build_class_context` are called inside the
per-method loop. For a class with N methods in a module with M statements, this is
O(N×M) work. Observable for large files (100+ methods, hundreds of imports).

**Contract implication:** Performance, not correctness. The output is identical to an
O(M+N) implementation. No spec clause needs to mandate performance, but this should
be documented as a known limitation until fixed.

---

### M4 — Star imports silently dropped (MEDIUM)

**Location:** `scope.py`, `_extract_imported_names`, star import branch.

**Problem:** `from x import *` returns an empty name set. Because the name set is empty,
`imported_names & func_names` is always the empty set, and the star import is never
included in context. If the function relies on names from a star import, those names
will be absent from context.

**Contract implication:** Captured in the Import Filtering Contract above as an accepted
false negative. However, the current test (`test_star_import_returns_empty`) documents
this behavior without any warning or fallback. A spec decision is needed on whether to
warn or include unconditionally (see Open Question 2).

---

### C3 — Submodule pointer advanced to upstream (CRITICAL for merge)

**Location:** `mutmut/` submodule pointer in the branch.

**Problem:** The branch records `mutmut` at upstream commit `56fc6a7` (v3.3.1+72), which
is missing all 7 local patches (pluggy hooks, whole-function mutation, etc.). The working
tree files are intact (tests pass) but the committed pointer is wrong.

**Contract implication:** None for this spec. This is a merge-time issue. The submodule
pointer MUST be reset to `0431bc7` before merging. This is unrelated to context quality
but blocks the merge.

---

### Branch Scope Creep — Unintended pipeline.py removals

**Location:** `pipeline.py` diff shows removal of `ErrorAction`, `classify_error`,
`TrackedSemaphore`, `_sigint_handler`, `_compute_concurrency`, async infrastructure.

**Problem:** These removals are stale-branch artifacts. The async parallel generation
feature (`worktree-agent-aaf84c48`) was merged to main after this branch was created.
The branch's `pipeline.py` predates that merge. Merging this branch as-is would
regress the async pipeline.

**Contract implication:** None for this spec delta—context quality is entirely in
`scope.py`. However, the `pipeline.py` diff MUST be discarded or cherry-picked at
merge time; only the `scope.py` and `test_scope.py` changes should land.
