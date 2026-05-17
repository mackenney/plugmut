# Conflict Resolution: register-operators caching

## What Changed

Module-level caching of `mutmut_register_operators` results in `file_mutation.py`,
plus a warm call in `__main__.py:create_mutants()` before `Pool()`.

### file_mutation.py
- Added module-level `_plugin_operators` cache and `get_plugin_operators()` /
  `reset_plugin_operators()` functions.
- Replaced the `for plugin_operators in pm.hook.mutmut_register_operators()`
  loop inside `create_mutations()` with a single `get_plugin_operators()` call.

### __main__.py
- Added `get_plugin_operators()` call in `create_mutants()` before `Pool()`
  to populate cache in parent process (children inherit via fork).

## Why It Couldn't Be Done Via Plugin

This is a core lifecycle bug — the `mutmut_register_operators` hook fires once
per source file (inside `create_mutations()`) instead of once per run. No plugin
can fix the frequency of its own invocation; only the core controls where/when
it calls the hook.

## How to Resolve Upstream Conflicts

### If upstream modifies `create_mutations()` operator collection (lines ~153-158):
Our change removes the `for` loop and replaces it with `get_plugin_operators()`.
Take upstream's collection logic but place it inside `get_plugin_operators()` instead
of inline in `create_mutations()`.

### If upstream modifies `create_mutants()` in __main__.py:
Our addition is a 2-line warm call before `Pool()`. Re-apply it before whatever
pool/multiprocessing construct upstream uses.

### If upstream independently fixes the per-file invocation bug:
Compare approaches. Prefer upstream's fix. Drop our patch. Keep
`reset_plugin_operators()` if it's used by test fixtures (search for it).

### If upstream changes `OPERATORS_TYPE`:
Update the `_plugin_operators` type annotation to match.
