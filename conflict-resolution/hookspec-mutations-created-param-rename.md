# Hookspec Param Rename: `source_by_mutant_name` → `source_tag_by_mutant_name`

## What Changed

In `mutmut/src/mutmut/hookspecs.py`, the `mutmut_mutations_created` hook parameter was renamed:

```python
# Before
def mutmut_mutations_created(self, filename: str, source_by_mutant_name: dict[str, str]) -> None:

# After
def mutmut_mutations_created(self, filename: str, source_tag_by_mutant_name: dict[str, str]) -> None:
```

The semantic meaning also changed: the dict now maps mutant name → operator source tag
(a short label identifying which operator produced the mutation), not the full mutated
source code string. This reflects that the hook is used for identification/tracking, not
for inspecting mutation content.

## Why This Couldn't Be Done via Plugin

Pluggy matches hook implementations to hookspecs by parameter name. A plugin implementing
`mutmut_mutations_created(self, filename, source_by_mutant_name)` would silently receive
no argument for `source_by_mutant_name` if the hookspec uses `source_tag_by_mutant_name`.
The rename must be applied simultaneously to both the hookspec and all plugin implementations.

## Files Changed in Core

- `mutmut/src/mutmut/hookspecs.py` — param renamed in spec
- `mutmut/tests/test_hookspecs.py` — tests updated

## Corresponding Plugin Changes

- `mutmut-llm/src/mutmut_llm/plugin.py` — `mutmut_mutations_created` updated to use
  `source_tag_by_mutant_name`
- `mutmut-llm/tests/test_plugin.py` — tests updated

## How to Resolve Upstream Conflicts

If upstream mutmut adds changes to `mutmut_mutations_created`:

1. Accept upstream changes in `mutmut/src/mutmut/hookspecs.py`
2. Ensure the parameter name in the hookspec stays `source_tag_by_mutant_name`
   (or rename again if upstream chose a different name)
3. Update all plugin implementations (`mutmut-llm/plugin.py`, `mutmut-extras` if applicable)
   to match the hookspec parameter name exactly
4. Run `uv run --package mutmut pytest mutmut/tests/` and `uv run --package mutmut-llm pytest`
   to confirm no hook dispatch errors

## Submodule Pointer

- Before: `39bd3184a585dfb5e2fe54ebbb1e8672c6f2e04d` (3.3.1-86-g39bd318)
- After: `ee0de28701754cafe0c557785f838350fad5ddd2` (3.3.1-90-gee0de28)
