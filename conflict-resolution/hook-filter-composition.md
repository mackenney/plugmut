# Hook filter composition patch

## What changed

`mutmut/src/mutmut/file_mutation.py`, `create_mutations()` function (around line 129).

Replaced the pluggy fan-out call to `mutmut_filter_mutations` with a manual `get_hookimpls()` reduce loop. Each filter plugin now receives the output of the previous plugin instead of the original unfiltered list.

### Before (broken)
```python
for result in pm.hook.mutmut_filter_mutations(filename=filename, mutations=mutations):
    if result is not None:
        mutations = result
```

### After (fixed)
```python
hook_impls = pm.hook.mutmut_filter_mutations.get_hookimpls()
hook_impls.sort(key=lambda h: (h.trylast, not h.tryfirst))
for impl in hook_impls:
    result = impl.function(filename=filename, mutations=mutations)
    if result is not None:
        mutations = result
```

## Why this couldn't be done via plugin

This is a bug in the hook *call site* inside mutmut core. Pluggy's default fan-out passes the same original arguments to every hook implementation, so a plugin cannot fix this from outside — the composition semantics are determined by the caller.

## How to resolve conflicts

If upstream modifies the `mutmut_filter_mutations` call in `create_mutations()`:

1. Check whether upstream adopted chained composition. If so, drop this patch.
2. If upstream still uses the fan-out pattern (`for result in pm.hook.mutmut_filter_mutations(...)`), reapply the `get_hookimpls()` reduce pattern shown above.
3. If upstream changed the hook signature (added/removed parameters), update the `impl.function()` call to match.

The sort key `(h.trylast, not h.tryfirst)` matches pluggy's execution order: `tryfirst` hooks first, then regular, then `trylast`.

## Tests

`mutmut/tests/test_hookspecs.py` contains three tests covering this fix:

- `test_filter_hooks_chain_results` — verifies the second plugin sees the first plugin's filtered output
- `test_filter_hooks_chain_none_passthrough` — verifies `None` return passes the current list through
- `test_filter_hooks_order_respected` — verifies `tryfirst` > regular > `trylast` ordering
