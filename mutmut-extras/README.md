# mutmut-extras

Extra mutation operators for [plugmut]({{REPO_URL}}).

mutmut-extras registers 19 additional mutation operators into plugmut, targeting AST patterns
the built-in operator set does not cover. Each operator is independently composable with other
plugin packages and activates automatically on installation.

## Installation

```bash
pip install mutmut-extras
```

The plugin registers automatically via plugmut's entry-point system — no configuration needed.

## Operators

| Operator | Description |
|---|---|
| `return_none` | Replaces non-`None` return values with `return None` |
| `exception_handler` | Replaces except-handler bodies with `pass` |
| `ternary` | Mutates `x if cond else y` — yields true-branch, false-branch, and swapped branches (3 mutations) |
| `assert_true` | Replaces assert test expressions with `True` |
| `slice_removal` | Removes individual slice components (`lower`, `upper`, `step`) one at a time |
| `void_call_removal` | Replaces standalone (void) function-call statements with `pass` |
| `yield_mutation` | Mutates `yield expr` → `yield None`; bare `yield` → `yield 0` |
| `comprehension_filter` | Removes all `if` clauses from comprehension `for` nodes |
| `super_call_deletion` | Replaces bare `super().method(...)` call statements with `pass` |
| `fstring_mutation` | Replaces f-string interpolation expressions `{expr}` with `{'XX'}` |
| `function_deletion` | Replaces function bodies with `pass` (sync, async, methods, nested) |
| `default_param_mutation` | Mutates `None` defaults → `0` and non-builtin name defaults → `None` |
| `reverse_iteration` | Wraps for-loop iterables with `reversed(iterable)` |
| `startswith_endswith_swap` | Swaps `.startswith()` ↔ `.endswith()` method calls |
| `strip_to_partial` | Replaces `.strip()` with `.lstrip()` and `.rstrip()` (2 mutations) |
| `operand_swap` | Swaps operands in non-commutative binary operations (`-`, `/`, `//`, `%`, `**`) |
| `remove_boundary_offset` | Removes `±1` from boundary expressions (`expr + 1`, `expr - 1`, `1 + expr`) |
| `exception_type_broadening` | Broadens exception types to `Exception` in except clauses |
| `exception_control_flow` | Replaces `pass` in except handlers with `break`, `continue`, or `return` (3 mutations) |

## Usage

Install alongside plugmut and run normally. Operators register automatically.

```bash
plugmut run
```

## Documentation

See [SPEC.md](SPEC.md) for detailed operator contracts, behavioral invariants, and known limitations.

Source repository: {{REPO_URL}}

## License

{{LICENSE}}
