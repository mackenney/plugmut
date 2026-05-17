# Operator exception isolation and identity-mutation guard

## What changed

`mutmut/src/mutmut/file_mutation.py`, `_create_mutations()` method:

1. Added `import warnings` at module level.
2. Wrapped `operator(node)` call in `try/except Exception` to isolate buggy operators — a raising operator produces zero mutations for that node and logs a `warnings.warn()` instead of aborting the run.
3. Added identity check `if mutated_node is node: continue` to skip phantom mutations where an operator yields the original node unchanged.

## Why this couldn't be done via plugin

This is the core mutation generation loop. Plugins supply operators but cannot change how the core loop invokes them or handles exceptions from them.

## Files modified

### `mutmut/src/mutmut/file_mutation.py`

```python
# Before
for mutated_node in operator(node):
    mutation = Mutation(...)
    self.mutations.append(mutation)

# After
try:
    mutated_nodes = list(operator(node))
except Exception as e:
    warnings.warn(f"Operator {source!r} raised on {type(node).__name__}: {e}; ...")
    continue
for mutated_node in mutated_nodes:
    if mutated_node is node:
        continue
    mutation = Mutation(...)
    self.mutations.append(mutation)
```

## How to resolve conflicts

If upstream modifies `_create_mutations()`:
1. Ensure the try/except wraps the operator call and uses `list()` to eagerly evaluate the generator.
2. Ensure exceptions are logged with `warnings.warn()` including operator source tag and node type.
3. Ensure `continue` skips to the next operator (zero mutations from this operator for this node).
4. Ensure the identity check `mutated_node is node` comes before Mutation creation.

## Verification

```bash
grep -q "Operator.*raised on" mutmut/src/mutmut/file_mutation.py
grep -q "mutated_node is node" mutmut/src/mutmut/file_mutation.py
uv run --package mutmut pytest mutmut/tests/ -x -q
```
