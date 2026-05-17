# Filter mutations cleanup

## What changed

`mutmut/src/mutmut/file_mutation.py`, `create_mutations()` function:

1. Added zero-mutations guard before filter hook chain — filter hooks SHOULD NOT be called when the visitor produced no mutations (SPEC requirement)
2. Removed `inspect.signature` introspection — hooks are now called with both params directly, per SPEC which requires all parameters

## Why this couldn't be done via plugin

This is the hook *call site*. Plugins implement hooks; they cannot change how the core invokes them.

## Files modified

### `mutmut/src/mutmut/file_mutation.py`

```python
# Before
import inspect

hook_impls = pm.hook.mutmut_filter_mutations.get_hookimpls()
hook_impls.sort(key=lambda h: (h.trylast, not h.tryfirst))
for impl in hook_impls:
    sig = inspect.signature(impl.function)
    available = {"filename": filename, "mutations": mutations}
    kwargs = {k: v for k, v in available.items() if k in sig.parameters}
    result = impl.function(**kwargs)
    ...

# After
if mutations:  # zero-mutations guard — SHOULD NOT call filter when no mutations
    hook_impls = pm.hook.mutmut_filter_mutations.get_hookimpls()
    hook_impls.sort(key=lambda h: (h.trylast, not h.tryfirst))
    for impl in hook_impls:
        result = impl.function(filename=filename, mutations=mutations)
        ...
```

## How to resolve conflicts

If upstream modifies the filter hook chain:
1. Ensure the zero-mutations guard wraps the entire filter block
2. Ensure direct call with both params: `impl.function(filename=filename, mutations=mutations)`
3. Do NOT reintroduce `inspect.signature` subsetting
4. Keep the `trylast/tryfirst` sort order

## Migration for plugin authors

Filter hook implementations MUST declare both parameters:

```python
def mutmut_filter_mutations(filename: str, mutations: list) -> list | None:
    ...
```

Implementations that omit `filename` will raise `TypeError` at runtime.
