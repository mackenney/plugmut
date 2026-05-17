# __init__ strip cleanup

## What changed

`mutmut/src/mutmut/__main__.py` lines 1360 and 1371: Removed redundant `mutant_name.replace("__init__.", "")` calls.

## Why this couldn't be done via plugin

This is internal mutant name handling in the core test runner. Plugins cannot modify name lookup logic.

## Files modified

### `mutmut/src/mutmut/__main__.py`

Removed two lines (originally 1360 and 1371):
```python
mutant_name = mutant_name.replace("__init__.", "")
```

These were dead code because:
1. Line 360 already strips `".__init__."` (with leading dot) at name *creation* time
2. The lookup-time pattern `"__init__."` (no leading dot) fires after creation
3. The pattern was already removed, so these lines did nothing

## How to resolve conflicts

If upstream modifies the mutant name lookup logic:
1. Do NOT re-add the `replace("__init__.", "")` calls
2. If `__init__` handling is needed, it should happen at name creation (line 360), not lookup
3. The pattern with leading dot (`".__init__."`) is the correct one

## Verification

```bash
grep -n 'mutant_name = mutant_name.replace("__init__\."' mutmut/src/mutmut/__main__.py | grep -v "360" | wc -l
# Should output 0
```
