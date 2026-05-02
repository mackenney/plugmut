# isinstance type reduction operator

## Status: deferred (not worth implementing without core change)

## What

An operator that narrows `isinstance` type tuples by removing one type at a time:
- `isinstance(x, (int, str, float))` -> `isinstance(x, (str, float))`, `isinstance(x, (int, float))`, `isinstance(x, (int, str))`
- `isinstance(x, (int, str))` -> `isinstance(x, int)`, `isinstance(x, str)` (unwraps single-element tuple)

## Problem

Mutmut hardcodes `NEVER_MUTATE_FUNCTION_CALLS = {"len", "isinstance"}` in `file_mutation.py`. The visitor skips the entire `Call` subtree for these, so no operator — core or plugin — ever sees the node.

## Why current allowlist approach was dropped

The initial approach added a `mutmut_allowlist_calls` hook that let plugins re-enable visiting inside skipped calls. This is fragile: it exposes the call's children to **all** core operators, producing junk mutations like `isinstance(None, int)` or `isinstance(x, "")`.

## Better core change required

The real fix is in `MutationVisitor._skip_node_and_children`: instead of skipping the `Call` node entirely, still run operators on the `Call` node itself but skip its children. This way:

1. The `isinstance_type_reduction` operator (registered as a `cst.Call` operator) sees the call and can rewrite the second argument.
2. Core operators never see the children (`Name("x")`, `Name("int")`), so no junk mutations.

Concrete change in `file_mutation.py`:

```python
def on_visit(self, node: cst.CSTNode) -> bool:
    if self._skip_node_and_children(node):
        # still let operators match the node itself before skipping children
        if self._should_mutate_node(node):
            self._create_mutations(node)
        return False

    if self._should_mutate_node(node):
        self._create_mutations(node)
    return True
```

This requires no new hook, no allowlist, and no plugin-side workaround. The operator just registers as `(cst.Call, operator_isinstance_type_reduction)` like any other operator.

## Decision

Not worth implementing right now. The core change above is small but touches a critical code path (`on_visit`) that affects every node in every file. It needs careful testing to make sure existing skip semantics (annotations, decorated functions, default params) aren't broken by running operators on skipped nodes. Revisit if there's demand for isinstance mutations or similar operators targeting other skipped calls.
