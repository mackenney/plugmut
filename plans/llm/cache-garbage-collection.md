# Cache Garbage Collection

## Context

Cache entries accumulate forever. Renamed/moved/deleted functions leave orphaned entries. After weeks of development, the cache grows unbounded with no cleanup mechanism beyond `clear_cache()` which nukes everything.

## Problem Analysis

### How orphaned entries accumulate

Cache keys encode `file_path`, `function_name`, and `source_hash` into the filename:

```
src_module.py__foo__a1b2c3d4e5f67890.json
```

Orphans appear in three scenarios:

1. **Function renamed** (`foo` -> `bar`): old `__foo__<hash>.json` persists, new `__bar__<hash>.json` is created. The old entry never matches a lookup because no code asks for `foo` anymore.

2. **File moved/deleted** (`src/module.py` -> `src/utils.py`): old `src_module.py__foo__<hash>.json` persists. The new path generates `src_utils.py__foo__<hash>.json`.

3. **Function body changed**: old hash entry stays on disk. `read_cache_entry` skips it (hash mismatch), but the file remains. This is the most common case -- every source edit to a cached function leaves a stale entry behind.

```python
# Day 1: generate cache for foo v1
# -> src_module.py__foo__aaaa.json

# Day 2: edit foo, regenerate
# -> src_module.py__foo__bbbb.json  (new)
# -> src_module.py__foo__aaaa.json  (orphan, never read again)

# Day 3: rename foo -> bar
# -> src_module.py__bar__bbbb.json  (new)
# -> src_module.py__foo__bbbb.json  (orphan)
# -> src_module.py__foo__aaaa.json  (orphan)
```

### Disk space impact

Each cache entry is ~1-5 KB (JSON with mutated code strings). For a project with 200 functions:
- Initial cache: ~200 files, ~400 KB
- After 10 refactor cycles with 20% churn: ~200 + 10*40 = 600 files, ~1.2 MB
- After 50 cycles: ~1200 files, ~2.4 MB

Disk space is not the primary concern. The real cost is cognitive: `list_cache_entries()` and `llm-status` report inflated numbers, and users cannot tell which entries are live vs stale.

### Impact on `list_cache_entries()` performance

`list_cache_entries()` reads and JSON-parses every `.json` file in the cache directory. With 1000+ orphaned files, this adds measurable latency to:
- `mutmut llm-status` (calls `list_cache_entries()`)
- `mutmut_post_run` hook (sums cost from all entries)
- `_llm_mutation_count_by_function()` (called during `mutmut_mutations_created`)

At 1000 files, expect ~50-200ms of I/O on spinning disk; SSD is ~10-30ms. Not catastrophic, but unnecessary.

### `clear_cache()` is too destructive

`clear_cache()` removes every `.json` file. After clearing, `mutmut generate` must re-call the LLM API for all functions, costing real money ($0.01-0.05 per function with Claude Sonnet). Users who rename one function should not pay to regenerate mutations for 199 unchanged functions.

## Implementation Plan

### `mutmut cache gc` command

Add a `gc` subcommand (and optionally `stats`) under a `cache` command group registered via `mutmut_register_commands`.

#### GC algorithm

```python
def gc_cache(base_dir: Path, dry_run: bool = False) -> GCResult:
    entries = list_cache_entries(base_dir)
    removed = []
    kept = []

    for entry in entries:
        reason = _check_orphaned(entry, base_dir)
        if reason:
            removed.append((entry, reason))
            if not dry_run:
                _remove_entry(entry, base_dir)
        else:
            kept.append(entry)

    return GCResult(removed=removed, kept=kept)
```

#### Orphan detection checks (in order)

1. **File exists**: `Path(entry.file_path).exists()`. If not, orphan reason = "file deleted/moved".

2. **Function exists in file**: Parse the file with `libcst` (already a dependency), walk the tree to find a `FunctionDef` with `entry.function_name`. If not found, orphan reason = "function renamed/deleted". For method names stored as `ClassName.method`, check for a `ClassDef` containing that `FunctionDef`.

3. **Source hash matches**: Extract the function source, compute `source_hash()`, compare to `entry.source_hash`. If mismatch, orphan reason = "source changed (stale hash)".

Check 3 is the most common orphan type. It is also the cheapest to validate since `source_hash` is just SHA-256 of the extracted source text.

#### Age-based pruning (optional flag)

```
mutmut cache gc --max-age 30
```

Remove entries where `generated_at` is older than N days, regardless of validity. Uses the `generated_at` ISO timestamp already stored in `CacheEntry`. Entries without `generated_at` (empty string) are treated as infinitely old.

#### Dry-run mode

```
mutmut cache gc --dry-run
```

Print what would be removed without deleting. Output format:

```
Would remove: src/module.py::foo (file deleted)
Would remove: src/module.py::bar (source changed)
Would remove: src/old_file.py::baz (function not found)

Dry run: 3 entries would be removed, 47 would be kept.
```

#### `mutmut cache stats`

Show cache health without modifying anything:

```
Cache directory: .mutmut-cache/llm/
Total entries: 50
  Valid: 42
  Orphaned: 8
    File deleted: 2
    Function removed: 3
    Source changed: 3
Total mutations cached: 187
Total generation cost: $0.42
Oldest entry: 2026-01-15
Newest entry: 2026-03-04
```

### CLI registration

The `mutmut_register_commands` hookspec receives the Click CLI group. Register a `cache` group with `gc` and `stats` subcommands:

```python
@hookimpl
def mutmut_register_commands(cli_group: object) -> None:
    # ... existing generate and llm-status commands ...

    @cli_group.group()  # type: ignore[union-attr]
    def cache() -> None:
        """Manage the LLM mutation cache."""

    @cache.command()
    @click.option("--dry-run", is_flag=True, help="Show what would be removed.")
    @click.option("--max-age", type=int, default=None, help="Remove entries older than N days.")
    def gc(dry_run: bool, max_age: int | None) -> None:
        """Remove orphaned cache entries."""
        from mutmut_llm.gc import gc_cache
        result = gc_cache(Path("."), dry_run=dry_run, max_age_days=max_age)
        # print summary

    @cache.command()
    def stats() -> None:
        """Show cache size and health."""
        from mutmut_llm.gc import cache_stats
        # print stats
```

**Conflict with existing commands**: The existing `generate` and `llm-status` commands are registered as top-level commands on `cli_group`. The `cache` group is a new namespace, no conflict. If Click does not support mixing `@cli_group.group()` with the existing hookimpl pattern, fall back to `mutmut cache-gc` and `mutmut cache-stats` as flat commands.

### Command signatures

```
mutmut cache gc [--dry-run] [--max-age DAYS]
mutmut cache stats
```

## Code Surface Impact

### New module: `mutmut-llm/src/mutmut_llm/gc.py`

~100-140 lines. Contains:

- `GCResult` dataclass (removed list, kept list, reasons)
- `gc_cache(base_dir, dry_run, max_age_days) -> GCResult`
- `_check_orphaned(entry, base_dir) -> str | None` (returns reason or None)
- `_remove_entry(entry, base_dir) -> None`
- `cache_stats(base_dir) -> CacheStats`
- `CacheStats` dataclass

### Changes to `cache.py`

Add `remove_cache_entry(file_path, function_name, src_hash, base_dir) -> bool` to delete a single entry by key. ~8 lines. The GC module needs this to remove individual files without reimplementing key logic.

### Changes to `plugin.py`

Add `cache` group with `gc` and `stats` subcommands inside `mutmut_register_commands`. ~30 lines.

### Estimated total new code

- `gc.py`: ~130 lines
- `cache.py` addition: ~8 lines
- `plugin.py` addition: ~30 lines
- Tests: ~150 lines
- **Total: ~320 lines**

## Testing Plan

### Unit tests for GC logic (`tests/test_gc.py`)

1. **Orphaned: file deleted** -- Write cache entry for `src/gone.py::foo`, do not create the file, run GC. Assert entry removed.

2. **Orphaned: function renamed** -- Write cache entry for `src/mod.py::old_name`, create `src/mod.py` with only `def new_name(): ...`. Assert entry removed.

3. **Orphaned: source changed** -- Write cache entry with hash of `def foo(): return 1`, create file with `def foo(): return 2`. Assert entry removed.

4. **Valid entry preserved** -- Write cache entry matching actual file/function/hash. Assert entry kept.

5. **Mixed: GC removes only orphans** -- Write 3 valid + 2 orphaned entries. Assert exactly 2 removed, 3 kept.

6. **Dry-run mode** -- Write orphaned entry, run GC with `dry_run=True`. Assert entry still exists on disk. Assert `GCResult.removed` lists it.

7. **Age-based pruning** -- Write entry with `generated_at` 60 days ago, run GC with `max_age_days=30`. Assert removed. Write entry from today, assert kept.

8. **Empty cache** -- Run GC on empty dir. Assert no error, 0 removed, 0 kept.

### Unit tests for stats (`tests/test_gc.py`)

9. **Stats with mixed entries** -- Write valid and orphaned entries. Assert counts match.

10. **Stats with empty cache** -- Assert all zeros.

### Integration test in `tests/test_plugin.py`

11. **CLI `cache gc --dry-run`** -- Invoke via Click test runner. Assert output contains expected summary.

12. **CLI `cache stats`** -- Invoke via Click test runner. Assert output format.

### Function existence check tests

13. **Method in class** -- Entry with `function_name="MyClass.method"`, file has `class MyClass` with `def method`. Assert valid.

14. **Nested function** -- Entry for top-level function that contains a nested def. Assert the outer function is found.

## Usability/Feature Impact

### When should users run GC?

- **After refactoring** (renames, moves, deletes) -- this is when orphans are created.
- **Periodically** in CI if `mutmut generate` runs in pipelines.
- Suggest in `mutmut cache stats` output when orphan ratio exceeds 20%.

### Should GC run automatically before `mutmut generate`?

No. Reasons:
- GC requires parsing source files (libcst), adding latency to every generate run.
- Users may want stale entries for rollback (checking out older branches).
- Explicit is better. Print a hint if `cache stats` shows high orphan count.

A future option `--auto-gc` on `mutmut generate` could enable this opt-in.

### Output format

Terse by default, verbose with `--dry-run`:

```
# Normal run
Removed 8 orphaned cache entries (3 deleted files, 2 renamed functions, 3 stale hashes).
47 valid entries kept.

# Dry run
Would remove: src/module.py::foo — file deleted
Would remove: src/module.py::bar — source changed (hash mismatch)
...
Dry run: 8 entries would be removed, 47 would be kept.
```

### Priority assessment

**Nice-to-have**, not a must-have. The cache works correctly without GC -- orphaned entries are never read (hash mismatch prevents stale reads). The primary value is:
- Accurate `llm-status` reporting (no inflated counts/costs from orphans)
- Slightly faster `list_cache_entries()` over time
- User confidence that the cache is clean

Recommended implementation order: after core LLM pipeline is stable and in regular use.
