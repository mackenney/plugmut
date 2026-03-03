# allowlist-calls hook patch

## What changed

Two files patched:

### `mutmut/src/mutmut/hookspecs.py`
Added `mutmut_allowlist_calls` hookspec to `MutmutHookSpec`:
```python
@hookspec
def mutmut_allowlist_calls(self) -> list[str]:
    """Return function call names that should NOT be skipped during mutation."""
```

### `mutmut/src/mutmut/file_mutation.py`
1. `MutationVisitor.__init__` gained `allowlist_calls: set[str] | None = None` parameter, stored as `self._allowlist_calls`.
2. `_skip_node_and_children` checks `node.func.value not in self._allowlist_calls` before skipping a call.
3. `create_mutations` collects the allowlist from `pm.hook.mutmut_allowlist_calls()` and passes it to the visitor.

## Why this couldn't be done via plugin

`NEVER_MUTATE_FUNCTION_CALLS` in `file_mutation.py` hardcodes `{"len", "isinstance"}`. The visitor's `_skip_node_and_children` returns `True` for matching calls, causing `on_visit` to return `False` — skipping the node AND all children. There is no plugin hook to override this behavior without patching the visitor.

The `isinstance` skip exists to prevent `operator_arg_removal` (a built-in operator) from producing nonsense mutants like `isinstance(None, (int, str))`. Removing it entirely would break the core test at `test_mutation.py:300` which expects `isinstance(a, b) -> []`. The allowlist hook lets targeted plugins re-enable visiting for specific calls without affecting other operators or users who don't load the plugin.

## How to resolve conflicts

### `hookspecs.py`
Add `mutmut_allowlist_calls` to the merged `MutmutHookSpec`. Name is unlikely to conflict with upstream additions since it follows the `mutmut_` prefix convention.

### `file_mutation.py`
Three change points:

1. `MutationVisitor.__init__` — add `allowlist_calls` parameter and assign to `self._allowlist_calls`.
2. `_skip_node_and_children` — add `and node.func.value not in self._allowlist_calls` to the NEVER_MUTATE_FUNCTION_CALLS branch.
3. `create_mutations` — after collecting operators, collect the allowlist:
   ```python
   allowlist_calls: set[str] = set()
   for names in pm.hook.mutmut_allowlist_calls():
       allowlist_calls.update(names)
   visitor = MutationVisitor(operators, ignored_lines, covered_lines, allowlist_calls=allowlist_calls)
   ```

If upstream refactors `_skip_node_and_children` or `create_mutations`, re-apply these three changes at the same logical points.
