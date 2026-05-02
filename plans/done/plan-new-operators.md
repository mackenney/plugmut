# Plan: New Deterministic Operators for mutmut-extras

**Priority: HIGH** — These are validated patterns from LLM mutation analysis that generalize across functions and are purely structural (CST-based, no semantic understanding needed).

## Operators to implement

### 1. `startswith_endswith_swap`

**What:** `s.startswith(x)` ↔ `s.endswith(x)`

**Why not already covered:** The symmetric string method swap table in mutmut core has lower/upper, lstrip/rstrip, find/rfind, index/rindex, removeprefix/removesuffix, partition/rpartition — but NOT startswith/endswith. This is an oversight.

**Implementation:** Add to `supported_symmetric_str_methods_swap` in `mutmut/src/mutmut/node_mutation.py`. Two entries:
```python
("startswith", "endswith"),
("endswith", "startswith"),
```

**Note:** This is technically a core mutmut patch (not extras). Needs a conflict-resolution guide. Alternatively, implement as a standalone operator in extras that matches the same `cst.Call` pattern independently.

**Decision needed:** Patch core (2 lines + conflict-resolution doc) vs. duplicate in extras (standalone operator, ~15 lines). Recommend extras to stay consistent with workspace principle of minimal core patches.

**Target node:** `cst.Call`
**Signature:** `(node: cst.Call) -> Iterable[cst.Call]`

---

### 2. `strip_to_partial_strip`

**What:** `s.strip()` → `s.lstrip()` and `s.strip()` → `s.rstrip()`

**Why not already covered:** Existing swaps are lstrip↔rstrip. Nobody touches `strip()` itself. `strip()` is extremely common in data processing code.

**Implementation:**
- Match `cst.Call` where `func` is `cst.Attribute(attr=cst.Name("strip"))` with zero args
- Yield two mutations: attr renamed to `"lstrip"` and `"rstrip"`
- Skip if args are present (strip with custom chars is a different pattern)

**Target node:** `cst.Call`
**Signature:** `(node: cst.Call) -> Iterable[cst.Call]`
**File:** `mutmut-extras/src/mutmut_extras/operators/strip_to_partial.py`

---

### 3. `remove_boundary_offset`

**What:** `expr + 1` → `expr`, `expr - 1` → `expr`, `len(x) - 1` → `len(x)`

**Why not already covered:** The existing number increment operator changes `1` → `2` (mutates the literal). This operator removes the entire `+ 1` / `- 1` operation, replacing the binary expression with just its left operand. Catches off-by-one bugs in boundary updates, recursive counters, length calculations.

**Implementation:**
- Match `cst.BinaryOperation` where:
  - `operator` is `cst.Add` or `cst.Subtract`
  - `right` is `cst.Integer(value="1")`
- Yield `node.left` (the expression without the +1/-1)
- Also handle right-side: `1 + expr` → `expr` (when left is `Integer("1")` and op is `Add`)

**Target node:** `cst.BinaryOperation`
**Signature:** `(node: cst.BinaryOperation) -> Iterable[cst.BaseExpression]`
**File:** `mutmut-extras/src/mutmut_extras/operators/remove_boundary_offset.py`

**Edge cases:**
- Don't match inside `range()` second arg (already covered by number increment on the literal)
- Consider also matching `+ 2`, `- 2` etc? Start with just `1` for precision.

---

### 4. `operand_swap`

**What:** `a - b` → `b - a`, `a / b` → `b / a`, `a ** b` → `b ** a`, `a % b` → `b % a`, `a // b` → `b // a`

**Why not already covered:** Existing `operator_swap_op` swaps the OPERATOR (e.g., `-` → `+`). This swaps the OPERANDS while keeping the operator. For non-commutative operations, this produces different results.

**Implementation:**
- Match `cst.BinaryOperation` where operator is one of: `Subtract`, `Divide`, `FloorDivide`, `Modulo`, `Power`
- Yield `node.with_changes(left=node.right, right=node.left)`
- Skip commutative operators (Add, Multiply, BitAnd, BitOr, BitXor)
- Preserve whitespace: swap the `whitespace_before`/`whitespace_after` on the operator node

**Target node:** `cst.BinaryOperation`
**Signature:** `(node: cst.BinaryOperation) -> Iterable[cst.BinaryOperation]`
**File:** `mutmut-extras/src/mutmut_extras/operators/operand_swap.py`

**Whitespace handling:** The left/right nodes carry leading/trailing whitespace. Need to be careful to produce valid code. Simplest approach: just swap `.left` and `.right` and let libcst handle it — test that `a - b` renders as `b - a` not `b-a` or `b -a`.

---

### 5. `exception_type_broadening`

**What:** `except ValueError:` → `except Exception:`

**Why not already covered:** The existing `exception_handler` operator replaces the handler BODY with `pass`. This changes the exception TYPE, which is a different bug class — silently swallowing errors that should propagate.

**Implementation:**
- Match `cst.ExceptHandler` where `type` is not None and not already `Exception`/`BaseException`
- Yield `node.with_changes(type=cst.Name("Exception"))`
- Handle tuple types: `except (ValueError, KeyError):` → for each type in the tuple, yield a mutation replacing that one type with `Exception`. Also yield replacing the entire tuple with just `Exception`.

**Target node:** `cst.ExceptHandler`
**Signature:** `(node: cst.ExceptHandler) -> Iterable[cst.ExceptHandler]`
**File:** `mutmut-extras/src/mutmut_extras/operators/exception_type_broadening.py`

**Edge cases:**
- Bare `except:` (no type) — skip
- `except Exception:` — skip (already broadest useful type)
- `except BaseException:` — skip
- Tuple of types: `except (A, B):` — replace each individually AND replace whole tuple

---

### 6. `isinstance_type_reduction`

**What:** `isinstance(x, (A, B))` → `isinstance(x, A)` and `isinstance(x, (A, B))` → `isinstance(x, B)`

**Why not already covered:** Existing arg removal replaces args with `None` or drops them entirely. This specifically targets the type tuple in isinstance, removing one type at a time.

**Implementation:**
- Match `cst.Call` where `func` is `cst.Name("isinstance")` and second arg is a `cst.Tuple` with 2+ elements
- For each element in the tuple, yield a mutation with that element removed
- If tuple reduces to 1 element, unwrap: `(A,)` → `A`

**Target node:** `cst.Call`
**Signature:** `(node: cst.Call) -> Iterable[cst.Call]`
**File:** `mutmut-extras/src/mutmut_extras/operators/isinstance_type_reduction.py`

**Edge cases:**
- `isinstance(x, str)` — no tuple, skip
- `isinstance(x, (A,))` — single-element tuple, skip (removing it would break isinstance)
- Nested: `isinstance(x, (A, (B, C)))` — rare, ignore

---

### 7. `exception_handler_control_flow`

**What:** `except X: pass` → `except X: break` (inside loops) or `except X: return` (in functions)

**Why not already covered:** The existing operator replaces handler bodies WITH `pass`. This does the inverse — when the body IS already `pass` (or trivial), it replaces with different control flow statements.

**Implementation:**
- Match `cst.ExceptHandler` whose body is a single `Pass` statement
- Always yield `break` variant (works in loops; will produce syntax error outside loops — that's filtered by mutmut's syntax validation)
- Always yield `continue` variant (same filtering logic)
- Optionally yield `return` variant

**Target node:** `cst.ExceptHandler`
**Signature:** `(node: cst.ExceptHandler) -> Iterable[cst.ExceptHandler]`
**File:** `mutmut-extras/src/mutmut_extras/operators/exception_control_flow.py`

**Note:** Generating `break` outside a loop produces invalid code. Two options:
1. Let mutmut's syntax validation filter these out (simpler)
2. Track parent context to know if we're in a loop (more complex)

Recommend option 1 for simplicity — mutmut already validates syntax of generated mutations.

---

## Implementation order

1. **`startswith_endswith_swap`** — smallest, validates the pattern
2. **`strip_to_partial_strip`** — similar structure, easy
3. **`operand_swap`** — straightforward BinaryOperation match
4. **`remove_boundary_offset`** — straightforward BinaryOperation match
5. **`isinstance_type_reduction`** — Call matching with tuple manipulation
6. **`exception_type_broadening`** — ExceptHandler with type handling
7. **`exception_handler_control_flow`** — ExceptHandler with body replacement

## Testing strategy

Each operator needs:
- Unit tests: isolated mutation validation (input node → expected mutated nodes)
- Integration test: end-to-end with `create_mutations` on a sample source file
- Edge case coverage per the notes above
