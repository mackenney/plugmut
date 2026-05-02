# Deterministic Mutant Deduplication and Normalization

Research findings and implementation proposal for a `mutmut_filter_mutations` plugin that eliminates equivalent and duplicated mutants using only deterministic, verifiable techniques.

## 1. Research Survey

### 1.1 Trivial Compiler Equivalence (TCE)

**Source:** Papadakis et al., ICSE 2015; Kintis et al., IEEE TSE 2018.

**Mechanism:** Compile both original and mutant, compare the resulting object code. If identical after optimization, the mutant is equivalent. If two mutants produce identical object code, they are duplicated.

**Results (C):** 7.4% equivalent, 21% duplicated. **Results (Java):** 5.7% equivalent, 5.4% duplicated. TCE catches ~30% of all equivalent mutants in C, ~54% in Java.

**TCE+ extension:** Uses ProGuard optimizer on top of javac to compensate for Java's weak compiler optimizations. Raises equivalent detection from 16.7% to 41.5%.

**Deterministic:** Yes. Zero false positives by construction (identical compiled output = provably identical behavior for all inputs).

**Python applicability:** Directly applicable. CPython's `compile()` produces bytecode (`co_code`) that includes peephole optimizations: constant folding, dead code elimination, jump optimization. Python's optimizer is weaker than GCC/Clang but still catches meaningful cases:
- `x + 0` folds to `x`
- `True and expr` folds to `expr`
- Dead branches after constant conditions are eliminated
- Constant arithmetic expressions are pre-computed

**Key limitation:** Python bytecode includes line number tables and metadata that differ between source locations. Comparison must strip `co_lnotab`/`co_linetable`, `co_filename`, and `co_firstlineno` before comparing. Since Python 3.11, use `co_code` + `co_consts` + `co_names` as the comparison tuple, ignoring positional metadata.

### 1.2 AST Normalization / Structural Deduplication

**Source:** Google's mutation testing at scale (Petrovic et al., IEEE TSE 2021); Fuzzing Book mutation analysis chapter.

**Mechanism:** Parse and unparse mutated code to a canonical form, stripping whitespace, comments, and formatting. Compare canonical forms to detect structurally identical mutants.

**Google's approach:** Normalizes source code by parsing and unparsing once before diffing. Uses AST-node hashing for cross-snapshot dedup: hash the mutation operator + mutated AST node context to identify "same" mutants across code revisions.

**Deterministic:** Yes for structural identity. Does not catch semantic equivalence.

**Python applicability:** Directly applicable. Two options:
1. **`ast.dump()`**: `ast.dump(ast.parse(code))` produces a canonical string. Loses formatting (good for comparison).
2. **libcst `deep_equals()`**: Compares CST nodes semantically, ignoring whitespace. Already available in the codebase since mutmut uses libcst.

**Use case in mutmut:** Two different mutation operators may produce the same mutated code for a given function. Comparing the serialized mutant source catches these exact duplicates.

### 1.3 Operator Subsumption (Static)

**Source:** Kurtz et al., ICST 2015; Identifying method-level mutation subsumption using Z3 (Kaminski et al., IST 2020).

**Mechanism:** For a given expression, if mutant A's kill set is guaranteed to be a superset of mutant B's kill set, B is redundant. Some subsumption relations can be proven statically from operator definitions alone.

**Known static subsumption rules (weak mutation):**
- For relational operator `<`: mutations to `false`, `<=`, `!=` are dominators. `==`, `>`, `>=`, `true` are subsumed.
- For `==`: mutations to `false` and `<=` and `>=` form a dominator set.
- AOR: `a + b -> a - b` subsumes `a + b -> a` (the latter is killed whenever the former is, assuming `b != 0`).
- Negation insertion subsumes many arithmetic replacements.

**Research finding:** Only 17 of 82 mutation operators are "Subsuming Mutation Operators" — the rest are redundant under subsumption analysis.

**Deterministic:** Partially. Static subsumption rules are proven correct for weak mutation (infection condition). Under strong mutation (propagation), they hold in most but not all cases. The Z3-based approach proves subsumption for specific code contexts with zero false positives.

**Python applicability:** Static subsumption rules between operators are language-independent. Applicable directly. Z3-based per-expression proving is possible but expensive and requires encoding Python semantics into SMT — high effort, limited payoff for dynamic language.

### 1.4 Constant Folding Equivalence

**Source:** Hariri et al., ICST 2019 (source vs. IR mutation comparison).

**Mechanism:** Mutations that change expressions which constant-fold to the same value at compile time are equivalent. E.g., mutating `2 * 3` to `2 + 3` — both fold to `6` and `5` respectively at compile time, so they're distinct. But mutating `x * 1` to `x / 1` — both are identity operations.

**Deterministic:** Yes, when verified via bytecode comparison (subsumed by TCE).

**Python applicability:** Subsumed by the bytecode TCE approach. CPython constant-folds `2 * 3 -> 6` at compile time. No separate implementation needed.

### 1.5 Google's Arid Node Detection

**Source:** Petrovic et al., IEEE TSE 2021.

**Mechanism:** Classify AST nodes as "arid" (unproductive to mutate) based on syntactic patterns: logging calls, string-only statements, empty returns, etc. Never generate mutants for arid nodes.

**Deterministic:** Yes — pattern matching rules are fixed.

**Python applicability:** Directly applicable. mutmut already does some of this (skipping `len`/`isinstance` calls, annotations, decorators). This is a generation-time filter, not a dedup technique per se, but reduces the mutant pool before dedup.

### 1.6 Dominator Mutation Analysis

**Source:** Kurtz et al., ICSE 2014; Ammann et al., ICST 2014.

**Mechanism:** Compute the minimal set of "dominator" mutants such that any test suite killing all dominators also kills all other mutants. The dominator set is typically 5-20% of the full mutant set.

**Deterministic:** Yes in theory (exact subsumption graph). In practice, computing the full dominator set requires running all mutants against all tests first — it's a post-hoc analysis, not a generation-time filter.

**Python applicability:** Not useful as a pre-filter. Useful for analyzing results after a full mutation run to identify the minimal adequate set. Out of scope for a `mutmut_filter_mutations` plugin.

### 1.7 Tools Summary

| Tool | Language | Equivalent Detection | Duplicate Detection |
|------|----------|---------------------|-------------------|
| **PIT** | Java | Filters known equivalents (hardcoded returns true/null); disables noisy operators by default | No explicit dedup |
| **Major** | Java | None built-in; designed for research | Supports subsumption analysis via external tools |
| **Stryker** | JS/C#/.NET | Manual annotation (`// Stryker disable`) | No automatic dedup |
| **Mull** | C++ (LLVM) | None built-in; mutant schemata avoids recompilation | No explicit dedup |
| **cargo-mutants** | Rust | Acknowledged as TODO; avoids trivial equivalents | No automatic dedup |
| **mutmut** | Python | `pragma: no mutate`; skips annotations/decorators | No automatic dedup |
| **MutPy** | Python | None | None |
| **Cosmic-Ray** | Python | None | None |

**No Python mutation testing tool currently implements automatic equivalent or duplicate mutant detection.**

## 2. Techniques Ranked by Python Applicability

| Rank | Technique | Deterministic | False Positive Rate | Effort | Impact |
|------|-----------|--------------|-------------------|--------|--------|
| 1 | **Bytecode TCE** | Yes | 0% (provable) | Low | High — catches equivalent + duplicated |
| 2 | **Source-level structural dedup** | Yes | 0% | Very low | Medium — catches exact duplicate mutants |
| 3 | **Static operator subsumption rules** | Yes (weak mutation) | ~0% for standard rules | Medium | Medium — reduces redundant mutants by known relationships |
| 4 | **Arid node expansion** | Yes | 0% | Low | Low-medium — prevents unproductive mutants |
| 5 | **Z3-based per-expression subsumption** | Yes | 0% | Very high | Low for Python (dynamic typing defeats most proofs) |

## 3. Implementation Proposal

### Phase 1: Source-Level Structural Dedup (1-2 days)

**Goal:** Eliminate mutants that produce identical mutated source code.

**Algorithm:**
1. In `mutmut_filter_mutations`, iterate through the mutations list.
2. For each mutation, compute the mutated function source by applying the mutation to the containing function's CST.
3. Normalize: `ast.dump(ast.parse(source), annotate_fields=True, include_attributes=False)` — this strips line numbers, col offsets, and whitespace.
4. Hash the normalized AST dump (SHA-256).
5. If the hash was already seen for this function, discard the mutation as a duplicate.
6. Return the deduplicated list.

**Integration point:** `mutmut_filter_mutations(filename, mutations) -> list`

**Why this first:** Cheapest to implement, zero false positives, works with existing libcst infrastructure. Catches cases where different operators produce the same mutated code (e.g., `not True` mutated to `not False` by boolean replacement and `True` by not-removal — same effective code if one operator's output matches another's).

**Limitation:** Only catches syntactically identical mutants. Two mutants with different syntax but same semantics (e.g., `x + 0` vs `x`) are not caught.

### Phase 2: Bytecode TCE — Equivalent and Duplicate Detection (3-5 days)

**Goal:** Detect mutants equivalent to the original and mutants equivalent to each other via bytecode comparison.

**Algorithm:**
```
def bytecode_signature(source: str) -> tuple:
    code = compile(source, "<mutant>", "exec")
    return _extract_signature(code)

def _extract_signature(code: types.CodeType) -> tuple:
    """Recursively extract comparison-relevant fields from code object."""
    return (
        code.co_code,           # bytecode instructions
        tuple(
            _extract_signature(c) if isinstance(c, types.CodeType) else c
            for c in code.co_consts
        ),
        code.co_names,          # global name references
        code.co_varnames,       # local variable names
        code.co_freevars,       # closure variables
        code.co_cellvars,       # cell variables
        code.co_stacksize,      # stack size (optimization-dependent)
        code.co_flags,          # function flags
    )
```

Steps:
1. Compute `bytecode_signature(original_function_source)` as the baseline.
2. For each mutation, apply it to produce mutated source, compute `bytecode_signature(mutated_source)`.
3. If mutant signature == original signature: mark as **equivalent**, remove.
4. Group remaining mutants by signature. Within each group, keep only one — the rest are **duplicates**.
5. Return the reduced list.

**Key details:**
- Must compile each mutant's containing function in isolation, not the whole module (avoids unrelated differences).
- Must handle `SyntaxError` from invalid mutants (skip them, they'll fail at runtime anyway).
- The recursive `_extract_signature` handles nested functions and lambdas.
- Exclude `co_lnotab`/`co_linetable` (line number mapping), `co_filename`, `co_firstlineno` — these are metadata, not semantics.

**Expected yield:** Based on TCE research, 5-8% equivalent mutants and 5-20% duplicated mutants. Python's weaker optimizer means the lower end is more likely, but even 5% equivalent + 5% duplicate = 10% reduction with zero false positives.

**Performance:** `compile()` is fast — sub-millisecond per function. For a file with 500 mutants, the overhead is <1 second total. Negligible compared to test execution.

### Phase 3: Static Operator Subsumption Rules (3-5 days)

**Goal:** Before generating mutants, encode known subsumption relationships so that dominated mutants are never created (or are filtered immediately).

**Algorithm:**

Define a subsumption table keyed by `(original_operator, context_type)`:

```python
SUBSUMPTION_RULES = {
    # For comparison operators: keep only dominator mutants
    # Original `<` → dominators are: `False`, `<=`, `!=`
    # Subsumed: `==`, `>`, `>=`, `True`
    ("Lt", "Compare"): {
        "dominators": [("Eq", "LtE", "NotEq")],  # keep these
        "subsumed": ["Eq", "Gt", "GtE"],          # remove these
    },
    # Original `==` → dominators: `False`, `<=`, `>=`
    ("Eq", "Compare"): {
        "dominators": ["LtE", "GtE"],
        "subsumed": ["Lt", "Gt"],
    },
    # For `a + b`: `a - b` dominates `a` and `b` individually
    # (but only under weak mutation assumption)
    ("Add", "BinaryOperation"): {
        "dominators": ["Sub"],
        "subsumed": [],  # conservative: don't remove anything for arithmetic
    },
}
```

Steps:
1. For each mutation, identify the operator class and context.
2. Check if the mutation produces a subsumed variant.
3. If another mutation at the same location produces the dominator, discard the subsumed one.
4. If no dominator exists at that location, keep the subsumed one (conservative: never discard without a dominator present).

**Why conservative:** Subsumption under strong mutation is not always guaranteed. Only apply rules with well-established theoretical backing (relational operators are the strongest case).

**Expected yield:** 10-30% reduction for comparison-heavy code. Less impact on code dominated by other mutation types.

### Phase 4: Arid Node Expansion (1-2 days)

**Goal:** Extend mutmut's existing skip rules with additional arid patterns from Google's research.

**New patterns to skip:**
- Logging calls: `logging.debug/info/warning/error`, `logger.*`
- String-only expressions: `"""docstring"""` at statement level
- `pass` statements
- `raise` in `except` blocks (re-raise, not new raise)
- `__repr__`, `__str__` methods (formatting, not logic)
- Constants assigned to `__all__`, `__version__`, `__author__`

**Integration:** Can be implemented as either generation-time skips or `mutmut_filter_mutations` filters. Prefer generation-time where possible (avoids creating + discarding).

## 4. What Does NOT Transfer from Compiled Languages

| Technique | Why it fails in Python |
|-----------|----------------------|
| GCC/Clang `-O2` optimization comparison | Python's compiler is intentionally minimal. No inlining, no loop unrolling, no register allocation. |
| ProGuard-style post-compilation optimization | No equivalent optimizer for `.pyc` files. Tools like Cython change semantics. |
| LLVM IR-level mutation (Mull) | Python has no LLVM IR. Bytecode is the closest analog but much higher-level. |
| Type-based equivalence proofs | Python's dynamic typing means type information is unavailable at compile time. `mypy`/`pyright` annotations could theoretically help but are optional and incomplete. |
| Z3 encoding of full program semantics | Feasible only for trivial expressions. Python's dynamic dispatch, duck typing, and runtime metaprogramming make complete SMT encoding impractical. |

## 5. Effort Summary

| Phase | Technique | Days | Cumulative Reduction | Risk |
|-------|-----------|------|---------------------|------|
| 1 | Source structural dedup | 1-2 | 2-5% | None |
| 2 | Bytecode TCE | 3-5 | 7-15% | Low — compile() edge cases |
| 3 | Static subsumption rules | 3-5 | 15-25% | Medium — must validate rules hold under strong mutation |
| 4 | Arid node expansion | 1-2 | 20-30% | None |
| **Total** | | **8-14 days** | **20-30%** | |

Phases 1 and 2 are the highest-value, lowest-risk targets. Phase 3 provides meaningful additional reduction but requires careful validation. Phase 4 is orthogonal and can be done at any time.

## 6. Architecture

All four phases integrate through the existing `mutmut_filter_mutations` hook:

```
mutmut core generates mutations
    → mutmut_filter_mutations (plugin chain)
        → Phase 4: arid node filter (cheap, runs first)
        → Phase 1: source structural dedup (cheap)
        → Phase 2: bytecode TCE (moderate cost)
        → Phase 3: subsumption pruning (moderate cost)
    → remaining mutations proceed to test execution
```

The plugin lives in a new package (e.g., `mutmut-dedup/`) or as a module within `mutmut-extras/`, following the workspace's plugin architecture.

## Sources

- [Papadakis et al. — TCE: Trivial Compiler Equivalence (ICSE 2015)](https://ieeexplore.ieee.org/document/7194639/)
- [Kintis et al. — Detecting Trivial Mutant Equivalences via Compiler Optimisations (IEEE TSE 2018)](https://ieeexplore.ieee.org/document/7882714/)
- [Houshmand & Paydar — TCE+: Extension for Java (2017)](https://link.springer.com/chapter/10.1007/978-3-319-68972-2_11)
- [Petrovic et al. — Practical Mutation Testing at Scale: Google (IEEE TSE 2021)](https://homes.cs.washington.edu/~rjust/publ/practical_mutation_testing_tse_2021.pdf)
- [Kaminski et al. — Identifying method-level mutation subsumption using Z3 (IST 2020)](https://www.sciencedirect.com/science/article/abs/pii/S095058492030238X)
- [Kurtz et al. — Static analysis of mutant subsumption (ICSE 2015)](https://ieeexplore.ieee.org/document/7107454/)
- [Ammann et al. — Mutant reduction based on dominance relation (IST 2016)](https://www.sciencedirect.com/science/article/abs/pii/S0950584916300805)
- [PIT Mutation Testing — Equivalent Mutant Avoidance](https://pitest.org/quickstart/basic_concepts/)
- [Stryker — Equivalent Mutants Documentation](https://stryker-mutator.io/docs/mutation-testing-elements/equivalent-mutants/)
- [cargo-mutants Design Document](https://github.com/sourcefrog/cargo-mutants/blob/main/DESIGN.md)
- [Mull — LLVM-based Mutation Testing](https://github.com/mull-project/mull)
- [CPython Peephole Optimizer](https://akaptur.com/blog/2014/08/02/the-cpython-peephole-optimizer-and-you/)
- [Python dis module — Bytecode Disassembler](https://docs.python.org/3/library/dis.html)
