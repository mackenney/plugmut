# Spec Delta: Mutation Source Tracking (mutmut core + extras)

> RFC 2119 keywords apply. This document describes the behavioral contracts that would need to
> be added to `mutmut/SPEC.md` and `mutmut-extras/SPEC.md` if branch `worktree-agent-afcf9355`
> were merged.

---

## Mutation Object Contract Changes

Additions to `mutmut/SPEC.md` under the Mutation dataclass section:

- A `Mutation` MUST carry a `source: str` field identifying which operator or plugin generated it.
- The `source` field default value MUST be `"builtin"` for any operator that does not declare attribution.
- `source` MUST be immutable after `Mutation` construction — it is part of the frozen dataclass.
- `source` MUST be set at mutation-creation time, not retroactively. The pipeline MUST NOT overwrite `source` after a `Mutation` is created.
- The `source` field is an opaque attribution string. The spec does not impose a format, namespace, or length constraint beyond: it MUST be a non-empty string.
- The value `"builtin"` is reserved for operators that ship with the core. Plugin operators SHOULD NOT use `"builtin"` as their source value.

---

## Source Attribution Contract

- `source` represents the operator or plugin package responsible for generating a mutation. It is a short, human-readable identifier (e.g., `"builtin"`, `"mutmut-extras"`, `"my-org-plugin"`).
- The contract does NOT specify: versioning, namespacing, uniqueness guarantees across plugins, or any structure beyond non-empty string.
- Two mutations produced by the same operator callable MUST have the same `source` value.
- The source value MUST be stable across runs for a given operator: a plugin that produces `"mutmut-extras"` on one run MUST NOT produce `"my-extras"` on the next run without a version bump or reconfiguration.
- The `source` field is not validated by the core. Core MUST accept any non-empty string.

**Open question**: Should core validate that `source` is non-empty and raise `ValueError` if an operator provides `""`? Currently no validation exists — an operator can set `__mutmut_source__ = ""` and get through.

---

## Operator Registration Contract Changes

Additions to `mutmut/SPEC.md` under the Plugin Operator Protocol section, and to `mutmut-extras/SPEC.md`:

### Core (mutmut)

- Operators MAY declare their attribution by setting a `__mutmut_source__` string attribute on the callable before it is returned from `mutmut_register_operators`.
- If `__mutmut_source__` is absent or unreadable via `getattr`, the core MUST fall back to `source="builtin"`.
- The core reads `__mutmut_source__` exactly once per operator, at mutation-creation time. Mutating the attribute after `mutmut_register_operators` returns MUST NOT affect mutations already created.
- The core MUST NOT crash if `__mutmut_source__` is present but not a `str` — behavior is unspecified but MUST NOT raise `AttributeError`.

**Bug (M5):** The protocol uses `func.__mutmut_source__ = value` attribute assignment. This silently fails for operators implemented as C extension functions or `functools.partial` objects — the attribute is silently lost and `source` falls back to `"builtin"`. No exception is raised, and no warning is emitted. This is a correctness hole: a plugin author who sets `__mutmut_source__` on a `partial`-wrapped operator will silently get wrong attribution.

**Recommended fix**: Use a separate `dict[int, str]` registry keyed by `id(func)` inside the core, populated at registration time, avoiding attribute mutation on the callable.

### mutmut-extras

- `mutmut-extras` MUST tag all operators it registers with `__mutmut_source__ = "mutmut-extras"` before returning from `mutmut_register_operators`.
- All 19 operators registered by `mutmut-extras` MUST produce `Mutation.source == "mutmut-extras"`.

---

## API Contract

**BREAKING CHANGE (C2):** This branch changes three public function signatures in `mutmut/src/mutmut/file_mutation.py`:

| Function | Old return type | New return type |
|---|---|---|
| `mutate_file_contents` | `tuple[str, Sequence[str]]` | `tuple[str, Sequence[str], dict[str, str]]` |
| `combine_mutations_to_source` | `tuple[str, Sequence[str]]` | `tuple[str, Sequence[str], dict[str, str]]` |
| `function_trampoline_arrangement` | `tuple[Sequence[...], Sequence[str]]` | `tuple[Sequence[...], Sequence[str], dict[str, str]]` |

The third element is a `dict[str, str]` mapping mutant function name (the mangled trampoline name, not the full qualified key) to its source attribution string.

**Required spec contract (if this API is accepted):**

- `mutate_file_contents` MUST return a 3-tuple: `(mutated_code, mutant_names, source_by_name)`.
- `source_by_name` MUST contain an entry for every name in `mutant_names`. The spec MUST NOT be weaker than this — a partial mapping is a violation.
- `combine_mutations_to_source` MUST return a 3-tuple with the same `source_by_name` guarantee.
- `function_trampoline_arrangement` MUST return a 3-tuple; `source_by_name` keys MUST exactly match the names in the returned `mutant_names`.
- Callers MUST be able to ignore the third element (`_code, names, _ = mutate_file_contents(...)`) without behavior change.

**Unresolved API design issue (C2):** Raw tuple return breaks all existing callers with `ValueError: too many values to unpack`. The recommended fix per wave2-review-findings.md is a `NamedTuple` or `@dataclass` result object. Until that is resolved, this spec delta cannot be finalized because the stable API shape is not determined.

---

## Backward Compatibility Contract

### Forward compatibility (new code reading old data)

- `SourceFileMutationData.load()` MUST tolerate `.meta` files written by older versions that lack `source_by_key`. When the key is absent, `source_by_key` MUST default to `{}`.
- This is implemented via `meta.pop("source_by_key", {})`.

### Backward compatibility (old code reading new data) — BROKEN

**Bug (L3):** `SourceFileMutationData.load()` in older mutmut versions contains `assert not meta` after popping all known keys. A `.meta` file written by this branch includes `source_by_key`, which old code never pops. The `assert not meta` fires, crashing with:

```
AssertionError: Meta file contains unexpected keys: {'source_by_key'}
```

This means users who run new mutmut to generate `.meta` files, then attempt to downgrade or use a mixed-version setup, will have their meta files become unreadable.

**Required spec contract (if backward compat is to be guaranteed):**
- `.meta` files written by this version MUST be readable by the immediately prior version of mutmut without modification. This requires either: (a) removing the `assert not meta` assertion from all prior versions (upstream change), or (b) writing `source_by_key` to a separate file, or (c) documenting this as an explicit break and incrementing a meta format version.
- Currently none of (a), (b), or (c) are implemented. The spec MUST either accept the incompatibility explicitly or mandate a migration path.

---

## Persistence Contract

Additions to `mutmut/SPEC.md` under the `.meta` file format section:

- `.meta` files MUST include a `source_by_key` top-level key containing a `dict[str, str]` mapping fully-qualified mutant names to attribution strings.
- `source_by_key` MUST have an entry for every key in `exit_code_by_key`. Entries MUST be populated at mutant creation time, not lazily.
- When `source_by_key` is absent in a loaded `.meta` file (old file), `source_by_key` MUST default to `{}` and NOT raise an error.

**Open question (meta format version):** There is no meta format version field. Adding `source_by_key` is a forward-compatible change (new reads old: fine). But old reads new is broken (L3). Should a `meta_format_version` key be added to detect and handle this?

---

## Hook Contract Changes

New `mutmut_mutations_created` hookspec:

- After all mutations are created for a file and the filter hook has run, `mutmut_mutations_created` MUST be called with:
  - `filename: str` — the source file path
  - `source_by_mutant_name: dict[str, str]` — mapping of mangled mutant name to attribution string
- `mutmut_mutations_created` MUST be called at most once per file per run.
- `mutmut_mutations_created` MUST NOT be called if `mutant_names` is empty (no mutations generated for the file).
- The `source_by_mutant_name` dict passed to the hook MUST be consistent with the one returned by `mutate_file_contents` for the same file.

**Bug — Hook docstring mismatch:** The hookspec docstring reads:
```
source_by_mutant_name maps mutant name -> mutated source code.
```
This is wrong. `source_by_mutant_name` maps mutant name → operator attribution string (e.g., `"builtin"`, `"mutmut-extras"`), not to source code. The parameter name itself is misleading. A corrected name would be `attribution_by_mutant_name` or `operator_by_mutant_name`.

---

## Reporting Contract

**Partially implemented.** `SourceFileMutationData` persists `source_by_key`. However:

- No per-operator kill/survival reporting is exposed via CLI, stats output, or any public API.
- `collect_stat()` and `calculate_summary_stats()` do not use `source_by_key`.
- The data is collected and persisted but not surfaced. The primary stated benefit of this feature ("per-operator kill/survival reporting") is not implemented.

**Required contracts if reporting is to be specified:**

- The spec SHOULD guarantee that `source_by_key` is accessible to plugins via `mutmut_post_run` hook's `source_file_mutation_data` argument.
- The spec MUST NOT promise any built-in CLI reporting command for per-operator stats unless one is implemented.

**Open question:** Is `source_by_key` data considered a stable public API that plugins can rely on? If a plugin reads `source_file_mutation_data.source_by_key` in `mutmut_post_run`, is that a supported use case?

---

## Open Questions

1. **API shape**: Should `mutate_file_contents` return a `NamedTuple`/`dataclass` result instead of a raw 3-tuple? This determines the stable API contract and prevents future breaks. (Blocks finalizing the API contract section above.)

2. **Source string validation**: Should core validate that `source` is non-empty? Should it warn if a plugin uses `"builtin"`?

3. **Attribute-stamping fragility (M5)**: The `__mutmut_source__` protocol silently fails for C extensions and `functools.partial`. Should the spec mandate a side-channel registry, or explicitly accept silent fallback to `"builtin"`?

4. **Backward compatibility guarantee**: Is breaking old mutmut's ability to read new `.meta` files (L3) an acceptable trade-off? If yes, should a `meta_format_version` be added?

5. **Reporting surface**: Per-operator reporting is the stated rationale for the feature but is not implemented. Is reporting in scope for this merge, or is persistence sufficient for now?

6. **`mutmut_mutations_created` semantics**: The hook name and docstring are misleading (claims to provide "mutated source code" but provides attribution). Should it be renamed or the docstring corrected before merge?

---

## Bugs / Inconsistencies in Branch Implementation

| ID | Severity | Location | Description |
|---|---|---|---|
| C2 | CRITICAL | `file_mutation.py` — `mutate_file_contents`, `combine_mutations_to_source`, `function_trampoline_arrangement` | Breaking API: 2-tuple → 3-tuple. All existing callers break with `ValueError: too many values to unpack`. No result object wrapping. |
| M5 | MEDIUM | `mutmut-extras/plugin.py:_tag_operators` | `func.__mutmut_source__ = source` silently fails for C extension callables and `functools.partial`. No fallback warning. |
| L3 | LOW | `mutmut/__main__.py:SourceFileMutationData.load()` | `assert not meta` in old mutmut crashes when reading new `.meta` file containing `source_by_key`. Forward compat is fine; backward compat is broken. |
| BUG | LOW | `mutmut/src/mutmut/hookspecs.py:mutmut_mutations_created` | Docstring says "maps mutant name -> mutated source code" — actually maps to attribution string. Misleading parameter name. |
| GAP | MEDIUM | `__main__.py:collect_stat`, `calculate_summary_stats` | `source_by_key` is persisted but not used in any stat calculation or CLI output. Core use case (per-operator kill rate) is unimplemented. |
