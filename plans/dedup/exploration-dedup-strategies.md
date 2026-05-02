# Exploration: Advanced Dedup Strategies

Further dedup/equivalence techniques beyond Phase 1 (structural dedup) and Phase 2 (bytecode TCE). These are documented for future exploration — none are immediately planned for implementation.

## Strategy A: Static Operator Subsumption

**Concept:** For a given expression, some mutations provably subsume others. If mutant A's kill set is a guaranteed superset of mutant B's kill set, B is redundant when A exists.

**Known rules (relational operators, proven under weak mutation):**

| Original | Dominator mutations (keep) | Subsumed mutations (remove if dominator exists) |
|----------|---------------------------|------------------------------------------------|
| `<`  | `<=`, `!=` | `==`, `>`, `>=` |
| `<=` | `<`, `==` | `!=`, `>`, `>=` |
| `>`  | `>=`, `!=` | `==`, `<`, `<=` |
| `>=` | `>`, `==` | `!=`, `<`, `<=` |
| `==` | `<=`, `>=` | `<`, `>`, `!=` |
| `!=` | `<`, `>` | `<=`, `>=`, `==` |

**Arithmetic (weaker guarantees):**
- `a + b → a - b` subsumes `a + b → a` (assuming `b != 0`)
- Negation insertion subsumes many arithmetic replacements

**Implementation sketch:**
1. For each mutation, identify the operator category and what it was mutated to.
2. Check if another mutation at the same location is a dominator.
3. If dominator present, remove the subsumed mutation.
4. If no dominator at that location, keep the subsumed one (conservative).

**Concerns:**
- Subsumption rules are proven for weak mutation (infection condition). Under strong mutation (propagation to output), they hold in most but not all cases. Need empirical validation on Python codebases.
- Requires inspecting mutation operator identity, which the current `Mutation` dataclass doesn't expose (no source tag). Would need to compare original vs mutated node structure to infer which operator acted.

**Effort:** 3-5 days. Medium risk — rules need validation under strong mutation.

**Sources:**
- Kurtz et al., "Analyzing the validity of selective mutation with dominator mutants" (ESEC/FSE 2014)
- Ammann et al., "Establishing confidence in mutation testing results" (ICST 2014)
- Kaminski et al., "Identifying method-level mutation subsumption using Z3" (IST 2020)

## Strategy B: Arid Node Expansion

**Concept:** Extend mutmut's existing node-skip patterns with additional "unproductive" mutation sites identified by Google's large-scale mutation testing research.

**Candidate patterns to skip:**
- Logging calls: `logging.debug/info/warning/error(...)`, `logger.*(...)`
- Docstrings: string-only expressions at statement level
- `__repr__`, `__str__`, `__format__` methods (formatting, not logic)
- Module metadata: `__all__`, `__version__`, `__author__` assignments
- Re-raise in except: `except X: raise` (re-raise of caught exception)
- Type-checking-only blocks: `if TYPE_CHECKING:` bodies

**Implementation:** Could be either:
1. A `mutmut_filter_mutations` implementation (post-generation filter)
2. A `mutmut_skip_node` implementation (prevents generation entirely — more efficient)

`mutmut_skip_node` is `firstresult=True`, so only one plugin can provide it. If mutmut core or another plugin already implements it, this would need coordination.

**Effort:** 1-2 days. Low risk — purely additive skip rules.

**Source:**
- Petrovic et al., "Practical mutation testing at scale" (IEEE TSE 2021, Google)

## Strategy C: Z3-Based Per-Expression Equivalence

**Concept:** Encode the original and mutated expression into Z3 SMT constraints. If `∀ inputs: original(inputs) == mutated(inputs)` is provable, the mutation is equivalent.

**Applicability to Python:** Very limited.
- Python's dynamic typing means variable types are unknown at analysis time.
- Duck typing, operator overloading (`__add__`, etc.), and runtime dispatch defeat static encoding.
- Feasible only for expressions over known-type literals (e.g., `2 * 3` vs `2 + 3`), which are already caught by bytecode TCE.
- Not worth the engineering effort for Python. The technique shines in statically-typed languages (Java, C).

**Effort:** Very high (10+ days). High risk of low yield.

**Source:**
- Kaminski et al., "Identifying method-level mutation subsumption using Z3" (IST 2020)

## Strategy D: Dominator Mutation Analysis (Post-Hoc)

**Concept:** After running all mutations against all tests, compute the minimal "dominator" set — the smallest subset of mutants such that any test suite killing all dominators also kills all others. Typically 5-20% of the full set.

**Key distinction:** This is NOT a pre-filter. It requires a complete mutation testing run first. Useful for:
- Reducing future runs (cache the dominator set)
- Analyzing test suite adequacy (dominator kill rate is a better metric than raw mutation score)
- Incremental testing (only re-run dominators on code changes)

**Not applicable to `mutmut_filter_mutations`** — the hook runs before tests, and dominators can only be computed after.

**Effort:** 5-8 days. Would require a new hook (`mutmut_post_run` analysis) and persistent storage.

**Sources:**
- Kurtz et al., "Analyzing the validity of selective mutation with dominator mutants" (ESEC/FSE 2014)
- Ammann et al., "Establishing confidence in mutation testing results" (ICST 2014)

## Strategy E: Commutative Operand Swap Detection

**Concept:** Detect mutations that swap operands of commutative operators (`a + b → b + a`, `a * b → b * a`, `a & b → b & a`, `a | b → b | a`, `a ^ b → b ^ a`). For Python's built-in numeric types, these are identity operations.

**Caveat:** Python allows operator overloading. `a + b` is NOT guaranteed equal to `b + a` for arbitrary objects (e.g., string concatenation, custom `__add__`). This makes the technique not fully deterministic without type information.

**Conservative approach:** Only flag as equivalent when BOTH operands are literals of the same numeric type. This is provably correct but very narrow.

**Already partially covered** by bytecode TCE (Phase 2) — if CPython constant-folds both orderings to the same value, TCE catches it.

**Effort:** 0.5 days if limited to literal operands. Folded into Phase 2 testing.

## Strategy F: Dead Code After Unconditional Control Flow

**Concept:** If a mutation only changes code after an unconditional `return`, `raise`, `break`, or `continue`, the change is unreachable and equivalent.

**Algorithm:**
1. Parse both original and mutated function bodies.
2. For each statement list (function body, if/else branches, loop bodies), find the first unconditional control flow statement.
3. Split into live (before) and dead (after) segments.
4. If live segments are identical and only dead segments differ → equivalent.

**Conservative scope:** Only check top-level statements in each block, not deeply nested ones.

**Partially covered by bytecode TCE** — CPython eliminates some dead code during compilation.

**Effort:** 1-2 days. Low risk — straightforward AST analysis.

## Strategy G: Identity Operation Detection (AST-Level)

**Concept:** Detect mutations that introduce mathematical identity operations, even when CPython's optimizer doesn't fold them (because they involve variables, not literals).

**Patterns:**
| Pattern | Identity | Commutative? |
|---------|----------|-------------|
| `x + 0`, `0 + x` | additive identity | yes |
| `x - 0` | additive identity | no |
| `x * 1`, `1 * x` | multiplicative identity | yes |
| `x / 1` | multiplicative identity | no |
| `x ** 1` | power identity | no |
| `x // 1` | floor division identity | no (for positive x) |
| `x ^ 0`, `0 ^ x` | XOR identity | yes |
| `x << 0`, `x >> 0` | shift identity | no |
| `x and True` | boolean identity | no |
| `x or False` | boolean identity | no |

**Only flag when the identity operand is a literal constant** (matched via `ast.Constant`). This avoids false positives from variables that happen to hold identity values.

**Caveat:** For integer types these are provably correct. For floats, `x + 0.0` may differ from `x` due to signed zero (`-0.0 + 0.0 = 0.0`). Limit to integer literals to be safe.

**Partially covered by bytecode TCE** for literal-only expressions. This strategy adds value for mixed variable+literal cases like `x + 0` where CPython doesn't fold.

**Effort:** 1-2 days. Low risk if limited to integer literals.

## Prioritization

| Strategy | Deterministic | Effort | Expected Yield | Recommendation |
|----------|--------------|--------|----------------|----------------|
| A: Subsumption | Mostly (weak mutation) | 3-5d | 10-30% on comparison-heavy code | Implement after Phases 1-2, validate empirically |
| B: Arid nodes | Yes | 1-2d | Low-medium | Quick win, do anytime |
| C: Z3 | Yes | 10+d | Negligible in Python | Skip |
| D: Dominators | Yes (post-hoc) | 5-8d | N/A (different goal) | Future project, not a filter |
| E: Commutative | Partially | 0.5d | Minimal beyond TCE | Fold into Phase 2 |
| F: Dead code | Yes | 1-2d | Low | Fold into Phase 2 or Strategy G |
| G: Identity ops | Yes (int literals) | 1-2d | Low-medium | Complement to TCE |

**Recommended sequence after Phases 1-2:** B (quick) → G+F (complement TCE) → A (highest yield but needs validation).

## General Sources

- Papadakis et al., "Trivial compiler equivalence" (ICSE 2015) — https://ieeexplore.ieee.org/document/7194639/
- Kintis et al., "Detecting trivial mutant equivalences via compiler optimisations" (IEEE TSE 2018) — https://ieeexplore.ieee.org/document/7882714/
- Petrovic et al., "Practical mutation testing at scale" (IEEE TSE 2021, Google) — https://homes.cs.washington.edu/~rjust/publ/practical_mutation_testing_tse_2021.pdf
- Kurtz et al., "Static analysis of mutant subsumption" (ICSE 2015) — https://ieeexplore.ieee.org/document/7107454/
- Kaminski et al., "Identifying method-level mutation subsumption using Z3" (IST 2020)
- Ammann et al., "Mutant reduction based on dominance relation" (IST 2016)
- CPython peephole optimizer — https://akaptur.com/blog/2014/08/02/the-cpython-peephole-optimizer-and-you/
- Python dis module — https://docs.python.org/3/library/dis.html
- PIT mutation testing concepts — https://pitest.org/quickstart/basic_concepts/
- cargo-mutants design — https://github.com/sourcefrog/cargo-mutants/blob/main/DESIGN.md
