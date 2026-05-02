# Fix: Chain `mutmut_filter_mutations` hook results

## Problem

`file_mutation.py:129-131` passes the **original** mutations list to every `mutmut_filter_mutations` hook implementation. Last non-None result wins, silently discarding earlier plugins' filtering.

```python
# Current (broken) — file_mutation.py:129-131
for result in pm.hook.mutmut_filter_mutations(filename=filename, mutations=mutations):
    if result is not None:
        mutations = result
```

Pluggy calls hooks in registration order (respecting `tryfirst`/`trylast`), but each hook receives the **same** `mutations` argument — the original list, not the previous hook's output.

## Impact

If plugin A (e.g., a security filter removing dangerous mutations) returns `[Y, Z]`, and plugin B (e.g., dedup with `trylast=True`) receives the original `[X, Y, Z]` and returns `[X, Z]` after deduplication, the final result is `[X, Z]` — re-introducing the mutation that A explicitly removed.

**Current exposure:** Only `mutmut-dedup` implements this hook. No other filter plugins exist yet. The bug is latent but will surface as soon as a second filter plugin is registered.

## Root cause

The pluggy `firstresult=False` hook collects all return values into a list. The iteration in `file_mutation.py` treats each result independently instead of chaining them.

## Proposed fix

### Option A: Chain results in the core loop (minimal change)

```python
# file_mutation.py — replace lines 129-131
for result in pm.hook.mutmut_filter_mutations(filename=filename, mutations=mutations):
    if result is not None:
        mutations = result
```

This already works correctly **if pluggy passes the mutated `mutations` variable to each subsequent hook call**. But it doesn't — pluggy captures the argument at call time and fans it out to all implementations.

The fix is to call hooks manually instead of using pluggy's fan-out:

```python
pm = get_plugin_manager()
hook_impls = pm.hook.mutmut_filter_mutations.get_hookimpls()
hook_impls.sort(key=lambda h: (h.hookimpl.trylast, not h.hookimpl.tryfirst))
for impl in hook_impls:
    result = impl.function(filename=filename, mutations=mutations)
    if result is not None:
        mutations = result
```

**Pros:** Minimal change, correct chaining, respects ordering hints.
**Cons:** Bypasses pluggy's hook calling machinery (wrappers, tracing). Fragile if pluggy internals change.

### Option B: Use a pluggy wrapper hook (idiomatic)

Change the hookspec to `firstresult=True` and have each plugin call the next:

```python
# hookspecs.py
@hookspec(firstresult=True)
def mutmut_filter_mutations(self, filename, mutations):
    """Filter mutations. Return filtered list or None to pass through."""
```

With `firstresult=True`, pluggy returns the first non-None result. Combined with `trylast`/`tryfirst` ordering, this gives a natural priority chain. But it doesn't compose — only one plugin's result is used.

**Verdict:** Doesn't solve the problem. Rejected.

### Option C: Accumulate via reduce pattern (recommended)

Replace the fan-out call with an explicit reduce:

```python
# file_mutation.py
for hook_impl in pm.hook.mutmut_filter_mutations.get_hookimpls():
    result = hook_impl.function(filename=filename, mutations=mutations)
    if result is not None:
        mutations = result
```

This is Option A but using `get_hookimpls()` which is a stable pluggy API.

**Pros:** Correct chaining, stable API, respects registration order.
**Cons:** Doesn't support pluggy hook wrappers (unlikely to matter for this hook).

## Steps

### Step 1: Write the patch

Change `file_mutation.py` lines 129-131 to use `get_hookimpls()` reduce pattern (Option C).

### Step 2: Add test

```python
def test_filter_hooks_chain_results():
    """Plugin A removes mutation X, plugin B (trylast) dedupes — X stays removed."""
    pm = get_plugin_manager()

    class _SecurityFilter:
        @staticmethod
        @hookimpl
        def mutmut_filter_mutations(filename, mutations):
            return [m for m in mutations if m.source != "dangerous"]

    class _DedupFilter:
        @staticmethod
        @hookimpl(trylast=True)
        def mutmut_filter_mutations(filename, mutations):
            seen = set()
            result = []
            for m in mutations:
                key = id(m.original_node)
                if key not in seen:
                    seen.add(key)
                    result.append(m)
            return result if len(result) < len(mutations) else None

    pm.register(_SecurityFilter())
    pm.register(_DedupFilter())

    # Create mutations including a "dangerous" one
    # Verify dangerous mutation is NOT in final result
```

### Step 3: Conflict resolution guide

Create `conflict-resolution/hook-filter-composition.md` per workspace rules.

### Step 4: Propose upstream

Open issue or PR on upstream mutmut explaining the composition bug with a minimal reproduction.

## Risk

**Low.** The change is 3 lines in `file_mutation.py`. The only behavioral difference is that hooks now see the chained result instead of the original list. Existing single-plugin setups are unaffected (the original list is passed to the first/only hook, same as before).
