# Spec Delta: Mutation Source Tracking

> RFC 2119 keywords apply. This document describes behavioral contracts that `mutmut/SPEC.md`
> and `mutmut-extras/SPEC.md` MUST include when branch `worktree-agent-afcf9355` is merged.
>
> Three decisions that were open in earlier drafts are resolved here explicitly. Where a decision
> could not be made from code alone, it is called out under Open Decisions.

---

## 1. Mutation Object Contract

### `source` field

- A `Mutation` MUST carry a `source: str` field identifying the operator or plugin that generated it.
- `source` MUST be set at construction time. The pipeline MUST NOT overwrite `source` after a `Mutation` is constructed.
- `source` is declared on a plain (non-frozen) `@dataclass`. The implementation does not prevent post-construction mutation. **The spec does not guarantee immutability** — the draft's "frozen dataclass" claim is factually wrong and is removed here.

### `source` value format

- `source` MUST be a non-empty string.
- `source` MUST consist only of printable ASCII characters. It MUST NOT contain whitespace (spaces, tabs, newlines, carriage returns). Reason: `source` values appear in NDJSON audit logs and `.meta` files where newlines corrupt the record.
- `source` SHOULD be the PyPI distribution name of the package providing the operator (e.g., `"mutmut-extras"`, `"my-org-mutations"`). Using the distribution name provides a globally unique, resolvable identifier with no additional coordination.
- `source` MUST be stable across runs for a given operator version and configuration. Changing `source` across runs without a version bump is a violation.
- The core MUST accept any conforming string. Core MUST NOT validate against a registry.

### `"builtin"` and `"unknown"` — reserved values

Two distinct reserved values are defined:

| Value | Meaning |
|---|---|
| `"builtin"` | Operator ships with the mutmut core package itself |
| `"unknown"` | Attribution was absent or failed to read at mutation creation time |

- `"builtin"` MUST be used only for operators that are part of the core package.
- Plugin operators MUST NOT use `"builtin"` as their source value.
- When `__mutmut_source__` is absent on the operator callable, core MUST use `"unknown"`, not `"builtin"`.
- When `__mutmut_source__` is present but is not a `str`, or is empty, core MUST use `"unknown"`.

**Bug in branch implementation:** The branch uses `"builtin"` as the fallback for missing attribution. This conflicts with the above contract. Before merge, the fallback MUST be changed to `"unknown"`.

---

## 2. Operator Attribution Protocol

### Core contract

- Operators MAY declare attribution by setting `__mutmut_source__` on the callable before returning from `mutmut_register_operators`.
- Core reads `__mutmut_source__` exactly once per operator, at mutation-creation time.
- Setting `__mutmut_source__` after `mutmut_register_operators` returns MUST NOT affect mutations already created.
- The core MUST NOT raise if `__mutmut_source__` is present but not a `str`.

### Known limitation: attribution failure for non-pure-Python callables (M5)

`func.__mutmut_source__ = value` silently fails for C extension functions and `functools.partial` objects — the attribute is not stored, and `getattr` subsequently returns `"unknown"`.

The core has no way to detect this failure. There is no exception and no warning. A plugin author who sets `__mutmut_source__` on a `partial`-wrapped operator gets `source="unknown"` silently.

**This is an accepted Known Limitation**, not a resolvable spec invariant. The spec states:

- `source` attribution is unreliable for operators that are not plain Python callables (C extensions, `functools.partial`, `functools.wraps`-decorated with `__wrapped__` pointing to a C function).
- The core SHOULD emit a `WARNING`-level log when it detects that `__mutmut_source__` was set on a callable but `getattr` did not return a `str`. However, detecting this requires checking before the set and after the get — the current implementation cannot detect it.
- Plugin authors SHOULD use plain Python `def` callables or attach attribution through a side-channel registry if using wrapped callables.

**Recommended fix** (not blocking spec ratification): Replace attribute-stamping with an explicit registry `dict[int, str]` keyed by `id(operator)`, populated by core during registration.

### `mutmut-extras` contract

- `mutmut-extras` MUST tag all 19 operators it registers with `source="mutmut-extras"` (via `__mutmut_source__`).
- All 19 operators registered by `mutmut-extras` MUST produce `Mutation.source == "mutmut-extras"`.

---

## 3. API Contract — BREAKING CHANGE ACCEPTED

**Decision:** The 2-tuple return type of `mutate_file_contents`, `combine_mutations_to_source`, and `function_trampoline_arrangement` is a breaking change. This is acceptable because the package is pre-publication with no external callers. The 3-tuple form is also a breaking change (see C2 in wave2-review-findings.md). The specified form is a **named result type** to prevent further breaks.

### Required: `MutationFileResult` named return type

Before merge, the return type of `mutate_file_contents` MUST be a `NamedTuple` (or `@dataclass`):

```python
class MutationFileResult(NamedTuple):
    mutated_code: str
    mutant_names: Sequence[str]
    source_by_name: dict[str, str]
```

- `mutate_file_contents` MUST return a `MutationFileResult`.
- `source_by_name` MUST contain an entry for every name in `mutant_names`. A partial mapping is a violation.
- `combine_mutations_to_source` and `function_trampoline_arrangement` MUST return analogous named types (not raw tuples).
- Callers that positionally unpack `code, names, source_by_name = result` are supported.
- Callers that unpack as `code, names = result` are **not supported**. This is a deliberate break from the pre-branch 2-tuple API.
- All internal callers (`__main__.py` and tests) MUST be updated before merge to use either positional 3-unpacking or named field access.

**Why not 3-tuple:** Raw tuples cannot be extended without breaking callers again. A `NamedTuple` allows `result.source_by_name` access and future field additions without positional breaks.

### `source_by_name` vs `source_by_key` key-space conversion

Two key formats exist:

| Map | Key format | Example |
|---|---|---|
| `source_by_name` (from `mutate_file_contents`) | Mangled trampoline name — short form | `"MyClass.__init___mutmut_0"` |
| `source_by_key` (in `.meta` persistence) | Fully-qualified mutant name | `"my_module.MyClass.__init___mutmut_0"` |

- The conversion from short-form to qualified-form is the caller's responsibility (`__main__.py`).
- The conversion algorithm MUST use the same logic as `get_mutant_name(filename, mutant_name)`.
- After conversion, every key in `source_by_key` MUST also be present in `exit_code_by_key`. An entry in `exit_code_by_key` without a corresponding `source_by_key` entry is a violation.

---

## 4. `mutmut_mutations_created` Hook Contract

New hookspec:

- `mutmut_mutations_created` MUST be called after all mutations for a file are assembled, before the function returns.
- Parameters: `filename: str`, `attribution_by_mutant_name: dict[str, str]`.
- `attribution_by_mutant_name` MUST contain an entry for every mutant name that will be written to the mutated file.
- `mutmut_mutations_created` MUST be called at most once per file per run.
- `mutmut_mutations_created` MUST NOT be called if no mutations were generated for the file.

**Pre-filter vs post-filter:** `mutmut_filter_mutations` is not called inside `mutate_file_contents`; filtering happens in the caller. Therefore `attribution_by_mutant_name` passed to `mutmut_mutations_created` reflects **pre-filter** mutations. Some names in `attribution_by_mutant_name` MAY not survive to the final mutant file if filtered after this hook fires. The spec acknowledges this; plugins MUST NOT assume all names in `attribution_by_mutant_name` produce surviving mutants.

**Parameter naming bug:** The hookspec docstring and parameter name in the branch implementation say "maps mutant name → mutated source code," which is wrong. The parameter maps mutant name → attribution string. The parameter MUST be renamed to `attribution_by_mutant_name` before merge.

---

## 5. Persistence Contract

### New `.meta` file field

- `.meta` files MUST include a `source_by_key` top-level key: a `dict[str, str]` mapping fully-qualified mutant names to attribution strings.
- `source_by_key` MUST have an entry for every key in `exit_code_by_key`.
- Entries MUST be populated at mutant creation time.

### Forward compatibility (new mutmut reading old `.meta` files)

- When `source_by_key` is absent in a loaded `.meta` file, `SourceFileMutationData.load()` MUST default `source_by_key` to `{}` without raising an error.

### Backward compatibility — explicit break accepted (L3)

**Decision:** Old mutmut versions cannot read `.meta` files produced by this version. This is an explicit, accepted break.

Reason: Old `SourceFileMutationData.load()` contains `assert not meta` after popping all known keys. A `.meta` file written by this version includes `source_by_key`, which old code never pops; the assertion fires and crashes.

The spec mandates:

- A `meta_format_version: int` field MUST be added to `.meta` files. Its value for this version is `2`. The pre-branch format is `1` (implicitly, by absence of the field).
- Loaders MUST check `meta_format_version` before processing. A loader that does not understand a version MUST raise a descriptive error (`MetaFormatVersionError` or equivalent), not an `AssertionError`.
- Users who downgrade mutmut after running with this version will see a clear error, not a confusing assertion failure.

---

## 6. Reporting Contract

### `source_by_key` is a stable public API

- `source_file_mutation_data.source_by_key` is a **stable public API**.
- Plugins accessing `source_by_key` inside `mutmut_post_run` are supported. The dict MUST contain an entry for every key in `exit_code_by_key` at the time `mutmut_post_run` is called.
- No built-in CLI reporting for per-operator stats is provided by this version. The spec MUST NOT promise any such command.
- The stated primary benefit of this feature (per-operator kill/survival rates) is achievable by plugins reading `source_by_key` in `mutmut_post_run`. Core reporting is not in scope for this merge.

---

## 7. Known Limitations

- **`source` tracks primary attribution only.** When `mutmut-dedup` is active and two operators independently generate semantically identical mutations for the same site, dedup discards all but the first. The surviving mutation's `source` reflects only the operator that ran first. Per-operator kill rates derived from `source_by_key` undercount operators whose mutations overlap with earlier operators. There is no multi-source attribution mechanism.
- **Attribution is unreliable for non-pure-Python callables.** See M5 note in Section 2.
- **`source` is not validated by core.** An operator can set `__mutmut_source__ = ""` and the core will substitute `"unknown"`, but there is no validation that the value is a valid PyPI name or that it is globally unique.
- **Pre-filter hook timing.** `attribution_by_mutant_name` in `mutmut_mutations_created` reflects pre-filter mutations (see Section 4).

---

## 8. Open Decisions

These items require explicit resolution before merge but were not resolvable from the codebase alone:

1. **`source` field in `Mutation` dataclass — should `frozen=True` be added?** The current implementation is a plain mutable dataclass. Adding `frozen=True` would enforce the spec's intended immutability but requires verifying no code assigns to `original_node`, `mutated_node`, or `contained_by_top_level_function` after construction. Low risk, high value.

2. **Source string validation — should core raise or warn on empty string?** Currently no validation. If an operator provides `""`, the core substitutes `"unknown"`. A `ValueError` at registration time would be safer. Low controversy.

3. **`mutmut_mutations_created` — should it be renamed?** The current name is misleading (sounds like it fires when mutations are registered). A name like `mutmut_mutations_assembled` or `mutmut_file_mutations_ready` more clearly signals post-assembly timing. Rename before merge is low cost.

---

## 9. Bugs in Branch Implementation

| ID | Severity | Location | Description |
|---|---|---|---|
| C2 | CRITICAL | `file_mutation.py` — three functions | Raw 3-tuple return breaks all callers with `ValueError: too many values to unpack`. Must be replaced with `MutationFileResult` NamedTuple before merge. |
| FALLBACK | HIGH | `file_mutation.py` | Default `source` fallback is `"builtin"` instead of `"unknown"`. Violates the reserved-value contract. Must be changed before merge. |
| DOCSTRING | HIGH | `hookspecs.py:mutmut_mutations_created` | Docstring and parameter name say "mutated source code" — actually attribution string. Must be corrected; parameter must be renamed to `attribution_by_mutant_name`. |
| M5 | MEDIUM | `mutmut-extras/plugin.py:_tag_operators` | `func.__mutmut_source__ = source` silently fails for C extensions and `functools.partial`. No warning emitted. Accepted as Known Limitation; SHOULD emit WARNING if detectable. |
| L3 | LOW | `__main__.py:SourceFileMutationData.load()` | Old mutmut `assert not meta` crashes reading new `.meta`. Resolved by `meta_format_version` field (Section 5). |
| GAP | MEDIUM | `collect_stat`, `calculate_summary_stats` | `source_by_key` is persisted but unused in stat calculations. Per-operator reporting is not implemented. Deferred to a future version; not a merge blocker. |
