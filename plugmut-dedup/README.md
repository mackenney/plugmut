# plugmut-dedup

Structural and bytecode deduplication for [plugmut](https://github.com/mackenney/plugmut).

Reduces mutation testing time by eliminating redundant mutations before test execution — mutations that would produce the same observable behavior as each other or as the original code.

## Installation

```bash
pip install plugmut-dedup
```

## Usage

Simply install alongside plugmut. Deduplication activates automatically via the `mutmut_filter_mutations` hook — no configuration needed.

```bash
plugmut run  # deduplication applied automatically
```

## How It Works

Deduplication runs in two successive phases on each batch of mutations before any tests execute.

### Phase 1: Structural Normalization

Two mutations at the same site are structurally equivalent if their normalized AST representations match. Normalization strips superficial syntactic differences:

- Whitespace and indentation
- Quote style (single vs. double)
- Comments
- Type annotations

**Examples of mutations removed by Phase 1:**

- `x = 'foo'` vs `x = "foo"` — same value, different quote style
- `def f(x: int): return x` vs `def f(x): return x` — annotation stripped

Structural normalization applies to all mutations, including module-level code.

### Phase 2: Bytecode Equivalence

After Phase 1, mutations inside function bodies are checked against compiled bytecode. A mutation is removed if:

- It compiles to the same bytecode as the **original** function (no behavioral change introduced)
- It compiles to the same bytecode as a **previously retained** mutation at the same site

Phase 2 only applies to mutations inside function bodies (`def` / `async def`). Module-level mutations are conservatively kept. When any step of bytecode comparison fails (serialization error, `SyntaxError`, etc.), the mutation is retained.

**Examples of mutations removed by Phase 2 (CPython ≥ 3.13):**

- `2 * 3` vs `6` — constant folded to identical bytecode
- `True and x` vs `x` — bool short-circuit folded away

## Python Version Notes

Deduplication results may vary between CPython versions:

- **Phase 1**: `ast.dump` format changed in Python 3.8 (unified `Constant` node) and 3.12 (added `type_params`). The set of structural duplicates detected can differ across these boundaries.
- **Phase 2**: CPython's peephole optimizer became more aggressive in Python 3.13, folding constant arithmetic and boolean short-circuits that earlier versions did not fold.

Results are reproducible within a single Python version. PyPy, Jython, and other non-CPython implementations are not supported for Phase 2.

## Performance

mutmut-dedup helps most when:

- Many mutations target the same site (e.g., multiple operators replacing a single binary expression)
- The codebase has heavily annotated function signatures (Phase 1 collapses annotation-only differences)
- CPython ≥ 3.13 is used (more aggressive constant folding increases Phase 2 yield)

Deduplication runs before any test subprocess is launched, so even modest reduction in mutation count yields proportional test-time savings.

## Documentation

See [SPEC.md](SPEC.md) for detailed equivalence definitions and behavioral invariants.

## License

MIT License. See [LICENSE](LICENSE).

Built on [plugmut](https://github.com/mackenney/mutmut) (a fork of [mutmut](https://github.com/boxed/mutmut) by Anders Hovmöller). The core mutation engine is the original author's work; this plugin is by Ignacio Mackenney.
