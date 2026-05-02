# Live API Integration Tests

Add a gated live API test layer for `mutmut-llm` that exercises the real Anthropic API. Tests are skipped unless `MUTMUT_LLM_E2E_LIVE=1` is set, so they never run in CI or casual `pytest` invocations.

**Prerequisite:** `ANTHROPIC_API_KEY` environment variable set with valid key.

## Architecture

```
mutmut-llm/tests/
├── conftest.py              # existing shared fixtures
├── e2e/
│   ├── __init__.py
│   ├── conftest.py          # e2e fixtures (sample projects, API key guard)
│   ├── test_e2e_llm.py      # existing mocked e2e tests
│   └── test_e2e_live.py     # NEW: live API tests
```

### Gating Mechanism

```python
import os
import pytest

LIVE_ENABLED = os.environ.get("MUTMUT_LLM_E2E_LIVE") == "1"
HAS_API_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))

skip_no_live = pytest.mark.skipif(
    not (LIVE_ENABLED and HAS_API_KEY),
    reason="Set MUTMUT_LLM_E2E_LIVE=1 and ANTHROPIC_API_KEY to run live tests",
)
```

Every test in `test_e2e_live.py` is decorated with `@skip_no_live`.

### Fixture Strategy

Use **module-scoped** fixtures for API calls to minimize cost. A single LLM call generates mutations for a sample function, and multiple test functions assert properties of that result.

```python
@pytest.fixture(scope="module")
def live_generation_result():
    """Call the real API once, reuse across all tests in this module."""
    from mutmut_llm.pipeline import _call_llm_and_validate
    from mutmut_llm.config import load_config

    config = load_config()
    source = SAMPLE_FUNCTION_SOURCE
    context = SAMPLE_CONTEXT
    mutations = _call_llm_and_validate(config, source, context)
    return mutations
```

### Sample Function

Use a deterministic, well-understood function that produces meaningful mutations:

```python
SAMPLE_FUNCTION_SOURCE = '''
def moving_average(values: list[float], window: int) -> list[float]:
    if window <= 0:
        raise ValueError("window must be positive")
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = values[start:i + 1]
        result.append(sum(chunk) / len(chunk))
    return result
'''

SAMPLE_CONTEXT = "from __future__ import annotations\n"
```

## Steps

### Step 1: Create test infrastructure

Create `mutmut-llm/tests/e2e/test_e2e_live.py` with:
- Skip decorator and gating constants
- Module-scoped fixture that makes a single API call
- Capture the API key at import time (before any test fixtures or monkeypatching)

**Verify:** `uv run --package mutmut-llm pytest mutmut-llm/tests/e2e/test_e2e_live.py -v` shows all tests SKIPPED (no env var set).

### Step 2: Basic response validation tests

Tests that verify the LLM returns structurally valid mutations:

1. **`test_live_returns_mutations`** — Result is a non-empty list.
2. **`test_live_mutations_have_required_fields`** — Each mutation dict has `mutated_code` key.
3. **`test_live_mutations_have_descriptions`** — Each mutation dict has `description` key (non-empty string).
4. **`test_live_mutation_count_within_budget`** — Number of mutations ≤ `config.max_mutations_per_function`.

**Verify:** `MUTMUT_LLM_E2E_LIVE=1 uv run --package mutmut-llm pytest mutmut-llm/tests/e2e/test_e2e_live.py -v -k "test_live_returns or test_live_mutations_have"` — all pass.

### Step 3: Syntax and validation tests

Tests that verify mutations pass the validation pipeline:

5. **`test_live_mutations_parse`** — Every `mutated_code` parses with `cst.parse_module()`.
6. **`test_live_mutations_are_functions`** — Every `mutated_code` contains a `FunctionDef` when parsed.
7. **`test_live_mutations_pass_import_validation`** — Run `validate_imports()` on each mutation against original. None introduce new imports.
8. **`test_live_mutations_differ_from_original`** — No mutation is identical to the original source (would be a no-op).

**Verify:** `MUTMUT_LLM_E2E_LIVE=1 uv run --package mutmut-llm pytest mutmut-llm/tests/e2e/test_e2e_live.py -v -k "test_live_mutations_parse or test_live_mutations_are or test_live_mutations_pass or test_live_mutations_differ"` — all pass.

### Step 4: Prompt quality assertions

Tests that verify the prompt engineering produces non-trivial mutations:

9. **`test_live_mutations_are_not_trivial_operator_swaps`** — Check that mutations don't just swap `+` to `-` or `==` to `!=` (the system prompt explicitly tells the LLM to avoid these). Parse both original and mutated ASTs, check that the diff is not a single operator replacement at a `BinOp` or `Compare` node.
10. **`test_live_mutations_preserve_function_signature`** — Function name and parameter list unchanged (mutations should be in the body, not the signature).

**Verify:** Run with live flag, confirm pass.

### Step 5: Full pipeline integration test

Test the complete `mutmut generate` flow with the real API:

11. **`test_live_full_pipeline`** — Create a temp directory with a `pyproject.toml` and a sample Python file. Call `run_generation()` with `scope="targeted"`, `targets=["sample.py:moving_average"]`, `budget=1`. Verify:
    - Cache entry created in `.mutmut-cache/llm/`
    - Cache entry contains valid mutations
    - Cache entry has correct `source_hash` matching the function source
    - Re-running with same source hits cache (no additional API call)

Use a **session-scoped** fixture for this one (separate from the module fixture) since it needs its own temp directory and config.

**Verify:** `MUTMUT_LLM_E2E_LIVE=1 uv run --package mutmut-llm pytest mutmut-llm/tests/e2e/test_e2e_live.py::test_live_full_pipeline -v`

### Step 6: Operator integration test

Test that cached mutations are picked up by the LLM operator during `create_mutations()`:

12. **`test_live_operator_reads_cache`** — After running the pipeline (Step 5 fixture), call `create_mutations()` on the sample source with the LLM plugin registered. Verify that LLM-sourced mutations appear in the result. Apply each via `module.deep_replace()` and confirm `.code` is parseable.

**Verify:** Run with live flag, confirm pass.

### Step 7: Error handling tests

Tests for graceful failure modes (these can use mocked API for reliability, but verify behavior matches live):

13. **`test_live_invalid_api_key`** — Set a bogus API key, call `_call_llm_and_validate()`. Verify it raises or returns empty list (not crash).
14. **`test_live_empty_function`** — Pass `def f(): pass` to the pipeline. Verify it handles gracefully (may return 0 mutations).

**Verify:** These can run without `MUTMUT_LLM_E2E_LIVE=1` if using mocked API, or with it for real validation.

### Step 8: Cross-suite regression check

```bash
uv run --package mutmut-llm pytest mutmut-llm/tests/ -v --ignore=mutmut-llm/tests/e2e/test_e2e_live.py
MUTMUT_LLM_E2E_LIVE=1 uv run --package mutmut-llm pytest mutmut-llm/tests/e2e/test_e2e_live.py -v
```

Confirm no existing tests break. Confirm live tests pass with valid API key.

## Cost Control

- Module-scoped fixture: **1 API call** per test run (the `live_generation_result` fixture).
- Session-scoped pipeline fixture: **1 additional API call** (for cache population).
- Total: **2 API calls per full live test run** (~$0.01-0.05 with Sonnet).
- No tests that loop or generate mutations for multiple functions.
- The gating mechanism (`MUTMUT_LLM_E2E_LIVE=1`) prevents accidental API spend.

## Pytest Markers

Register in `mutmut-llm/pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = [
    "e2e_live: tests requiring real Anthropic API access (set MUTMUT_LLM_E2E_LIVE=1)",
]
```
