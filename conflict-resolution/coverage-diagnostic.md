# Coverage diagnostic

## What changed

`mutmut/src/mutmut/code_coverage.py`, `get_covered_lines_for_file()` function:

Added `import warnings` and a warning when a file has no coverage data. This explains why the file produces zero mutants when `mutate_only_covered_lines=True`.

## Why this couldn't be done via plugin

Coverage data handling is internal to the core. Plugins cannot intercept or modify coverage data processing.

## Files modified

### `mutmut/src/mutmut/code_coverage.py`

Added `import warnings` to imports.

Added after checking if file is in `covered_lines`:

```python
if lines is None:
    warnings.warn(
        f"No coverage data for {filename}; file will produce zero mutants when mutate_only_covered_lines=True",
        stacklevel=2,
    )
```

## How to resolve conflicts

If upstream modifies `get_covered_lines_for_file()`:
1. Ensure the warning fires when `lines is None` (file not found in coverage data)
2. Keep the warning message clear about the consequence (zero mutants)
3. Use `stacklevel=2` so the warning points to the caller

If upstream adds a different diagnostic mechanism:
1. Use upstream's mechanism instead of `warnings.warn` if appropriate
2. Ensure the diagnostic still fires for missing coverage data

## Verification

```bash
grep -q "No coverage data for" mutmut/src/mutmut/code_coverage.py
```
