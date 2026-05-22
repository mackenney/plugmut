# Changelog

All notable changes to mutmut-extras will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.1] - 2026-05-17

### Added
- Initial release with 19 mutation operators
- Plugin integration via `mutmut_register_operators` hook
- `return_none`: replaces non-None return values with `None`
- `exception_handler`: replaces exception handler body with `pass`
- `ternary`: three mutations per ternary — true branch, false branch, swapped branches
- `assert_true`: replaces assert test with `True`
- `slice_removal`: removes individual slice components (`lower`, `upper`, `step`)
- `void_call_removal`: replaces bare function call statements with `pass`
- `yield_mutation`: mutates `yield expr` to `yield None` and bare `yield` to `yield 0`
- `comprehension_filter`: removes all `if` clauses from comprehension `for` nodes
- `super_call_deletion`: replaces `super().method(...)` statements with `pass`
- `fstring_mutation`: replaces f-string interpolation expressions with `'XX'`
- `function_deletion`: replaces function body with `pass`
- `default_param_mutation`: mutates `None` defaults to `0` and non-builtin name defaults to `None`
- `reverse_iteration`: wraps `for` loop iterables with `reversed()`
- `startswith_endswith_swap`: swaps `.startswith()` and `.endswith()` calls
- `strip_to_partial`: replaces `.strip()` with `.lstrip()` and `.rstrip()`
- `operand_swap`: swaps operands of non-commutative binary operators (`-`, `/`, `//`, `%`, `**`)
- `remove_boundary_offset`: removes `+1`/`-1` boundary offsets
- `exception_type_broadening`: broadens exception types to `Exception`
- `exception_control_flow`: replaces `pass`-body exception handlers with `break`, `continue`, or `return`
