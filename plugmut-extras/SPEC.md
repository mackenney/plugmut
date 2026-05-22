# mutmut-extras Specification

> The key words MUST, MUST NOT, SHOULD, SHOULD NOT, MAY are used per RFC 2119.

## Purpose

mutmut-extras is a plugin package that registers 19 additional mutation operators into a
plugmut installation. It extends plugmut's built-in operator set by targeting AST patterns
that the built-ins do not cover or deliberately skip. Each operator is independently
activatable and independently composable with other plugin packages.

## Non-Goals

- mutmut-extras does NOT replace or modify core mutmut behavior; it only appends operators.
- mutmut-extras does NOT control which mutations are run, filtered, or reported; that is
  the core's responsibility.
- mutmut-extras does NOT guarantee that generated mutations are semantically valid (only
  libcst-parseable); semantic errors such as `break` outside a loop are left for the test
  runner to discover. `ast.parse` compatibility is NOT guaranteed for operators that are
  scope-unaware (see `exception_control_flow` below and Bug B3).
- mutmut-extras does NOT provide deduplication. When multiple operators independently
  produce structurally identical mutants for the same node, both mutations appear in the
  pipeline; deduplication is a separate concern.
- mutmut-extras does NOT fill all gaps in the built-in operator set; coverage decisions are
  explicit design choices documented per operator.

## Plugin Contract

mutmut-extras registers itself as a mutmut plugin via the `plugmut` entry-point group.
When installed, it implements the `mutmut_register_operators` hook and returns a flat
list of `(NodeType, callable)` tuples — one per operator function.

An operator callable MUST accept exactly one positional argument — a CST node of the
declared type — and return an iterable of zero or more mutated nodes of a compatible CST
type. Returning an empty iterable is a valid "no mutation" result.

Each operator MUST be a pure function: the same input node MUST yield the same ordered
sequence of output nodes on every call. Operators MUST NOT have side effects or shared
state.

The input node MUST be unchanged after the operator returns. The operator is responsible
for constructing new nodes; it MUST NOT mutate the node in place.

Each operator is invoked with, and only with, nodes whose type matches the type declared
in its `(NodeType, callable)` registration tuple. Whether two or more operators declare
the same `NodeType`, they ALL fire independently on every matching node.

## Operator Catalogue

### return_none

**Trigger:** `cst.Return` node where `.value` is present (not a bare `return`) and is not
the identifier `None`.

**Output contract:** Yields exactly one mutation: the same `Return` node with `.value`
replaced by the identifier `None`.

**Non-goals:** Does not mutate bare `return` (no value). Does not mutate `return None`
(already the target). Does not produce multiple mutations from a single node.

---

### exception_handler

**Trigger:** `cst.ExceptHandler` node whose body is not already a single `pass` statement.
The check is structural: a body of exactly one `cst.Pass` node, ignoring whitespace and
comments attached to the node.

**Output contract:** Yields exactly one mutation: the handler with its body replaced by a
single-statement `pass` block. Handler type (`except ValueError`, `except:`, etc.) and
all whitespace structure are preserved unchanged.

**Non-goals:** Does not mutate the exception type. Does not generate multiple body
replacements.

---

### ternary

**Trigger:** `cst.IfExp` node (any `x if cond else y` expression).

**Output contract:** Yields exactly three mutations in this order:
1. The true-branch expression, replacing the entire ternary
2. The false-branch expression, replacing the entire ternary
3. The same ternary expression with its true-branch and false-branch exchanged

All three yielded nodes are the same CST sub-expressions extracted from the ternary's
fields; they are structurally valid at the position the `IfExp` occupied.

**Non-goals:** Does not mutate the condition expression.

---

### assert_true

**Trigger:** `cst.Assert` node whose test is not the identifier `True`. The guard compares
the test Name node's identifier text against `"True"`, not full structural equality;
attached whitespace does not affect the check.

**Output contract:** Yields exactly one mutation: the `Assert` with its test replaced by
the identifier `True`. If present, the assertion message is preserved unchanged.

**Non-goals:** Does not mutate `assert True`. Does not generate `assert False`.

---

### slice_removal

**Trigger:** `cst.Slice` node that has at least one non-absent component (`lower`, `upper`,
or `step`). A component written explicitly as `None` in source (e.g., `a[:None]`) is
treated as present and triggers a mutation replacing it with the absent (default) form.

**Output contract:** Yields one mutation per present component — each mutation removes
that one component (`lower`, `upper`, or `step`), leaving the others unchanged. When
`step` is removed, the resulting slice serializes without a trailing colon (e.g., `a[x:y]`
not `a[x:y:]`). Maximum three mutations per slice node.

**Non-goals:** Does not remove the subscript itself. Does not combine multiple component
removals in a single mutation.

---

### void_call_removal

**Trigger:** `cst.SimpleStatementLine` where the body is exactly one statement that is a
bare function call expression (not assigned to anything).

**Output contract:** Yields exactly one mutation: the line with body replaced by a single
`pass` statement.

**Non-goals:** Does not fire when the call's return value is used (assignment, comparison,
return, etc.). Does not fire on multi-statement lines. Does not treat `super()` calls
differently from other calls (see Bugs / Inconsistencies, B2).

---

### yield_mutation

**Trigger:** `cst.Yield` node that is not a `yield from` expression.

**Output contract:**
- `yield expr` where `expr` is not the identifier `None` → yields one mutation: `yield None`
- bare `yield` (no value) → yields one mutation: `yield 0`
- `yield None` → yields nothing (already target)
- `yield from ...` → yields nothing (out of scope)

**Non-goals:** Does not mutate `yield from` expressions.

---

### comprehension_filter

**Trigger:** `cst.CompFor` node with at least one `if` clause.

**Output contract:** Yields exactly one mutation: the same `CompFor` with all `if` clauses
removed. Applies to list, set, dict, and generator comprehensions. The operator fires
independently on each `CompFor` node in the CST, including inner comprehensions within
nested structures.

**Non-goals:** Does not remove the comprehension itself. Does not remove individual `if`
clauses one at a time when multiple are present (removes all at once).

---

### super_call_deletion

**Trigger:** `cst.SimpleStatementLine` whose sole body statement is a bare call of the
form `super(...).method(...)`. Concretely: the call's function position is an attribute
access whose immediate object is a direct call to `super` (with any arguments). This
matches `super()`, `super(MyClass, self)`, `super().__init__()`, `super().save()`, etc.

**Output contract:** Yields exactly one mutation: the line with body replaced by `pass`.

**Non-goals:** Does not fire when `super(...)` result is assigned (`x = super().__init__()`).
Does not fire on plain `super()` calls without an attribute access. Does not fire on
further-chained super calls such as `super().method().chained()` — only one level of
attribute access from `super()` is matched.

---

### fstring_mutation

**Trigger:** `cst.FormattedStringExpression` node (an interpolation slot `{expr}` inside
an f-string) whose `.expression` is not already the string literal `'XX'`. Fires on every
such node at any nesting depth, including interpolations inside nested f-strings.

**Output contract:** Yields exactly one mutation: the same interpolation node with
`.expression` replaced by the string literal `'XX'`. Conversion flags (`!r`, `!s`, `!a`)
and format specs (`:fmt`) are preserved unchanged since only `.expression` is replaced.

**Non-goals:** Does not mutate the f-string literal parts (non-interpolated text). Does
not remove the f-string entirely.

---

### function_deletion

**Trigger:** `cst.FunctionDef` node whose body is not already a single `pass` statement.
The check is structural: a body of exactly one `cst.Pass` node, ignoring whitespace and
comments.

**Output contract:** Yields exactly one mutation: the function with its body replaced by a
single `pass` statement. The function's name, parameters, return annotation, decorators,
`async` keyword, and leading whitespace are structurally identical to the input.

Applies to sync and async functions, top-level functions, methods, and nested functions.

**Non-goals:** Does not fire on functions whose body is already `pass`. Does not delete
class definitions. Does not strip decorators.

**Core interaction constraint:** The core visitor skips `FunctionDef` nodes that have
unsafe decorators (any decorator not in the safe set: `staticmethod`, `classmethod`,
`abstractmethod`, `override`, `wraps`). Therefore `function_deletion` will not fire on
functions with non-safe decorators even when installed. This is a core constraint, not
fixable within this package.

---

### default_param_mutation

**Trigger:** `cst.Param` node with a default value falling into one of these cases:
1. Default is the identifier `None`
2. Default is a non-builtin name (any `Name` node that is not `True` or `False`)

**Output contract:**
- Case 1 (`None` default) → yields one mutation: `param=0`
- Case 2 (non-builtin name default) → yields one mutation: `param=None`
- Yields nothing if the default is a builtin literal (`True`, `False`, integer, float, string).

**Non-goals:** Does not mutate parameters without defaults. Does not duplicate mutations
already covered by built-in operators.

---

### reverse_iteration

**Trigger:** `cst.For` node where the iterable is not already a `reversed(...)` call.
In libcst, `async for` loops are represented as `cst.For` nodes with a non-None `asynchronous`
attribute. The operator checks `node.asynchronous` and skips async `for` loops.

**Output contract:** Yields exactly one mutation: the `for` node with the iterable wrapped
in `reversed(iterable)`.

**Non-goals:** Does not mutate the loop body or target variable. Does not add an import
for `reversed` (it is a built-in).

---

### startswith_endswith_swap

**Trigger:** `cst.Call` node where the callee is an attribute access named exactly
`startswith` or `endswith`, at any depth of attribute chaining (e.g., both `obj.startswith(x)`
and `obj.attr.startswith(x)` trigger). Does not fire on free functions named
`startswith`/`endswith` (they are not attribute accesses).

**Output contract:**
- `.startswith(...)` → yields one mutation: `.endswith(...)` with all arguments preserved
- `.endswith(...)` → yields one mutation: `.startswith(...)` with all arguments preserved

**Non-goals:** Does not mutate arguments. Does not fire on `str.startswith(x, ...)` where
`str` is the type (attribute on a `Name("str")` — same trigger semantics; this case is NOT
excluded by the trigger, only the unbound form with three arguments is excluded by name
semantics).

---

### strip_to_partial

**Trigger:** `cst.Call` node where the callee is an attribute access named exactly `strip`
AND the call has zero arguments.

**Output contract:** Yields exactly two mutations in this order:
1. `.lstrip()` — left-strip only
2. `.rstrip()` — right-strip only

**Non-goals:** Does not fire on `strip(chars)` calls with arguments. Does not produce an
identity mutation. Does not fire on free functions named `strip`. Does not fire on
`.lstrip()` or `.rstrip()` calls (those are not named `strip`).

---

### operand_swap

**Trigger:** `cst.BinaryOperation` node with one of these non-commutative operators: `-`,
`/`, `//`, `%`, `**`. The `@` matrix multiplication operator is explicitly excluded from
this version; it is non-commutative but left to future work.

**Output contract:** Yields exactly one mutation: the same binary operation with left and
right operands swapped. The operator symbol is preserved.

Does not fire on commutative operators: `+`, `*`, `&`, `|`, `^`, `@`.

**Non-goals:** Does not chain-swap nested binary expressions. Does not mutate the operator
symbol itself.

---

### remove_boundary_offset

**Trigger:** `cst.BinaryOperation` node matching one of these patterns:
- `expr + 1` (right operand is the integer literal `1`, operator is `+`)
- `expr - 1` (right operand is the integer literal `1`, operator is `-`)
- `1 + expr` (left operand is the integer literal `1`, operator is `+`)

Does NOT fire on `1 - expr`.

**Output contract:** Yields exactly one mutation: the non-`1` operand (`expr`), replacing
the entire `BinaryOperation` at its parent's position in the tree. The yielded node type
is whatever `node.left` or `node.right` is — not necessarily a `BinaryOperation`.

**Non-goals:** Does not target offsets other than `1`. Does not target `* 1` or `/ 1`
patterns.

---

### exception_type_broadening

**Trigger:** `cst.ExceptHandler` node with a non-absent exception type that is not already
`Exception` or `BaseException`.

**Output contract:**
- `except SomeError:` → yields one mutation: `except Exception:`
- `except (A, B):` with two or more element types → yields, in this order:
  1. The entire tuple replaced with `Exception` (e.g., `except Exception:`)
  2. For each element that is not already `Exception` or `BaseException`, a mutation
     replacing that element with `Exception` while leaving the others unchanged
  - Maximum mutations = 1 + count(elements not already in {Exception, BaseException})
- `except (A,):` (single-element tuple) → yields nothing

**Non-goals:** Does not fire on bare `except:`. Does not broaden to `BaseException`. Does
not mutate the handler body.

---

### exception_control_flow

**Trigger:** `cst.ExceptHandler` node whose body is EXACTLY a single `pass` statement.
The check is structural: a body of exactly one `cst.Pass` node, ignoring whitespace and
comments.

**Output contract:** Yields exactly three mutations in this order:
1. Body replaced with `break`
2. Body replaced with `continue`
3. Body replaced with `return`

**Non-goals:** Does not fire when the handler body has more than one statement or any
statement other than `pass`. Does not produce `raise` as a mutation.

**Semantic validity note:** The operator does not inspect whether the handler is nested
inside a loop. When the handler IS inside a loop, `break` and `continue` are semantically
valid. When it is NOT inside a loop, `break` and `continue` will cause `SyntaxError` at
Python compile time; such mutations fail `ast.parse` on the mutated module and are killed
by the test runner. This is by design: the operator is intentionally scope-unaware. See
also the Syntax Guarantee caveat in Behavioral Invariants.

---

## Behavioral Invariants

### Syntax guarantee (libcst)

Every mutation yielded by every operator MUST produce a CST node that, when substituted
into the original module and serialized, produces source parseable by libcst.

`ast.parse` compatibility is NOT universally guaranteed: scope-unaware operators
(`exception_control_flow`) may generate `break`/`continue` outside a loop, which is
libcst-valid but `ast.parse`-invalid. Consumers requiring `ast.parse` validity for all
mutations must apply a post-generation filter; that filter is outside this package's scope.

### Determinism

Every operator call MUST produce the same ordered sequence of output nodes for the same
input node. Output order is part of the contract for operators whose spec states "in this
order." Cross-operator ordering within a single `mutmut_register_operators` response is
determined by the position of each `(NodeType, callable)` tuple in the returned list; that
registration order is NOT part of this package's behavioral contract to callers.

### No identity mutations (single-target operators)

Operators with a single defined target state MUST yield nothing when the input node is
already in that target state. This prevents self-referential mutations. Each operator's
trigger condition encodes its guard.

Operators that yield multiple structurally distinct outputs (ternary, exception_control_flow,
strip_to_partial) do not have a single target state; no idempotency guard applies to them
since none of their outputs is the original input.

### No side effects

The input node MUST be unchanged after the operator returns.

### Independent activation

Each operator is invoked with, and only with, nodes whose type matches the type declared
in its registration tuple. The presence or absence of other operators does not change which
nodes any given operator fires on.

### Multiple operators on the same node type

When multiple operators declare the same `NodeType`, they ALL fire on every matching node,
producing multiple mutations for a single node. The relative order of mutations across
operators is determined by registration order (not contractually specified to callers).

### No filter hook

mutmut-extras does NOT implement `mutmut_filter_mutations`. Post-generation filtering is
outside this package's scope.

### Builtin non-duplication (default_param_mutation)

`default_param_mutation` MUST NOT generate mutations that the mutmut core built-in operators
already produce. Specifically, it MUST NOT yield mutations for `True`, `False`, integer,
float, or string-literal defaults.

---

## Known Limitations / Accepted Trade-offs

- **`super().method()` handled exclusively by `super_call_deletion`:** `void_call_removal`
  explicitly skips calls matching `super(...).method(...)` to avoid duplicate `pass` mutations.
  Only `super_call_deletion` fires on these sites.

- **exception_control_flow semantically invalid mutations:** `break`/`continue` mutations
  outside loops are libcst-valid but `ast.parse`-invalid, as documented in the
  Syntax Guarantee above. Accepted: the operator is scope-unaware by design.

- **reverse_iteration skips async for:** `cst.For` in libcst covers both sync and async for
  loops. The operator guards `if node.asynchronous is not None: return` and skips async iterables.

- **Decorated function exclusion:** `function_deletion` cannot fire on functions with
  non-safe decorators due to core-level skip logic. Not fixable in this package.

- **No `isinstance` type-reduction:** Blocked by core's `NEVER_MUTATE_FUNCTION_CALLS` list.
  Explicitly deferred until core exposes an override mechanism.

---

## Open Questions

1. **comprehension_filter multi-clause behavior:** When a comprehension has multiple `if`
   clauses (`[x for x in items if x > 0 if x < 10]`), the operator removes ALL `if` clauses
   in one mutation. Should individual-clause removal also be supported? The current single-
   mutation behavior is the only behavior; there are no tests for multi-clause input.

2. **remove_boundary_offset asymmetry:** `1 - expr` is intentionally excluded (only
   `expr - 1` fires). The rationale is a code comment "not the same pattern." Is this the
   intended final contract, or is `1 - expr` a missed case?

3. **yield 0 as the bare-yield sentinel:** Bare `yield` becomes `yield 0`. The choice of
   `0` is undocumented. Is `0` always the right sentinel, or should this be configurable?

4. **strip_to_partial and lstrip/rstrip targets:** If the input is `.lstrip()` or
   `.rstrip()`, neither `strip_to_partial` nor the built-ins fire on it. Is this intentional?

5. **super_call_deletion chaining depth:** The operator matches exactly one level of
   attribute access from `super()`. `super().method().chained()` does not trigger. Should
   this be extended to match further-chained forms?

## Acceptance Criteria

```
# All unit tests pass
uv run --package plugmut-extras pytest plugmut-extras/tests/ -q

# Verify Bug B4 is fixed (async for guard present)
uv run --package plugmut-extras pytest plugmut-extras/tests/ -k "async" -v

# Confirm no operator produces a mutation identical to its input
uv run --package plugmut-extras pytest plugmut-extras/tests/ -v
```
