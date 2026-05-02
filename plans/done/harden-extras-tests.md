# Plan: Harden mutmut-extras test suite — DONE

Implemented in commit `51a63f4`. All 128 extras tests pass.

Based on mutation testing results: 159 mutants, 154 killed, 5 survived (96.9% score).

## Fix 1: Slice removal — test that step removal drops the trailing colon

**Surviving mutant:** `operator_slice_removal__mutmut_6` — removing the
`second_colon=cst.MaybeSentinel.DEFAULT` kwarg leaves the original
`second_colon=Colon()` on the node, producing `items[1:5:]` instead of
`items[1:5]`.

**File:** `tests/test_slice_removal.py`

**Change:** Add a test to `TestOperatorSliceRemoval` that renders the mutated
slice back to source and asserts no trailing colon:

```python
def test_step_removal_drops_trailing_colon(self):
    """items[1:5:2] with step removed -> items[1:5], not items[1:5:]"""
    expr = cst.parse_expression("items[1:5:2]")
    assert isinstance(expr, cst.Subscript)
    slc = expr.slice[0].slice
    assert isinstance(slc, cst.Slice)
    mutants = list(operator_slice_removal(slc))
    step_removed = [m for m in mutants if m.step is None]
    assert len(step_removed) == 1
    new_expr = expr.with_changes(
        slice=[cst.SubscriptElement(slice=step_removed[0])]
    )
    assert "items[1:5]" == new_expr.code  # NOT "items[1:5:]"
```

**Note:** `operator_slice_removal__mutmut_4` (`DEFAULT` -> `None`) is an
equivalent mutant — both `MaybeSentinel.DEFAULT` and `None` suppress the colon
when step is `None`. No test needed for that one.

## Fix 2: Default param mutation — remove dead `"None"` from `_BUILTIN_NAMES`

**Surviving mutants:** `operator_default_param_mutation__mutmut_10/11/12` — all
mutate the `"None"` string entry in `_BUILTIN_NAMES = {"True", "False", "None"}`.

**Root cause:** The `"None"` entry is unreachable dead code. The preceding
`if m.matches(default, m.Name("None"))` on line 28 catches all `Name("None")`
nodes before the `elif` on line 31 that uses `_BUILTIN_NAMES`. By the time the
set membership check runs, the node is guaranteed NOT to be `Name("None")`.

**File:** `src/mutmut_extras/operators/default_param_mutation.py`

**Change:** Remove `"None"` from the set:

```python
# Before
_BUILTIN_NAMES = {"True", "False", "None"}

# After
_BUILTIN_NAMES = {"True", "False"}
```

This eliminates 3 surviving mutants by removing the dead code rather than
writing untestable tests for unreachable paths.

## Summary

| Action | Mutants killed | Type |
|--------|---------------|------|
| Add `test_step_removal_drops_trailing_colon` | 1 (mutant 6) | New test |
| Remove `"None"` from `_BUILTIN_NAMES` | 3 (mutants 10-12) | Dead code removal |
| No action for mutant 4 | 0 | Equivalent mutant |

**Expected result:** 158/159 killed (99.4%), 1 equivalent mutant remaining.
