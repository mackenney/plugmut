# Fact-Check Report — Release Plan Pre-Execution
Generated: 2026-05-17

---

## Claim 1: `mutmut/src/mutmut/hookspecs.py` contains `HookspecMarker("mutmut")` and `HookimplMarker("mutmut")`
Verdict: CONFIRMED
Evidence: `hookspecs.py:12: hookspec = pluggy.HookspecMarker("mutmut")`, `hookspecs.py:13: hookimpl = pluggy.HookimplMarker("mutmut")`
Notes: Both markers present at lines 12–13.

---

## Claim 2: `mutmut/src/mutmut/plugin_manager.py` contains `PluginManager("mutmut")`, `load_setuptools_entrypoints("mutmut")`, and `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD`
Verdict: CONFIRMED
Evidence: `plugin_manager.py:14: _pm = pluggy.PluginManager("mutmut")`, `plugin_manager.py:16: if not os.environ.get("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD"):`, `plugin_manager.py:18: _pm.load_setuptools_entrypoints("mutmut")`
Notes: All three strings present at lines 14, 16, 18.

---

## Claim 3: `mutmut/src/mutmut/__init__.py` contains `importlib.metadata.version("mutmut")` (version lookup using old package name)
Verdict: CONFIRMED
Evidence: `__init__.py:3: import importlib.metadata`, `__init__.py:10: __version__ = importlib.metadata.version("mutmut")`
Notes: Uses `"mutmut"` as the package name argument — this will break after rename to `plugmut`.

---

## Claim 4: `mutmut/pyproject.toml` has `name = "mutmut"` and a scripts section with `mutmut = "mutmut.__main__:cli"`
Verdict: CONFIRMED
Evidence: `mutmut/pyproject.toml:2: name = "mutmut"`, `mutmut/pyproject.toml:45: [project.scripts]`, `mutmut/pyproject.toml:46: mutmut = "mutmut.__main__:cli"`
Notes: Both present as claimed.

---

## Claim 5: `mutmut/src/mutmut/__main__.py` reads config from `data["tool"]["mutmut"]` (branding plan Step 3.1)
Verdict: CONFIRMED
Evidence: `__main__.py:949: config = data["tool"]["mutmut"]`
Notes: TOML tool section uses key `"mutmut"`.

---

## Claim 6: `mutmut/src/mutmut/__main__.py` reads setup.cfg from `config_parser.get("mutmut", key)` (branding plan Step 3.2)
Verdict: CONFIRMED
Evidence: `__main__.py:968: result: Any = config_parser.get("mutmut", key)`
Notes: setup.cfg section name is `"mutmut"`.

---

## Claim 7: `mutmut-extras/pyproject.toml` has `[project.entry-points.mutmut]` and dependency `mutmut>=3.5.0`
Verdict: CONFIRMED
Evidence: `mutmut-extras/pyproject.toml:8: "mutmut>=3.5.0"`, `mutmut-extras/pyproject.toml:12: [project.entry-points.mutmut]`
Notes: Both present as claimed.

---

## Claim 8: `mutmut-llm/pyproject.toml` has `[project.entry-points.mutmut]` and dependency `mutmut>=3.5.0`
Verdict: CONFIRMED
Evidence: `mutmut-llm/pyproject.toml:8: "mutmut>=3.5.0"`, `mutmut-llm/pyproject.toml:15: [project.entry-points.mutmut]`
Notes: Both present as claimed.

---

## Claim 9: `mutmut-dedup/pyproject.toml` has `[project.entry-points.mutmut]` and dependency `mutmut>=3.5.0`
Verdict: CONFIRMED
Evidence: `mutmut-dedup/pyproject.toml:8: "mutmut>=3.5.0"`, `mutmut-dedup/pyproject.toml:13: [project.entry-points.mutmut]`
Notes: Both present as claimed.

---

## Claim 10: `mutmut-dedup/pyproject.toml` already declares `libcst>=1.8.5` as a dependency
Verdict: CONFIRMED
Evidence: `mutmut-dedup/pyproject.toml:10: "libcst>=1.8.5"`
Notes: Present as claimed; metadata plan assertion "already present, no change needed" is accurate.

---

## Claim 11: Workspace root `pyproject.toml` has a `[tool.uv.sources]` section with `mutmut = { workspace = true }`
Verdict: CONFIRMED
Evidence: `pyproject.toml:13: [tool.uv.sources]`, `pyproject.toml:14: mutmut = { workspace = true }`
Notes: All four packages (mutmut, mutmut-extras, mutmut-llm, mutmut-dedup) are listed as workspace sources.

---

## Claim 12: `mutmut-extras/SPEC.md` exists
Verdict: CONFIRMED
Evidence: `ls /home/ignacio/pr/mutmut2/mutmut-extras/SPEC.md` → file present.
Notes: —

---

## Claim 13: `mutmut-llm/SPEC.md` exists
Verdict: CONFIRMED
Evidence: `ls /home/ignacio/pr/mutmut2/mutmut-llm/SPEC.md` → file present.
Notes: —

---

## Claim 14: `mutmut-dedup/SPEC.md` exists
Verdict: CONFIRMED
Evidence: `ls /home/ignacio/pr/mutmut2/mutmut-dedup/SPEC.md` → file present.
Notes: —

---

## Claim 15: No `README.md` exists in `mutmut-extras/`, `mutmut-llm/`, or `mutmut-dedup/` root dirs
Verdict: CONFIRMED
Evidence: `ls mutmut-extras/README.md mutmut-llm/README.md mutmut-dedup/README.md` → all return "No such file or directory".
Notes: Steps 07–09 (README creation) start from a blank slate as expected.

---

## Claim 16: `dist/` contains `plugmut-3.5.0-py3-none-any.whl` (stale artifact to remove)
Verdict: CONFIRMED
Evidence: `dist/plugmut-3.5.0-py3-none-any.whl` present. Also present: `dist/plugmut-3.5.0.tar.gz`.
Notes: Both wheel and sdist are stale artifacts. Step-12 (cleanup) should remove both, not just the whl.

---

## Claim 17: `mutmut/tests/conftest.py` sets `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD` (the env var to be renamed)
Verdict: CONFIRMED
Evidence: `mutmut/tests/conftest.py:12: os.environ["PLUGMUT_DISABLE_PLUGIN_AUTOLOAD"] = "1"`, `conftest.py:16: os.environ.pop("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", None)`
Notes: Set and torn down in a fixture.

---

## Claim 18: `mutmut-extras/tests/` test files use `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD` (the step claims 17 files)
Verdict: REFUTED (count is wrong; "step claims 17" is also false)
Evidence: `grep -rl "PLUGMUT_DISABLE_PLUGIN_AUTOLOAD" mutmut-extras/tests/ | grep '\.py$' | wc -l` → **21 files**. `grep -c "17" plans/release/step-05-env-var-rename.md` → 0 (the string "17" does not appear in step-05).
Notes: The env var IS present across all those test files (confirmed). However:
  1. The actual count is **21 .py files**, not 17.
  2. step-05-env-var-rename.md never states a count of 17 — it only says "all .py files in `mutmut-extras/tests/`". The "17 files" claim does not appear anywhere in the step files.
  Worker executing step-05 Task 5.3 should run the find command provided in the step to get the real file list rather than relying on any count.

---

## Claim 19: `mutmut-dedup/tests/` test files use `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD` (the step claims 3 files)
Verdict: PARTIAL
Evidence: `grep -rl "PLUGMUT_DISABLE_PLUGIN_AUTOLOAD" mutmut-dedup/tests/ | grep '\.py$'` → 3 files: `test_dedup_metrics.py`, `test_plugin.py`, `test_e2e.py`. Count is correct. However, step-05 never states "3 files" — it says "all .py files in `mutmut-dedup/tests/`" with no count.
Notes: The count of 3 is accurate. The "step claims 3 files" framing is misleading — the step makes no explicit count claim, but the actual count matches.

---

## Claim 20: `mutmut-llm/tests/e2e/test_e2e_live.py` contains `PLUGMUT_LLM_E2E_LIVE`
Verdict: CONFIRMED
Evidence: `test_e2e_live.py:3: Gated behind PLUGMUT_LLM_E2E_LIVE=1`, `test_e2e_live.py:31: LIVE_ENABLED = os.environ.get("PLUGMUT_LLM_E2E_LIVE") == "1"`, `test_e2e_live.py:36: reason="Set PLUGMUT_LLM_E2E_LIVE=1 and ANTHROPIC_API_KEY to run live tests"`
Notes: File exists at `mutmut-llm/tests/e2e/test_e2e_live.py`. No `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD` usage found in `mutmut-llm/` (mutmut-llm tests do not need isolation fixtures).

---

## Summary Table

| # | Cluster | Verdict |
|---|---------|---------|
| 1 | A | CONFIRMED |
| 2 | A | CONFIRMED |
| 3 | A | CONFIRMED |
| 4 | A | CONFIRMED |
| 5 | A | CONFIRMED |
| 6 | A | CONFIRMED |
| 7 | B | CONFIRMED |
| 8 | B | CONFIRMED |
| 9 | B | CONFIRMED |
| 10 | B | CONFIRMED |
| 11 | B | CONFIRMED |
| 12 | C | CONFIRMED |
| 13 | C | CONFIRMED |
| 14 | C | CONFIRMED |
| 15 | C | CONFIRMED |
| 16 | C | CONFIRMED |
| 17 | D | CONFIRMED |
| 18 | D | REFUTED (count: 21 actual, not 17; step never states a count) |
| 19 | D | PARTIAL (count 3 is correct; step doesn't claim it) |
| 20 | D | CONFIRMED |

## Action Items for Execution Team

1. **Claim 18 (HIGH):** step-05 Task 5.3 workers should not assume 17 files — the actual count is **21 .py files** in `mutmut-extras/tests/`. Use the `find` command provided in the step to enumerate them rather than a hardcoded list.
2. **Claim 16 (MEDIUM):** step-12 cleanup should remove **both** `dist/plugmut-3.5.0-py3-none-any.whl` **and** `dist/plugmut-3.5.0.tar.gz`.
3. **Claim 3 (informational):** `__init__.py:10` uses `importlib.metadata.version("mutmut")` — step-01 must update this string to `"plugmut"` or the version lookup will break after rename.
