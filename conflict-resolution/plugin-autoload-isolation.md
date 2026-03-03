# Plugin autoload disabled during core mutmut tests

## What changed

**Added file:** `mutmut/tests/conftest.py`

```python
import os
import pytest
from mutmut.plugin_manager import reset_plugin_manager

@pytest.fixture(autouse=True, scope="session")
def _disable_plugin_autoload():
    os.environ["MUTMUT_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    reset_plugin_manager()
    yield
    os.environ.pop("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", None)
    reset_plugin_manager()
```

## Why

This workspace installs `mutmut-extras` as a sibling package. Because
`mutmut-extras` registers a pluggy entry point under the `mutmut` group,
`get_plugin_manager()` loads it automatically via `load_setuptools_entrypoints`.

The extras plugin adds mutation operators (`return None`, slice removal, etc.)
that produce additional mutants not expected by the core test suite. This causes
snapshot mismatches and assertion failures in tests like `test_module_mutation`,
`test_basic_class`, `test_basic_mutations`, and others — the mutant count and
numbering shift because extra mutations are injected.

The `MUTMUT_DISABLE_PLUGIN_AUTOLOAD` env var is already respected by
`plugin_manager.py` (both upstream and here). The conftest sets it before any
test runs, then resets the singleton plugin manager to ensure a clean state.

## How the plugin system works

1. `plugin_manager.py` holds a module-level singleton `_pm`
2. `get_plugin_manager()` lazily initializes it, loading entry points unless
   `MUTMUT_DISABLE_PLUGIN_AUTOLOAD` is set
3. `reset_plugin_manager()` nulls the singleton so the next call re-initializes
4. Mutation operators from plugins are collected in `file_mutation.py` via
   `get_plugin_manager().hook.mutmut_register_operators()`

## Conflict scenario

If upstream adds their own `mutmut/tests/conftest.py`, this file will conflict
directly. Resolution:

1. Check if upstream's conftest already sets `MUTMUT_DISABLE_PLUGIN_AUTOLOAD`
2. If yes, drop our version entirely
3. If no, merge our fixture into their conftest
4. If upstream changes the env var name or plugin loading mechanism, update the
   fixture to match

## Verification

```bash
# Core tests pass without plugin contamination
uv run --package mutmut pytest mutmut/tests/ --ignore=mutmut/tests/e2e -x

# Extras tests still load the plugin (no conftest blocking them)
uv run --package mutmut-extras pytest mutmut-extras/tests/ -x
```
