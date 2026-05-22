# e2e_utils.py: CWD-relative path → file-relative path

## What changed

**File:** `mutmut/tests/e2e/e2e_utils.py`, `run_mutmut_on_project()`

```python
# Before (upstream)
project_path = Path("..").parent / "e2e_projects" / project

# After (our fix)
project_path = Path(__file__).parent.parent.parent / "e2e_projects" / project
```

## Why

`Path("..").parent` resolves to `Path(".")` — it depends on the process CWD.
In the upstream repo, pytest is typically invoked from within `mutmut/`, so
`./e2e_projects/config` resolves correctly. In this workspace, pytest runs from
the workspace root (`mutmut2/`), so the path resolves to
`mutmut2/e2e_projects/config` which doesn't exist.

`Path(__file__).parent.parent.parent` anchors to the file's physical location
(`mutmut/tests/e2e/` → `mutmut/`), making the resolution CWD-independent.

## Conflict scenario

If upstream modifies `run_mutmut_on_project()` or moves `e2e_projects/`, this
patch may conflict. Resolution:

1. Check where `e2e_projects/` lives relative to the test file
2. Adjust the number of `.parent` calls accordingly
3. The principle stays the same: anchor to `__file__`, never to CWD

## Verification

```bash
uv run --package plugmut pytest mutmut/tests/e2e/ -x
```
