# Step 04 Result: Workspace pyproject.toml

**Status:** Complete ✅ (done by step-01)

## Findings

The workspace root `pyproject.toml` was already updated by step-01 (commit `daacd05`).

Current state:
- `[tool.uv.sources]`: `plugmut = { workspace = true }` ✅ (no `mutmut = ...` entry)
- `[tool.uv.workspace] members`: still uses directory names `["mutmut", "mutmut-extras", ...]` ✅ (correct — directory name, not package name)
- Remaining `mutmut` references are all intentional: plugin package names (`mutmut-extras`, `mutmut-llm`, `mutmut-dedup`) and path references

## Acceptance Criteria

| Criterion | Result |
|---|---|
| No `mutmut =` source entry | PASS |
| `plugmut = { workspace = true }` present | PASS |
| `uv sync` exits 0 | PASS |
| `uv pip show plugmut` resolves correctly | PASS (v4.0.0, editable from `mutmut/`) |

## No Changes Made

Step-01 already handled the `[tool.uv.sources]` update as a side effect of the core rename.
