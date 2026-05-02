# Adversarial Critique: Dynamic Exclusion Spec Delta

> Grounded in actual implementation at `.claude/worktrees/agent-a9c42fae/mutmut-llm/src/mutmut_llm/prompts.py` and `pipeline.py`.

---

## Timing Contract Precision

**Verdict: Under-specified. The MUST statement is not where it should be.**

The spec states: "The exclusion list MUST be built at **generation-run time**, not at module import time." This is correct in intent but places the only operative MUST in a rationale paragraph. The actual requirement — "The canonical call point is once per `run_generation()` invocation, before the per-target loop begins" — is in a prose rationale comment, not a MUST statement.

Problems:
1. "Generation-run time" is not defined. Does it mean: when the first LLM call is made? When `run_generation()` is entered? After all `mutmut_configure` hooks have fired? The implementation calls it at the start of `_generate_mutations()`, which is one call per `run_generation()` — but the spec doesn't mandate this.
2. "At first use" and "once per run" are observationally distinct if plugins can register mid-run. The spec should state explicitly: MUST be called after all plugins have registered and before any LLM API call. "Generation-run time" does not imply this.
3. The pipeline (`pipeline.py:94`) does the right thing; the spec should describe that contract, not just the prohibition.

**Required fix:** Add as a MUST: "MUST be called after plugin registration is complete and before the first LLM API call of the run. MUST NOT be called during module import."

---

## Determinism / Ordering Issues

**Verdict: Raised as open question but should be resolved before spec is ratified.**

The code (`prompts.py:112-121`) iterates operators in plugin hook invocation order — which is pluggy's registration order, not alphabetical. The spec acknowledges this as Open Question 2: "the spec should state whether the exclusion list order is deterministic."

This is not just cosmetic. If the system prompt content changes between runs (because plugin registration order is non-deterministic), Anthropic prompt-caching keyed on system-prompt content will miss. A different prompt → new cache entry every run.

The spec should resolve this, not leave it open. Two viable options:
- MUST sort descriptions alphabetically before formatting (deterministic, cache-friendly)
- MUST document that order is unspecified and implementors MUST NOT rely on it

Leaving it open means the spec cannot be used to verify correct behavior.

---

## Fallback Contract Gaps

**Verdict: Incomplete. One case undocumented; one case mislabeled.**

**Gap 1: Non-empty `operator_lists` with all-empty sublists.** The spec specifies:
- `operator_lists=[]` → hardcoded fallback ✓
- `operator_lists=None` + empty hook result → hardcoded fallback ✓
- `operator_lists=None` + import failure → hardcoded fallback ✓

But `operator_lists=[[]]` (list of one empty sublist) is unspecified. The code handles it correctly (falls through to `return "\n".join(lines) if lines else _HARDCODED_EXCLUSIONS`), but the spec doesn't cover it. If the spec is used to write an alternative implementation, this case would be ambiguous.

**Gap 2: "When `operator_lists` is an empty list `[]`"** — the spec says the return MUST be the hardcoded exclusion string. But the code does `if not operator_lists: return _HARDCODED_EXCLUSIONS`. This also covers `operator_lists=None` (before the None-query branch). The spec conflates the explicit-empty-list case with the None-query case in a way that misrepresents the branching logic.

**Gap 3: Fallback content contract.** The spec says "The fallback MUST be the complete hardcoded exclusion list, not an empty string." But `_HARDCODED_EXCLUSIONS` is a string constant; nothing prevents future edits from changing it. The spec should define the minimum required content (which it partially does via the bullet list) but should make explicit that the fallback cannot be empty or partial.

---

## Security Contract Missing or Weak

**Verdict: MUST stated but implementation currently VIOLATES it. Spec should flag this explicitly.**

The spec states: "The substitution MUST NOT fail when operator docstrings contain literal brace characters." This is the correct post-fix contract. But the current implementation at `prompts.py:148`:
```python
return SYSTEM_PROMPT_TEMPLATE.format(exclusion_list=exclusion_list)
```
currently VIOLATES this MUST. An operator with docstring `"Swap {a} and {b}"` causes `KeyError`.

A spec delta that states a MUST which the branch implementation violates is a spec for an unfixed branch, not a spec for what can be merged. The spec must either:
- Mark this MUST with "(currently violated — see BUG-3)" to indicate merge is blocked on this fix, or
- Move it to the bugs section rather than the normative contract section.

Ratifying a MUST that the code breaks risks merging a spec and code that are already inconsistent.

Additionally: the spec only prohibits `KeyError` and `ValueError`. It should also prohibit crashing for `{:format_spec}` patterns (which raise `ValueError`) and `{0}` positional references (which would be substituted if `format()` sees them). The fix (use `.replace()`) eliminates all these at once; the spec should specify the fix approach, not just enumerate failure modes.

---

## No-Docstring Handling

**Verdict: Spec covers the happy path; the degenerate-quality case is buried in "INCONSISTENCY-1".**

The spec correctly specifies: when `__doc__` is absent, fall back to `"{name} (targets {NodeType} nodes)"`. This is specified as a MUST.

However, the spec does not address:
1. **What if `__name__` is also absent?** The code does `getattr(fn, "__name__", "unknown")`. The spec says "derived from the callable's `__name__`" — but says nothing about the `__name__`-absent case. If `__name__` is absent, the description becomes `"unknown (targets X nodes)"`. This is a valid behavior but should be explicit.
2. **Quality floor.** The spec raises Open Question 5 ("Should the spec require meaningful descriptions?") but punts the decision. The consequence is documented under INCONSISTENCY-1: with 1/20 operators having a docstring, the dynamic exclusion list is likely LESS informative to the LLM than the hardcoded fallback. This is a design-intent mismatch that a spec should resolve, not defer.
3. **Multi-line docstrings.** The spec says "first non-empty line of the callable's `__doc__`." The code does `doc.strip().split("\n")[0].strip()`. What if the first line of the docstring is a blank line? `doc.strip()` removes leading/trailing whitespace, so leading blank lines are stripped before the split. This behavior is implicitly correct but not stated in the spec.

---

## LLM Behavioral Guarantee Ambiguity

**Verdict: Critical gap. The spec specifies HOW the list is built but says NOTHING about what effect it should have.**

The entire feature is called "dynamic EXCLUSION list" — yet the spec contains zero statements about what the LLM MUST or SHOULD do with it. The spec specifies:
- How the list is built ✓
- How it's formatted ✓
- When it's constructed ✓

Missing:
- Whether the LLM MUST NOT generate excluded mutation types (it cannot — LLMs are probabilistic)
- Whether the exclusion list is a hard prohibition, a soft hint, or guidance only
- What the caller can rely on: reduced duplication? zero duplication? lower probability only?

Without this, the "exclusion" framing implies a guarantee the system cannot provide. The spec should explicitly state something like: "The exclusion list SHOULD reduce the frequency with which the LLM generates mutation types already covered by rule-based operators. It does NOT guarantee the LLM will never generate such mutations; it is best-effort guidance."

Omitting this creates false expectations in consumers and makes the feature non-falsifiable.

---

## Deduplication Not Fully Addressed

**Verdict: Narrow. Three distinct gaps.**

**Gap 1: Deduplication granularity.** The spec says "Duplicate descriptions (same string from different operators) MUST be suppressed." The code deduplicates on the raw description before the `  * ` prefix is added (`if desc not in seen`). The spec should say this clearly: deduplication is on the raw description string, case-sensitive, exact-match.

**Gap 2: Same-plugin duplicates.** The spec says "from different operators" but the code deduplicates across ALL pairs, regardless of source. If the same plugin returns two operators with the same description (possible if two operators have the same first docstring line), the spec's "from different operators" wording would not require deduplication. The code deduplicates it anyway. The spec should be: "duplicate descriptions MUST be suppressed regardless of source."

**Gap 3: Deduplication vs. cross-plugin coverage.** If plugin A and plugin B both implement `operator_return_none` and both have docstring "Remove return value", they deduplicate to one entry. The spec should note this as an accepted consequence: one entry means both operators are mentioned implicitly, but a consumer cannot know two separate operators were deduplicated.

---

## `build_system_with_context` Entirely Unspecified

**Verdict: Blocker. This is the function with the import-time bug and it has no contract in the spec.**

`build_system_with_context` (`prompts.py:156`) is the actual function called by the pipeline (`pipeline.py:192`). The spec delta says nothing about it. Yet:

1. It has the import-time fallback bug (Open Question 4 in the draft).
2. It produces the multi-block structure for Anthropic's prompt caching — the semantics of `ttl`, `cache_control`, and context block assembly are not specified.
3. Its `system_prompt=None` default silently uses the stale `SYSTEM_PROMPT` constant.

Open Question 4 — "Should `build_system_with_context` always require an explicit `system_prompt` argument?" — answers itself from the timing contract: yes. This should be a MUST NOT in the spec: "MUST NOT default `system_prompt` to a module-level constant built at import time. Callers MUST pass an explicit `system_prompt` constructed after plugin registration."

The function's existence, signature, and contract should be in the spec since it is part of the public API of this feature.

---

## Verdict

The draft is grounded in the code and correctly identifies the known bugs. However, it has several structural problems that prevent it from being a usable spec:

| Category | Status |
|---|---|
| Timing contract | Weak — MUST in rationale text, not in normative section |
| Determinism | Unresolved open question — ordering affects cache hit rates |
| Fallback coverage | Incomplete — `[[]]` case missing; all-empty-sublists undocumented |
| Security MUST | Stated but violated by current code — must be flagged |
| LLM guarantee | Entirely absent — major false-expectation risk |
| Deduplication | Partially specified — granularity and cross-plugin cases missing |
| `build_system_with_context` | Not specified at all — blocks open question 4 resolution |
| `__name__`-absent case | Not specified |

**Recommended revisions before ratification:**
1. Promote timing rationale to MUST in normative section with precise definition.
2. Resolve determinism (mandate alphabetical sort or explicit undefined-order declaration).
3. Add `build_system_with_context` contract section — it is part of this feature's public surface.
4. Add LLM best-effort disclaimer — "exclusion list is guidance, not a guarantee."
5. Flag BUG-3 in the security MUST as "currently violated — merge blocked on fix."
6. Resolve Open Question 4 as a MUST NOT.
