# mutmut-dedup SPEC.md — Final Revision Summary

**Spec written:** `mutmut-dedup/SPEC.md` (262 lines)
**Test docstring fixed:** `mutmut-dedup/tests/test_bytecode.py` (class docstring corrected from "3.14" to "3.13+")

## Critique Points Addressed

| Issue | Severity | Resolution |
|-------|----------|------------|
| FP1 — MUST NOT guarantee contradicts annotation caveat | CRITICAL | Guarantee scoped: "MUST NOT for mutations whose difference is not confined to annotation effects." Annotation caveat moved into the guarantee clause itself. |
| E1 — "top-level function" undefined for methods/nested/async | CRITICAL | Defined explicitly: non-None `contained_by_function` means any FunctionDef or AsyncFunctionDef, including class methods, nested functions, async functions. Lambdas are NOT included. |
| G1 — "bytecode-equivalent" term conflicts with site-scoped "bytecode-duplicate" | HIGH | Removed the general "bytecode-equivalent" term. Only "original-equivalent" (mutation vs original, site-scoped) and "bytecode-duplicate" (mutation vs mutation, same site) remain. Both explicitly site-scoped. |
| FP3 — Orphaned-node guard may be dead code | HIGH | Spec now states BOTH detection mechanisms (identity check AND source equality) as valid conservative implementations. Added as B4 bug. |
| V1 — Phase 1 ast.dump version sensitivity absent | HIGH | Added full Phase 1 version sensitivity section: 3.12 type_params, PEP 695, 3.8 Constant unification. |
| IC1 — Mutation list granularity unspecified | HIGH | Added explicit section: dedup operates on whatever list it receives; cross-function scope depends on call granularity; per-file is the expected pattern. |
| IL1 — Process sections describe algorithm, not behavior | HIGH | Rewrote Phase 1 and Phase 2 as MUST/MUST NOT behavioral invariants. |
| G2 — Normalize function omits wrapping step | MEDIUM | Added full wrapping logic to normalization definition (compound/small vs other nodes). |
| G3 — Three-level fallback documented as two-level | LOW | Documented all three levels plus the SyntaxError path explicitly. |
| FP2 — "normal operation" undefined | HIGH | Added explicit definition as a named block. |
| IL2 — `trylast=True` in a MUST statement | MEDIUM | Removed; replaced with "MUST execute after all other filter hook implementations." |
| P1 — Return value comparison wording ambiguous | MEDIUM | Clarified: comparison is `len(final) < len(original_input)`. |
| IC2 — AttributeError asymmetry undocumented | MEDIUM | Added to Mutation Object Requirements and added as B6 bug. |
| S1 — Spec coupled to mutmut by name | MEDIUM | Reframed: general deduplication entry point first, mutmut hook integration as wiring detail second. |
| V2 — Test class docstring said "CPython 3.14" | LOW | Fixed in test file. Added as B5 in spec Bugs section. |
| E2 — Comment/whitespace mutations | LOW | Not added (correctly out of scope; mutmut does not generate such mutations). |

## New Sections Added

- **"Definition: contained by a function"** — precise definition including class methods, async, nested; explicitly excludes lambdas
- **"Definition: normal operation"** — scopes the false-positive guarantee
- **Phase 1 version sensitivity** — ast.dump format changes
- **Mutation List Granularity** — call granularity and cross-function scope
- **B4** — orphaned-node guard may be dead code
- **B5** — test docstring version error (fixed)
- **B6** — Phase 1 AttributeError propagation asymmetry

## Invariants Captured (MUST/MUST NOT)

Phase 1:
- MUST remove iff same-site same-normalized-form appeared earlier
- MUST retain first occurrence
- MUST NOT deduplicate across sites
- MUST preserve relative order

Phase 2:
- MUST keep mutations with `contained_by_function = None`
- MUST remove original-equivalent mutations
- MUST remove bytecode-duplicate mutations
- MUST keep conservatively on reconstruction/compilation failure
- MUST keep when mutation site not found in function tree

Integration:
- filename MUST NOT affect result
- MUST NOT modify input mutation objects
- MUST execute after all other filter implementations
- Return None when count unchanged; return reduced list when count decreases

## Open Questions (4, all inherited from draft — none resolved)

- OQ4 (test tolerance) is the most actionable: the `-1` in `test_no_duplicates_same_count` needs investigation.

## Surviving Bugs from Draft

B1 (libcst undeclared), B2 (test tolerance), B3 (key asymmetry), B4 (orphaned guard), B5 (docstring), B6 (AttributeError asymmetry).
