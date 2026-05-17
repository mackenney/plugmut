# Step 02 Result: Plugin Entry-Points

**Status: Complete ✅ (done by step-01, commit daacd05)**

## Verification

All three plugin `pyproject.toml` files already contain the required changes from step 01:

| File | Dependency | Entry-point group |
|------|-----------|-------------------|
| `mutmut-extras/pyproject.toml` | `plugmut>=4.0.0` ✅ | `[project.entry-points.plugmut]` ✅ |
| `mutmut-llm/pyproject.toml` | `plugmut>=4.0.0` ✅ | `[project.entry-points.plugmut]` ✅ |
| `mutmut-dedup/pyproject.toml` | `plugmut>=4.0.0` ✅ | `[project.entry-points.plugmut]` ✅ |

## Acceptance Criteria Results

- `grep 'entry-points.plugmut'` — ✅ all three files match
- `grep 'plugmut>=4'` — ✅ all three files match
- `grep '"mutmut>='` — ✅ PASS: no old references
- `grep 'entry-points.mutmut\]'` — ✅ PASS: no old references
- `uv run --package mutmut-extras pytest mutmut-extras/tests/ -q` — ✅ 189 passed
- `uv run --package mutmut-dedup pytest mutmut-dedup/tests/ -q` — ✅ 61 passed, 1 skipped
