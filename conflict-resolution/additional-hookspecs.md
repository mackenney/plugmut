# Additional hookspecs patch

## What changed

Added 6 hook specifications to `mutmut/src/mutmut/hookspecs.py`:

- `mutmut_configure(config)` — called after config loading
- `mutmut_register_commands(cli_group)` — called at module load to register CLI commands
- `mutmut_filter_mutations(filename, mutations)` — called after mutation generation
- `mutmut_post_test(mutant_name, exit_code, status, duration)` — called after each test result
- `mutmut_post_run(source_file_mutation_data)` — called after all tests complete
- `mutmut_mutations_created(filename, source_tag_by_mutant_name)` — called after mutations are written

## Hook call sites patched

| Hook | File | Location |
|------|------|----------|
| `mutmut_configure` | `__main__.py` | `ensure_config_loaded()`, after `load_config()` |
| `mutmut_register_commands` | `__main__.py` | Module-level `_register_plugin_commands()`, after all built-in commands |
| `mutmut_filter_mutations` | `file_mutation.py` | `create_mutations()`, after visitor runs |
| `mutmut_mutations_created` | `file_mutation.py` | `mutate_file_contents()`, after `combine_mutations_to_source()` |
| `mutmut_post_test` | `__main__.py` | `SourceFileMutationData.register_result()`, after saving |
| `mutmut_post_run` | `__main__.py` | End of `_run()`, after all results printed |

## Why this couldn't be done via plugin

These are the hook *definitions* and *call sites* — they extend mutmut's plugin system itself. Plugins can only implement hooks that already exist in the host. Without these specs, plugins cannot receive lifecycle events beyond operator registration.

## `create_mutations()` signature change

`create_mutations()` gained a `filename` keyword argument (default `""`) to pass through to `mutmut_filter_mutations`. The only call site in `mutate_file_contents()` already has the filename available.

## How to resolve conflicts

### hookspecs.py
Upstream only has `mutmut_register_operators`. Our patch adds 6 more specs to `MutmutHookSpec`. If upstream adds their own hooks, merge both sets — names shouldn't conflict since these follow the `mutmut_` prefix convention.

We also added a `-> OPERATORS_TYPE` return type annotation to the existing `mutmut_register_operators` hookspec, importing `OPERATORS_TYPE` from `node_mutation.py`. If upstream adds their own return annotation that conflicts, keep whichever is more specific.

### file_mutation.py
Two changes:
1. `create_mutations()` signature gains `filename=""` parameter and calls `mutmut_filter_mutations` after the visitor.
2. `mutate_file_contents()` calls `mutmut_mutations_created` after combining mutations.

If upstream modifies `create_mutations` or `mutate_file_contents`, re-apply the hook calls at the same logical points (after mutation generation, after source combination).

### __main__.py
Four insertion points. If upstream refactors:
- `mutmut_configure`: find where config is first loaded and call hook after
- `mutmut_register_commands`: find CLI group definition and call hook at module level after all commands
- `mutmut_post_test`: find where test exit codes are recorded (currently `register_result`) and call after
- `mutmut_post_run`: find end of the main run loop and call after stats are printed
