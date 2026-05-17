# Command registration fault tolerance

## What changed

`mutmut/src/mutmut/__main__.py`, `_register_plugin_commands()` function:

Added try/except around `mutmut_register_commands` hook call. If a plugin raises, the CLI now fails with a clear error message identifying the registration phase.

## Why this couldn't be done via plugin

This is the hook *call site* for plugin command registration. Plugins cannot wrap the call to their own registration hook.

## Files modified

### `mutmut/src/mutmut/__main__.py`

```python
# Before
def _register_plugin_commands() -> None:
    from mutmut.plugin_manager import get_plugin_manager
    get_plugin_manager().hook.mutmut_register_commands(cli_group=cli)

# After
def _register_plugin_commands() -> None:
    from mutmut.plugin_manager import get_plugin_manager
    try:
        get_plugin_manager().hook.mutmut_register_commands(cli_group=cli)
    except Exception as e:
        raise RuntimeError(f"Plugin raised during command registration: {e}") from e
```

## How to resolve conflicts

If upstream modifies `_register_plugin_commands()`:
1. Ensure the hook call is wrapped in try/except
2. Ensure the error message identifies "command registration" as the phase
3. Chain the original exception with `from e`

## Verification

```bash
grep -q "Plugin raised during command registration" mutmut/src/mutmut/__main__.py
```
