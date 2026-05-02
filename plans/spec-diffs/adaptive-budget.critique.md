# Adversarial Critique: Adaptive Budget Spec Delta

> Reviewed from: `plans/spec-diffs/adaptive-budget.draft.md`
> Cross-referenced: `plans/wave2-review-findings.md` H2, M1, M6

---

## Complexity Formula Precision Issues

### CF-1: The spec codifies a known bug as the behavioral contract

The draft specifies:
> "Branch count is the number of **regex word-boundary matches** of any keyword in this set against the raw source string."
> "**Critical implication**: keywords appearing inside string literals, comments, or f-string expressions ARE counted."

This is not spec precision — it is implementing a defect. If two implementations disagree about branch count (one uses regex, one uses AST), there is no correct answer under this spec. Both are compliant. A spec that says "count branches defined as the number of occurrences of these keywords in raw text including inside string literals" is not a behavioral contract — it's an implementation constraint dressed up as one.

**Gap:** The spec should specify the *semantic intent* (measure decision-point density) and separately document that the current implementation approximates this via text matching with known false-positive behavior. Saying "MUST use regex" ties all future implementations to a known-bad algorithm. Saying "MUST count branch-path-creating constructs" gives a testable behavioral contract.

### CF-2: `else` is counted — contradicts McCabe and the stated intent

`else` is in the keyword set. In standard cyclomatic complexity, `else` does NOT create a new branch — it is the default path of an existing `if`. Including `else` means every `if/else` pair counts as 2 when the actual branch complexity is 1. An `if/elif/elif/else` chain (4 keywords) produces a branch_bonus of 4//3 = 1, but the actual CC complexity increase is 3 (three conditions). The spec gives no rationale for counting `else`. The draft does not flag this.

**Gap:** Missing invariant about whether `else` is intentional. If intentional, justify it. If not, the keyword set is wrong and the formula produces incorrect relative rankings between functions that use if/else vs. bare if.

### CF-3: `elif` and `if` interaction is unspecified

The keyword set contains both `if` and `elif`. The regex `\b(if|elif|...)\b` applied to `elif x:` — does it match once (for `elif`) or twice? Order of alternation matters: `elif` appears first, so the match is `elif`. But the spec doesn't state this. An implementation using a different regex engine ordering, or applying `if` and `elif` patterns separately, would double-count. This must be unambiguous.

**Gap:** Specify that `elif` contributes exactly 1 to branch count, not 2.

### CF-4: Multiline `def` signatures not addressed

```python
def f(
    x: int,
    y: str,
) -> bool:
    return x > 0
```

The spec says subtract 1 for "the def line." This function has 6 lines of source, minus 1 (def line) = 5 effective lines. But the actual body is 1 line. Parameter list lines inflate effective count by 3. The spec does not address multi-line signatures, and for large dataclass-like functions with many parameters, effective lines could be dominated by signature boilerplate.

**Gap:** Does "the def line" mean only line 1, or the entire function signature up to `:` ?

### CF-5: Decorator lines are ambiguous

The spec says "verbatim source text as extracted at scope-resolution time." It does not say whether decorator lines (`@property`, `@staticmethod`) are included or excluded from the line count. If included, decorated functions get systematically higher budgets for reasons unrelated to body complexity.

**Gap:** Decorators must be explicitly in or out of the line count.

---

## Min/Max Semantics Gaps

### MM-1: No behavioral contract when `min > max` (M1 unfixed)

The draft documents the buggy behavior: when `min > max`, the implementation silently returns `max`, violating the stated minimum. It notes "should this raise ValueError?" but **does not specify the correct behavior**. A spec cannot say "it is unclear what MUST happen." Either:
- (a) `LLMConfig` MUST raise `ValueError` at construction when `min > max`, or
- (b) `compute_mutation_budget` MUST raise `ValueError` when called with `min_budget > max_budget`, or
- (c) the behavior when `min > max` is explicitly undefined (and callers must not do this)

The draft says none of these. It leaves the contract void.

**Verdict:** This is a speccing failure, not a documentation choice. Pick one, state it as MUST.

### MM-2: Minimum contract violated by truncation algorithm

The allocation algorithm in step 4 states: "If all functions are at 1 and the sum still exceeds total_budget, allocate only the first `total_budget` functions and exclude the rest." Excluded functions receive 0, which violates `min_per_function = 2`. The spec in section "Budget Allocation Contract" says "MUST receive at least as many mutations" in the unconstrained case — but the truncation case silently drops the per-function minimum.

**Gap:** The spec must explicitly state that the total-budget cap takes priority over per-function minimum, or that excluded functions are exempt from the minimum guarantee. Right now these two clauses contradict each other.

---

## Budget Determinism

### BD-1: Determinism depends on iteration order of `_extract_functions`

The allocation algorithm — specifically step 3 "decrement largest allocations first" and step 4 "allocate only the first N functions" — produces results that depend on iteration order. Two valid implementations that order `_extract_functions` differently (e.g., alphabetical vs. source order) would produce different budgets for the same file. The spec says nothing about what ordering is required.

**Gap:** The spec must either (a) guarantee source-order iteration, or (b) state that when multiple functions have equal raw budgets, allocation order is implementation-defined.

### BD-2: Proportional scaling produces non-deterministic results for equal raw budgets

Two functions with raw_budget=5 scaled by factor 0.6 both produce `int(5 * 0.6) = 3`. No ambiguity there. But `int(4 * 0.6) = 2` and `int(5 * 0.6) = 3`. Python's `int()` truncates. Is this the contract? What about rounding? The spec says "Scale all raw budgets proportionally (factor = total_budget / sum(raw_budgets))" and "Apply a floor of 1" but does not say whether rounding is floor (int()), round(), or ceiling. Different implementations will produce different sums.

**Gap:** Specify rounding mode for proportional scaling.

---

## Unit Definition Gaps

### UD-1: "Line" is not defined

The spec says "non-blank, non-comment lines." What is a line? The source text may use `\r\n`, `\r`, or `\n` line endings. The spec says "Split `S` on newlines" — which newline characters? Python `str.splitlines()` handles all; `str.split('\n')` does not handle `\r\n`. An implementation using `split('\n')` on Windows source would get different effective line counts.

**Gap:** Specify the line-splitting behavior.

### UD-2: Inline comments are not addressed

Line `x = 1  # setup` is not blank, does not start with `#`, and is correctly counted. But `x = 1  # if you need help` — the comment portion includes the word `if`, which bumps branch_count. The spec's "critical implication" acknowledges this for string literals but does not separately call out inline comments as a known false-positive source.

**Gap:** The known false-positive behavior should enumerate: string literals, docstrings, inline comments, and f-string expressions.

### UD-3: Docstring lines are inconsistently handled

The draft's edge case §4 notes: "The plan says non-docstring lines; the implementation only excludes blank/comment lines." The spec as written INCLUDES docstring lines in effective count (since `"""` does not start with `#`). For a function with a 15-line docstring and 3 lines of body, effective = 17, budget inflated by ~5. The plan's intent vs. implementation discrepancy is documented but the spec still codifies the implementation, not the intent.

**Gap:** The spec must pick one and commit. If docstrings are included, the spec should say so explicitly and explain why. If excluded, the implementation must be fixed before merge.

---

## Branch Count Definition Gaps

### BC-1: `with` in keyword set contradicts stated intent (edge case §1, unresolved)

The draft flags `with` as inflating budget for context-manager-heavy functions and notes "decision needed," but then the spec body states the keyword set as a MUST. The spec is internally inconsistent: it simultaneously says MUST include `with` and "this needs a decision." A spec cannot contain unresolved decisions in its normative section.

**Verdict:** Either resolve this before the spec is finalized, or move the `with` keyword to the Open Questions and mark the keyword set as provisional.

### BC-2: `try`/`except` double-counts

A `try`/`except` block contributes two keywords. In cyclomatic complexity, a `try/except` adds 1 (one branch path for the exception). The spec counts it as 2. For exception-heavy code (e.g., retry logic with multiple `except` clauses), the budget is systematically inflated. This produces higher budgets for defensive/safe code. The spec does not acknowledge this property.

**Gap:** Document that `try` and `except` each count independently and that exception handlers are double-weighted by design (or flag as a known distortion).

---

## Edge Cases Not Addressed

### EC-1: Complexity = 0 / 1 with `min_per_function = 0`

The spec says `min_per_function` defaults to 2. But if a caller passes `min_budget = 0`, then a 1-line function (effective=1, base=0, branch_bonus=0, raw=0) returns 0. Zero mutations requested. The validation pipeline never runs. Is `min_budget = 0` valid? The spec says "Return a value in `[min_budget, max_budget]` inclusive for all inputs" — technically a value of 0 for a function is allowed if min=0. But the downstream effect (no mutations generated for that function) is not documented.

### EC-2: `total_budget = 0`

No MUST statement covers `total_budget = 0`. The allocation algorithm: step 4 says "allocate only the first `total_budget` functions" — with `total_budget = 0`, all functions are excluded. Is this valid input? Should it raise, warn, or silently produce an empty allocation?

### EC-3: Single-function case with scaling

If there is one function and `total_budget = 1`, but raw_budget = 5, the scale factor is `1/5 = 0.2`, and `max(1, int(5 * 0.2)) = max(1, 1) = 1`. Fine. But if raw_budget = 0 and min = 2, the step "Apply floor of 1" produces 1, which is below `min_per_function = 2`. The clamping to `[min, max]` does not appear in the allocation algorithm — it only appears in `compute_mutation_budget`. The allocator operates on raw pre-clamped values and applies its own floor-of-1. These are two different floors with potentially different values. The interaction is undefined.

---

## Breaking Change Contract Missing

### BK-1: `max_mutations_per_function` default 5→10 has no migration contract (M6 unfixed)

The draft documents this as a bug/note but provides no behavioral contract for how breaking changes MUST be handled. A spec should state: "A change in a default configuration value that increases costs for existing users MUST be accompanied by a deprecation notice and/or opt-in mechanism." Without this, the spec implicitly permits silent cost doubling on upgrade indefinitely.

**Gap:** Either (a) specify the default as 5 and document 10 as an opt-in, or (b) specify a policy for how default changes are communicated, or (c) document that this feature requires opting in and the default budget behavior is unchanged until the user sets the config key.

### BK-2: No contract for migration from flat to adaptive budget

Before this feature, every function received `max_mutations_per_function` (flat) mutations. After, they receive `compute_mutation_budget(source, min, max)`. For short functions, this reduces mutations (from flat 5 to adaptive 2). For long functions, it increases them (from flat 5 to adaptive 10). The spec does not document this behavioral regression for the common case of small utility functions that previously received 5 mutations and now receive 2.

---

## Missing Invariants

### MI-1: Relationship to validation pipeline undefined

The budget `N` is passed to the LLM as a request count. If the LLM generates N candidates and K fail validation, does the pipeline retry to reach N valid mutations? Or does budget mean "LLM calls" not "valid mutations produced"? The spec says nothing about this. The `mutmut-llm/SPEC.md` presumably covers this, but the adaptive budget spec delta should state how budget interacts with validation.

### MI-2: Relationship between `compute_mutation_budget` and API call budget cap

The existing `mutmut-llm` spec (per draft 3 summary) distinguishes "budget allocation" from "API call budget cap." The adaptive budget delta uses `max_mutations_per_function` as both the per-function cap and the allocation bound. The spec does not clarify whether this is the same concept or a new one that supersedes or supplements the existing cap.

### MI-3: What "unconstrained total_budget" means in allocation contract

The ordering guarantee ("more complex MUST receive ≥ budget of less complex") is scoped to "unconstrained total_budget." But `total_budget` is an open question (OQ4) — its meaning is undefined. An invariant that holds under condition X, where X is undefined, is not a testable invariant.

### MI-4: No invariant about monotonicity within a single function

Given the same function, if `max_per_function` increases from 5 to 10, the budget MUST NOT decrease. This is an obvious property but is not stated. An implementation could clamp differently on different calls with different bounds and the spec would not catch it.

### MI-5: No invariant about `compute_mutation_budget` stability across calls

Given the same `source`, `min_budget`, and `max_budget`, calling `compute_mutation_budget` twice MUST return the same result (pure function, already stated). But: is the function thread-safe? The spec says no side effects, but does not say the function MUST be safe to call concurrently, which matters for the async parallel generation path.

---

## Verdict

**The spec delta is not ready for merge sign-off.** Specific blockers:

1. **The branch-count contract codifies a known bug** (regex on raw text). This is not a behavioral contract — it is a constraint on implementation strategy. Two implementations using different counting methods would both be "spec-compliant" but produce different results. The spec must either (a) specify semantic branch-point counting and document the known approximation as a quality-of-implementation note, or (b) explicitly state "the textual approximation IS the contract, including false positives" and accept that consequence.

2. **`min > max` behavior is unspecified.** The contract is void for this case. M1 from the wave2 review remains unfixed and unspecified.

3. **The total_budget/min_per_function contradiction** (EC-3, MM-2) means the allocation invariants are mutually inconsistent for constrained budgets.

4. **Four unresolved normative decisions** are embedded in the spec body (with/elif counting, else counting, docstring exclusion, iteration order) without resolution — making the spec non-normative in the sections where it appears most precise.

5. **B4 (LLMConfig field deletion)** is a merge-blocker that the spec makes no mention of. The spec delta should note that the branch drops `min_concurrency`, `max_concurrency`, `max_retries`, `base_backoff_seconds`, and `request_timeout_seconds` from `LLMConfig`, and that this MUST be restored before merge.

**Recommended revision priorities:**
1. Decouple semantic intent from implementation mechanism for branch counting
2. Specify `min > max` behavior as MUST (ValueError or MUST NOT be called)
3. State that total_budget cap takes precedence over per-function minimum (or redesign)
4. Resolve the `with`/`else` keyword decisions before marking any MUST as final
5. Add migration contract for flat→adaptive behavioral change
