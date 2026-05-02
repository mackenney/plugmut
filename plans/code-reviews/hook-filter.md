# Code Review: Hook Filter Composition (agent-a8b9d9a9)

## Summary

The core semantic change is 8 lines in `mutmut/src/mutmut/file_mutation.py` (`create_mutations`).
Three new tests verify chaining, None passthrough, and tryfirst/regular/trylast ordering.
A conflict-resolution guide documents the patch.

The chaining logic is conceptually correct, but **C1 is present and confirmed as a live crash**.
The fix cannot be merged until C1 is addressed. One additional undocumented behavioral
difference from pluggy's standard semantics was found.

---

## Known Issues Status

### C1 — Pluggy arg subsetting bypass: **PRESENT**

```python
# f644cda: src/mutmut/file_mutation.py, lines 144-149
hook_impls = pm.hook.mutmut_filter_mutations.get_hookimpls()
hook_impls.sort(key=lambda h: (h.trylast, not h.tryfirst))
for impl in hook_impls:
    result = impl.function(filename=filename, mutations=mutations)  # ← BUG
    if result is not None:
        mutations = result
```

`impl.function(filename=filename, mutations=mutations)` calls the raw bound method directly,
bypassing pluggy's argument subsetting. Any plugin that declares only `mutations` in its
hook signature (a valid subset per the hookspec) crashes immediately:

```
TypeError: SubsetPlugin.mutmut_filter_mutations() got an unexpected keyword argument 'filename'
```

**Verified live** — a two-line test plugin reproduces the crash against the actual committed code.

Pluggy demonstrates the contrast:
```python
# Normal pluggy call — arg subsetting handled automatically:
pm.hook.my_hook(x=5, y=10)      # plugin accepting only x= works fine

# Direct impl.function call — crashes:
hi.function(x=5, y=10)          # plugin accepting only x= → TypeError
```

**Fix** (from wave2 findings):
```python
import inspect
hook_impls = pm.hook.mutmut_filter_mutations.get_hookimpls()
hook_impls.sort(key=lambda h: (h.trylast, not h.tryfirst))
for impl in hook_impls:
    sig = inspect.signature(impl.function)
    kwargs = {"filename": filename, "mutations": mutations}
    accepted = {k: v for k, v in kwargs.items() if k in sig.parameters}
    result = impl.function(**accepted)
    if result is not None:
        mutations = result
```

### H5 — Merge conflict with source tracking (agent-afcf9355): **RISK CONFIRMED**

Both branches modify `file_mutation.py`. This branch changes `create_mutations` (lines
~138–149). The source tracking branch changes `mutate_file_contents` (return type) and
`mutmut_mutations_created` arguments. Distinct functions, but the files will need a
3-way merge. The conflict-resolution guide does not document this; it only covers upstream
conflicts, not sibling branch merges.

---

## New Issues Found

### BLOCKER

**No test for C1 crash scenario**

All three new tests declare `mutmut_filter_mutations(self, filename, mutations)` — the full
parameter list. Zero tests exercise a plugin that accepts only a subset (e.g., only
`mutations`). The C1 crash is entirely absent from the test suite; it will regress silently
after any refactor of the call site.

Required test:
```python
def test_filter_hook_arg_subsetting():
    """A plugin that omits 'filename' from its signature MUST NOT crash."""
    class MutationsOnlyPlugin:
        @hookimpl
        def mutmut_filter_mutations(self, mutations):
            return mutations[1:]

    pm = get_plugin_manager()
    plugin = MutationsOnlyPlugin()
    pm.register(plugin)
    try:
        _, result = create_mutations("def f():\n    return 1 + 2\n", filename="t.py")
        assert len(result) > 0
    finally:
        pm.unregister(plugin)
```

### IMPORTANT

**Within-tier ordering is FIFO; pluggy standard is LIFO — undocumented behavioral difference**

The sort key `(h.trylast, not h.tryfirst)` uses Python's stable sort, so within the same
tier (e.g., two regular plugins, or two trylast plugins) the first-registered plugin runs
first. Pluggy's standard semantics within a tier is LIFO (last-registered runs first).

Verified:
```
Branch behavior: ['first', 'second']     # FIFO
Pluggy standard: ['pluggy_second', 'pluggy_first']  # LIFO
```

This is not necessarily wrong — FIFO is arguably more natural for pipeline semantics — but
it is a silent deviation from what plugin authors who have used pluggy elsewhere expect.
The conflict-resolution guide and code comment should document this deviation explicitly.

### SUGGESTION

**`tryfirst=True, trylast=True` combination silently assigned middle priority**

A plugin with both `tryfirst=True` and `trylast=True` gets sort key `(True, False)`, which
places it between regular plugins and trylast-only plugins. Pluggy raises `ValueError` for
this combination. The branch accepts it silently with undefined semantics. Since this is a
pathological case, a guard (`assert not (impl.tryfirst and impl.trylast)`) or a comment
is sufficient, but the current silence is misleading.

**Conflict-resolution guide doesn't mention sibling-branch merge risk**

`conflict-resolution/hook-filter-composition.md` documents upstream conflict resolution only.
It should note that agent-afcf9355 (source tracking) also modifies `file_mutation.py` and
requires a 3-way merge between the two branches before either can be merged to main.

---

## Chaining Semantics Correctness

The core logic is correct:

```python
for impl in hook_impls:
    result = impl.function(filename=filename, mutations=mutations)
    if result is not None:
        mutations = result  # next iteration receives this, not the original
```

- **None passthrough**: a plugin returning `None` means "no change"; the current `mutations`
  is passed to the next plugin unchanged. Correct.
- **Empty list**: `[]` is not `None`, so `mutations` becomes `[]` and subsequent plugins
  receive an empty list. Correct and intentional.
- **Ordering sort**: `(False, False)` (tryfirst) < `(False, True)` (regular) < `(True, True)`
  (trylast). Correct mapping to pluggy's priority tiers.
- **Short-circuit**: there is no short-circuit on empty list. All registered plugins always
  run. This is consistent with the pluggy `firstresult=False` semantics of this hookspec.

---

## Test Coverage Assessment

| Scenario | Covered |
|---|---|
| Chaining (second sees first's output) | ✅ `test_filter_hooks_chain_results` |
| None passthrough | ✅ `test_filter_hooks_chain_none_passthrough` |
| tryfirst / regular / trylast ordering | ✅ `test_filter_hooks_order_respected` |
| Arg subsetting (plugin with `mutations`-only signature) | ❌ **Not covered — C1 crash** |
| Within-tier ordering (two regular plugins) | ❌ Not covered |
| Empty mutations list at entry | ❌ Not covered (low priority) |
| Exception propagation mid-chain | ❌ Not covered (low priority) |

All 13 tests in `test_hookspecs.py` pass against the committed submodule (`f644cda`).

---

## Recommendation

**DO NOT MERGE** until C1 is fixed.

Required before merge:
1. Apply the `inspect.signature` arg-subsetting fix to `impl.function(...)` call
2. Add `test_filter_hook_arg_subsetting` to verify plugins with subset signatures work
3. Document FIFO-vs-LIFO deviation in code comment and conflict-resolution guide

Recommended before merge:
4. Add within-tier ordering test (two same-tier plugins, verify first-registered runs first)
5. Note sibling branch merge risk (afcf9355) in conflict-resolution guide

The chaining semantics, None handling, and priority ordering are all correct. The implementation
is one `inspect.signature` guard and one test away from being mergeable.
