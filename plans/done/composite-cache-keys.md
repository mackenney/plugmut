# Composite Cache Keys

> **STATUS: Subsumed by `model-validation-on-read.md` (Multi-Model Cache).** The index restructuring in Steps 5-6 of that plan fixes the collision bug described here. Move to `done/` after implementation.

## Context

The in-memory cache index (`_cache_index` in `operators.py`) is keyed by `source_hash` alone. Two functions with identical source but different names or files silently collide: the last entry loaded by `_build_cache_index()` overwrites all previous ones. The on-disk cache is already correctly keyed by `(file_path, function_name, source_hash)` via `_cache_key()`, so the bug is limited to the in-memory index used during `mutmut run`.

## Problem Analysis

### Where the bug lives

1. **`operators.py:35`** — `_build_cache_index()` iterates all cache entries and sets `index[entry.source_hash] = entry`. When two entries share the same `source_hash`, the second silently overwrites the first.

2. **`operators.py:57`** — `operator_llm()` looks up `index.get(src_hash)`. It gets whichever entry happened to load last, which may belong to a different file/function. The mutations still get applied (they parse as valid FunctionDef nodes with matching names), but they are the wrong function's mutations.

### Concrete collision scenarios

**Identical getter bodies.** Two files with trivially identical functions:
```python
# models/user.py
def get_name(self):
    return self.name

# models/product.py
def get_name(self):
    return self.name
```
Both produce the same `source_hash`. Only one set of LLM mutations survives in the index. The other function silently gets zero LLM mutations during `mutmut run`.

**Stub/placeholder functions.** `def not_implemented(self): raise NotImplementedError` appearing in multiple files.

**Delegating wrappers.** `def run(self): return self.execute()` in multiple classes across different files.

### Impact scope

- Only affects `mutmut run` (the operator side). The `mutmut generate` pipeline uses `read_cache_entry()` with the full `(file_path, function_name, source_hash)` key and is not affected.
- The on-disk cache files are named with composite keys (`_cache_key()`), so no data is lost on disk. The bug is purely in the in-memory index.

## Implementation Plan

### Step 1: Change `_cache_index` key to composite tuple

In `operators.py`, change the index type from `dict[str, CacheEntry]` to `dict[tuple[str, str, str], CacheEntry]` keyed by `(file_path, function_name, source_hash)`.

```python
_cache_index: dict[tuple[str, str, str], CacheEntry] | None = None
```

### Step 2: Update `_build_cache_index()`

```python
def _build_cache_index() -> dict[tuple[str, str, str], CacheEntry]:
    index: dict[tuple[str, str, str], CacheEntry] = {}
    for entry in list_cache_entries():
        key = (entry.file_path, entry.function_name, entry.source_hash)
        index[key] = entry
    return index
```

### Step 3: Add a secondary index by `source_hash` for operator lookup

The operator receives only a CST `FunctionDef` node — it does not know the current file path. This is the core design tension.

**Option A: Pass file context through mutmut's operator interface.** Requires a hookspec change upstream (operators currently receive only the node). Rejected — violates "minimal changes to mutmut/" principle.

**Option B: Secondary index from `source_hash` to list of entries.** Build a `dict[str, list[CacheEntry]]` alongside the primary index. When `operator_llm()` finds multiple entries for the same `source_hash`, yield mutations from all of them (deduplicated by `mutated_code`). This is safe because mutations for identically-sourced functions are semantically valid for any instance.

**Option C: Use `source_hash` + `function_name` as composite key.** The operator has access to `node.name.value`. Key the index by `(source_hash, function_name)`. This resolves collisions between different-named functions that happen to hash the same (unlikely but possible with hash truncation). It does NOT resolve same-named, same-source functions in different files.

**Recommended: Option B** (secondary index with dedup). It handles all collision cases without requiring upstream changes. When there's exactly one match (the common case), behavior is unchanged. When there are multiple matches, we union the mutations.

### Step 4: Update `operator_llm()` lookup

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

### Step 5: Update `_get_cache_index()` return type

Change to `dict[str, list[CacheEntry]]` (keyed by `source_hash`, values are lists).

```python
_cache_index: dict[str, list[CacheEntry]] | None = None

def _build_cache_index() -> dict[str, list[CacheEntry]]:
    index: dict[str, list[CacheEntry]] = {}
    for entry in list_cache_entries():
        index.setdefault(entry.source_hash, []).append(entry)
    return index
```

### Step 6: No changes needed to cache.py

`write_cache_entry()`, `read_cache_entry()`, and `_cache_key()` already use the full composite key `(file_path, function_name, source_hash)`. No changes required.

### Step 7: No changes needed to pipeline.py

`_generate_mutations()` calls `read_cache_entry()` with full composite key. No changes required.

## Code Surface Impact

| File | Functions changed | Estimated diff |
|------|-------------------|----------------|
| `mutmut-llm/src/mutmut_llm/operators.py` | `_build_cache_index`, `_get_cache_index`, `operator_llm`, type annotation for `_cache_index` | ~20 lines |
| `mutmut-llm/tests/test_plugin.py` | Add collision test case | ~25 lines |
| `mutmut-llm/src/mutmut_llm/plugin.py` | No changes needed (imports `_reset_cache_index` and `operator_llm` — both keep same signatures) | 0 lines |
| `mutmut-llm/src/mutmut_llm/cache.py` | No changes | 0 lines |
| `mutmut-llm/src/mutmut_llm/pipeline.py` | No changes | 0 lines |
| `mutmut-llm/src/mutmut_llm/storage.py` | No changes | 0 lines |

**Total estimated diff: ~45 lines** (including tests).

## Testing Plan

### Test: collision scenario (two identical functions, different files)

Create two cache entries with the same `source_hash` but different `file_path`/`function_name`. Call `_build_cache_index()` and verify both entries are present under the same `source_hash` key. Call `operator_llm()` on a matching node and verify mutations from both entries are yielded (deduplicated).

### Test: deduplication of identical mutations

Two entries with the same `source_hash` where one mutation appears in both. Verify `operator_llm` yields it only once.

### Test: backwards compatibility with existing cache files

No migration needed — on-disk format is unchanged. The change is purely in-memory index structure. Verify `list_cache_entries()` still reads old-format files correctly (it already does; the format hasn't changed).

### Test: cache miss when source changes

Existing `TestHashKeying.test_wrong_hash_returns_none` already covers this for `read_cache_entry`. Add an analogous test for the in-memory index: modify source, compute new hash, verify `operator_llm` yields nothing.

### Test: single entry (common case) regression

Verify that the common case (one function, one file, one cache entry) still works identically. This is covered by existing `test_plugin.py::TestMutmutMutationsCreated` tests but add explicit `operator_llm` unit test.

## Usability/Feature Impact

**CLI behavior:** No change. `mutmut generate`, `mutmut run`, and `mutmut llm-status` all behave identically for the common case. The only observable difference is that functions which previously silently lost their LLM mutations due to hash collisions will now correctly receive them.

**Existing cache invalidation:** None. On-disk cache format is unchanged. No migration needed.

**Performance impact:** Negligible. The index changes from `dict[str, CacheEntry]` to `dict[str, list[CacheEntry]]`. The list lookup is O(n) where n is the number of entries sharing a hash — in practice 1-2. The dedup set adds a string comparison per mutation. Both are dominated by the CST parse cost that already exists.
