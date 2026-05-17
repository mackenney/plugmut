# Content-addressed mutant naming

## What changed

Replaced sequential positional naming (`{mangled_name}_{i+1}`) with content-addressed
hash-based naming (`{mangled_name}__{hash}` — 12 hex chars).

New file: `mutmut/src/mutmut/normalize.py`
Modified: `mutmut/src/mutmut/file_mutation.py` (`function_trampoline_arrangement`)

### Before
```python
mutant_name = f"{mangled_name}_{i + 1}"
```

### After
```python
hash_suffix = compute_mutant_hash(norm_path, norm_original, norm_mutated, idx)
mutant_name = f"{mangled_name}__{hash_suffix}"
```

The double underscore separator distinguishes hash-based names from the old sequential
names. Hash inputs: normalized relative file path, normalized original CST, normalized
mutated CST, and an occurrence index (so identical transformations at the same site are
still distinct).

## Why this couldn't be done via plugin

Mutant naming is core functionality. It determines result persistence, test runner
identification, and how plugins identify their own mutations via
`mutmut_mutations_created`. Plugins cannot intercept name assignment.

## Files modified

### `mutmut/src/mutmut/normalize.py` (new)

Added `normalize_path()` and `compute_mutant_hash()` alongside the normalization
primitives already shared with `mutmut-dedup`.

### `mutmut/src/mutmut/file_mutation.py`

- `function_trampoline_arrangement()` signature gains `relative_path: str` parameter.
- Naming loop replaced with hash-based logic using `compute_mutant_hash()`.
- Call sites in `combine_mutations_to_source()` pass `filename` as `relative_path`.

## How to resolve conflicts

If upstream modifies `function_trampoline_arrangement()`:
1. Check if upstream adopted content-addressed naming — if so, drop this patch.
2. Ensure `relative_path: str` is present in the function signature.
3. Ensure the naming loop builds `occurrence_counts` keyed on `(norm_original, norm_mutated)`.
4. Ensure `compute_mutant_hash()` from `normalize.py` is used.
5. Name format uses double underscore: `{mangled_name}__{hash}` (12 hex chars).
6. Update e2e snapshots after any change: `uv run --package mutmut pytest mutmut/tests/e2e/ --inline-snapshot=fix`.

## Verification

```bash
test -f mutmut/src/mutmut/normalize.py
grep -q "compute_mutant_hash" mutmut/src/mutmut/normalize.py
grep -q "hash_suffix" mutmut/src/mutmut/file_mutation.py
uv run --package mutmut pytest mutmut/tests/ -x -q
uv run --package mutmut pytest mutmut/tests/e2e/ -x -q
```
