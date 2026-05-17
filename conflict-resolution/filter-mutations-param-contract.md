# filter_mutations hook parameter contract

## What changed

The `mutmut_filter_mutations` hook requires both `filename` and `mutations` parameters.
Plugins that omit `filename` raise `TypeError` at call time — this is intentional per SPEC.

## Why this couldn't be done via plugin

The contract is enforced by the hookspec call site in `create_mutations()`. Plugins cannot
change the argument list that the host passes to the hook.

## How to resolve conflicts

If upstream modifies `mutmut_filter_mutations` hookspec:
- Both `filename` and `mutations` must remain required parameters
- The call site in `create_mutations()` must pass both kwargs
- Tests in `test_hookspecs.py::test_filter_hook_requires_both_params` validate this
