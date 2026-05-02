# Spec Delta: Adaptive Budget (mutmut-llm)

> RFC 2119 keywords apply. This document specifies behavioral contracts that MUST be added to
> `mutmut-llm/SPEC.md` if the `worktree-agent-a225536b` branch is merged.
>
> **Merge prerequisites** are listed at the end. The spec is written assuming they have been satisfied.

---

## Purpose of This Feature

The adaptive budget replaces the flat per-function mutation count with a complexity-weighted
allocation. Each function's mutation budget is proportional to its estimated complexity, subject
to per-function bounds and a global budget cap.

---

## Complexity Measurement Contract

### Semantic intent

The budget estimator approximates the decision-point density of a function. It MUST produce
a non-negative integer for any non-empty function source. It MUST produce higher estimates for
functions with more branches and more code than for functions with fewer.

### Textual approximation (current implementation contract)

The implementation approximates decision-point density via textual keyword counting. This is a
**known approximation**, not exact cyclomatic complexity. Both the intent and the approximation
are part of the contract: the intent defines correctness direction; the approximation defines
the deterministic rule an implementation MUST follow.

**Effective line count** — computed from the raw function source string `S`:

1. Split `S` on `str.splitlines()` (handles `\n`, `\r\n`, `\r` uniformly).
2. Remove lines that are empty or contain only whitespace.
3. Remove lines whose first non-whitespace character is `#` (full-line comments only).
   Inline comments (e.g., `x = 1  # note`) are NOT excluded — the entire line counts.
4. Count the remaining lines; call this `N`.
5. `effective = max(1, N - 1)` — subtract 1 for the `def` line.

"The def line" means line 1 of `S` only. For multi-line function signatures, all parameter
list lines are included in the effective count.

Decorator lines (`@decorator`) MUST NOT be included in `S` — they are stripped at scope-
resolution time before this function is called.

Docstring lines ARE included in the effective count (the current implementation does not strip
`"""..."""` blocks). This is a **known gap** from the stated intent; see Bugs / Inconsistencies.

**Branch density count** — a textual approximation of branching constructs:

The keyword set is: `{if, elif, else, for, while, try, except, with}`.

Branch count is the number of regex word-boundary matches (`\b(keyword)\b`) of any keyword in
this set against the full source string `S`, **including occurrences inside string literals,
inline comments, docstrings, and f-string expressions**.

This is a textual approximation. The following false-positive sources are known and accepted:
- String literals: `msg = "if this fails, try again"` adds 2 to branch count.
- Inline comments: `x = 1  # elif branch` adds 1.
- Docstring text: any branch keyword in a docstring adds to the count.
- f-string expressions: keywords inside `{}` are counted.

**Known deviations from standard cyclomatic complexity** (intentional, not bugs):

- `else` is counted: a `try/else` or `if/else` block counts 2 instead of 1. This is intentional
  — every explicitly-named code path is a measurement signal, not just decision points.
- `elif` is counted as 1 (not 2): the regex matches `elif` as a single token; `if` inside
  `elif` is NOT double-counted.
- `try` and `except` each count independently: a `try/except` block contributes 2. Exception-
  heavy code receives proportionally higher budgets. This is intentional.
- `with` is counted: context managers contribute to branch density. Standard McCabe does not
  count `with`; this implementation does. This inflates budgets for resource-management-heavy
  functions. This is intentional.

**Budget formula** (MUST be applied exactly):

```
base         = effective // 3
branch_bonus = branch_count // 3
raw          = base + branch_bonus
budget       = max(min_budget, min(max_budget, raw))
```

Integer division (`//`) truncates toward zero. The `max(min, min(max, raw))` clamp is applied
after integer division.

---

## `compute_mutation_budget` Contract

`compute_mutation_budget(source: str, min_budget: int, max_budget: int) -> int` MUST:

- Return a value in `[min_budget, max_budget]` inclusive for any `source`.
- Return `min_budget` when `source` is empty or all-whitespace.
- Apply the exact formula above without deviation.
- Be a pure function: no network calls, no file I/O, no mutable state, no side effects.
- Be thread-safe: safe to call concurrently from multiple threads or async tasks with independent arguments.

`compute_mutation_budget` MUST NOT be called with `min_budget > max_budget`. Callers bear
responsibility for ensuring this precondition. If called in violation, behavior is undefined.

---

## Configuration Contract

Two new fields are added to `LLMConfig`:

| Field | Type | Default | Config key |
|-------|------|---------|------------|
| `min_mutations_per_function` | `int` | `2` | `[tool.mutmut.llm] min_mutations_per_function` |
| `max_mutations_per_function` | `int` | `10` | `[tool.mutmut.llm] max_mutations_per_function` |

`load_config` MUST validate that `min_mutations_per_function <= max_mutations_per_function`
after reading both fields. If the constraint is violated, `load_config` MUST raise `ValueError`
with a message identifying both values. Silent clamping or defaulting is not permitted.

`LLMConfig.__post_init__` MUST also validate this constraint so that programmatic construction
fails fast: `LLMConfig(min_mutations_per_function=10, max_mutations_per_function=3)` MUST raise
`ValueError`.

**Breaking change:** The default for `max_mutations_per_function` changed from 5 to 10 in this
branch. Users who upgrade without changing config will see up to double the API usage for
functions that previously hit the cap. See Migration section.

---

## Budget Allocation Contract

`_allocate_budget(raw_budgets: dict[str, int], total_budget: int) -> dict[str, int]` MUST:

1. When `sum(raw_budgets.values()) <= total_budget`: return `raw_budgets` unchanged (no scaling).
2. When `sum(raw_budgets.values()) > total_budget`: apply proportional scaling:
   a. Compute `scale = total_budget / sum(raw_budgets.values())`.
   b. For each function: `scaled = max(1, int(raw * scale))` (floor rounding, then floor-of-1).
   c. If `sum(scaled) > total_budget`: decrement the largest values (by source-file order for
      tie-breaking) until the sum equals `total_budget`.
   d. If after all values are at 1 the sum still exceeds `total_budget`: retain only the first
      `total_budget` functions in source-file order (top-to-bottom). The remaining functions
      receive allocation 0 and are excluded from mutation generation for this run.
3. Never return a sum exceeding `total_budget`.

**Source-file order** means the order `_extract_functions` produces functions, which MUST be
top-to-bottom declaration order within each file.

**Total budget precedence:** The `total_budget` cap takes unconditional precedence over
`min_per_function`. Excluded functions (allocation 0) are not considered violations of the
per-function minimum. The per-function minimum applies only to functions that receive a
non-zero allocation.

**Complexity-ordering property:** When `total_budget` is unconstrained (case 1), functions with
higher raw budget values MUST receive allocations ≥ functions with lower raw budget values.
This is a best-effort property under scaling (case 2): after floor rounding, two functions with
different raw budgets may receive equal allocations; this is permitted.

**Edge cases:**
- `total_budget = 0`: all functions receive allocation 0 (empty result). This is valid input,
  not an error.
- `raw_budgets` is empty: return empty dict.
- Single function with `raw = 0` and `total_budget >= 1`: scaling produces `max(1, 0) = 1`
  (floor-of-1 applies). The `compute_mutation_budget` clamp to `min_per_function` does NOT
  apply inside the allocator — the allocator operates on pre-clamped raw values and applies
  only its own floor-of-1. Callers MUST pass pre-clamped values if they want the min guarantee.

---

## `resolve_scope_deep` Contract

`resolve_scope_deep(paths, budget, max_per_function, min_per_function=2)` MUST:

- Pass `min_per_function` and `max_per_function` unmodified to `compute_mutation_budget`.
- Pass the resulting raw budgets and `budget` to `_allocate_budget`.
- Default `min_per_function` to 2 when not supplied by caller.

Budget semantics: `budget` represents the maximum number of LLM generation calls across all
functions in `paths` for this invocation. It is NOT a guarantee of valid mutations produced.
If the LLM generates `N` candidates for a function and `K < N` fail validation, the function
receives `K` valid mutations — the budget is not retried to reach `N`.

---

## Migration Contract

**Behavioral change from flat to adaptive:**

Before this feature, each function received exactly `max_mutations_per_function` mutations.
After this feature, each function receives `compute_mutation_budget(source, min, max)` mutations.

For functions with ≤ 5 effective lines (body only): adaptive budget returns `min_per_function`
(2 by default), reduced from flat 5. This is a **behavioral regression for small utility
functions**. Callers who relied on receiving at least 5 mutations per function MUST update their
expectations or set `min_mutations_per_function = 5`.

**Default change (max 5→10):**

Users upgrading from a version with flat budget `max = 5` to this version will see:
- Small functions: fewer mutations (flat 5 → adaptive 2)
- Large/complex functions: more mutations (flat 5 → adaptive up to 10)
- Net API cost: depends on codebase; can increase or decrease

This change SHOULD be communicated in the changelog. No opt-in flag is required by this spec,
but the default change MUST be documented as a potentially breaking cost change.

---

## Known Limitations / Accepted Trade-offs

- **Docstring inflation:** Multi-line docstrings inflate effective line count since `"""` lines
  are not excluded. A 15-line docstring with 2 lines of body gives effective=16 instead of 2.
  This is a known gap from the stated intent. Fixing it requires stripping docstring nodes
  before counting, which requires an AST/CST parse.
- **String/comment keyword inflation:** Branch count includes keywords in string literals,
  inline comments, and docstrings. This produces false positives for documentation-heavy code.
- **`else`/`with`/`try` deviations from McCabe:** Documented above under Branch Density Count.
- **Iteration-order exclusion:** When total budget is exhausted, functions later in the file
  are systematically excluded. There is no signal to the caller about which functions were
  skipped. This is a known limitation — callers SHOULD increase `budget` or reduce file scope.

---

## Open Questions

1. **Docstring exclusion:** Should docstring lines be excluded from effective line count (requires
   AST parse pass before counting)? The intent says yes; the implementation says no. This spec
   documents the implementation behavior. If fixed, the effective-line contract changes.

2. **`compute_mutation_budget` public API stability:** Is this function part of the stable public
   API (callable by plugins)? If yes, it needs a stability guarantee in the main SPEC.md.

3. **Excluded function reporting:** Should `ScopeResult` carry a list of functions that received
   allocation 0 due to budget exhaustion? Currently there is no such signal.

4. **Complexity-ordering under scaling:** Should the ordering property be a hard guarantee even
   after proportional scaling and floor rounding? Currently it is best-effort only.

---

## Bugs / Inconsistencies in Branch Implementation

### B1. Branch count uses regex on raw source (H2 — UNFIXED)

`_branch_count` applies a regex match to the raw source string. See Complexity Measurement
section for enumerated false-positive sources. This is the current contract; fixing it requires
switching to AST node counting and changes this spec.

### B2. `min > max` silently misbehaves (M1 — UNFIXED, BLOCKED)

`compute_mutation_budget(source, min_budget=10, max_budget=3)` evaluates as
`min(3, max(10, raw)) = 3` always — `min` is silently violated. This MUST be fixed by adding
validation in `LLMConfig.__post_init__` and `load_config` per the Configuration Contract above.
**This branch MUST NOT be merged until this fix is present.**

### B3. Default `max_mutations_per_function` doubled (M6 — UNFIXED, DOCUMENTED)

Default changed from 5 → 10. See Migration Contract. This is intentional but undocumented.
Must be noted in the changelog before merge.

### B4. `LLMConfig` drops concurrency and retry fields (HIGH — MERGE BLOCKER)

The branch removes `min_concurrency`, `max_concurrency`, `max_retries`, `base_backoff_seconds`,
and `request_timeout_seconds` from `LLMConfig`. These fields exist on `main` and are specified
in the existing `mutmut-llm` spec. Merging this branch would silently delete async concurrency
configuration. **This MUST be restored before merge** — the adaptive budget feature is
independent of these fields and their removal appears to be an artifact of branching from an
intermediate commit.

### B5. `load_config` does not validate `min <= max` relationship

`load_config` reads both fields independently but never validates `min <= max`. Must be fixed
per the Configuration Contract.

---

## Merge Prerequisites

The following MUST be resolved before this branch is merged:

| # | Issue | Required action |
|---|-------|----------------|
| P1 | B4: LLMConfig drops concurrency fields | Restore `min_concurrency`, `max_concurrency`, `max_retries`, `base_backoff_seconds`, `request_timeout_seconds` |
| P2 | B2: `min > max` silent misbehavior (M1) | Add `ValueError` validation in `LLMConfig.__post_init__` and `load_config` |
| P3 | B5: No `min <= max` validation in `load_config` | Add validation (same fix as P2) |
| P4 | B3: Default change undocumented (M6) | Add changelog entry noting cost impact |
| P5 | H2: Regex branch counting (wave2) | Out of scope for this merge — document in known limitations and open a follow-up issue |
