# Conflict Resolution: set_start_method guard in __main__.py

## What changed

`mutmut/src/mutmut/__main__.py` — the bare module-level call:

```python
set_start_method("fork")
```

was replaced with a guarded form:

```python
try:
    set_start_method("fork")
except RuntimeError:
    pass  # context already set by parent process or test runner
```

## Why it couldn't be done via plugin

`set_start_method("fork")` is module-level code in `__main__.py`. There is no pluggy hook that runs before module import. Plugin hooks only fire after the plugin manager is initialized, which happens well after this line executes.

## Why it was necessary

When mutmut runs as a subprocess (`python -m mutmut run`), the module is loaded as `__main__`, not as `mutmut.__main__`. The module is therefore absent from `sys.modules['mutmut.__main__']`. When mutmut forks a child process to run the test suite, the forked child inherits the parent's multiprocessing context (fork already set) but does NOT inherit `sys.modules['mutmut.__main__']`. The child's trampoline code then does:

```python
from mutmut.__main__ import record_trampoline_hit
```

This triggers a fresh import of `mutmut.__main__`, which re-executes the module-level `set_start_method("fork")` call on a context that is already set — raising `RuntimeError: context has already been set`.

The guard makes the import safe in any execution context (in-process, subprocess, forked child).

## How to resolve if upstream touches the same code

Upstream may add their own guard or restructure the code. Likely conflicts:

1. **Upstream removes the call entirely** — drop our patch, no longer needed.
2. **Upstream wraps it in `if __name__ == "__main__"`** — that would break trampoline imports differently. Our guard is still needed; keep it alongside theirs.
3. **Upstream uses `force=True`** — that would force `fork` even if another method was set, which is more aggressive. Our try/except is more conservative (respects whatever was set first). Evaluate which is correct for the upstream context.
4. **Upstream moves the call into a function** — straightforward merge; apply the try/except inside that function.

The patch is a 3-line wrapper around a single call. Any conflict will be obvious and mechanical to resolve.
