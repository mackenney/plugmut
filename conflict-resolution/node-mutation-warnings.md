# Node mutation warnings

## What changed

`mutmut/src/mutmut/node_mutation.py` line 30: Changed `print()` to `warnings.warn()` for unexpected number type handling.

## Why this couldn't be done via plugin

This is inside the builtin `operator_number` mutation operator. Plugins can add operators but cannot modify builtin operators.

## Files modified

### `mutmut/src/mutmut/node_mutation.py`

```python
# Before
print("Unexpected number type", node)

# After
import warnings  # at top of file
# ...
warnings.warn(f"Unexpected number type: {node!r}", stacklevel=2)
```

## How to resolve conflicts

If upstream modifies `operator_number`:
1. Ensure the fallback branch uses `warnings.warn()` not `print()`
2. Use `stacklevel=2` so the warning points to the caller
3. Use `{node!r}` for the repr format

## Verification

```bash
grep -q 'warnings.warn.*Unexpected number type' mutmut/src/mutmut/node_mutation.py
```
