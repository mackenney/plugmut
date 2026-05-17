# Progress

## Status
In Progress

## Tasks

### Step 03: Config Section Rename ✅
- Updated `__main__.py` to read from `[tool.plugmut]` / `[plugmut]` instead of `[tool.mutmut]` / `[mutmut]`
- Added deprecation ValueError for old section names in both pyproject.toml and setup.cfg readers
- Updated all 8 e2e fixture pyproject.toml files from `[tool.mutmut]` to `[tool.plugmut]`
- 226 tests pass, 2 skipped
- Commits: submodule 1ca3c1d, workspace bd179a2

### Step 11: CHANGELOG Creation ✅
- Created `mutmut-extras/CHANGELOG.md` with 19 operators listed
- Created `mutmut-llm/CHANGELOG.md` with LLM generation features
- Created `mutmut-dedup/CHANGELOG.md` with two-phase dedup features
- All files follow Keep a Changelog format, version 0.1.0, date 2026-05-17

### Step 05: Environment Variable Rename ✅
- Renamed `MUTMUT_DISABLE_PLUGIN_AUTOLOAD` → `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD` in 26 .py files
- Renamed `MUTMUT_LLM_E2E_LIVE` → `PLUGMUT_LLM_E2E_LIVE` in 1 .py file
- Updated .md files (conflict-resolution docs, AGENTS.md, plan docs)
- Commit: ffe3a47

## Files Changed (step-05)
- mutmut/src/mutmut/plugin_manager.py
- mutmut/tests/conftest.py
- 19 files in mutmut-extras/tests/
- 3 files in mutmut-dedup/tests/
- mutmut-llm/tests/e2e/test_e2e_live.py
- conflict-resolution/plugin-autoload-isolation.md (and other .md files)

### Step 14: GitHub Actions Workflows ✅
- Created `.github/workflows/tests.yml` — matrix: Python 3.10-3.13, tests all 4 packages, ignores LLM e2e
- Created `.github/workflows/publish.yml` — trusted publishing (OIDC), builds all 4 packages on `v*` tags
- Both files were already present in git from step-05 commit; content verified against spec
- All 6 acceptance criteria pass
- Commit: step-14 (see below)

## Notes
