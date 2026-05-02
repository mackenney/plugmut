# Multi-Model Cache

## Context

Cache entries store the `model` field (e.g. `"claude-sonnet-4-6"`) but the cache key on disk does not include it. Switching models in `[tool.mutmut.llm]` overwrites the previous model's entries. The original plan proposed invalidation on model switch — but that wastes already-paid-for mutations that are equally valid regardless of which model produced them.

This plan replaces the invalidation approach with **multi-model accumulation**: keep entries from all models, merge at read time.

This plan also subsumes `composite-cache-keys.md` — the in-memory index collision bug (keyed by `source_hash` alone) is fixed as part of the same index restructuring.

## Design Principles

1. **A valid mutation is a valid mutation.** Mutations are syntax-validated at generation time. Their value is independent of which model produced them.
2. **Never discard paid-for work.** Model switches should add mutations, not replace them.
3. **Generate incrementally.** `mutmut generate` only calls the API for the currently configured model. If that model already has an entry, skip.
4. **Merge at run time.** `mutmut run` yields mutations from all cached models, deduplicated.

## Problem Analysis

### Current cache key (on disk)

```python
def _cache_key(file_path, function_name, src_hash):
    return f"{safe_path}__{function_name}__{src_hash}"
```

No model component. Switching models overwrites the file.

### In-memory index (operators.py)

```python
index[entry.source_hash] = entry  # last writer wins
```

Keyed by `source_hash` alone — identical functions in different files collide (documented in `composite-cache-keys.md`).

### User-facing symptoms

1. Switch model → old mutations silently overwritten → must regenerate everything.
2. Identical functions across files → only one gets LLM mutations during `mutmut run`.

## Implementation Plan

### Step 1: Add model to `_cache_key()`

```python
def _cache_key(file_path: str, function_name: str, src_hash: str, model: str) -> str:
    safe_path = file_path.replace("/", "_").replace("\\", "_")
    safe_model = model.replace("/", "_").replace("\\", "_")
    return f"{safe_path}__{function_name}__{src_hash}__{safe_model}"
```

Disk layout becomes:
```
.mutmut-cache/llm/
  src_module_py__foo__abc123__claude-sonnet-4-6.json
  src_module_py__foo__abc123__claude-opus-4-6.json
```

Both entries coexist. No overwriting.

### Step 2: Update `write_cache_entry()`

Pass `entry.model` to `_cache_key()`:

```python
def write_cache_entry(entry: CacheEntry, base_dir: Path = Path(".")) -> Path:
    d = _cache_dir(base_dir)
    d.mkdir(parents=True, exist_ok=True)
    key = _cache_key(entry.file_path, entry.function_name, entry.source_hash, entry.model)
    path = d / f"{key}.json"
    path.write_text(json.dumps(entry.to_dict(), indent=2))
    return path
```

### Step 3: Update `read_cache_entry()` with model parameter

```python
def read_cache_entry(
    file_path: str,
    function_name: str,
    src_hash: str,
    base_dir: Path = Path("."),
    model: str | None = None,
) -> CacheEntry | None:
    if model is None:
        # Backwards-compatible: scan for any matching entry (ignoring model)
        return _read_any_matching_entry(file_path, function_name, src_hash, base_dir)

    key = _cache_key(file_path, function_name, src_hash, model)
    path = _cache_dir(base_dir) / f"{key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        entry = CacheEntry.from_dict(data)
        if entry.source_hash != src_hash:
            return None
        return entry
    except (json.JSONDecodeError, KeyError):
        return None
```

When `model` is provided (the `mutmut generate` path), look up the exact file. When `model=None`, fall back to scanning — needed for backwards compat and for callers that don't care about model.

### Step 4: Pass model through `_generate_mutations()`

In `pipeline.py`, pass `config.model` so generation checks only whether THIS model already has an entry:

```python
cached = read_cache_entry(
    target.file_path, target.function_name, src_hash,
    model=config.model, **cache_kwargs
)
```

If sonnet already has entries but opus doesn't, only opus generates. Sonnet's entries are untouched.

### Step 5: Restructure `_build_cache_index()` to merge across models

Change from `dict[str, CacheEntry]` to `dict[str, list[CacheEntry]]`:

```python
_cache_index: dict[str, list[CacheEntry]] | None = None

def _build_cache_index() -> dict[str, list[CacheEntry]]:
    index: dict[str, list[CacheEntry]] = {}
    for entry in list_cache_entries():
        index.setdefault(entry.source_hash, []).append(entry)
    return index
```

This fixes two bugs at once:
- **Multi-model**: entries from different models coexist under the same source_hash.
- **Composite-keys collision**: identical functions from different files both appear in the list instead of overwriting.

### Step 6: Update `operator_llm()` to merge and dedup

```python
def operator_llm(node: cst.FunctionDef) -> Iterable[cst.FunctionDef]:
    func_source = cst.Module(body=[node]).code
    src_hash = source_hash(func_source)

    index = _get_cache_index()
    entries = index.get(src_hash, [])
    if not entries:
        return

    func_name = node.name.value
    seen: set[str] = set()
    for entry in entries:
        for cached in entry.mutations:
            if cached.mutated_code in seen:
                continue
            seen.add(cached.mutated_code)
            mutated_node = _parse_mutation(cached.mutated_code, func_name)
            if mutated_node is not None:
                yield mutated_node
```

All mutations from all models are yielded, deduplicated by `mutated_code`.

### Step 7: Handle old cache entries (migration)

Old entries have no model in the filename. They follow the pattern `{safe_path}__{function_name}__{src_hash}.json` (3 segments separated by `__`) vs the new 4-segment format.

Two options:

**Option A (recommended): Read old entries as `model=""`.**
`list_cache_entries()` already loads them and `from_dict()` defaults `model` to `""`. They appear in the index and their mutations get merged. `mutmut generate` with a configured model checks `read_cache_entry(..., model="claude-opus-4-6")` which looks for the 4-segment filename — won't find the old file — generates a new entry. Old file becomes dead weight but causes no harm. Users can run `mutmut cache clear` if they want a clean slate.

**Option B: Auto-migrate on first load.** Read old entry, rewrite with model in filename, delete old file. More complex, marginal benefit.

Go with Option A. No migration code needed.

### Step 8: Optional `--llm-model` filter for `mutmut run`

For users who want to benchmark a single model in isolation:

```
mutmut run --llm-model claude-opus-4-6
```

Implementation: set `_active_model` in `operators.py` from the CLI flag. When set, `_build_cache_index()` filters entries to only that model. When unset (default), all models are merged.

This is a follow-up enhancement, not required for the initial implementation.

## Code Surface Impact

| File | Change | Est. diff |
|------|--------|-----------|
| `cache.py` | `_cache_key()` adds model param, `write_cache_entry()` passes model, `read_cache_entry()` adds model param with exact-file lookup | ~25 lines |
| `pipeline.py` | Pass `config.model` to `read_cache_entry()` | ~1 line |
| `operators.py` | `_cache_index` type → `dict[str, list[CacheEntry]]`, `_build_cache_index()` uses `setdefault/append`, `operator_llm()` iterates list with dedup | ~20 lines |
| Tests | Model coexistence, collision fix, dedup, backwards compat | ~60 lines |

**Total: ~50 lines core + ~60 lines tests.**

## Testing Plan

### Cache layer (`test_cache.py`)

- **`test_multi_model_entries_coexist`**: Write entries for same function with model A and model B. Both files exist on disk. `list_cache_entries()` returns both.
- **`test_read_with_model_returns_exact_match`**: Write entry with model="sonnet". `read_cache_entry(..., model="sonnet")` returns it. `read_cache_entry(..., model="opus")` returns `None`.
- **`test_read_without_model_returns_any`**: Write entry with model="sonnet". `read_cache_entry(..., model=None)` returns it (backwards compat).
- **`test_old_format_entries_still_readable`**: Write entry using old 3-segment key. `list_cache_entries()` loads it with `model=""`.

### Operator layer (`test_operators.py` or `test_plugin.py`)

- **`test_index_merges_across_models`**: Populate cache with entries from two models for same function. `_build_cache_index()` returns both under same `source_hash` key.
- **`test_operator_deduplicates_across_models`**: Two models produce overlapping mutations. `operator_llm()` yields each unique mutation exactly once.
- **`test_index_handles_identical_functions_different_files`**: Two functions with same source in different files. Both entries appear in index (composite-keys bug fix).

### Pipeline layer (`test_pipeline.py`)

- **`test_generate_skips_cached_model`**: Generate with model A. Generate again with model A. Second run makes zero API calls.
- **`test_generate_runs_for_new_model`**: Generate with model A. Switch to model B. Generate again. Second run makes API calls for model B. Model A entries untouched on disk.

## Relationship to Other Plans

- **`composite-cache-keys.md`**: Fully subsumed. The index restructuring (Step 5-6) fixes the collision bug. Mark as done after implementation.
- **`dedup/`**: Multi-model merge increases the value of dedup — more entries means more potential duplicates. No conflict.
- **`async-parallel-generation`**: Compatible. Async generation still writes one entry per (function, model). Atomic writes (separate plan) remain a prerequisite.
- **`dynamic-exclusion-list`**: Compatible. Exclusion applies at generation time per-model; cached mutations from other models are unaffected.
