# P0: Step 6 Post-Review Fixes

Fixes from critical review of the storage + reporting changes (Step 6).

---

## Fix 1: Unify mutant name parsing (bug)

**Problem:** `reporting.py:format_mutant_name` naively splits on `.` and doesn't understand mutmut's actual naming:
- `x_` prefix on function names (e.g. `x_foo__mutmut_1`)
- `ǁ` (CLASS_NAME_SEPARATOR) for class hierarchy (e.g. `xǁMyClassǁmethod__mutmut_2`)
- Module-qualified names: `some.module.x_foo__mutmut_1`

Meanwhile `plugin.py:_extract_function_name` handles all of these correctly. The two parsers produce inconsistent results for the same input.

**Fix:**
- Extract a shared `parse_mutant_name(mutant_name: str) -> tuple[str, str | None, str, str]` (module_path, class_name, function_name, mutant_id) into a new or existing utility location. Candidates:
  - Add to `storage.py` since both `plugin.py` and `reporting.py` already import from it
  - Or keep in `reporting.py` and have `plugin.py` call it — but plugin.py only needs function_name, not the full tuple
- Simplest: keep `_extract_function_name` in plugin.py (it only needs function name), and fix `format_mutant_name` in reporting.py to handle `x_` and `ǁ` correctly. No shared code needed — they serve different purposes.
- Update `format_mutant_name` to:
  1. Split off `__mutmut_N` suffix (already done)
  2. Split on `.` to get module parts + qualified name
  3. Handle `ǁ` in the last component to extract class and function
  4. Strip `x_` prefix from the function/class component
  5. Reconstruct file path from module parts only (not class name)

**Tests to update:**
- `test_reporting.py:TestFormatMutantName` — all cases need updating to use real mutmut name format
- `test_nested_class_method`: fix assertion from `src/pkg/mod/MyClass.py` to `src/pkg/mod.py`
- Add test case: `some.module.xǁMyClassǁmethod__mutmut_2` → file=`some/module.py`, function=`MyClass.method`, mutant_id=`2`
- Add test case: `some.module.x_foo__mutmut_1` → file=`some/module.py`, function=`foo`, mutant_id=`1`

---

## Fix 2: Delete dead code `_build_llm_function_names` (cleanup)

**Problem:** `plugin.py:_build_llm_function_names()` (lines 60-62) is defined but never called. `_llm_mutation_count_by_function()` is the one actually used by `mutmut_mutations_created`.

**Fix:** Delete the function. No tests reference it.

---

## Fix 3: Handle corrupt JSON in `list_runs` / `load_run` (robustness)

**Problem:** A malformed `.json` file in `.mutmut-cache/llm/runs/` crashes `list_runs()`, which cascades to `load_latest_run()` and `mutmut llm-status`. Real scenario: process killed mid-write, disk full, manual editing.

**Fix:**
- `list_runs`: wrap the per-file parse in `try/except (json.JSONDecodeError, KeyError)` and `continue` on failure
- `load_run`: wrap parse in `try/except` and return `None` on failure (same as "not found")
- Optional: log a warning via `click.echo` or `warnings.warn` so the user knows a file was skipped. Lean toward silent skip for now — these are cache files, not user data.

**Tests to add in `test_storage.py`:**
- `test_list_runs_skips_corrupt_file`: write a valid run + a corrupt `.json` file, assert `list_runs` returns only the valid one
- `test_load_run_returns_none_on_corrupt`: write garbage to `{run_id}.json`, assert `load_run(run_id)` returns `None`

---

## Execution order

1. Fix 2 (dead code) — trivial, no dependencies
2. Fix 3 (corrupt JSON) — isolated to storage.py + test_storage.py
3. Fix 1 (name parsing) — touches reporting.py + test_reporting.py, most involved

All three are independent and could be done in parallel, but sequential is fine for a single commit.
