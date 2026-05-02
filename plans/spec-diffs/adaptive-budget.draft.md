# Spec Delta: Adaptive Budget (mutmut-llm)

> RFC 2119 keywords apply. This document specifies behavioral contracts that MUST be added to
> `mutmut-llm/SPEC.md` if the `worktree-agent-a225536b` branch is merged.

---

## New Behavioral Contracts

### Complexity Measurement

The system MUST compute a per-function mutation budget based on two signals derived from the
function's source text:
- **Effective line count** — non-blank, non-comment lines, minus 1 for the `def` line.
- **Branch keyword count** — occurrences of the keywords `if`, `elif`, `else`, `for`, `while`,
  `try`, `except`, `with` in the source text.

The budget formula MUST be:
```
base        = effective_lines // 3
branch_bonus = branch_keyword_count // 3
raw_budget   = base + branch_bonus
budget       = clamp(raw_budget, min_per_function, max_per_function)
```

The measurement MUST be applied to the verbatim source text of each function as extracted at
scope-resolution time.

### `compute_mutation_budget` Contract

The function `compute_mutation_budget(source, min_budget, max_budget) -> int` MUST:
- Return a value in `[min_budget, max_budget]` inclusive for all inputs.
- Return `min_budget` for empty source strings.
- Exclude blank lines and lines whose first non-whitespace character is `#` from the effective
  line count.
- Treat the function definition line (`def …:`) as one line that is subtracted from the
  effective count (via `max(1, raw_count - 1)` with a floor of 1 before the subtraction).

`compute_mutation_budget` MUST NOT make network calls, read files, or have side effects.

### Budget Allocation Contract

Budget allocation MUST be complexity-weighted: functions with higher computed budget values MUST
receive at least as many mutations as functions with lower computed budget values when the
total API budget is unconstrained (i.e., `sum(raw_budgets) <= total_budget`).

When `sum(raw_budgets) > total_budget`, the allocator MUST:
1. Scale all raw budgets proportionally (factor = `total_budget / sum(raw_budgets)`).
2. Apply a floor of 1 to each scaled value.
3. Reduce excess (sum > total_budget) by decrementing the largest allocations first.
4. If all functions are at 1 and the sum still exceeds total_budget, allocate only the first
   `total_budget` functions (in iteration order) and exclude the rest.

The sum of all allocated budgets MUST NOT exceed `total_budget` under any input.

### Scope Resolution Contract

`resolve_scope_deep(paths, budget, max_per_function, min_per_function)` MUST pass both
`min_per_function` and `max_per_function` to the budget allocator unchanged.

The `min_per_function` parameter MUST default to `2` when not specified by the caller.

---

## Configuration Additions

| Key | Type | Default | Pyproject key |
|-----|------|---------|---------------|
| `min_mutations_per_function` | `int` | `2` | `[tool.mutmut.llm] min_mutations_per_function` |
| `max_mutations_per_function` | `int` | `10` | `[tool.mutmut.llm] max_mutations_per_function` |

**Note:** `max_mutations_per_function` default changed from `5` to `10` in this branch. See
Bugs/Inconsistencies section.

`LLMConfig` MUST expose both fields. `load_config` MUST read both from `[tool.mutmut.llm]`
when present and pass them through to `resolve_scope_deep`.

---

## Complexity Measurement Contract — Detailed

### What "effective lines" means

Given function source `S`:
1. Split `S` on newlines.
2. Remove lines that are blank (all whitespace).
3. Remove lines whose first non-whitespace character is `#`.
4. Count remaining lines; call this `N`.
5. `effective = max(1, N - 1)` — the `- 1` removes the `def` line.

### What "branch keywords" means

The keyword set is: `{if, elif, else, for, while, try, except, with}`.

Branch count is the number of **regex word-boundary matches** of any keyword in this set
against the raw source string. This is a textual match, not an AST match.

**Critical implication**: keywords appearing inside string literals, comments, or f-string
expressions ARE counted. `msg = "if you see this"` adds 1 to the branch count.

### Budget formula

```
base         = effective // 3
branch_bonus = branch_count // 3
raw          = base + branch_bonus
budget       = max(min_per_function, min(max_per_function, raw))
```

For a 1-line function: effective=1, base=0, branch_bonus=0, raw=0 → budget = min_per_function.

---

## Edge Cases That Need Specifying

### 1. `with` counted as a branch keyword

`with` is included in the branch keyword set. Standard McCabe cyclomatic complexity does NOT
count `with` — it introduces no new branch path. Including `with` inflates the branch bonus for
functions that use context managers. The spec should declare whether `with` is intentionally
included or a mistake.

**Decision needed:** Should `with` remain in the branch keyword set?

### 2. Relative ordering NOT guaranteed after scaling

When total_budget forces proportional scaling + trimming, the complexity-weighted ordering
guarantee only holds weakly. After `max(1, int(v * scale))` flooring, two functions with
different raw budgets may receive the same scaled allocation. Trimming then reduces the largest
values, further eroding ordering. The test `test_scaling_preserves_relative_order` checks only
`>=`, not strict `>`.

**Decision needed:** Should ordering be a hard guarantee even after scaling, or only
a best-effort property?

### 3. Functions excluded from allocation (budget exhausted)

When total_budget < number of targets (after all are at 1), some functions receive no allocation
and are silently excluded from mutation. The test `test_total_never_exceeds_budget` no longer
asserts `all(v >= 1)` — the old test did. There is no documentation or observable signal to the
caller about which functions were excluded.

**Decision needed:** Should excluded functions be reported to the caller? Should `ScopeResult`
carry a list of skipped targets?

### 4. Docstring lines in line count

The plan description says "non-blank, non-comment, non-docstring" lines. The implementation
only excludes blank lines and `#`-prefixed lines. Multi-line docstrings (`"""..."""`) are NOT
excluded from the effective line count. A 10-line docstring inflates the budget.

**Decision needed:** Should docstring lines be excluded from effective line count?

### 5. Iteration order of exclusion

When budget exhausts (case 4 above), functions are included in iteration order (the order
`_extract_functions` produces them, typically top-to-bottom in file). Later functions in large
files may be systematically excluded.

**Decision needed:** Should the allocator prioritize higher-complexity functions before simpler
ones when truncating?

---

## Open Questions

1. **min > max behavior (unresolved M1):** When `min_mutations_per_function > max_mutations_per_function`,
   the implementation silently returns `max` for every function, rendering `min` ineffective.
   Should this raise `ValueError` at config load time? The wave2 review (M1) says yes, but the
   fix is not present in the branch.

2. **Default max change (unresolved M6):** `max_mutations_per_function` default changed from 5
   to 10. Users who upgrade without changing config will see doubled API costs. Is this a
   breaking change? Should it be gated on an explicit "opt into adaptive budget" flag, or is the
   doubling acceptable because smaller functions now get fewer (2) mutations instead of the old
   flat 5?

3. **`compute_mutation_budget` as public API:** The function is importable from `mutmut_llm.scope`.
   Is this part of the public API surface (callable by plugins/users) or an internal detail?
   If public, it needs stability guarantees.

4. **What is `total_budget` semantically?** In `resolve_scope_deep`, `budget` is the parameter
   name. In `_allocate_budget`, it's `total_budget`. The spec needs to declare what this number
   represents: total mutations across all functions? Total API calls? Something else?

---

## Bugs / Inconsistencies in Branch Implementation

### B1. Branch count uses regex on raw source (H2 from wave2-review-findings.md — UNFIXED)

`_branch_count` applies a regex word-boundary match to the raw source string. Keywords inside
string literals, comments, and f-strings are counted as branches. Example:
```python
def f():
    msg = "if you see this error, try again"  # counted: if=1, try=1 → branch_bonus += 0 (6//3=2 needed)
    return msg
```
This function has 0 actual branches but `_branch_count` returns 2, adding 0 to branch_bonus
(2//3=0), but for strings with more keywords the overcounting compounds.

### B2. `min > max` silently misbehaves (M1 from wave2-review-findings.md — UNFIXED)

```python
config = LLMConfig()
config.min_mutations_per_function = 10
config.max_mutations_per_function = 3
```
`compute_mutation_budget(source, min_budget=10, max_budget=3)` evaluates as
`min(3, max(10, raw)) = min(3, 10) = 3` always. `min` is silently ignored and the declared
minimum is violated. No `ValueError` is raised.

### B3. Default `max_mutations_per_function` doubled (M6 from wave2-review-findings.md — UNFIXED)

Default changed from 5 → 10. This is a silent breaking change for existing users: without
any config change, the maximum per-function mutations doubles. For projects where many functions
are complex enough to hit the cap, API costs double on upgrade. The change is not noted in any
changelog or migration guide.

### B4. `__post_init__` validation removed for several fields

The branch removes validation for `min_concurrency`, `max_concurrency`, `max_retries`,
`base_backoff_seconds`, and `request_timeout_seconds` from `LLMConfig.__post_init__`. This
appears to be an unintentional diff artifact — these fields are removed from the dataclass
entirely, not just their validation. This suggests the branch was based on an intermediate
working state that removed the async concurrency config. The current `main` has these fields;
merging this branch would drop them. **This is a HIGH-severity merge risk.**

### B5. No validation that `min_per_function <= max_per_function` at config load time

`load_config` reads `min_mutations_per_function` and `max_mutations_per_function` from TOML
independently but never validates their relationship. The `__post_init__` only validates
`cache_ttl`.
