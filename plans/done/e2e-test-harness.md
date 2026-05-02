# E2E Test Harness

## Context

Running end-to-end tests for mutmut plugins is currently manual and friction-heavy. The workflow during `mutmut-extras` development was:

1. Manually create a project directory with source and test files.
2. Figure out CWD requirements (mutmut expects to run from the project root).
3. Use the workspace venv binary directly (`/path/to/venv/bin/mutmut run`).
4. Parse results from CLI output or inspect `.meta` files manually.
5. Reset state between runs (delete `.mutmut-cache/`, `.meta` files).

Mutmut has `e2e_utils.py` (in `mutmut/tests/`) with `run_mutmut_on_project()` that wraps `_run()` programmatically, but it:

- Assumes it's running within the mutmut package's test suite.
- Uses relative path resolution that breaks from `mutmut-extras`.
- Does not handle plugin manager state reset between runs.
- Does not expose results in a structured format.

The `mutmut-extras/e2e_project/` directory already exists with demo code (`demo.py`, `test_demo.py`) targeting all 5 custom operators.

## Why It Matters

- Plugin authors need automated verification that operators produce valid mutations through the full pipeline (generation -> trampoline -> test execution -> result).
- Without automated e2e tests, regressions in mutmut core or plugin operators go undetected until manual testing.
- CI integration is impossible without a programmatic test harness.
- The current manual process takes 5-10 minutes per test cycle — orders of magnitude slower than it should be.

## Benefits

- Automated regression testing for plugin operators.
- CI integration: run e2e tests on every PR to `mutmut-extras`.
- Snapshot-based mutation tracking: detect when operator changes affect mutation counts.
- Comparative testing: baseline (builtins only) vs with-plugins, report the delta.
- Reusable by any mutmut plugin author, not just `mutmut-extras`.

## Implementation Recommendation

### Directory structure

```
mutmut-extras/
    tests/
        e2e/
            __init__.py
            e2e_utils.py       — core test utilities
            test_e2e.py        — e2e test cases
            conftest.py        — pytest fixtures
    e2e_project/               — already exists
        demo.py
        test_demo.py
        pyproject.toml
```

### 1. `e2e_utils.py` — Core utilities

Adapted from mutmut's `e2e_utils.py`, with fixes for cross-package use:

```python
from pathlib import Path
from mutmut.__main__ import _run
from mutmut.file_mutation import reset_global_state  # if exposed

E2E_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent / "e2e_project"

def run_mutmut_on_project(
    project_dir: Path = E2E_PROJECT_DIR,
    extra_args: list[str] | None = None,
    with_plugins: bool = True,
) -> MutmutResult:
    """Run mutmut on a project directory programmatically.

    Handles:
    - CWD change to project_dir
    - Global state reset between runs
    - Plugin manager reinitialization
    - Result parsing into structured format
    """
    ...

@dataclass
class MutmutResult:
    total_mutants: int
    killed: int
    survived: int
    exit_codes: dict[str, int]  # mutant_name -> exit_code
    duration: float
```

Key implementation details:

- **CWD handling:** Use `os.chdir(project_dir)` in a context manager that restores the original CWD on exit.
- **State reset:** Clear any module-level caches in `file_mutation.py` (mutation caches, visited nodes). If mutmut doesn't expose a reset function, monkey-patch the relevant globals.
- **Plugin manager:** Reinitialize `get_plugin_manager()` between runs to ensure clean operator registration. Currently `get_plugin_manager()` in mutmut caches the manager — need to invalidate.
- **Result parsing:** Read `.meta` files from the project directory after `_run()` completes, parse exit codes into `MutmutResult`.

### 2. `conftest.py` — Pytest fixtures

```python
import pytest
from pathlib import Path
from .e2e_utils import run_mutmut_on_project, E2E_PROJECT_DIR

@pytest.fixture
def clean_e2e_project(tmp_path):
    """Copy e2e_project to a temp directory for isolated runs."""
    import shutil
    project = tmp_path / "e2e_project"
    shutil.copytree(E2E_PROJECT_DIR, project)
    return project

@pytest.fixture
def mutmut_baseline(clean_e2e_project):
    """Run mutmut without plugins, return results."""
    return run_mutmut_on_project(clean_e2e_project, with_plugins=False)

@pytest.fixture
def mutmut_with_plugins(clean_e2e_project):
    """Run mutmut with mutmut-extras plugins, return results."""
    return run_mutmut_on_project(clean_e2e_project, with_plugins=True)
```

### 3. Comparative testing helper

```python
@dataclass
class MutationDelta:
    baseline_total: int
    plugin_total: int
    new_mutants: int          # plugin_total - baseline_total
    new_killed: int
    new_survived: int
    plugin_kill_rate: float   # killed / total for plugin-only mutants

def compare_runs(baseline: MutmutResult, with_plugins: MutmutResult) -> MutationDelta:
    """Compare baseline vs with-plugins runs, return the delta."""
    ...
```

### 4. Test cases (`test_e2e.py`)

```python
def test_plugin_operators_generate_mutations(mutmut_with_plugins):
    """Verify that plugin operators produce at least some mutations."""
    assert mutmut_with_plugins.total_mutants > 0

def test_plugin_adds_mutations_over_baseline(mutmut_baseline, mutmut_with_plugins):
    """Verify that plugins add mutations beyond builtins."""
    assert mutmut_with_plugins.total_mutants > mutmut_baseline.total_mutants

def test_mutation_count_snapshot(mutmut_with_plugins):
    """Snapshot test: mutation count should match expected value.
    Update expected value when operators change intentionally.
    """
    # This catches accidental regressions in operator behavior
    assert mutmut_with_plugins.total_mutants == EXPECTED_MUTANT_COUNT

def test_all_mutants_are_valid(mutmut_with_plugins):
    """Verify no mutants caused import errors or syntax errors."""
    for name, exit_code in mutmut_with_plugins.exit_codes.items():
        assert exit_code != 2, f"Mutant {name} caused an error (exit code 2)"
```

### 5. Known challenges

- **`_run()` internals:** `_run()` may call `sys.exit()` — need to catch `SystemExit` or find a lower-level entry point.
- **Plugin manager singleton:** `get_plugin_manager()` likely caches the pluggy `PluginManager`. Resetting between runs requires either patching the cache or re-importing the module.
- **Parallel test isolation:** If pytest-xdist runs e2e tests in parallel, each worker needs its own project copy (the `tmp_path` fixture handles this).
- **Performance:** Full e2e runs are slow (mutmut runs tests for every mutant). Consider marking e2e tests with `@pytest.mark.slow` and skipping in default CI.
