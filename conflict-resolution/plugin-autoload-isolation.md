# Plugin autoload disabled during core mutmut tests

## What changed

**Added file:** `mutmut/tests/conftest.py`

```python
import os

import pytest

from mutmut.file_mutation import reset_plugin_operators
from mutmut.plugin_manager import reset_plugin_manager


@pytest.fixture(autouse=True, scope="session")
def _disable_plugin_autoload():
    """Prevent third-party plugins from loading during core tests."""
    os.environ["PLUGMUT_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    reset_plugin_manager()
    reset_plugin_operators()
    yield
    os.environ.pop("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", None)
    reset_plugin_manager()
    reset_plugin_operators()
```

## Why

This workspace installs `mutmut-extras` as a sibling package. Because
`mutmut-extras` registers a pluggy entry point under the `plugmut` group,
`get_plugin_manager()` loads it automatically via `load_setuptools_entrypoints`.

The extras plugin adds mutation operators (`return None`, slice removal, etc.)
that produce additional mutants not expected by the core test suite. This causes
snapshot mismatches and assertion failures in tests like `test_module_mutation`,
`test_basic_class`, `test_basic_mutations`, and others — the mutant count and
numbering shift because extra mutations are injected.

The `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD` env var is already respected by
`plugin_manager.py` (both upstream and here). The conftest sets it before any
test runs, then resets the singleton plugin manager to ensure a clean state.

## How the plugin system works

1. `plugin_manager.py` creates `pluggy.PluginManager("plugmut")` as a module-level singleton `_pm`
2. `get_plugin_manager()` lazily initializes it, loading entry points unless
   `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD` is set
3. `reset_plugin_manager()` nulls `_pm` so the next call re-initializes
4. `file_mutation.py` holds a separate module-level cache `_plugin_operators`
   populated by `get_plugin_operators()` on first use
5. `reset_plugin_operators()` nulls `_plugin_operators` — must be called alongside
   `reset_plugin_manager()` to fully clear plugin state between tests
6. Mutation operators enter the cache via `get_plugin_operators()`,
   which calls `get_plugin_manager().hook.mutmut_register_operators()` once

## Conflict scenario

If upstream adds their own `mutmut/tests/conftest.py`, this file will conflict
directly. Resolution:

1. Check if upstream's conftest already sets `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD`
2. If yes, drop our version entirely
3. If no, merge our fixture into their conftest
4. If upstream changes the env var name or plugin loading mechanism, update the
   fixture to match
5. When merging, ensure both `reset_plugin_manager()` and `reset_plugin_operators()`
   are called — resetting only the plugin manager leaves stale cached operators

## Verification

```bash
# Core tests pass without plugin contamination
uv run --package mutmut pytest mutmut/tests/ --ignore=mutmut/tests/e2e -x

# Extras tests still load the plugin (no conftest blocking them)
uv run --package mutmut-extras pytest mutmut-extras/tests/ -x
```
