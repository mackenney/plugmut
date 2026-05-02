# P1: Verify mutmut Core Tests & Add Plugin System Tests

## Context

We modified the mutmut submodule by adding:
- `mutmut/src/mutmut/hookspecs.py` -- pluggy hook specifications
- `mutmut/src/mutmut/plugin_manager.py` -- singleton PluginManager with setuptools entrypoint loading
- `mutmut/src/mutmut/file_mutation.py` -- modified `create_mutations()` to call plugin hooks

We have not verified that mutmut's existing test suite still passes. We also have no tests for the plugin system inside mutmut's own test directory. The comprehensive plugin integration tests live in mutmut-extras, but mutmut itself should have minimal coverage of its own plugin infrastructure.

## Why This Matters

- We're modifying a submodule. If existing tests break, we've introduced regressions that could affect upstream.
- The plugin system (`get_plugin_manager`, `reset_plugin_manager`, hookspec dispatch in `create_mutations`) is mutmut infrastructure. It should be testable without installing mutmut-extras.
- Anyone working on mutmut core needs confidence the plugin system works in isolation.

## Implementation

### 1. Run existing mutmut tests

```bash
cd mutmut && uv run pytest tests/ -x -q
```

Fix any failures before proceeding. The submodule changes should be backwards-compatible (plugin hooks return empty list when no plugins registered, so `create_mutations` behavior is unchanged).

### 2. Add plugin system unit tests

File: `mutmut/tests/test_plugin_system.py`

Tests to write:

**plugin_manager.py:**
- `test_get_plugin_manager_returns_singleton` -- calling twice returns same object
- `test_reset_plugin_manager_clears_singleton` -- after reset, new object returned
- `test_autoload_disabled_via_env` -- with `MUTMUT_DISABLE_PLUGIN_AUTOLOAD=1`, no entrypoints loaded (verify `load_setuptools_entrypoints` not called, using monkeypatch)
- `test_register_and_call_hook` -- register a mock plugin, verify `hook.mutmut_register_operators()` returns its operators

**create_mutations with plugins:**
- `test_create_mutations_without_plugins` -- default behavior unchanged, no crash
- `test_create_mutations_with_mock_plugin` -- register a trivial operator (e.g., negate integers), verify its mutations appear in output
- `test_create_mutations_plugin_extends_builtins` -- verify mutation count increases when plugin adds operators

### 3. Keep tests minimal

These tests verify the infrastructure, not operator correctness. Each test should be <15 lines. The mock operator can be a lambda or trivial function -- no need for real mutation logic.

Example mock operator:
```python
def mock_op(node: cst.Integer) -> Iterable[cst.Integer]:
    yield node.with_changes(value="42")
```

### Notes

- Tests go in `mutmut/tests/test_plugin_system.py` (new file)
- All tests must use `monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")` and `reset_plugin_manager()` to avoid interference from installed plugins
- Do not add mutmut-extras as a test dependency of mutmut
