# Plan: Decorator Support for Mutmut Trampolines

## Context

mutmut blanket-skips ALL decorated functions (`file_mutation.py:200`). `@staticmethod`, `@classmethod`, `@abstractmethod`, and every other decorated function gets zero mutations. In the agate trial, 5 of 7 methods in `api_key_utils.py` were invisible because they were `@staticmethod`.

This plan replaces the blanket skip with a safe-decorator classification system. Three tiers:
- **Tier 1** (pure wrappers like `@abstractmethod`, `@override`, `@wraps`): work with existing trampoline unchanged — just stop skipping them
- **Tier 2** (`@staticmethod`, `@classmethod`): need modified trampoline codegen (different dispatch, different self_arg handling)
- **Tier 3** (everything else: `@property`, `@app.route(...)`, `@contextmanager`, etc.): keep skipping

Users can register additional safe decorators via `[tool.mutmut] safe_decorators = [...]`.

## Files to modify

| File | What changes |
|---|---|
| `mutmut/src/mutmut/file_mutation.py` | Skip logic, trampoline codegen, new helpers |
| `mutmut/src/mutmut/__main__.py` | Config: `safe_decorators` field + loading |
| `mutmut/tests/test_mutation.py` | New tests + verify existing still pass |
| `conflict-resolution/decorator-support.md` | Required by workspace rules |

**No changes needed** to `mutmut/src/mutmut/trampoline_templates.py` — the `self_arg` mechanism already handles `None` (for staticmethod) and arbitrary values (for classmethod with `cls`).

---

## Background: How trampolines work today

The trampoline mechanism replaces each function body with a dispatcher:

```python
# Original
class Foo:
    def bar(self, x):
        return x + 1

# After mutation
class Foo:
    def bar(self, x):                          # ← trampoline wrapper (same signature)
        args = [x]
        kwargs = {}
        return _mutmut_trampoline(
            object.__getattribute__(self, 'xǁFooǁbar__mutmut_orig'),
            object.__getattribute__(self, 'xǁFooǁbar__mutmut_mutants'),
            args, kwargs, self
        )

    def xǁFooǁbar__mutmut_orig(self, x):      # ← original body, renamed
        return x + 1

    def xǁFooǁbar__mutmut_1(self, x):          # ← mutant copy
        return x - 1

    xǁFooǁbar__mutmut_mutants = {...}           # ← dict mapping names to mutant functions
    xǁFooǁbar__mutmut_orig.__name__ = 'xǁFooǁbar__mutmut'
```

Key code locations:
- `_skip_node_and_children()` (line 173) — decides what to skip during CST visiting
- `combine_mutations_to_source()` (line 213) — orchestrates mutation for all functions in a module
- `function_trampoline_arrangement()` (line 271) — creates wrapper + copies + dict for one function
- `create_trampoline_wrapper()` (line 311) — builds the trampoline wrapper body
- `create_trampoline_lookup()` (trampoline_templates.py:4) — generates the mutants dict + `__name__` assignment
- `_mutmut_trampoline()` (trampoline_templates.py:38) — runtime dispatcher (reads `MUTANT_UNDER_TEST` env var)

### Why decorated functions are currently skipped

The blanket skip at line 200 cites three reasons:
1. **Side effects from copying** — `@app.route("/foo")` would re-register routes for each copy
2. **Decorator argument mutation** — `@decorator(a=2)` mutating `a=2` could break imports
3. **`@property` breaks the trampoline** — property returns a descriptor, not a callable

### Why `@staticmethod`/`@classmethod` break the current trampoline

Three hardcoded assumptions in `create_trampoline_wrapper`:

1. **Arg stripping** (line 320-322): `args = args[1:]` removes `self`. Static methods have no `self` — this would strip a real parameter.
2. **Dispatch lookup** (line 338-342): `object.__getattribute__(self, name)` requires `self`. Static methods have no `self`.
3. **self_arg forwarding** (line 351): passes `self` to `_mutmut_trampoline`. Static methods have no `self`; classmethods have `cls`.

Additionally, `function.with_changes(name=...)` (used for copies at lines 288, 295, 297) preserves ALL attributes including decorators. So `_orig` and mutant copies would carry `@staticmethod`/`@classmethod`, turning them into descriptors — breaking the `mutants[name](*args)` call pattern which expects plain functions.

---

## Step 1: Add helper functions to `file_mutation.py`

**Where:** After the existing constants (around line 21, before `def mutate_file_contents`).

### 1a. Constant: `BUILTIN_SAFE_DECORATORS`

```python
BUILTIN_SAFE_DECORATORS: frozenset[str] = frozenset({
    "staticmethod", "classmethod", "abstractmethod", "override", "wraps",
})
```

These are decorators that:
- Don't register the function anywhere (no side effects)
- Don't fundamentally transform the return type (unlike `@property` which returns a descriptor)
- Either don't change calling convention (Tier 1) or change it in a way we handle (Tier 2)

### 1b. Function: `_get_decorator_leaf_name`

Extracts the rightmost identifier from any decorator form:
- `@foo` → `"foo"` (CST: `cst.Name`)
- `@foo.bar` → `"bar"` (CST: `cst.Attribute`)
- `@foo(args)` → `"foo"` (CST: `cst.Call` wrapping `cst.Name`)
- `@foo.bar(args)` → `"bar"` (CST: `cst.Call` wrapping `cst.Attribute`)

```python
def _get_decorator_leaf_name(decorator: cst.Decorator) -> str | None:
    node = decorator.decorator
    if isinstance(node, cst.Call):
        node = node.func
    if isinstance(node, cst.Attribute):
        return node.attr.value
    if isinstance(node, cst.Name):
        return node.value
    return None
```

### 1c. Function: `_has_only_safe_decorators`

Returns `True` only when EVERY decorator on the node has a leaf name in the safe set. If any single decorator is unknown/unsafe, the whole function is skipped.

```python
def _has_only_safe_decorators(
    node: cst.FunctionDef | cst.ClassDef, safe_set: frozenset[str]
) -> bool:
    for dec in node.decorators:
        name = _get_decorator_leaf_name(dec)
        if name is None or name not in safe_set:
            return False
    return True
```

### 1d. Function: `_detect_method_type`

Determines the dispatch strategy needed for the trampoline. Only relevant for class methods.

```python
def _detect_method_type(function: cst.FunctionDef) -> str:
    for dec in function.decorators:
        name = _get_decorator_leaf_name(dec)
        if name == "staticmethod":
            return "static"
        if name == "classmethod":
            return "classmethod"
    return "instance"
```

Return values and their meaning:
- `"static"` → no `self`/`cls` param, use `ClassName.attr` for dispatch, pass `None` as `self_arg`
- `"classmethod"` → has `cls` param, use `cls.attr` for dispatch, pass `cls` as `self_arg`
- `"instance"` → has `self` param, use existing `object.__getattribute__(self, ...)` dispatch

### 1e. Function: `_strip_decorators`

```python
def _strip_decorators(function: cst.FunctionDef) -> cst.FunctionDef:
    return function.with_changes(decorators=())
```

---

## Step 2: Modify `_skip_node_and_children` (line 196-201)

**Current code (lines 196-201):**
```python
# ignore decorated functions, because
# 1) copying them for the trampoline setup can cause side effects (e.g. multiple @app.post("/foo") definitions)
# 2) decorators are executed when the function is defined, so we don't want to mutate their arguments and cause exceptions
# 3) @property decorators break the trampoline signature assignment (which expects it to be a function)
if isinstance(node, (cst.FunctionDef, cst.ClassDef)) and len(node.decorators):
    return True
```

**Replace with:**
```python
# Do not mutate decorator arguments — they execute at definition time
# (e.g. @some_decorator(a=2) should not mutate a=2)
if isinstance(node, cst.Decorator):
    return True

# Skip decorated functions unless ALL decorators are known-safe
if isinstance(node, (cst.FunctionDef, cst.ClassDef)) and node.decorators:
    if not _has_only_safe_decorators(node, self._safe_decorators):
        return True
```

Two changes:
1. **New `cst.Decorator` skip** — prevents mutating decorator arguments while still allowing the function body to be visited. This addresses reason #2 from the original comment.
2. **Conditional function skip** — only skip if any decorator is NOT in the safe set. Uses `self._safe_decorators` (threaded via constructor, see Step 3).

---

## Step 3: Thread `safe_decorators` through the call chain

### 3a. `MutationVisitor.__init__` (line 131)

**Current:**
```python
def __init__(self, operators: OPERATORS_TYPE, ignore_lines: set[int], covered_lines: set[int] | None = None):
```

**Change to:**
```python
def __init__(self, operators: OPERATORS_TYPE, ignore_lines: set[int], covered_lines: set[int] | None = None,
             safe_decorators: frozenset[str] = BUILTIN_SAFE_DECORATORS):
```

Add to body (after line 135):
```python
self._safe_decorators = safe_decorators
```

### 3b. `create_mutations` (line 51)

**Current signature:**
```python
def create_mutations(
    code: str, covered_lines: set[int] | None = None, filename: str = "",
) -> tuple[cst.Module, list[Mutation]]:
```

**Change to:**
```python
def create_mutations(
    code: str, covered_lines: set[int] | None = None, filename: str = "",
    safe_decorators: frozenset[str] = BUILTIN_SAFE_DECORATORS,
) -> tuple[cst.Module, list[Mutation]]:
```

**Change line 68** (visitor construction):
```python
visitor = MutationVisitor(operators, ignored_lines, covered_lines, safe_decorators)
```

### 3c. `mutate_file_contents` (line 32)

**Add before the `create_mutations` call** (line 36):
```python
import mutmut
safe = mutmut.config.safe_decorators if mutmut.config else BUILTIN_SAFE_DECORATORS
```

**Change line 36:**
```python
module, mutations = create_mutations(code, covered_lines, filename=filename, safe_decorators=safe)
```

This means:
- When called from `__main__.py` (real runs): uses config value (built-in + user additions)
- When called from tests via `mutants_for_source`: uses `BUILTIN_SAFE_DECORATORS` default (no config needed)

---

## Step 4: Add `safe_decorators` to Config (`__main__.py`)

### 4a. Import (top of file or at usage site)

```python
from mutmut.file_mutation import BUILTIN_SAFE_DECORATORS
```

### 4b. `Config` dataclass (line 905, add after line 915)

```python
safe_decorators: frozenset[str]
```

### 4c. `load_config` (line 981, add to the Config constructor around line 1003)

```python
safe_decorators=BUILTIN_SAFE_DECORATORS | frozenset(s("safe_decorators", [])),
```

**User-facing config:**
```toml
[tool.mutmut]
safe_decorators = ["login_required", "retry", "cache"]
```

Matching is by leaf name: `@functools.cache` matches `"cache"`, `@login_required` matches `"login_required"`.

---

## Step 5: Modify `function_trampoline_arrangement` (line 271)

This function creates the trampoline wrapper, the `_orig` copy, and all mutant copies. Three changes needed.

### 5a. Detect method type (after line 280)

**Add after** `name = function.name.value` (line 280):
```python
method_type = _detect_method_type(function) if class_name else "instance"
```

### 5b. Pass method_type to trampoline wrapper (line 285)

**Current:**
```python
nodes.append(create_trampoline_wrapper(function, mangled_name, class_name))
```

**Change to:**
```python
nodes.append(create_trampoline_wrapper(function, mangled_name, class_name, method_type))
```

### 5c. Strip decorators from `_orig` copy (line 288)

**Current:**
```python
nodes.append(function.with_changes(name=cst.Name(mangled_name + "_orig")))
```

**Change to:**
```python
nodes.append(_strip_decorators(function).with_changes(name=cst.Name(mangled_name + "_orig")))
```

**Why:** `function.with_changes(name=...)` preserves all attributes including decorators. If `_orig` keeps `@staticmethod`, it becomes a descriptor object, and the `__name__` assignment in `create_trampoline_lookup` (trampoline_templates.py:14) would fail — `staticmethod` objects don't support `__name__` assignment. Stripping decorators makes `_orig` a plain function where `__name__` assignment works.

### 5d. Strip decorators from mutant copies (lines 291-299)

**Current (lines 294-298):**
```python
if mutant.original_node is function:
    mutated_method = mutant.mutated_node.with_changes(name=cst.Name(mutant_name))
else:
    mutated_method = function.with_changes(name=cst.Name(mutant_name))
    mutated_method = deep_replace(mutated_method, mutant.original_node, mutant.mutated_node)
```

**Change to:**
```python
if mutant.original_node is function:
    mutated_method = _strip_decorators(mutant.mutated_node).with_changes(name=cst.Name(mutant_name))
else:
    mutated_method = _strip_decorators(function).with_changes(name=cst.Name(mutant_name))
    mutated_method = deep_replace(mutated_method, mutant.original_node, mutant.mutated_node)
```

**Why:** Mutant copies are stored in a dict and called as plain functions via `mutants[name](*args)`. If they had `@staticmethod`, they'd be descriptor objects, not callable in that way. The trampoline wrapper (which keeps the decorator) is the only version that needs the decorator — it's the public-facing function.

---

## Step 6: Modify `create_trampoline_wrapper` (line 311)

This function builds the trampoline wrapper that replaces the original function body. Three sections need changes based on `method_type`.

### 6a. Add `method_type` parameter (line 311)

**Current:**
```python
def create_trampoline_wrapper(function: cst.FunctionDef, mangled_name: str, class_name: str | None) -> cst.FunctionDef:
```

**Change to:**
```python
def create_trampoline_wrapper(
    function: cst.FunctionDef, mangled_name: str, class_name: str | None, method_type: str = "instance",
) -> cst.FunctionDef:
```

### 6b. Conditional arg stripping (lines 320-322)

**Current:**
```python
if class_name is not None:
    # remove self arg (handled by the trampoline function)
    args = args[1:]
```

**Change to:**
```python
if class_name is not None and method_type != "static":
    # remove self/cls arg (handled by the trampoline function)
    args = args[1:]
```

**Why:** `@staticmethod` methods have no `self` or `cls` — there's nothing to strip. Stripping the first arg would incorrectly remove a real parameter.

### 6c. Three-branch `_get_local_name` (lines 334-342)

**Current:**
```python
def _get_local_name(func_name: str) -> cst.BaseExpression:
    # for top level, simply return the name
    if class_name is None:
        return cst.Name(func_name)
    # for class methods, use object.__getattribute__(self, name)
    return cst.Call(
        func=cst.Attribute(cst.Name("object"), cst.Name("__getattribute__")),
        args=[cst.Arg(cst.Name("self")), cst.Arg(cst.SimpleString(f"'{func_name}'"))],
    )
```

**Change to:**
```python
def _get_local_name(func_name: str) -> cst.BaseExpression:
    if class_name is None:
        return cst.Name(func_name)
    if method_type == "static":
        # No self available — use ClassName.attr (resolved at call time, class exists by then)
        return cst.Attribute(cst.Name(class_name), cst.Name(func_name))
    if method_type == "classmethod":
        # cls is the first param — use cls.attr
        return cst.Attribute(cst.Name("cls"), cst.Name(func_name))
    # Regular instance method — use object.__getattribute__(self, name) to bypass descriptors
    return cst.Call(
        func=cst.Attribute(cst.Name("object"), cst.Name("__getattribute__")),
        args=[cst.Arg(cst.Name("self")), cst.Arg(cst.SimpleString(f"'{func_name}'"))],
    )
```

**Dispatch strategies explained:**
- **`@staticmethod`**: `ClassName.attr` — the class name is a hardcoded reference to the containing class. Works because the trampoline body executes at call time, when the class is already fully defined. **Known limitation:** fails for classes defined inside functions (factory pattern) where `ClassName` is a local variable not in module scope.
- **`@classmethod`**: `cls.attr` — `cls` is always available as the first parameter. Works correctly with inheritance (MRO finds the right class's mutants).
- **instance**: `object.__getattribute__(self, name)` — unchanged from current behavior.

### 6d. Three-branch `self_arg` (line 351)

**Current:**
```python
cst.Arg(cst.Name("None" if class_name is None else "self")),
```

**Change to:**
```python
cst.Arg(cst.Name(
    "None" if (class_name is None or method_type == "static")
    else ("cls" if method_type == "classmethod" else "self")
)),
```

**What happens at runtime in `_mutmut_trampoline` (trampoline_templates.py:56-60):**
- `self_arg=None` (static): calls `mutants[name](*call_args, **call_kwargs)` — no self/cls prepended
- `self_arg=cls` (classmethod): calls `mutants[name](cls, *call_args, **call_kwargs)` — cls prepended because mutant copies are plain functions expecting cls as first arg
- `self_arg=self` (instance): unchanged behavior

### 6e. The trampoline wrapper preserves decorators — NO CHANGE NEEDED (line 374)

```python
return function.with_changes(body=cst.IndentedBlock([...]))
```

`with_changes(body=...)` only replaces the body, preserving decorators. This is correct: the trampoline IS the public function, so it must carry `@staticmethod`/`@classmethod`/`@abstractmethod` etc.

---

## Step 7: Tests (`test_mutation.py`)

### 7a. Verify existing test still passes

`test_do_not_mutate_top_level_decorators` (line 698) uses:
- `@some_decorator(a = 2)` — leaf name `some_decorator`, NOT in safe set → skipped ✓
- `@unique` on class — leaf name `unique`, NOT in safe set → skipped ✓
- `@property` on method — leaf name `property`, NOT in safe set → skipped ✓

No change needed to this test.

### 7b. New positive tests — decorated functions now generate mutations

```python
def test_staticmethod_generates_mutants():
    source = """
class Foo:
    @staticmethod
    def bar(x):
        return x + 1
""".strip()
    mutants = mutants_for_source(source)
    assert mutants

def test_classmethod_generates_mutants():
    source = """
class Foo:
    @classmethod
    def create(cls, val):
        return cls(val + 1)
""".strip()
    mutants = mutants_for_source(source)
    assert mutants

def test_abstractmethod_generates_mutants():
    source = """
from abc import abstractmethod
class Base:
    @abstractmethod
    def process(self, data):
        return data + 1
""".strip()
    mutants = mutants_for_source(source)
    assert mutants
```

### 7c. New negative tests — unsafe decorators still skipped

```python
def test_property_still_skipped():
    source = """
class Foo:
    @property
    def value(self):
        return self._value + 1
""".strip()
    mutants = mutants_for_source(source)
    assert not mutants

def test_unknown_decorator_skipped():
    source = """
@app.route("/foo")
def handler():
    return 1 + 2
""".strip()
    mutants = mutants_for_source(source)
    assert not mutants
```

### 7d. Stacking rule test

```python
def test_mixed_safe_unsafe_decorators_skipped():
    source = """
class Foo:
    @staticmethod
    @unknown_thing
    def bar(x):
        return x + 1
""".strip()
    mutants = mutants_for_source(source)
    assert not mutants
```

### 7e. Trampoline output tests — verify correct codegen

```python
def test_staticmethod_trampoline_output():
    source = """
class Foo:
    @staticmethod
    def bar(x):
        return x + 1
""".strip()
    output = mutated_module(source)
    # Trampoline keeps @staticmethod
    assert "@staticmethod" in output
    # Dispatch uses ClassName.attr
    assert "Foo." in output
    # _orig copy does NOT have @staticmethod (check the orig function definition)
    after_orig = output.split("__mutmut_orig")[1]
    lines_before_next_def = after_orig.split("def ")[0]
    assert "@staticmethod" not in lines_before_next_def

def test_classmethod_trampoline_output():
    source = """
class Foo:
    @classmethod
    def create(cls, val):
        return cls(val + 1)
""".strip()
    output = mutated_module(source)
    assert "@classmethod" in output
    # Dispatch uses cls.attr
    assert "cls." in output
```

### 7f. User safe_decorators config test

```python
def test_user_safe_decorators_config():
    source = """
@custom_retry
def foo():
    return 1 + 2
""".strip()
    # Default: skipped (custom_retry not in built-in safe set)
    _, default_mutations = create_mutations(source)
    assert not default_mutations
    # With user config: allowed
    custom_safe = BUILTIN_SAFE_DECORATORS | frozenset({"custom_retry"})
    _, custom_mutations = create_mutations(source, safe_decorators=custom_safe)
    assert custom_mutations
```

### 7g. Decorator arguments are not mutated

```python
def test_decorator_arguments_not_mutated():
    source = """
from abc import abstractmethod
class Base:
    @abstractmethod
    def process(self, data):
        return data + 1
""".strip()
    mutants = mutants_for_source(source)
    # Mutations should only be in the body (data + 1), not in the decorator
    for m in mutants:
        assert "@abstractmethod" in m
```

---

## Step 8: Conflict resolution guide

Create `conflict-resolution/decorator-support.md` with:

**What changed:**
- `file_mutation.py`: `_skip_node_and_children` (decorator classification instead of blanket skip), `create_trampoline_wrapper` (method_type parameter with 3-branch dispatch), `function_trampoline_arrangement` (decorator stripping from copies), new helpers
- `__main__.py`: `Config.safe_decorators` field, `load_config` reads it

**Why not plugin:**
The skip logic (`_skip_node_and_children`) and trampoline codegen (`create_trampoline_wrapper`) are core mechanisms not exposed via pluggy hooks. No hook exists for `mutmut_filter_node_for_mutation` or similar.

**How to resolve if upstream modifies these functions:**
- If upstream changes the decorator skip: merge their logic with the safe-decorator classification
- If upstream changes `create_trampoline_wrapper`: re-add the `method_type` branching in `_get_local_name` and `self_arg`
- If upstream changes `function_trampoline_arrangement`: re-add `_strip_decorators` calls on copies

---

## Implementation order

1. Step 1 (helpers) — pure functions, no behavior change
2. Step 7b, 7c, 7d (write failing tests first) — TDD
3. Step 2 (skip logic change) — makes Tier 1 tests pass
4. Step 3 (thread safe_decorators) — enables config support
5. Step 5 (function_trampoline_arrangement) — decorator stripping
6. Step 6 (create_trampoline_wrapper) — Tier 2 dispatch
7. Step 7e, 7f, 7g (trampoline output + config tests)
8. Step 4 (Config in __main__.py)
9. Step 8 (conflict resolution doc)
10. Run full test suite: `uv run --package mutmut pytest mutmut/tests/`
11. Run e2e: `uv run --package mutmut pytest mutmut/tests/e2e/`

---

## Known limitations

1. **`ClassName.attr` for `@staticmethod` fails for nested/factory classes** — classes defined inside functions have `ClassName` as a local, not in module globals at call time. Module-level classes (the vast majority of mutation targets) work fine.
2. **Unknown decorators default to skip** — conservative. Users opt in via `safe_decorators` config.
3. **Decorator arguments never mutated** — intentional. They execute at definition time; mutating them risks import-time crashes.
4. **`@property` not supported** — fundamentally incompatible with the trampoline (returns a descriptor, not a callable). Would require a completely different trampoline strategy.

---

## Verification

1. `uv run --package mutmut pytest mutmut/tests/test_mutation.py -k "decorator or staticmethod or classmethod"` — all new tests pass
2. `uv run --package mutmut pytest mutmut/tests/` — existing tests still pass (especially `test_do_not_mutate_top_level_decorators`)
3. `uv run --package mutmut pytest mutmut/tests/e2e/` — e2e tests pass
4. Re-run the agate trial to verify `@staticmethod` methods in `api_key_utils.py` now produce mutants

---

## Appendix: Decorator safety taxonomy

Full classification from investigation. Useful for extending the built-in safe set in the future.

### Tier 1 — Safe (pure wrappers, no calling convention change)

| Decorator | Why safe |
|---|---|
| `@abstractmethod` | Just sets `__isabstractmethod__` flag |
| `@typing.override` | Just sets `__override__` flag |
| `@functools.wraps(f)` | Copies metadata, no behavioral change |
| `@login_required` | Pure auth-checking wrapper |
| `@permission_required` | Pure auth-checking wrapper |
| `@csrf_exempt` | Sets attribute flag only |
| `@transaction.atomic` | Pure transaction wrapper |
| `@pytest.mark.*` | Metadata markers only |
| `@tenacity.retry` / `@retry` | Pure retry wrapper |
| `@beartype` | Pure type-checking wrapper |
| `@deprecated` | Pure warning-emitting wrapper |

### Tier 2 — Safe with special trampoline handling

| Decorator | What's different |
|---|---|
| `@staticmethod` | No self, ClassName.attr dispatch, self_arg=None |
| `@classmethod` | Has cls, cls.attr dispatch, self_arg=cls |

### Tier 3 — Must skip

| Decorator | Danger |
|---|---|
| `@property` | Returns descriptor, not callable |
| `@hybrid_property` | Same as @property |
| `@contextmanager` | Requires yield in body; trampoline body has no yield |
| `@asynccontextmanager` | Same as @contextmanager |
| `@app.route(...)` / `@app.get(...)` | Route registration side effect |
| `@app.task` / `@shared_task` | Task registry + returns Task object |
| `@click.command()` | Returns Command object, not function |
| `@functools.singledispatch` | Dispatch registry incompatible with copy mechanism |
| `@typing.overload` | Bodies are meaningless stubs |
| `@field_validator` / `@model_validator` | Pydantic descriptor proxy + metaclass |
| `@unittest.mock.patch` | Modifies signature at call time |
| `@atexit.register` | Exit handler registration |
| `@event.listens_for(...)` | Event listener registration |
