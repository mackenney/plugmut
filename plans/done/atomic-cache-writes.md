# Atomic Cache Writes

## Context

Current `write_cache_entry()` uses `path.write_text()` directly — not atomic. A crash mid-write leaves corrupt JSON. This is a prerequisite for any future parallelization of LLM calls.

## Problem Analysis

### Write code locations

1. **`mutmut-llm/src/mutmut_llm/cache.py:86`** — `write_cache_entry()`:
   ```python
   path.write_text(json.dumps(entry.to_dict(), indent=2))
   ```

2. **`mutmut-llm/src/mutmut_llm/storage.py:48`** — `save_run()`:
   ```python
   path.write_text(json.dumps(asdict(run), indent=2))
   ```

3. **`mutmut-llm/src/mutmut_llm/pipeline.py:141`** — calls `write_cache_entry(entry, **cache_kwargs)` inside the generation loop. This is the hot path during `mutmut generate`.

### Failure scenarios

- **Crash mid-write**: `write_text()` internally opens the file, truncates it, then writes. If the process is killed between truncate and write completion, the file is left empty or partially written. Next `read_cache_entry()` sees `JSONDecodeError` and returns `None` — silently discarding a potentially expensive LLM call that already consumed API budget.
- **Disk full**: Write starts, fills remaining space, and leaves a truncated JSON blob. Same corruption outcome.
- **Concurrent `mutmut generate` processes**: Two processes targeting the same function write to the same cache key simultaneously. One overwrites the other mid-write, producing interleaved bytes. Even if both complete, last-writer-wins with no coordination means one result is silently lost.

### Read-side resilience

`read_cache_entry()` (cache.py:103-110) and `load_run()` (storage.py:71-75) both catch `JSONDecodeError` and `KeyError`, returning `None`. `list_cache_entries()` and `list_runs()` skip corrupt files with `continue`. This is a reasonable safety net but shouldn't be relied upon as the primary defense — a cache miss after a paid API call is a silent cost leak.

## Implementation Plan

### Step 1: Atomic write helper

Create a shared `_atomic_write(path: Path, data: str) -> None` function (could live in a new `mutmut_llm/_io.py` or inline in each module).

```python
import os
import tempfile

def _atomic_write(target: Path, data: str) -> None:
    fd, tmp_path = tempfile.mkstemp(
        dir=target.parent,
        suffix=".tmp",
        prefix=target.stem + ".",
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(target))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
```

Key details:
- Temp file in same directory ensures `os.replace()` is same-filesystem (required for atomicity on POSIX).
- `os.fsync()` flushes to disk before rename — prevents data loss on power failure.
- `os.replace()` is atomic on POSIX. On Windows it is atomic if the target doesn't exist; if it does, it is a rename-over which is near-atomic (single syscall, but not guaranteed by NTFS).
- `BaseException` catch ensures cleanup on `KeyboardInterrupt` too.

### Step 2: Apply to `write_cache_entry()`

In `cache.py:write_cache_entry()`, replace:
```python
path.write_text(json.dumps(entry.to_dict(), indent=2))
```
with:
```python
_atomic_write(path, json.dumps(entry.to_dict(), indent=2))
```

### Step 3: Apply to `save_run()`

In `storage.py:save_run()`, replace:
```python
path.write_text(json.dumps(asdict(run), indent=2))
```
with:
```python
_atomic_write(path, json.dumps(asdict(run), indent=2))
```

### Step 4: File-based locking for concurrent writers

For concurrent `mutmut generate` processes writing to the same cache key, add advisory locking. Two options:

**Option A: `fcntl.flock`** (POSIX only, stdlib)
- Lock `{path}.lock` before write, release after `os.replace()`.
- Pro: no new dependency. Con: not portable to Windows.

**Option B: `filelock` library** (cross-platform)
- `pip install filelock`, use `FileLock(f"{path}.lock")`.
- Pro: works everywhere, timeout support. Con: new dependency.

Recommendation: **Option A** initially. mutmut's target audience is Linux/macOS CI. Add `filelock` later only if Windows support becomes a requirement. Use a context manager wrapper:

```python
import fcntl

@contextlib.contextmanager
def _file_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
```

Integrate into `_atomic_write`:
```python
with _file_lock(target):
    # tempfile + write + fsync + os.replace
```

### Step 5: Stale temp file cleanup

Add a `clean_stale_temps(directory: Path, max_age_seconds: int = 300)` utility that removes `.tmp` files older than the threshold. Call it at the start of `run_generation()` in pipeline.py — cheap check, prevents temp file accumulation from crashed processes.

### Step 6: Error handling

- `_atomic_write` already cleans up temp on failure (Step 1).
- If `os.replace()` itself fails (permissions, readonly filesystem), the exception propagates — correct behavior since the caller (pipeline.py) should know the cache write failed.
- Lock files are harmless empty files; no cleanup needed (they're reused).

## Code Surface Impact

| File | Function | Change |
|------|----------|--------|
| `mutmut-llm/src/mutmut_llm/_io.py` | `_atomic_write()`, `_file_lock()`, `clean_stale_temps()` | **New file** |
| `mutmut-llm/src/mutmut_llm/cache.py` | `write_cache_entry()` | Replace `path.write_text()` with `_atomic_write()` (~2 lines) |
| `mutmut-llm/src/mutmut_llm/storage.py` | `save_run()` | Replace `path.write_text()` with `_atomic_write()` (~2 lines) |
| `mutmut-llm/src/mutmut_llm/pipeline.py` | `_generate_mutations()` | Add `clean_stale_temps()` call at start (~1 line) |

### Dependencies

- No new PyPI dependencies for Option A (`fcntl` is stdlib on POSIX).
- If Windows locking needed later: add `filelock` to `[project.optional-dependencies]`.

### Estimated diff size

~60 lines new code in `_io.py`, ~10 lines changed across cache.py/storage.py/pipeline.py. ~80 lines of new tests. Total: ~150 lines.

## Testing Plan

### Atomic write correctness
- Write an entry, verify file contains valid JSON (existing tests already cover this; they continue to pass).
- Simulate write failure (mock `os.fdopen` to raise after creating temp), verify temp file is cleaned up and target file is absent.

### Crash-during-write simulation
- Write a valid cache entry, then mock `os.replace` to raise. Verify original file (if any) is untouched and temp is cleaned up.

### Concurrent writes
- Use `multiprocessing` to launch two `write_cache_entry()` calls for the same cache key simultaneously. Verify the resulting file is valid JSON (not interleaved garbage). Run 50 iterations to stress.

### Stale temp cleanup
- Create `.tmp` files with old mtimes, call `clean_stale_temps()`, verify they're removed. Verify fresh temps are untouched.

### Disk-full simulation
- Use `unittest.mock.patch("builtins.open")` or a tiny tmpfs mount to trigger `OSError` during write. Verify temp cleanup and exception propagation. (Low priority — difficult to make portable.)

### Backward compatibility
- Existing test suites (`test_cache.py`, `test_storage.py`) must pass unchanged. The atomic write is an implementation detail invisible to callers.

## Usability/Feature Impact

- **Transparent to users**: No CLI changes, no config changes, no behavioral differences in the happy path.
- **Enables future parallelization**: With locking + atomic writes, multiple `mutmut generate` workers can safely write to the same cache directory. This unblocks parallel LLM API calls (the main latency bottleneck in generation).
- **Performance overhead**: One extra `fsync` per write (~0.1-1ms on SSD, ~5-10ms on HDD). Negligible relative to LLM API latency (2-10 seconds per call). Lock acquisition is ~1 microsecond uncontended. Total overhead per cache write: <2ms on SSD.
- **Disk usage**: Temp files exist for the duration of a single write (<1ms). Lock files are empty, one per cache key, persistent but harmless. `clean_stale_temps()` handles leaked temps from crashes.
