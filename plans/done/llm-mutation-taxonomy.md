# Mutation Testing Operator Taxonomy

## Current Coverage: mutmut core (14 operators) + mutmut-extras (12 operators)

### mutmut core

| # | Operator | Target Node | Description |
|---|----------|-------------|-------------|
| 1 | `operator_number` | `cst.BaseNumber` | Increment by 1 |
| 2 | `operator_string` | `cst.SimpleString` | XX prefix/suffix, upper/lower case |
| 3 | `operator_name` | `cst.Name` | True↔False, deepcopy→copy |
| 4 | `operator_swap_op` | Binary/Unary/Bool/Comparison/AugAssign | Full arithmetic/comparison/logical/bitwise swaps |
| 5 | `operator_augmented_assignment` | `cst.AugAssign` | `x += 1` → `x = 1` |
| 6 | `operator_assignment` | `cst.Assign`/`cst.AnnAssign` | `a = b` → `a = None`; `a = None` → `a = ""` |
| 7 | `operator_lambda` | `cst.Lambda` | `lambda: x` → `lambda: None`/`lambda: 0` |
| 8 | `operator_dict_arguments` | `cst.Call` | `dict(a=b)` → `dict(aXX=b)` |
| 9 | `operator_arg_removal` | `cst.Call` | Replace args with None, drop args |
| 10 | `operator_symmetric_string_methods_swap` | `cst.Call` | lower↔upper, lstrip↔rstrip, find↔rfind, etc. |
| 11 | `operator_unsymmetrical_string_methods_swap` | `cst.Call` | split↔rsplit (conditional) |
| 12 | `operator_remove_unary_ops` | `cst.UnaryOperation` | Remove `not`, `~` |
| 13 | `operator_keywords` | `cst.CSTNode` | is↔is not, in↔not in, break→return, continue→break |
| 14 | `operator_match` | `cst.Match` | Drop individual case clauses |

### mutmut-extras

| # | Operator | Target Node | Description |
|---|----------|-------------|-------------|
| 1 | `operator_return_none` | `cst.Return` | `return x` → `return None` |
| 2 | `operator_exception_handler` | `cst.ExceptHandler` | Handler body → `pass` |
| 3 | `operator_ternary` | `cst.IfExp` | Collapse to branch, swap branches |
| 4 | `operator_assert_true` | `cst.Assert` | `assert cond` → `assert True` |
| 5 | `operator_slice_removal` | `cst.Slice` | Remove lower/upper/step |
| 6 | `operator_void_call_removal` | `cst.SimpleStatementLine` | Standalone call → `pass` |
| 7 | `operator_yield_mutation` | `cst.Yield` | `yield x` → `yield None` |
| 8 | `operator_comprehension_filter_removal` | `cst.CompFor` | Remove `if` in comprehension |
| 9 | `operator_super_call_deletion` | `cst.SimpleStatementLine` | `super().method()` → `pass` |
| 10 | `operator_fstring_mutation` | `cst.FormattedStringExpression` | `{expr}` → `{'XX'}` |
| 11 | `operator_default_param_mutation` | `cst.Param` | None→0, compound→None |
| 12 | `operator_reverse_iteration` | `cst.For` | Wrap iterable in `reversed()` |

---

## Gap Analysis: Known operators NOT in mutmut

### Tier 1 — High value, straightforward

| Operator | Source | Example |
|----------|--------|---------|
| Decorator deletion (DDL) | MutPy, Cosmic-Ray | `@cache def f():` → `def f():` |
| Exception swallowing (EXS) | MutPy | `raise ValueError("x")` → `pass` |
| Exception type replacement | Cosmic-Ray | `except ValueError:` → `except _MutantException:` |
| Zero iteration loop (ZIL) | MutPy, Cosmic-Ray | `for x in items:` → `for x in []:` |
| One iteration loop (OIL) | MutPy | `for x in items:` → `for x in items[:1]:` |
| Statement deletion (SDL) | MutPy, Major | Any statement → `pass` |
| Conditional to True/False | PIT, Stryker | `if cond:` → `if True:` / `if False:` |
| Collection literal emptying | Stryker | `[1, 2, 3]` → `[]`; `{"a": 1}` → `{}` |
| Builtin swap: min↔max | Stryker | `min(a, b)` → `max(a, b)` |
| Builtin swap: any↔all | Stryker | `any(items)` → `all(items)` |
| Method swap: startswith↔endswith | Stryker | `s.startswith(x)` → `s.endswith(x)` |
| sorted/reversed removal | Arcmutate | `sorted(items)` → `items` |
| Conditional operator insertion (COI) | MutPy | Insert `not` in boolean contexts |

### Tier 2 — Medium value, moderate complexity

| Operator | Source | Example |
|----------|--------|---------|
| Arithmetic operand deletion (AOD) | MutPy, PIT | `a + b` → `a` or `b` |
| Naked receiver | PIT | `x.strip()` → `x` |
| Parameter swap | Arcmutate | `foo(a, b)` → `foo(b, a)` |
| Chained call removal | Arcmutate | `obj.a().b()` → `obj.a()` |
| Self variable deletion (SVD) | MutPy | `self.x` → `x` |
| Member write removal | PIT, Arcmutate | Remove `self.x = val` |
| Constructor to None | PIT | `Foo()` → `None` |
| filter() removal | Arcmutate | `filter(fn, items)` → `items` |
| Regex mutation | Stryker weapon-regex | Mutate regex patterns |
| Return type-appropriate empty | PIT Empty Returns | `return items` → `return []` |

### Tier 3 — Niche or harder

| Operator | Source | Example |
|----------|--------|---------|
| Async/await removal | Novel | `await f()` → `f()` |
| Context manager bypass | Novel | Skip `with` block |
| Overriding method deletion (IOD) | MutPy | Remove method that overrides parent |
| super() call position change (IOP) | MutPy | Move super() from start to end |
| Variable replacement | Cosmic-Ray | Replace variable with another in scope |
| Walrus operator removal | Novel | `if (m := expr):` → `if expr:` |
| Star unpacking removal | Novel | `a, *b = items` → `a = items` |
| isinstance() negation | Novel | `isinstance(x, int)` → `not isinstance(x, int)` |
