# mutmut-dedup Specification

> RFC 2119: The key words MUST, MUST NOT, SHOULD, SHOULD NOT, MAY are used as defined in RFC 2119.

## Purpose

mutmut-dedup reduces the number of mutations submitted for test execution by identifying and removing mutations that produce the same observable runtime behavior as another mutation at the same site, or that produce the same behavior as the original code. A mutation that duplicates another mutation's effect wastes test time without improving kill coverage. Deduplication removes these redundant mutations before testing begins. The package applies two successive phases: structural normalization (Phase 1) and bytecode equivalence checking (Phase 2).

## Non-Goals

- **Semantic equivalence beyond bytecode**: The package does not perform program analysis, symbolic execution, or any reasoning about whether two mutations behave identically under inputs not visible at compile time.
- **Cross-Python-implementation support**: Bytecode comparison is CPython-specific. PyPy, Jython, GraalPy, and other implementations are explicitly out of scope.
- **Module-level bytecode deduplication**: Mutations outside any function boundary are excluded from Phase 2. Phase 1 still applies to them.
- **Annotation-semantics-aware deduplication**: The package does not detect whether type annotations have runtime effects. Annotation stripping in Phase 1 may produce false positives for codebases that use annotations at runtime (see Correctness Guarantee).
- **Cross-version determinism**: The set of mutations removed is allowed to differ between CPython releases due to both optimizer behavior changes (Phase 2) and `ast.dump` format changes (Phase 1).

## Core Mental Model

A **mutation** is a triple: `(original_node, mutated_node, contained_by_function)`, where:
- `original_node` is a CST node identifying the mutation site. Object identity (`id()`) is the site key.
- `mutated_node` is the replacement CST node.
- `contained_by_function` (`contained_by_top_level_function` in the implementation) is a `FunctionDef` or `AsyncFunctionDef` CST node, or `None` for mutations in module-level code outside any function.

> **Definition: "contained by a function"** — A mutation has a non-None `contained_by_function` value if its mutation site is inside the body of any `FunctionDef` or `AsyncFunctionDef` node. This includes module-scope functions, class methods, async methods, static methods, and nested functions. The value is `None` only for mutations at module scope outside all function bodies. Lambdas are not `FunctionDef` nodes; mutations inside a lambda body have `contained_by_function = None`.

A **mutation site** is the set of all mutations sharing the same `original_node` object identity. Two mutations at different sites MUST NOT be deduplicated against each other, even if their mutated forms are identical.

**Deduplication** removes all but one representative from a group of equivalent mutations at the same site. The retained representative is always the first occurrence in the input order (first-wins). Equivalence is determined independently by each phase.

The two phases apply independent equivalence notions:

- **Phase 1 (structural)**: Two mutated nodes at the same site are equivalent if their normalized structural representation is identical. Normalization strips superficial syntactic differences (whitespace, quote style, comments, type annotations).
- **Phase 2 (bytecode)**: A mutation is **original-equivalent** if applying it to its containing function produces compiled bytecode identical to the unmodified function. A mutation is a **bytecode duplicate** if another mutation at the same `(original_node, containing_function)` pair was already retained and produces the same mutated-function bytecode. Both kinds MUST be removed. These are site-scoped relationships; mutations at different sites are never compared for bytecode equivalence.

## Equivalence Definitions

### Phase 1: Structural Normalization

Two mutated nodes `A` and `B` at the same site are structurally equivalent if and only if `normalize(A) == normalize(B)`, where `normalize` is a deterministic pure function defined as follows:

**Step 1 — CST wrapping**: Wrap the node for serialization:
- If the node is a `BaseCompoundStatement` or `BaseSmallStatement`: wrap as `Module(body=[node])`
- Otherwise: wrap as `Module(body=[SimpleStatementLine(body=[node])])`

**Step 2 — Source serialization**: Serialize the wrapped module to source text via `.code`.

**Step 3 — AST parse**: Parse the source text into an AST.

**Step 4 — Annotation stripping**: Apply a transformer that:
- Removes all function argument annotations (including `*args` and `**kwargs`)
- Removes all function return annotations
- Converts `x: T = v` (annotated assignment with value) into `x = v`
- Drops `x: T` (annotation-only, no value) entirely

**Step 5 — Canonical dump**: Produce `ast.dump(tree, annotate_fields=True, include_attributes=False)`. This excludes line numbers and column offsets.

**Fallback chain** (when any step above fails):
1. If Step 2 (`.code` serialization) raises any exception: attempt `code_for_node(node)` on an empty module. If this succeeds, proceed to Step 3 with the resulting source.
2. If `code_for_node` also raises: return `repr(node)` immediately (no AST processing). The `repr` string is the final normalized form.
3. If Step 3 (`ast.parse`) raises `SyntaxError`: return the stripped source text from Step 2 as the normalized form (no AST processing).

Fallback normalized forms MUST NOT be considered equivalent to any other form unless they are byte-identical strings.

**What Phase 1 ignores**: whitespace, indentation, quote style (single vs. double), comments, type annotations.

**What Phase 1 does NOT ignore**: variable names, literal values (other than annotation-stripped ones), structural shape (operators, control flow).

Phase 1 MUST NOT compare `mutated_node` against `original_node`. A mutation where the mutated form is structurally identical to the original is retained by Phase 1 (Phase 2 handles original-equivalence removal).

### Phase 2: Bytecode Equivalence

A **bytecode signature** is a recursively extracted tuple of the following fields from a compiled `CodeType` object:
- `co_code` — compiled bytecode instructions
- `co_consts` — constants, with nested `CodeType` objects extracted recursively
- `co_names` — global and attribute names referenced
- `co_varnames` — local variable names
- `co_freevars` — free variable names (closures)
- `co_cellvars` — cell variable names
- `co_flags` — code object flags
- `co_name` — function name
- `co_argcount`, `co_posonlyargcount`, `co_kwonlyargcount` — argument counts
- `co_exceptiontable` — exception handler table (Python ≥ 3.11 only; absent on earlier versions)

The signature explicitly excludes fields that do not affect execution: line number tables, filename, first line number, stack size.

A mutation is **original-equivalent** (at its site) if: applying the mutation to `contained_by_function`, serializing the result to a module-wrapped source string, and compiling it produces a bytecode signature equal to the bytecode signature of the unmodified `contained_by_function`. This comparison is scoped to the single `(original_node, containing_function)` pair; mutations at different sites are never compared for bytecode equivalence.

A mutation is a **bytecode duplicate** if another mutation at the same `(original_node, containing_function)` pair has already been processed and retained, and that previously-retained mutation produces the same mutated-function bytecode signature. The dedup key is `(id(original_node), id(containing_function), mut_sig)`.

## Phase 1: Structural Normalization

### Behavioral Invariants

- A mutation MUST be removed if and only if a mutation at the same site (`id(original_node)`) with the same normalized form appeared earlier in the input.
- The first occurrence of each normalized form per site MUST be retained.
- Subsequent occurrences of the same normalized form at the same site MUST be removed.
- The relative order of retained mutations MUST match their relative order in the input.
- Phase 1 MUST NOT deduplicate across sites. Two mutations at different sites with identical normalized forms MUST both be retained by Phase 1.

### What Phase 1 Does NOT Do

Phase 1 does NOT compare `mutated_node` against `original_node`. A mutation where the mutated form normalizes identically to the original is retained by Phase 1 and proceeds to Phase 2 for original-equivalence checking.

Phase 1 does NOT require mutations to be inside a function. Module-level mutations are processed by Phase 1 identically to function-level mutations.

## Phase 2: Bytecode TCE

### Applicability

Phase 2 processes only mutations where `contained_by_function` is not `None`. Mutations where `contained_by_function is None` MUST be passed through Phase 2 unchanged (conservatively kept). This conservatism may retain bytecode-equivalent module-level mutations unnecessarily; that is an accepted limitation.

### Behavioral Invariants

- An original-equivalent mutation MUST be removed.
- A bytecode-duplicate mutation MUST be removed. The first retained occurrence is kept.
- The relative order of retained mutations MUST match their relative order among Phase 2's inputs.

### Conservative Behavior

Phase 2 MUST err on the side of retaining mutations when the equivalence check cannot be completed:

- If source reconstruction raises any exception (`SyntaxError`, `TypeError`, `ValueError`, `AttributeError`): keep.
- If compilation of either source raises `SyntaxError`: keep.
- If either bytecode signature is `None` (indicating compilation failure): keep.
- If the mutation site is not found in the containing function's CST tree (detected by the mutated-function source being identical to the original-function source, or by `deep_replace` returning the same object identity as the input): keep.

These conservative fallbacks ensure Phase 2 never removes a mutation due to tooling errors. False negatives (retaining equivalent mutations) are preferred over false positives.

## Phase Composition

Phase 1 MUST be applied before Phase 2. The output of Phase 1 is the input to Phase 2. A mutation removed by Phase 1 does not proceed to Phase 2.

A mutation is removed from the final output if and only if it is removed by Phase 1 OR by Phase 2.

The relative order of retained mutations in the final output MUST be the same as their relative order in the original input.

The hook's return value is determined by comparing the final count (after both phases) against the original input count:
- If `len(final) < len(input)`: return `final` (which MAY be empty).
- If `len(final) == len(input)` (no deduplication occurred, including the empty-input case): return `None`.
- The hook MUST NOT return the original list object, a modified input object, or a list longer than the input.

## Integration Contract

### Deduplication Entry Point

The deduplication entry point accepts a list of mutation objects (satisfying the Mutation Object Requirements below) and returns either a reduced list or `None`. It applies Phase 1 followed by Phase 2 in sequence.

This entry point is wired into mutmut's `mutmut_filter_mutations` plugin hook. The hook MUST be registered to execute after all other implementations of the `mutmut_filter_mutations` hook, so that deduplication operates on the already-filtered mutation set.

### Mutation List Granularity

The deduplication logic does not assume any particular granularity of the input list. It deduplicates within whatever list it receives:
- If the hook is called once per file (all file mutations in a single list), Phase 1 can deduplicate across all functions in the file.
- If the hook is called once per function (per-function batches), Phase 1 can only deduplicate within that function's mutations.

The granularity of the call is determined by the caller (mutmut core), not by this package. Per-file call granularity is the expected pattern in mutmut's current implementation.

### Input Contract

The `filename` parameter is accepted but MUST NOT affect the deduplication result. The same `mutations` list passed with any `filename` value MUST produce the same output.

The `mutations` list is treated as a read-only sequence. The implementation MUST NOT modify any mutation object in the input list.

### Mutation Object Requirements

Each mutation object MUST expose:
- `original_node`: a CST node; `id()` is used as the site key
- `mutated_node`: a CST node that can be serialized to source text
- `contained_by_top_level_function`: a `FunctionDef` or `AsyncFunctionDef` CST node, or `None`

If a mutation object raises `AttributeError` when `contained_by_top_level_function` is accessed, Phase 2 treats it identically to exceptions during reconstruction (conservative keep). If a mutation object raises `AttributeError` when `original_node` is accessed, Phase 1 behavior is undefined (the exception propagates). Callers MUST ensure `original_node` is accessible on all mutation objects.

## Correctness Guarantee

**Phase 2 MUST NOT introduce false positives under normal operation.** A false positive would cause a mutation to be silently discarded when it produces different observable behavior from the original, potentially hiding a surviving mutant.

> **Definition: "normal operation"** — All of the following hold: (a) CST serialization and `ast.parse` complete without exception; (b) the containing function compiles without `SyntaxError`; (c) `deep_replace` can locate the mutation site; (d) the type annotations in the mutated code have no runtime effects.

All conservative fallbacks in Phase 2 are deliberate choices that prefer false negatives (retaining equivalent mutations) over false positives.

**Phase 1 false-positive scope**: Phase 1 MUST NOT introduce false positives for mutations whose behavioral difference is not confined to type annotation effects at runtime. Phase 1 MAY introduce false positives when mutations differ only in type annotations that are evaluated at runtime (e.g., `typing.get_type_hints()`, `__annotations__` reads). This is a known accepted trade-off; the package documents the limitation rather than attempting to detect runtime annotation usage.

**False negatives (retaining equivalent mutations) are acceptable.** A retained equivalent mutation wastes test time but does not affect kill coverage accuracy.

## Python Version Sensitivity

### Phase 1: `ast.dump` format changes

Phase 1 uses `ast.dump(tree, annotate_fields=True, include_attributes=False)`. The output format is CPython-version-specific:

- Python 3.12 added `type_params: []` to `FunctionDef`, `ClassDef`, and `AsyncFunctionDef` nodes. Mutations involving these nodes produce different `ast.dump` strings on 3.12 vs 3.11.
- Python 3.12 introduced `TypeAlias` AST nodes (PEP 695). Code using `type X = Y` syntax produces nodes absent on earlier versions.
- Python ≤ 3.7 uses separate `Num`, `Str`, `Bytes` literal nodes; Python ≥ 3.8 uses `Constant`. Mutations on literal nodes produce different normalized forms across this boundary.

The set of mutations deduplicated by Phase 1 may differ between Python versions for any of the above reasons.

### Phase 2: CPython optimizer behavior

The CPython peephole optimizer may fold constructs at compile time, causing textually different mutations to produce identical bytecode signatures. The extent of folding is CPython-version-dependent:

- **Python ≤ 3.12**: Constant arithmetic (e.g., `2 * 3` vs `6`) and bool short-circuit (`True and x` vs `x`) are NOT folded to identical bytecode signatures. The optimizer emits equivalent opcodes but retains original literals in `co_consts`, making signatures differ.
- **Python ≥ 3.13**: The above pairs produce identical bytecode signatures. Phase 2 correctly identifies them as equivalent on Python 3.13+.

More aggressive optimizer folding on a given Python version increases the number of mutations eliminated by Phase 2. This is not a false positive — bytecode-identical code on a given CPython version IS identical in execution behavior on that version.

### Phase 2: `co_exceptiontable` (Python ≥ 3.11)

On Python 3.11 and later, `co_exceptiontable` is included in the bytecode signature. On earlier versions it is not. Bytecode signatures computed under different Python versions are not comparable; the test suite MUST account for this by treating Phase 2 optimizer-behavior tests as version-specific.

### Summary

The set of mutations removed by mutmut-dedup is allowed to differ between CPython versions. This is a documented, accepted trade-off. Results are reproducible within a single Python version.

## Known Limitations

1. **Module-level bytecode equivalence not checked.** Mutations outside any function body bypass Phase 2. Structurally distinct mutations that are bytecode-equivalent at module scope (e.g., `x = 2 * 3` vs `x = 6`) are not removed.

2. **Object identity keys.** Phase 1 uses `id(original_node)` as the site key. Phase 2 uses `id(original_node)` and `id(containing_function)`. If two logically distinct CST nodes share the same memory address (possible only if one was garbage-collected before the other was created), deduplication behavior is incorrect. In practice this cannot occur within a single call to the hook, since all mutation objects hold references to their nodes.

3. **Annotation-only statements normalize identically.** An `x: int` (no value) statement normalizes to an empty AST dump (`Module(body=[], type_ignores=[])`). Any two annotation-only mutations at the same site are deduplicated to the first. This is correct only if annotation-only statements have no runtime effect.

4. **`libcst` undeclared as a direct dependency.** `pyproject.toml` declares only `mutmut>=3.5.0` and `pluggy>=1.5.0`. `libcst` is available transitively through `mutmut` but is not declared directly. A standalone installation without `mutmut` would produce an `ImportError`.

5. **Phase 2 recompiles the containing function for every mutation.** For a function with N mutations, Phase 2 performs N+1 compilations (N mutated + 1 original). No cross-mutation caching is performed.

6. **Cross-function deduplication scope depends on call granularity.** If the hook is called once per function rather than once per file, Phase 1 cannot detect structurally identical mutations from different functions at the same logical site (e.g., two `return None` mutations in different functions sharing the same operator).

## Open Questions

1. **Should `filename` influence deduplication?** The `filename` parameter is currently ignored. Per-file budget limits or file-pattern exclusions would require a contract change.

2. **Should Phase 2 cache the original function signature?** For a function with N mutations, the original function is recompiled N times. Caching `orig_sig` per `id(containing_function)` would reduce compilations to N+1 per function. This is a performance decision.

3. **What is the long-term strategy for module-level mutations?** Phase 2 conservatively skips all module-level mutations. Should bytecode-equivalent module-level mutations (e.g., `x = 2 * 3` vs `x = 6`) ever be removed, or is the current conservatism permanent?

4. **Suspicious tolerance in `test_no_duplicates_same_count`.** The test asserts `len(mutations_with_dedup) >= count_before - 1` instead of `== count_before` for a source with no expected duplicates (`x = 1\n`). The `-1` tolerance is unexplained. See B2 below.

## Bugs / Inconsistencies Observed

### B1. `libcst` undeclared direct dependency

`mutmut-dedup/pyproject.toml` lists only `mutmut>=3.5.0` and `pluggy>=1.5.0`. `libcst` is imported in `normalize.py` and `bytecode.py`. An installation of `mutmut-dedup` without `mutmut` would fail on import with no clear diagnostic.

### B2. Unexplained tolerance in `test_no_duplicates_same_count`

The e2e test asserts `len(mutations_with_dedup) >= count_before - 1` instead of `== count_before`. The source (`x = 1\n`) contains no expected duplicates, so deduplication should produce no change. The `-1` tolerance may mask a Phase 2 bug (a module-level mutation being incorrectly removed) or a known Phase 1 edge case that has not been documented. Until resolved, this test does not fully verify the no-duplicates invariant.

### B3. Phase 1 and Phase 2 cross-site key asymmetry

Phase 1 uses only `id(original_node)` as the dedup key. Phase 2 uses `(id(original_node), id(containing_function), mut_sig)`. This asymmetry means Phase 2 can deduplicate two mutations at the same site that target the same function and produce the same compiled output, even if their `mutated_node` values differ at the CST level. This is the correct semantics but is not documented and may surprise contributors.

### B4. Orphaned-node guard may be dead code

The Phase 2 implementation checks `if mutated_func is func` to detect when `deep_replace` failed to locate the mutation site and returned the original node unchanged. The code comment asserts libcst returns the same object identity when no replacement is made. If this assumption is wrong (i.e., libcst always returns a new object even when no replacement occurs), the guard never fires. In that scenario, orphaned mutations would proceed to signature comparison, and since `orig_source == mut_source`, they would be removed as original-equivalent — a false positive. The correctness of the guard depends on undocumented libcst behavior.

### B5. Test class docstring stated wrong version boundary

`TestCPythonOptimizerBehavior`'s class docstring previously referred to "CPython 3.14" as the folding boundary. This was incorrect; the boundary is CPython 3.13. The docstring has been updated. The parametrize cases carry explicit `expected` booleans documenting per-case behavior.

### B6. Phase 1 propagates `AttributeError` from `m.original_node`

Phase 2 catches `AttributeError` during reconstruction and conservatively keeps the mutation. Phase 1's `id(m.original_node)` access does not have equivalent protection. If a mutation object raises on `original_node` access, Phase 1 propagates the exception to the caller. This asymmetry is not documented.
