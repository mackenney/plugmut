# Dynamic Exclusion List from Registered Operators

Build the LLM's "do NOT generate these" exclusion list dynamically from the actual registered operators, rather than hardcoding it in the system prompt.

## Problem

The current system prompt hardcodes 7 exclusion categories, but there are ~33 rule-based operators (20 in extras, 13+ in core). The LLM generates 26.3% REDUNDANT mutations that overlap with rule-based operators it doesn't know about.

## Available Metadata

Operators are `(cst_node_type, callable)` tuples. The callable has:
- `__name__` — e.g., `operator_operand_swap`, `operator_return_none`
- `__doc__` — e.g., "Swap left and right operands for non-commutative operators."
- Module `__doc__` — e.g., "Mutation operator: return <expr> -> return None."

No structured metadata field exists today.

## Design Options

### Option A: Read operator docstrings at generation time

At `run_generation()` time, call `pm.hook.mutmut_register_operators()` to get all registered operators, then extract `fn.__doc__` from each callable. Build an exclusion section from these docstrings.

**Pros:** Zero changes to operator code. Works with any plugin.
**Cons:** Docstring quality varies. Some are terse ("Mutate assert statements."). Need to handle missing docstrings.

```python
# In pipeline.py or prompts.py
def build_exclusion_list() -> str:
    from mutmut.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    lines = []
    for operators in pm.hook.mutmut_register_operators():
        for node_type, fn in operators:
            doc = fn.__doc__
            if doc:
                lines.append(f"  * {doc.strip().split(chr(10))[0]}")
            else:
                name = fn.__name__.replace("operator_", "").replace("_", " ")
                lines.append(f"  * {name}")
    return "\n".join(lines)
```

Then inject into the system prompt:
```
- Do NOT generate mutations already handled by these rule-based operators:
{exclusion_list}
```

### Option B: Add a `description` field to operator registration

Extend `OPERATORS_TYPE` to optionally accept a 3-tuple: `(node_type, callable, description)`.

**Pros:** Explicit, clean metadata. Description optimized for LLM consumption.
**Cons:** Requires changing the hookspec return type (core change). All existing operators need updating. Breaks the "minimal changes to mutmut/" principle.

### Option C: Companion metadata registry via new hook

Add a new hookspec:
```python
@hookspec
def mutmut_describe_operators(self) -> list[str]:
    """Return human-readable descriptions of what each operator does."""
```

Plugins implement this alongside `mutmut_register_operators`.

**Pros:** No change to existing operator format. Clean separation.
**Cons:** Another hookspec to maintain. Descriptions can drift from actual behavior.

### Option D: Generate descriptions from operator names + node types

Parse the operator function name and the CST node type to generate a description automatically:
```python
def describe_operator(node_type: type, fn: Callable) -> str:
    name = fn.__name__.replace("operator_", "").replace("_", " ")
    target = node_type.__name__
    return f"{name} (targets {target} nodes)"
```

**Pros:** Zero maintenance. Always in sync.
**Cons:** Descriptions are mechanical, may not convey enough nuance for the LLM.

## Decision

**Option A** (docstrings) as the primary source, with **Option D** (name-based) as fallback for operators without docstrings. No core changes needed, no new hookspecs.

## Steps

### Step 1: Add `build_exclusion_list()` to prompts.py

Function that queries the plugin manager, iterates all registered operators, collects docstrings (first line only) or generates from name+type as fallback.

### Step 2: Make SYSTEM_PROMPT a function

Change `SYSTEM_PROMPT` from a constant to `build_system_prompt()` that calls `build_exclusion_list()` and interpolates the result into the prompt template. Keep the existing hardcoded exclusions as a fallback for when plugins aren't loaded.

### Step 3: Update pipeline.py

Replace `SYSTEM_PROMPT` reference with `build_system_prompt()` call. Cache the result per generation run (operators don't change mid-run).

### Step 4: Improve operator docstrings in mutmut-extras

Review all 20 operator docstrings. Ensure each has a clear first-line summary suitable for LLM consumption. Pattern: "Mutate X by doing Y. Example: `a + b` → `b + a`."

### Step 5: Test

- Generate mutations with dynamic exclusion list active.
- Compare REDUNDANT rate against the 26.3% baseline.
- Verify the built exclusion list includes all expected operators.

### Step 6: Optional — add core operator docstrings

If core operators lack good docstrings, add them. This requires a `mutmut/` submodule patch + conflict resolution guide.
