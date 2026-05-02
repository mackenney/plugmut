# Spec Delta: Context Quality Improvement (mutmut-llm)

> Describes behavioral contracts to be added to `mutmut-llm/SPEC.md` if branch
> `worktree-agent-a28bdd9d` is merged. RFC 2119 keywords apply.
>
> Where the branch implementation deviates from the contract, the deviation is
> marked **BUG** with severity. BUGs marked BLOCKS MERGE must be fixed before
> the branch lands.

## Summary of Changes

**Before (main):** `ScopeTarget.context` contains all module import statements
verbatim, and `class Name: ...` as a single-line placeholder for methods inside
a class.

**After (branch):** Context is per-function: only imports and module-level
constants whose names appear in the function source are included, plus rich
class context (full method signature list with decorators and return types,
class attributes).

---

## Context Assembly Contract

- Each `ScopeTarget` MUST carry a `context` string assembled independently for
  the specific function being targeted, not shared across all functions in a
  file.

- For top-level functions, `context` MUST contain only imports and module-level
  constants determined relevant to that function (see Import Filtering Contract
  and Constants Contract).

- For methods inside a class, `context` MUST additionally include the enclosing
  class's structural summary (see Class Context Contract).

- `context` MAY be the empty string when no relevant context can be determined.

- `context` MUST NOT contain the full source body of the target function. The
  target function's source is provided separately as `ScopeTarget.source`.

- Context assembly MUST be deterministic: given the same source file and
  function name, `ScopeTarget.context` MUST be identical across all calls to
  the extraction function. (The current implementation satisfies this because
  AST traversal follows document order and set operations only affect
  inclusion/exclusion, but the guarantee must be explicit because context feeds
  the LLM cache key.)

---

## Import Filtering Contract

### Bound-name definition

The filtering unit is the **locally-bound name**: the name introduced into the
local scope by the import statement.

| Import form | Bound name |
|---|---|
| `import os` | `os` |
| `from pathlib import Path` | `Path` |
| `import a.b.c` (no alias) | `a` (leftmost segment) |
| `from x import a as b` | `b` |

### Intended contract (Framing B — required by H1 fix before merge)

An import statement MUST be included if and only if one or more of its
locally-bound names appears as a referenced identifier in the function's AST
(i.e., a `Name` node whose value equals the bound name, ignoring string
literals and comments).

An import statement MUST NOT be included if none of its locally-bound names
appear as a referenced identifier in the function's AST.

> **BUG H1 — BLOCKS MERGE:** The branch implements text-level word-boundary
> regex matching instead of AST identifier extraction. Under the current
> implementation, a function containing `x = "os"` includes `import os` even
> if `os` is never used as an identifier. The MUST contract above (Framing B)
> is violated. Required fix: replace `re.findall(r"\b(\w+)\b", function_source)`
> with a libcst `Name` node visitor that collects only actual identifier
> references. Until H1 is fixed, the implementation satisfies only the weaker
> Framing A (text-level) and the Framing B MUST cannot be ratified.

### Current implementation behavior (Framing A — what ships if H1 is not fixed)

If H1 is not fixed before merge, the following weaker contract applies instead:

An import statement MUST be included if any of its locally-bound names appears
as a word-boundary token anywhere in the raw function source text, including
string literals and comments.

Under Framing A, `import os` being included when the function contains
`msg = "os"` is **correct behavior**, not a false positive. The distinction
matters because reviewers must know which contract to test against.

> **Recommendation:** Fix H1 before merge so the stronger Framing B contract
> applies. Framing A is documented here for accuracy, not endorsement.

### Compound-statement lines

> **BUG (NEW — not in wave2 findings) — BLOCKS MERGE:** The current
> implementation calls `break` after evaluating the first item in each
> `SimpleStatementLine.body`. For a semicolon-compound line such as
> `import os; import sys`, only `import os` is evaluated; `import sys` is
> silently skipped. The Framing B MUST (and even the weaker Framing A MUST)
> is violated for any import that is not the first statement on its line.
> Required fix: remove the `break` and process all items in `stmt.body` before
> moving to the next statement line. Semicolon-compound imports are uncommon
> in practice but the spec cannot knowingly permit this exclusion.

### Wildcard imports

`from x import *` (wildcard imports) MUST be included in context unconditionally.

Rationale: the filtering contract cannot apply to wildcard imports because no
locally-bound name set is statically available. Omitting the import statement
entirely is a false negative: if the function uses names introduced by the
wildcard, those names appear without any import line in the LLM context. Adding
one import statement line is negligible cost; the symbols are not included
regardless. Conservative inclusion is therefore correct.

> **BUG M4:** The branch silently omits wildcard imports (the empty name set
> produced by `_extract_imported_names` for `from x import *` means the
> intersection is always empty). Fix: detect `ImportStar` nodes and include
> the parent import statement unconditionally.

---

## Constants Contract

A module-level simple assignment (`NAME = value` or `NAME: type = value`) MUST
be included if one or more of its target names appears as a referenced
identifier in the function (under the same identifier-extraction semantics as
the Import Filtering Contract — text-level matching under Framing A, AST
`Name` nodes under Framing B).

> **Note:** The H1 contamination issue applies equally to constants. Under
> Framing A, `MAX_SIZE = 1000` is included if the string `"MAX_SIZE"` appears
> anywhere in the function source text.

Only simple name targets are matched. Tuple unpacking and attribute assignment
targets MUST NOT be included.

Multi-target assignments (`a = b = value`) MUST be processed such that the
line is included if any target name matches. Both `a` and `b` are extractable
targets; this is already implemented correctly and is a closed question (not
Open Question 5 from the draft — the code handles this correctly via
`Assign.targets` iteration).

Included constants appear in the same output string as imports, in the order
they appear in the module source.

### Known exclusions (document as limitations, not open questions)

- **Augmented assignments** (`COUNTER += 1` at module level): excluded silently.
  `cst.AugAssign` is not handled. These are excluded without warning.

- **Constants inside `if TYPE_CHECKING:` blocks**: excluded silently.
  `if TYPE_CHECKING:` is an `If` node at the module body level, not a
  `SimpleStatementLine`. This is a more significant gap than
  `if __name__ == '__main__'` in type-annotation-heavy code.

- **Constants inside any conditional block** (`if __name__ == '__main__'`, etc.):
  excluded. Only `SimpleStatementLine` nodes at module body level are examined.

---

## Class Context Contract

For a method `ClassName.method_name`, the context MUST include the class header
(`class ClassName(Bases):`) and MUST NOT reduce the class to
`class ClassName: ...`.

The context MUST include the **signature** (not body) of every method defined
directly in the class **except the target function** (see Deduplication Contract).
A signature is rendered as:
`[decorators] def name(params) -> return_type: ...` where decorators use their
full syntax and `...` is a literal ellipsis placeholder.

The context MUST include class-level attribute assignments and annotated
assignments (`MAX = 100`, `x: int = 5`) as they appear in the class body.

Base classes MUST appear in the class header as they are written in the source
(e.g., `Parent`, `Mixin`, `Generic[T]`).

### Class context size

> **Open Question 3 (BLOCKS MERGE):** The MUST to include all method signatures
> is unsafe without a size bound. For a class with many methods and multi-line
> decorator chains, the context string can exceed LLM context-window limits,
> causing API failures. The following placeholder normative statement applies
> until this question is resolved:
>
> Implementations SHOULD provide a configurable maximum number of sibling
> signatures to include. When the number of sibling methods exceeds the
> threshold, the implementation SHOULD prefer methods nearest (by line number)
> to the target function. The exact threshold value and truncation algorithm
> are not yet specified and constitute Open Question 3.
>
> In the absence of a configured bound, context growth is unbounded, which MAY
> cause LLM API failures for classes with many methods.

Nested classes inside the target class are not specified; behavior for deeply
nested structures is undefined.

---

## Target-Function Deduplication Contract

The target function's full source is provided as `ScopeTarget.source`.

The class context MUST NOT include any reference to the target function. This
means the target function's signature MUST NOT appear as a sibling method stub
in the class context. The target function MUST be identified by its unqualified
method name (e.g., `"method_name"`, not `"ClassName.method_name"`).

> **BUG H4 — BLOCKS MERGE:** `_build_class_context` includes ALL method
> signatures unconditionally. The LLM receives the target function's signature
> in `context` AND its full body in `source`. Required fix: pass the target
> function name to `_build_class_context` and skip it when building the
> signature list. This requires adding a `target_name: str` parameter to
> `_build_class_context`; the current signature `(module, class_def,
> module_context)` does not include it.

---

## Context Per-Function Isolation

The context for function A MUST be computed independently from function B even
when A and B are in the same file. Two top-level functions with different import
usage MUST receive different contexts.

For class methods: each method MUST have its context computed against its own
source. The module context for `ClassName.method_a` and `ClassName.method_b`
MAY differ if they reference different identifiers.

> **BUG M3 (performance, not correctness):** The branch calls
> `_build_module_context` and `_build_class_context` once per method in a
> class, re-traversing the full module AST for each method. For a class with N
> methods in a module with M statements, this is O(N×M) work — observable for
> large files. Module-level context extraction SHOULD be computed once per
> module file, not once per function extracted from that file. Output is
> identical to a correct O(M+N) implementation; this is a known performance
> limitation, not a correctness issue.

---

## Merge Blockers (not context-quality spec items)

The following issues are in the branch but outside the scope of this spec delta.
Both MUST be resolved before merge:

- **BUG C3 — Submodule pointer:** The branch records `mutmut/` at upstream
  commit `56fc6a7` (missing all 7 local patches). The submodule pointer MUST
  be reset to `0431bc7` before merging.

- **Scope creep — pipeline.py regressions:** The branch's `pipeline.py` predates
  the async parallel generation merge (`worktree-agent-aaf84c48`). Merging it
  would remove `ErrorAction`, `classify_error`, `TrackedSemaphore`, and the
  SIGINT handler. Only the `scope.py` and `test_scope.py` changes from this
  branch should land; `pipeline.py` MUST be discarded or reconciled against main.

---

## Open Questions

1. **Target exclusion scope:** Should the target function be excluded only from
   its direct enclosing class context, or also from any nested-class or
   function-in-function context? The plan only discusses the top-level class.

3. **Class context size bound:** See Class Context Contract. Exact threshold
   and truncation algorithm (e.g., nearest-by-line-number vs alphabetical vs
   uncapped) are undecided. This blocks ratifying the "all signatures MUST be
   included" clause.

4. **Constants from conditional scopes:** `if __name__ == '__main__'` and
   `if TYPE_CHECKING:` constants are currently excluded. Is this the intended
   contract, or a known limitation to be fixed? `if TYPE_CHECKING:` in
   particular is widely used in typed code.

---

## Resolved Questions (closed from draft)

- **Open Question 2 (wildcard import policy):** Resolved as MUST include
  (conservative inclusion). See Wildcard imports section.

- **Open Question 5 (chained assignment extraction):** Resolved as already
  implemented correctly. `Assign.targets` yields all name targets; both `a`
  and `b` in `a = b = CONSTANT` are extracted.
