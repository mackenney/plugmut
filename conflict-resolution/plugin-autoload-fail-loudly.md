# Plugin autoload fail-loudly

## What changed

`mutmut/src/mutmut/plugin_manager.py` lines 20-21: Changed from `warnings.warn()` to `raise RuntimeError()` when plugin loading fails.

## Why this couldn't be done via plugin

This is the plugin *loading* mechanism itself. Plugins cannot modify how they are loaded.

## Files modified

### `mutmut/src/mutmut/plugin_manager.py`

```python
# Before
except Exception as e:
    warnings.warn(f"Failed to load plugmut plugins: {e}")

# After
except Exception as e:
    raise RuntimeError(f"Failed to load plugmut plugins: {e}") from e
```

## How to resolve conflicts

If upstream modifies the exception handling in `get_plugin_manager()`:
1. Ensure exceptions propagate with a clear message identifying the plugin loading phase
2. Do NOT silently swallow or warn-and-continue
3. Chain the original exception with `from e` for debugging

## Verification

```bash
uv run --package mutmut pytest mutmut/tests/ -x -q
```
