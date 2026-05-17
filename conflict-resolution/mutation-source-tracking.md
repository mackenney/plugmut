# Mutation source tracking patch

## What changed

Added a `source` field to the `Mutation` dataclass and threaded it through the entire mutation pipeline, from operator registration to `.meta` file persistence.

## Why it couldn't be done via plugin

The `Mutation` dataclass is defined in `mutmut/src/mutmut/file_mutation.py` and instantiated in `MutationVisitor._create_mutations()`. There is no hook that allows plugins to attach metadata to `Mutation` objects at creation time. The `source` field must exist on the dataclass itself and be populated during the `_create_mutations` loop where the operator reference is available.

Similarly, the `.meta` file format is owned by `SourceFileMutationData` in `__main__.py` — no plugin hook exists to extend it.

## Files modified

### `mutmut/src/mutmut/file_mutation.py`

1. **`Mutation` dataclass (line ~80):** Added `source: str = "builtin"` field. Default preserves backward compatibility.

2. **`MutationVisitor._create_mutations()` (line ~210):** Reads `__mutmut_source__` attribute from operator callables via `getattr(operator, "__mutmut_source__", "builtin")`. Passes source to `Mutation` constructor.

3. **`mutate_file_contents()` (line ~87):** Return type is now `MutationResult` — a `NamedTuple` with fields `mutated_code`, `mutant_names`, and `source_by_name`. The NamedTuple allows callers to unpack two or three fields without breaking the old 2-field positional pattern. Also passes `source_by_name` to `mutmut_mutations_created` hook instead of empty strings.

   ```python
   class MutationResult(NamedTuple):
       mutated_code: str
       mutant_names: Sequence[str]
       source_by_name: dict[str, str]
   ```

4. **`combine_mutations_to_source()` (line ~280):** Return type changed from `tuple[str, Sequence[str]]` to `tuple[str, Sequence[str], dict[str, str]]`. Collects source-by-name from `function_trampoline_arrangement`.

5. **`function_trampoline_arrangement()` (line ~340):** Return type changed from `tuple[Sequence[...], Sequence[str]]` to `tuple[Sequence[...], Sequence[str], dict[str, str]]`. Builds source mapping from `mutant.source`.

### `mutmut/src/mutmut/__main__.py`

1. **`SourceFileMutationData.__init__()` (line ~370):** Added `self.source_by_key: dict[str, str] = {}`.

2. **`SourceFileMutationData.load()` (line ~381):** Reads `source_by_key` from meta with `meta.pop("source_by_key", {})`. The default `{}` ensures backward compatibility with old `.meta` files that lack this key.

3. **`SourceFileMutationData.save()` (line ~424):** Writes `source_by_key` to the JSON dump.

4. **`write_all_mutants_to_file()` (line ~361):** Updated to unpack 3-tuple from `mutate_file_contents` and return `(mutant_names, source_by_name)`.

5. **`create_mutants_for_file()` (line ~299):** Updated to receive `source_by_name` and populate `source_file_mutation_data.source_by_key`.

## How to resolve conflicts

### If upstream modifies `Mutation` dataclass
Add the `source: str = "builtin"` field after whatever upstream changes. The default value ensures it's non-breaking.

### If upstream modifies `_create_mutations`
Re-add the `source = getattr(operator, "__mutmut_source__", "builtin")` line and pass `source=source` to the `Mutation` constructor.

### If upstream changes return types of `mutate_file_contents`, `combine_mutations_to_source`, or `function_trampoline_arrangement`
`mutate_file_contents` returns `MutationResult` (NamedTuple). If upstream changes its return type, convert `MutationResult` to match the new shape, keeping `source_by_name` as the last field. The NamedTuple class lives in `file_mutation.py` alongside `Mutation`.

`combine_mutations_to_source` and `function_trampoline_arrangement` return plain 3-tuples — re-add `source_by_name` as the third element if upstream drops it.

### If upstream changes `.meta` format or `SourceFileMutationData`
Ensure `source_by_key` is included in save/load. The `meta.pop("source_by_key", {})` pattern in `load()` handles backward compatibility with old files.

### Test files
All callers of `mutate_file_contents` and `function_trampoline_arrangement` in tests were updated to unpack the additional return value. If upstream adds new callers, they need the extra `_` in the unpacking.

## Protocol for plugin authors

To tag mutations with a custom source, set `__mutmut_source__` on operator callables before returning them from `mutmut_register_operators`:

```python
def my_operator(node):
    ...

my_operator.__mutmut_source__ = "my-plugin"
```

Operators without this attribute default to `source="builtin"`.
