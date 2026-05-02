# Adversarial Critique Summary: mutmut-dedup Spec

**Critique written to:** `mutmut-dedup/SPEC.md.critique`
**Draft reviewed:** `mutmut-dedup/SPEC.md.draft`
**Issues found:** 14 (2 CRITICAL, 5 HIGH, 5 MEDIUM, 2 LOW)

---

## Verdict: Do Not Ratify

Two blocking issues prevent ratification.

---

## CRITICAL Issues

### FP1 — False positive guarantee contradicts the annotation caveat
The "MUST NOT occur" guarantee in the Correctness section is directly contradicted by the Phase 1 False-Positive Caveat section, which documents an annotation-related false positive case. A MUST NOT with a documented exception is not a MUST NOT. The guarantee must be scoped precisely (exclude annotation-only behavioral differences) or demoted to SHOULD NOT.

### E1 — "Top-level function" undefined for class methods, nested functions, lambdas, async
`contained_by_top_level_function` is the core concept driving Phase 2 applicability, yet "top-level function" is never defined. Class methods (the most common mutation target in OO code) have ambiguous status — are they "top-level functions"? Nested functions? Async functions? Lambdas? All of Phase 2's scope depends on this definition.

---

## HIGH Issues

### G1 — "bytecode-equivalent" defined cross-site, dedup key is site-scoped
The general "bytecode-equivalent" definition implies cross-site deduplication. The "bytecode-duplicate" subtype restricts to the same `(original_node, containing_function)` pair. These contradict each other on cross-site pairs that produce identical mutated-function bytecode. Remove the general definition or explicitly scope it.

### FP3 — Dead guard may cause false-positive removal of orphaned mutations
The spec documents a guard (`if mutated_func is func: keep`) for orphaned mutations. The draft spec itself noted (B2) that this guard is dead code since libcst always returns a new object from `deep_replace`. If true, orphaned mutations are silently removed as original-equivalent, violating the false-positive guarantee. Must resolve: does the guard fire or not?

### FP2 — "Normal operation" is undefined
The guarantee "MUST NOT occur in normal operation" has an undefined scope. The exclusions (reconstruction failure, compilation failure, annotation effects) are not part of the guarantee statement.

### V1 — Phase 1 has undocumented Python version sensitivity
`ast.dump` output changed in Python 3.12 (`type_params` field added to `FunctionDef`, `ClassDef`, `AsyncFunctionDef`). Phase 1 equivalence results are Python-version-dependent, but the version sensitivity section only covers Phase 2. The Non-Goal "Deterministic across Python versions" should explicitly cover both phases.

### IC1 — Granularity of `mutations` list is unspecified
The spec does not state whether the hook receives all mutations for a file, per-function batches, or per-operator batches. This matters for Phase 1 cross-site deduplication scope. If called per-function, Phase 1 cannot deduplicate across function boundaries. If called per-file, it can. The contract must specify.

---

## MEDIUM Issues

### IL1 — Process sections are algorithm specs, not behavioral contracts
Phase 1 and Phase 2 "Process" subsections enumerate implementation steps (group by id, track in set, compare keys). A spec should state observable behavioral outcomes, not implementation procedures. Rewrite as MUST/MUST NOT invariants: "A mutation MUST be removed if and only if a structurally-equivalent mutation at the same site appeared earlier in the input."

### IL2 — `trylast=True` is implementation detail in a MUST statement
Replace "MUST be registered with `trylast=True`" with "MUST execute after all other implementations of the filter hook."

### G2 — Normalization omits node-wrapping step
The `normalize` algorithm description omits that the CST node is wrapped in a `Module` (or `SimpleStatementLine`) before serialization. Two implementations disagreeing on wrapping would produce different equivalence decisions.

### IC2 — `AttributeError` on malformed mutation objects: asymmetric handling
Phase 2 catches `AttributeError` on `contained_by_top_level_function` (conservative keep). Phase 1's `m.original_node` access raises `AttributeError` uncaught. Behavior on malformed mutation objects is inconsistent and unspecified.

### S1 — Spec defines itself in terms of its consumer (mutmut)
The Integration Contract section frames dedup in terms of mutmut's plugin system. A self-contained spec should define the contract independently (input: list of objects satisfying Mutation Object Requirements; output: reduced list or None). The pluggy wiring is the consumer's concern.

---

## LOW Issues

### V2 — Test class docstring says "CPython 3.14" but behavior changed in 3.13
The `TestCPythonOptimizerBehavior` docstring was not updated when the parametrize test was fixed. Spec is correct (says 3.13); docstring is wrong. Documentation inconsistency only.

### E2 — Comment-only and whitespace-only mutations unaddressed
The spec neither covers nor excludes them. Should state they are out of scope (mutmut doesn't generate them) or that they are equivalent under Phase 1 by definition.

---

## Files
- Full critique with grounded evidence: `mutmut-dedup/SPEC.md.critique`
