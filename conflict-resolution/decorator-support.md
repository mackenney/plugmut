# Decorator support for safe-decorated functions

## What changed

### `file_mutation.py`

**New constants and helpers (after line 22):**
- `BUILTIN_SAFE_DECORATORS` — frozenset of decorator names known to be safe for mutation
- `_get_decorator_leaf_name()` — extracts rightmost identifier from any decorator form
- `_has_only_safe_decorators()` — returns True only when ALL decorators are in the safe set
- `_detect_method_type()` — returns `"static"`, `"classmethod"`, or `"instance"`
- `_strip_decorators()` — removes all decorators from a FunctionDef
- `_strip_non_dispatch_decorators()` — keeps only `@staticmethod`/`@classmethod`, strips the rest

**`_skip_node_and_children()` (was line 196-201):**
- Added `cst.Decorator` skip to prevent mutating decorator arguments
- Changed blanket decorator skip to safe-decorator classification via `_has_only_safe_decorators()`
- Uses `self._safe_decorators` (threaded via constructor)

**`MutationVisitor.__init__` (was line 131):**
- Added `safe_decorators` parameter (default: `BUILTIN_SAFE_DECORATORS`)
- Stored as `self._safe_decorators`

**`create_mutations` (was line 51):**
- Added `safe_decorators` parameter, forwarded to `MutationVisitor`

**`mutate_file_contents` (was line 32):**
- Reads `safe_decorators` from `mutmut.config` when available

**`function_trampoline_arrangement` (was line 271):**
- Detects `method_type` via `_detect_method_type()`
- Passes `method_type` to `create_trampoline_wrapper()`
- `_orig` copy uses `_strip_non_dispatch_decorators()` (keeps @staticmethod/@classmethod for dispatch, strips @abstractmethod etc.)
- Mutant copies use `_strip_decorators()` (fully stripped — called as plain functions via dict)

**`create_trampoline_wrapper` (was line 311):**
- Added `method_type` parameter
- Conditional arg stripping: skips `args[1:]` for `method_type == "static"` (no self to strip)
- 3-branch `_get_local_name()`: `Foo.attr` (static), `cls.attr` (classmethod), `object.__getattribute__(self, ...)` (instance)
- 3-branch `self_arg`: `None` (static), `cls` (classmethod), `self` (instance)

### `trampoline_templates.py`

**`create_trampoline_lookup` (line 14):**
- Changed `__name__` assignment to use `getattr(x, '__func__', x).__name__` to handle classmethod/staticmethod descriptors whose `__name__` setter doesn't propagate to `__func__`

### `__main__.py`

- Added `safe_decorators: frozenset[str]` field to `Config` dataclass
- `load_config()` reads `safe_decorators` from pyproject.toml and unions with `BUILTIN_SAFE_DECORATORS`
- Added import of `BUILTIN_SAFE_DECORATORS` from `file_mutation`

## Why not plugin

The skip logic (`_skip_node_and_children`) and trampoline codegen (`create_trampoline_wrapper`, `function_trampoline_arrangement`) are core mechanisms not exposed via pluggy hooks. No hook exists for `mutmut_filter_node_for_mutation` or similar.

## How to resolve conflicts

**If upstream changes the decorator skip in `_skip_node_and_children`:**
Merge their logic with the safe-decorator classification. Keep the `cst.Decorator` skip (prevents decorator arg mutation) and the `_has_only_safe_decorators()` check.

**If upstream changes `create_trampoline_wrapper`:**
Re-add the `method_type` parameter and the 3-branch dispatch in `_get_local_name()` and `self_arg`.

**If upstream changes `function_trampoline_arrangement`:**
Re-add `_strip_non_dispatch_decorators()` on `_orig` copies and `_strip_decorators()` on mutant copies. Re-add `method_type` detection and forwarding.

**If upstream changes `create_trampoline_lookup` in `trampoline_templates.py`:**
Re-add the `getattr(x, '__func__', x).__name__` pattern for the `__name__` assignment line.

**If upstream changes `Config` or `load_config`:**
Re-add the `safe_decorators` field and the `BUILTIN_SAFE_DECORATORS | frozenset(s("safe_decorators", []))` loading.
