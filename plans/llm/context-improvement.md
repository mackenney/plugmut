# Improve LLM Prompt Context Quality

Provide the LLM with better, more relevant context about the function being mutated.

## Problems Identified

1. **Irrelevant imports:** All module imports are included regardless of use. `fibonacci` gets `ctypes` and `asyncio` — wastes tokens, may confuse the model.
2. **Skeleton class context:** Methods see only `class Point: ...` — no sibling method signatures. Model can't reason about how a mutation to `__init__` affects `abs()` or `add()`.
3. **No used-name awareness:** The model doesn't know what names the function actually references.

## Plan

### Part 1: Filter imports to relevant ones

**File:** `scope.py`, `_build_module_context`

Currently collects ALL import statements. Filter to only imports whose imported names appear in the function source.

```python
def _build_module_context(module: cst.Module, function_source: str) -> str:
    """Extract only import statements relevant to the target function."""
    func_names = set(re.findall(r'\b(\w+)\b', function_source))
    lines: list[str] = []
    for stmt in module.body:
        if isinstance(stmt, cst.SimpleStatementLine):
            for item in stmt.body:
                if isinstance(item, (cst.Import, cst.ImportFrom)):
                    imported_names = _extract_imported_names(item)
                    if imported_names & func_names:
                        lines.append(module.code_for_node(stmt).strip())
                    break
    return "\n".join(lines)
```

Helper to extract imported names:
```python
def _extract_imported_names(node: cst.Import | cst.ImportFrom) -> set[str]:
    names = set()
    if isinstance(node, cst.ImportFrom) and isinstance(node.names, (list, tuple)):
        for alias in node.names:
            if isinstance(alias, cst.ImportAlias):
                if alias.asname and isinstance(alias.asname.name, cst.Name):
                    names.add(alias.asname.name.value)
                elif isinstance(alias.name, cst.Name):
                    names.add(alias.name.value)
    elif isinstance(node, cst.Import) and isinstance(node.names, (list, tuple)):
        for alias in node.names:
            if isinstance(alias, cst.ImportAlias):
                if alias.asname and isinstance(alias.asname.name, cst.Name):
                    names.add(alias.asname.name.value)
                elif isinstance(alias.name, cst.Name):
                    names.add(alias.name.value)
    return names
```

**Signature change:** `_build_module_context` now takes `function_source` as a second arg. Update call sites in `_extract_functions`.

### Part 2: Rich class context with method signatures

**File:** `scope.py`, `_build_class_context`

Currently produces `class Point: ...`. Replace with class header + all method signatures (just the `def` line, no bodies):

```python
def _build_class_context(
    module: cst.Module, class_def: cst.ClassDef, module_context: str
) -> str:
    parts: list[str] = []

    # Class header with bases
    header = f"class {class_def.name.value}"
    if class_def.bases:
        bases = ", ".join(module.code_for_node(b) for b in class_def.bases)
        header += f"({bases})"
    header += ":"
    parts.append(header)

    # Class-level attributes and method signatures
    for stmt in class_def.body.body:
        if isinstance(stmt, cst.SimpleStatementLine):
            # Class attributes: x = 5, x: int = 5
            code = module.code_for_node(stmt).strip()
            parts.append(f"    {code}")
        elif isinstance(stmt, cst.FunctionDef):
            # Method signature only
            sig = _extract_signature(module, stmt)
            parts.append(f"    {sig}")

    class_block = "\n".join(parts)
    if module_context:
        return f"{module_context}\n\n{class_block}"
    return class_block
```

Signature extraction:
```python
def _extract_signature(module: cst.Module, func: cst.FunctionDef) -> str:
    """Extract `def name(params) -> ret: ...` from a FunctionDef."""
    # Build params string from the node
    params_code = module.code_for_node(func.params).strip()
    name = func.name.value

    decorators = ""
    for dec in func.decorators:
        dec_code = module.code_for_node(dec).strip()
        decorators += f"{dec_code}\n    "

    ret = ""
    if func.returns:
        ret_code = module.code_for_node(func.returns.annotation).strip()
        ret = f" -> {ret_code}"

    return f"{decorators}def {name}({params_code}){ret}: ..."
```

**Result for `Point.__init__`:**
```python
class Point:
    def __init__(self, x: int, y: int) -> None: ...
    def abs(self) -> 'Point': ...
    def add(self, other: 'Point'): ...
    def to_origin(self): ...
    @staticmethod
    def from_coords(coords: tuple[int, int]) -> 'Point': ...
    @property
    def coords(self) -> tuple[int, int]: ...
    def __len__(self) -> int: ...
```

This gives the LLM enough context to know that mutations to `__init__` affect `abs`, `add`, etc., without bloating the prompt with full method bodies.

### Part 3: Module-level constants and assignments

Some functions reference module-level constants (e.g., `BUILTIN_SAFE_DECORATORS`, `DEFAULT_TIMEOUT`). Include simple module-level assignments that the function references.

```python
def _build_module_context(module: cst.Module, function_source: str) -> str:
    func_names = set(re.findall(r'\b(\w+)\b', function_source))
    lines: list[str] = []

    for stmt in module.body:
        if isinstance(stmt, cst.SimpleStatementLine):
            for item in stmt.body:
                if isinstance(item, (cst.Import, cst.ImportFrom)):
                    imported_names = _extract_imported_names(item)
                    if imported_names & func_names:
                        lines.append(module.code_for_node(stmt).strip())
                    break
                elif isinstance(item, (cst.Assign, cst.AnnAssign)):
                    # Module-level constant referenced by the function
                    assign_names = _extract_assign_targets(item)
                    if assign_names & func_names:
                        lines.append(module.code_for_node(stmt).strip())
                    break

    return "\n".join(lines)
```

## Steps

### Step 1: Filter imports by relevance

Update `_build_module_context` to accept `function_source`, filter imports to those whose names appear in the function. Add `_extract_imported_names` helper.

### Step 2: Include module-level constants

Extend the same function to also include simple assignments whose target names appear in the function source.

### Step 3: Rich class context

Replace `_build_class_context` with version that includes method signatures and class attributes. Add `_extract_signature` helper.

### Step 4: Update call sites

`_extract_functions` passes `target.source` to `_build_module_context`. `_build_class_context` already receives `class_def` so no signature change needed there.

### Step 5: Test

- Unit test `_build_module_context` with a module containing 5 imports, function using 2 → only 2 appear.
- Unit test `_build_class_context` → verify output includes all method signatures.
- Integration: run `mutmut generate --dry-run` and inspect the generated prompts (add a `--verbose` flag or log the user prompt).
- Re-run dedup metrics, check if REDUNDANT rate decreases (model has better context → fewer confused mutations).

### Step 6: Token budget check

Measure prompt token counts before/after. Rich class context adds tokens but filtered imports remove them. Net should be roughly neutral for most files. For large classes (20+ methods), the signature list could be long — consider truncating to the 10 closest methods (by line proximity to the target method).
