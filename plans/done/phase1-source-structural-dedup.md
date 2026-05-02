# Phase 1: Source Structural Dedup Plugin

Standalone `mutmut-dedup` plugin implementing `mutmut_filter_mutations` to remove structurally identical mutations across all sources (core, extras, llm).

## Architecture

New workspace member: `mutmut-dedup/`

```
mutmut-dedup/
├── pyproject.toml
├── src/mutmut_dedup/
│   ├── __init__.py
│   ├── plugin.py          # hookimpl for mutmut_filter_mutations
│   └── normalize.py       # AST normalization + dedup logic
└── tests/
    ├── conftest.py
    ├── test_normalize.py   # unit tests for normalization
    ├── test_dedup.py       # unit tests for dedup logic
    ├── test_plugin.py      # integration tests with plugin system
    └── test_e2e.py         # end-to-end with real mutation runs
```

Entry point in pyproject.toml:
```toml
[project.entry-points.mutmut]
dedup = "mutmut_dedup.plugin"
```

Add `"mutmut-dedup"` to root `pyproject.toml` workspace members.

## Public API

```python
# normalize.py

def normalize_mutation(node: cst.CSTNode) -> str:
    """Convert a CST node to a canonical string via ast.dump().

    Strips whitespace, comments, string quote style, type annotations.
    Returns ast.dump(tree, annotate_fields=True, include_attributes=False).
    """

def normalize_pair(original: cst.CSTNode, mutated: cst.CSTNode) -> tuple[str, str]:
    """Normalize both original and mutated nodes. Returns (orig_norm, mut_norm)."""

def deduplicate(mutations: list[Mutation]) -> list[Mutation]:
    """Remove mutations whose normalized mutated_node matches another mutation
    at the same original_node. First occurrence wins."""
```

```python
# plugin.py

@hookimpl(trylast=True)  # run after other filter plugins
def mutmut_filter_mutations(filename: str, mutations: list) -> list | None:
    result = deduplicate(mutations)
    if len(result) < len(mutations):
        return result
    return None
```

## Normalization Algorithm

1. Render `cst.CSTNode` to source string via `module.code_for_node(node)` or reconstruct via `cst.Module(body=[node]).code`.
2. Parse with `ast.parse(source)`.
3. Run `_StripAnnotations` transformer:
   - `visit_FunctionDef`/`visit_AsyncFunctionDef`: set `returns = None`, clear all arg annotations.
   - `visit_AnnAssign`: convert to `Assign` if value present, remove if annotation-only.
4. `ast.fix_missing_locations(tree)`.
5. Return `ast.dump(tree, annotate_fields=True, include_attributes=False)`.

On `SyntaxError` during parse, fall back to `source.strip()` — still catches exact textual duplicates.

## Deduplication Algorithm

1. Group mutations by identity of `original_node` (same `id()` = same AST location).
2. For each group, compute `normalize_mutation(m.mutated_node)` for every mutation.
3. Track seen normalized forms in a `set`. First occurrence wins, subsequent duplicates dropped.
4. Return flattened list preserving original order.

## Steps

### Step 1: Scaffold the package

Create `mutmut-dedup/` with:
- `pyproject.toml` (dependencies: `mutmut>=3.5.0`, dev: `pytest>=8`)
- `src/mutmut_dedup/__init__.py` (empty)
- `src/mutmut_dedup/normalize.py` (stubs only)
- `src/mutmut_dedup/plugin.py` (stub hookimpl returning `None`)
- `tests/conftest.py`
- Empty test files

Add to root workspace members. Run `uv sync`.

**Verify:** `uv run --package mutmut-dedup python -c "from mutmut_dedup.plugin import mutmut_filter_mutations; print('ok')"` succeeds.

### Step 2: Implement `normalize_mutation`

Write `normalize.py` with `normalize_mutation(node: cst.CSTNode) -> str`.

Handle:
- Simple expressions: `1 + 2`, `"hello"`
- Function definitions with annotations
- Annotation-only statements (`x: int`)
- Syntax errors in edge-case CST output (fallback to `.strip()`)

**Unit tests** (`test_normalize.py`):
1. Two CST nodes with different whitespace normalize to same string
2. Two CST nodes with different quote styles (`'x'` vs `"x"`) normalize to same string
3. Annotated vs unannotated function signatures normalize to same string
4. `x: int = 5` and `x = 5` normalize to same string (annotation stripped)
5. `x: int` (annotation-only) normalizes to empty / is handled gracefully
6. Invalid/unparseable CST falls back to stripped source
7. Identical nodes produce identical normalized output (idempotence check)

**Smoke test:** Run `uv run --package mutmut-dedup pytest mutmut-dedup/tests/test_normalize.py -v`

### Step 3: Implement `deduplicate`

Write the `deduplicate(mutations: list[Mutation]) -> list[Mutation]` function.

Uses `normalize_mutation` on each `mutated_node`. Groups by `id(m.original_node)` to scope dedup within same mutation site.

**Unit tests** (`test_dedup.py`):
1. Empty list → empty list
2. Single mutation → unchanged
3. Two mutations with different `mutated_node` → both kept
4. Two mutations at same `original_node` producing identical normalized output → one removed
5. Two mutations at **different** `original_node` producing identical normalized output → both kept (different sites)
6. Three mutations: A, B duplicate of A, C unique → returns [A, C]
7. Order preservation: first occurrence always wins
8. Mutations whose normalization falls back to string (syntax error) still dedup correctly

**Smoke test:** `uv run --package mutmut-dedup pytest mutmut-dedup/tests/test_dedup.py -v`

### Step 4: Wire up the plugin hook

Implement `plugin.py`:
```python
from mutmut.hookspecs import hookimpl
from mutmut_dedup.normalize import deduplicate

@hookimpl(trylast=True)
def mutmut_filter_mutations(filename: str, mutations: list) -> list | None:
    result = deduplicate(mutations)
    if len(result) < len(mutations):
        return result
    return None
```

**Integration tests** (`test_plugin.py`):
1. Register the plugin manually via pluggy, confirm hook is discovered
2. Create mutations from source with known duplicates (craft source that produces dupes across core + extras operators), confirm dedup removes them
3. Confirm `trylast=True` ordering: register another filter plugin that adds a tag, verify dedup runs after it
4. Confirm `None` returned when no duplicates found (no unnecessary list copy)

Setup pattern for integration tests:
```python
@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    from mutmut.plugin_manager import reset_plugin_manager
    reset_plugin_manager()
    yield
    reset_plugin_manager()
```

**Smoke test:** `uv run --package mutmut-dedup pytest mutmut-dedup/tests/test_plugin.py -v`

### Step 5: End-to-end tests

Test the full pipeline: source code → `create_mutations()` → filter hook → verify dedup happened.

**E2E tests** (`test_e2e.py`):
1. Write a Python source string that triggers overlapping operators (e.g., a function returning `a + b` — core's binary operator and extras' operand_swap both produce mutations). Run `create_mutations()` with all plugins loaded. Count mutations with and without dedup plugin. Verify count decreased.
2. Write a source that produces NO duplicates. Verify mutation count unchanged.
3. Write a source with 3+ duplicates at same site. Verify exactly 1 survivor per normalized form.
4. Verify that surviving mutations are still valid: apply each via `module.deep_replace(m.original_node, m.mutated_node)` and confirm `.code` produces parseable Python.

**Full suite smoke test:** `uv run --package mutmut-dedup pytest mutmut-dedup/ -v`

### Step 6: Cross-plugin verification

Run the full mutmut test suites to confirm no regressions:
```bash
uv run --package mutmut pytest mutmut/tests/ -x
uv run --package mutmut-extras pytest -x
uv run --package mutmut-dedup pytest -x
```

Manually run mutmut on a small project with all plugins enabled to observe dedup in action. Check that mutation count is ≤ the count without dedup.
