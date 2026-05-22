# Whole-function mutation support in function_trampoline_arrangement

## What changed

**Modified function:** `function_trampoline_arrangement()` in `mutmut/src/mutmut/file_mutation.py`

```python
# Before
mutated_method_base = function.with_changes(name=cst.Name(mutant_name))
mutated_method_result = deep_replace(mutated_method_base, mutant.original_node, mutant.mutated_node)
nodes.append(mutated_method_result)

# After
if mutant.original_node is function:
    mutated_method = mutant.mutated_node.with_changes(name=cst.Name(mutant_name))
else:
    mutated_method = function.with_changes(name=cst.Name(mutant_name))
    mutated_method = deep_replace(mutated_method, mutant.original_node, mutant.mutated_node)
nodes.append(mutated_method)
```

## Why

`deep_replace()` uses object identity (`is`) to locate the node to replace.
When an operator targets `FunctionDef` itself (e.g. deleting the function body),
`mutant.original_node` is the same object as the `function` parameter. But the
old code called `function.with_changes(name=...)` first, which creates a new CST
object — breaking the identity check. `deep_replace` then silently returned the
node unchanged, producing a "mutant" identical to the original.

The fix checks whether the mutation targets the whole function. If so, it applies
`with_changes(name=...)` to the already-mutated node directly, bypassing
`deep_replace` entirely.

## Conflict scenario

If upstream modifies `function_trampoline_arrangement()`, check whether they
still use `deep_replace` for all mutations in the loop. The identity-check branch
(`if mutant.original_node is function`) is safe to re-add as long as:

1. The `function` parameter name hasn't changed
2. `deep_replace` still uses `is` for node comparison
3. The loop variable is still `mutant` with `.original_node` / `.mutated_node`

If upstream adds their own whole-function mutation support, drop this patch.

## Verification

```bash
uv run --package plugmut pytest mutmut/tests/ --ignore=mutmut/tests/e2e -x
```
