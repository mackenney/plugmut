# Phase 2: Bytecode TCE (Trivial Compiler Equivalence)

Extends the `mutmut-dedup` plugin from Phase 1 with bytecode-level equivalence and duplicate detection. Compiles original and mutated code via `compile()`, compares code object signatures. Identical bytecode = provably equivalent (zero false positives).

**Prerequisite:** Phase 1 complete (mutmut-dedup package exists with structural dedup).

## Background

TCE exploits the compiler as a free theorem prover. CPython's peephole optimizer handles:
- Constant folding: `2 * 3` → `6`
- Identity elimination: `x + 0` → `x` (in some contexts)
- Dead branch removal after constant conditions
- Boolean short-circuit simplification

If a mutation produces bytecode identical to the original, the mutation is provably equivalent — no test can ever kill it. If two mutations produce identical bytecode, they are duplicates — only one needs testing.

## New Module

```
mutmut-dedup/src/mutmut_dedup/
├── normalize.py     # (Phase 1, unchanged)
├── bytecode.py      # NEW: bytecode signature extraction + comparison
└── plugin.py        # Extended: adds bytecode TCE pass
```

## Public API

```python
# bytecode.py

import types

def bytecode_signature(source: str) -> tuple | None:
    """Compile source and extract a comparison-relevant signature tuple.

    Returns None if source fails to compile (SyntaxError).
    """

def is_equivalent(original_source: str, mutated_source: str) -> bool:
    """True if original and mutated compile to identical bytecode signatures."""

def group_by_bytecode(sources: list[str]) -> dict[tuple, list[int]]:
    """Group source strings by their bytecode signature.
    Returns {signature: [indices]}. Groups of size >1 are duplicates."""
```

## Bytecode Signature Algorithm

```python
def _extract_signature(code: types.CodeType) -> tuple:
    return (
        code.co_code,
        tuple(
            _extract_signature(c) if isinstance(c, types.CodeType) else c
            for c in code.co_consts
        ),
        code.co_names,
        code.co_varnames,
        code.co_freevars,
        code.co_cellvars,
        code.co_flags,
    )

def bytecode_signature(source: str) -> tuple | None:
    try:
        code = compile(source, "<mutant>", "exec")
    except SyntaxError:
        return None
    return _extract_signature(code)
```

Excluded from signature (metadata, not semantics):
- `co_lnotab` / `co_linetable` — line number mapping
- `co_filename` — source file path
- `co_firstlineno` — starting line
- `co_stacksize` — implementation detail, may vary

`co_consts` is recursed because nested function definitions (lambdas, inner functions) appear as nested `CodeType` objects within `co_consts`.

## Integration into Plugin

```python
# plugin.py (extended from Phase 1)

@hookimpl(trylast=True)
def mutmut_filter_mutations(filename: str, mutations: list) -> list | None:
    # Phase 1: structural dedup (cheap, runs first)
    result = deduplicate(mutations)

    # Phase 2: bytecode TCE (moderate cost, runs second)
    result = bytecode_filter(result)

    if len(result) < len(mutations):
        return result
    return None
```

The `bytecode_filter` function:
1. For each mutation, reconstruct the mutated function source by applying `module.deep_replace(m.original_node, m.mutated_node).code`.
2. Also reconstruct the original function source.
3. Compute `bytecode_signature()` for both.
4. If mutant signature == original signature → **equivalent**, remove.
5. Group remaining mutants by (original_node_id, bytecode_signature). Within each group, keep first → **dedup**, remove rest.

## Steps

### Step 1: Implement `bytecode_signature`

Write `bytecode.py` with `bytecode_signature(source: str) -> tuple | None` and `_extract_signature(code: types.CodeType) -> tuple`.

**Unit tests** (`test_bytecode.py`):
1. Simple function: `def f(): return 1` produces a non-None signature
2. Same source compiled twice produces identical signature
3. Different source produces different signature: `def f(): return 1` vs `def f(): return 2`
4. SyntaxError source returns `None`
5. Signature excludes line numbers: same code at different indentation levels → same signature
6. Nested functions: `def f():\n def g(): return 1\n return g` — signature captures inner function
7. Lambda: `lambda x: x + 1` vs `lambda x: x + 2` → different signatures
8. Empty function: `def f(): pass` produces valid signature

**Smoke test:** `uv run --package mutmut-dedup pytest mutmut-dedup/tests/test_bytecode.py -v`

### Step 2: Verify TCE catches known identity operations

Test that CPython's compiler actually folds the cases we expect.

**Unit tests** (`test_bytecode.py`, continued):
1. `x + 0` vs `x` — check if CPython folds this (it may NOT for variables, only literals)
2. `True and x` vs `x` — boolean short-circuit
3. `2 * 3` vs `6` — constant folding of literals
4. `not not x` vs `x` — double negation
5. `if True: return x` vs `return x` — dead branch removal
6. `x * 1` vs `x` — identity multiplication

Document which cases CPython actually catches vs doesn't. This is empirical — the tests serve as documentation of CPython's optimizer behavior. Failures here aren't bugs; they just mean that specific pattern isn't caught by TCE in the current Python version.

**Smoke test:** Run tests, note which identity patterns are caught. Record results as comments in test file for future reference.

### Step 3: Implement `is_equivalent`

```python
def is_equivalent(original_source: str, mutated_source: str) -> bool:
    orig_sig = bytecode_signature(original_source)
    mut_sig = bytecode_signature(mutated_source)
    if orig_sig is None or mut_sig is None:
        return False
    return orig_sig == mut_sig
```

**Unit tests** (`test_bytecode.py`, continued):
1. Identical source → `True`
2. Semantically different source → `False`
3. One side has SyntaxError → `False`
4. Both sides have SyntaxError → `False`
5. Known identity operation that CPython folds → `True` (use cases confirmed in Step 2)

**Smoke test:** `uv run --package mutmut-dedup pytest mutmut-dedup/tests/test_bytecode.py -v`

### Step 4: Implement `bytecode_filter`

Write the filter function that takes `list[Mutation]` and returns filtered list.

Challenge: extracting source from CST nodes. The mutation has `original_node` and `mutated_node` as `cst.CSTNode`. To compile, we need source strings. The containing function is `m.contained_by_top_level_function`.

Approach:
```python
def _mutation_to_source(mutation: Mutation, module: cst.Module) -> tuple[str, str] | None:
    """Extract original and mutated function source strings."""
    func = mutation.contained_by_top_level_function
    if func is None:
        return None
    original_source = module.code_for_node(func)
    mutated_func = func.deep_replace(mutation.original_node, mutation.mutated_node)
    mutated_source = module.code_for_node(mutated_func)  # won't work — need module context
    return original_source, mutated_source
```

Note: `module.code_for_node()` requires the node to be in the module's tree. For the mutated version, generate source via `cst.Module(body=[mutated_func]).code` or use the simpler `cst.parse_module("").code_for_node()` approach. Investigate the exact CST API during implementation.

If extracting full function source is impractical, fall back to comparing just the mutated node's source: `cst.Module(body=[cst.SimpleStatementLine(body=[mutated_node])]).code`. This is less precise (doesn't capture function-level optimizations) but simpler.

**Unit tests** (`test_dedup.py`, extended):
1. Two mutations that produce bytecode-identical functions → one removed
2. Mutation producing bytecode identical to original → removed (equivalent)
3. Mutation at module level (no containing function) → skipped by bytecode filter, kept
4. Mutation with SyntaxError in reconstructed source → skipped, kept
5. Mixed: 5 mutations, 1 equivalent, 2 duplicates of each other, 2 unique → returns 3

**Smoke test:** `uv run --package mutmut-dedup pytest mutmut-dedup/tests/test_dedup.py -v`

### Step 5: Wire bytecode filter into plugin

Update `plugin.py` to chain structural dedup → bytecode filter.

**Integration tests** (`test_plugin.py`, extended):
1. Source with known equivalent mutation (identity operation) → confirm removed
2. Source with two operators producing bytecode-identical mutants → confirm deduped
3. Source with no equivalents or duplicates → confirm list unchanged (returns `None`)
4. Performance sanity: source with 100 mutations → filter completes in <1 second

Setup: same `_isolate_plugins` fixture as Phase 1.

**Smoke test:** `uv run --package mutmut-dedup pytest mutmut-dedup/tests/test_plugin.py -v`

### Step 6: End-to-end tests

**E2E tests** (`test_e2e.py`, extended):
1. Craft source with `x + 0` pattern inside a function. Run full `create_mutations()` pipeline with dedup plugin. If CPython folds this, verify mutation count decreased. If not, document and skip.
2. Craft source that triggers the same mutation from two different operators (e.g., function body that both core and extras mutate to identical bytecode). Verify one is removed.
3. Compare mutation counts: run `create_mutations()` twice — once without dedup plugin, once with. Verify `with_dedup <= without_dedup`.
4. Verify all surviving mutations are still valid: each can be applied and produces parseable Python.

**Full suite smoke test:** `uv run --package mutmut-dedup pytest mutmut-dedup/ -v`

### Step 7: Cross-plugin regression check

```bash
uv run --package mutmut pytest mutmut/tests/ -x
uv run --package mutmut-extras pytest -x
uv run --package mutmut-dedup pytest -x
```

Manually run mutmut on a small project. Compare results with/without dedup to quantify reduction percentage.

## CPython Version Considerations

The bytecode format changes across Python versions. The signature extraction uses only stable `CodeType` attributes available since Python 3.8+. However:
- Python 3.11 changed `co_lnotab` to `co_linetable` — we exclude both, so no impact.
- Python 3.12 added `co_qualname` — not included in signature (metadata).
- Python 3.13 may change `co_code` format — the signature is version-specific by design (comparing within same interpreter).

Tests should pass on any single Python version. Cross-version bytecode comparison is not a goal.

## Expected Yield

Based on TCE research (Papadakis et al., ICSE 2015):
- C programs: 7.4% equivalent, 21% duplicated
- Java programs: 5.7% equivalent, 5.4% duplicated
- Python (estimated): 3-8% equivalent, 3-10% duplicated

Python's optimizer is weaker than GCC/javac, so yields will be at the lower end. Even 5% total reduction is meaningful — those are mutations that can never be killed, wasting test execution time.

## Known Limitations (Post-Implementation)

### CPython 3.13+ reduced compile-time folding

CPython 3.13 introduced `LOAD_SMALL_INT` and deferred more optimizations to the JIT tier. Consequences for bytecode TCE:

- **Dead constants in `co_consts`:** After constant folding, the original source-level literals remain in `co_consts` as unreferenced entries. `2 * 3` and `6` produce identical opcodes but different `co_consts` tuples, causing a false negative.
- **Empirical result on 3.14:** Zero equivalences detected across 97 mutations from 20 diverse source files using core operators. None of the 6 classical identity patterns (constant folding, boolean short-circuit, double negation, identity add/mul, dead branch) produce identical signatures.

**Where TCE still provides value:**
- **Bytecode duplicate detection** — two mutations producing identical mutated functions (same `co_code` + `co_consts`) are caught regardless of optimizer behavior
- **LLM-generated mutations** — produce semantically-equivalent-but-syntactically-different code, the exact pattern TCE excels at
- **mutmut-extras operators** — more operators = more duplicate opportunities at each mutation site
- **CPython ≤ 3.12** — aggressive peephole optimizer folds more patterns at compile time

**Possible future improvement:** Filter `co_consts` to only include entries referenced by `LOAD_CONST` instructions (via `dis.get_instructions()`), then remap `LOAD_CONST` operands. This would recover constant-folding equivalence detection on 3.13+.

### Upstream hook composition issue

The `mutmut_filter_mutations` hook in `file_mutation.py:129-131` uses last-non-None-wins semantics:

```python
for result in pm.hook.mutmut_filter_mutations(filename=filename, mutations=mutations):
    if result is not None:
        mutations = result
```

Each plugin receives the **original** mutations list, not the output of the previous plugin. If plugin A removes mutation X and returns `[Y, Z]`, plugin B (dedup, `trylast=True`) still receives `[X, Y, Z]`. If dedup returns non-None, it overwrites A's filtering.

**Current impact:** No other filter plugins exist, so this is latent. See `plans/upstream/hook-filter-composition.md` for the proposed upstream fix.
