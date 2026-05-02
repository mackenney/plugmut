# Whole-Function Mutations

## Context

LLM-based mutation operators need to replace entire function bodies — send a function's source to an LLM, get back a semantically mutated version. The current `function_trampoline_arrangement()` in `mutmut/src/mutmut/file_mutation.py` (lines 266-270) assumes mutations are **sub-node replacements within a function**:

```python
mutant_function = deep_replace(function, mutant.original_node, mutant.mutated_node)
mutant_function = mutant_function.with_changes(name=cst.Name(mutant_name))
```

`deep_replace()` walks the function's CST looking for `mutant.original_node` and swaps it with `mutant.mutated_node`. When `original_node` IS the function itself (i.e., a whole-function replacement), `deep_replace` fails because it's searching for the function node inside itself — a degenerate case that either produces no replacement or corrupts the tree.

## Why It Matters

This is a **hard prerequisite** for LLM mutation operators. Without whole-function replacement support:

- LLM operators cannot return mutated function bodies through the standard pipeline.
- Plugin authors are limited to sub-expression mutations — the same class of mutations builtins already cover.
- The original project goal (LLM-powered mutation testing) is blocked.

## Benefits

- Unlocks LLM-powered mutation testing — the primary differentiator of the project.
- Enables any operator that works at function granularity (not just LLMs): function body randomization, algorithm substitution, contract-based mutation.
- No impact on existing sub-node mutations — this is a new code path triggered only when `original_node` is the function itself.

## Implementation Recommendation

### 1. Detection in `function_trampoline_arrangement()`

Add a check before `deep_replace`:

```python
if mutant.original_node is function:
    # Whole-function replacement: use mutated_node directly
    mutant_function = mutant.mutated_node.with_changes(
        name=cst.Name(mutant_name)
    )
else:
    # Sub-node replacement: existing behavior
    mutant_function = deep_replace(function, mutant.original_node, mutant.mutated_node)
    mutant_function = mutant_function.with_changes(name=cst.Name(mutant_name))
```

### 2. Identity comparison

Use `is` (identity), not `==` (equality). Two different CST nodes could be structurally equal but represent different positions in the tree. Identity comparison ensures we only take the whole-function path when the operator explicitly returned the function node as `original_node`.

### 3. Operator contract for whole-function mutations

Plugin operators producing whole-function mutations must:

- Return `(function_node, mutated_function_node)` where `function_node` is the exact `FunctionDef` passed to the operator.
- Ensure `mutated_function_node` is a valid `FunctionDef` with the same signature (parameters, decorators, return type) — only the body changes.
- The name will be overwritten by the trampoline system, so the returned name doesn't matter.

Example operator signature:

```python
def operator_llm(node, context=None, **kwargs):
    if not isinstance(node, cst.FunctionDef):
        return
    mutated_body = get_llm_mutation(node)  # from cache or API
    if mutated_body:
        yield node, node.with_changes(body=mutated_body)
```

### 4. Test coverage

Add tests in `mutmut/tests/` that:

- Create a `FunctionDef` node, produce a whole-function mutation, run through `function_trampoline_arrangement()`, verify the trampoline dispatches correctly.
- Confirm sub-node mutations still work unchanged (regression).
- Verify identity check with structurally-equal-but-different nodes.

### 5. Reference

The reference implementation at `~/pr/mutmut/` has this exact pattern working, including the `is` check and the `with_changes(name=...)` path.
