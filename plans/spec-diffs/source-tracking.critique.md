# Adversarial Critique: Source Tracking Spec Delta

## Source Field Format Underspecified

The spec declares `source` an "opaque attribution string" with a single constraint: non-empty string. This is too loose to be a useful contract.

**Problems:**
- No character set constraint. Is `"my plugin\nv2"` valid? A newline in a source field would corrupt NDJSON reporting.
- No length limit. A 10 MB docstring as the source value satisfies the spec.
- No namespace or collision-prevention convention. Two unrelated plugins can independently choose `"extras"` and produce indistinguishable attributions. The spec recommends using package distribution name (e.g., `"mutmut-extras"`) as an example but does NOT mandate it. Two implementations could produce `"mutmut_extras"` vs `"mutmut-extras"` — both satisfy "non-empty string."
- "Stable across runs" is vague. Stable across what? Python version changes? Plugin reinstalls? Config changes? The spec gives one example (`"mutmut-extras"` → `"my-extras"` is not stable) but doesn't define the stability domain.

**Required fix:** The spec must state the permitted character set (printable Unicode? ASCII only?), length bound (or explicitly disclaim one), and collision-prevention convention (SHOULD use the PyPI distribution name; MUST NOT include whitespace?). Without this, two conforming implementations of the same operator can produce different `source` values for identical mutations.

---

## API Backward Compat Contract Contradicts Itself

The spec simultaneously states MUST requirements for the 3-tuple return type AND admits the API is unresolved:

> "Required spec contract (if this API is accepted): `mutate_file_contents` MUST return a 3-tuple…"
> "Unresolved API design issue (C2): … Until that is resolved, this spec delta cannot be finalized because the stable API shape is not determined."

These cannot coexist in a spec. MUST statements in parenthetical "if this API is accepted" form are not spec invariants — they are notes. A spec that says "MUST do X (if we decide to do X)" provides zero behavioral guarantee.

**Required fix:** Make the decision:
- (a) Adopt NamedTuple/dataclass result, spec the type and its fields, remove all 3-tuple language, OR
- (b) Explicitly defer the entire API Contract section until the decision is made (remove all MUST statements about tuple shape)

The current state is worse than having no API spec — it creates false confidence in a contract that has explicitly not been decided.

Callers MUST be able to ignore the third element (`_code, names, _ = ...`) — this implies a raw tuple is fine. But the NamedTuple approach allows `result.source_by_name` access without positional unpacking, which is more forward-compatible. Pick one.

---

## "builtin" Has Two Irreconcilable Meanings

The spec says `"builtin"` is:
1. The value for "operators that ship with the core"
2. The fallback when `__mutmut_source__` is absent or unreadable

M5 adds a third case: `__mutmut_source__` was SET by the plugin but the attribute assignment silently failed (C extensions, `functools.partial`). The `getattr(operator, "__mutmut_source__", "builtin")` call succeeds and returns `"builtin"` — indistinguishable from case 1 or 2.

Any per-operator reporting built on `source` cannot tell apart:
- A core builtin operator (legitimately `"builtin"`)
- A plugin operator that didn't bother setting attribution (ambiguously `"builtin"`)
- A plugin operator whose `__mutmut_source__` assignment silently failed (incorrectly `"builtin"`)

The spec acknowledges M5 as a bug but then writes a MUST contract (`MUST fall back to "builtin"`) that bakes this ambiguity into the behavioral contract. Normalizing a bug into a spec invariant is not a resolution.

**Required fix:** Either:
- Reserve `"builtin"` strictly for core operators and define a distinct fallback (e.g., `"unknown"`) for failed/absent attribution, OR
- Explicitly state in the spec that `"builtin"` is semantically overloaded, `source` cannot reliably identify failed attribution, and per-operator reporting has a known false-negative class for this case

The spec currently does neither.

---

## Multiple-Source Ambiguity Unaddressed

The spec states: "Two mutations produced by the same operator callable MUST have the same source value." It says nothing about the inverse: mutations from DIFFERENT operators that happen to be identical.

The dedup phase (`mutmut-dedup`) removes duplicate mutations by retaining the first occurrence and discarding the rest. When two operators (e.g., a core builtin and `mutmut-extras`) independently produce semantically identical mutations for the same node, dedup keeps one. The surviving mutation's `source` field reflects only one operator — the one that ran first. The other operator's contribution is silently lost.

Per-operator kill rates derived from `source_by_key` are therefore systematically undercounted for operators that generate overlapping mutations with core builtins.

**Verdict:** This is not just an implementation gap — it is a fundamental limitation of single-`source` attribution when dedup is active. The spec MUST acknowledge it as a Known Limitation and explicitly disclaim that `source` tracks primary attribution only, not exhaustive attribution.

---

## Reporting Contract Is Entirely Negative

The reporting section specifies only what is NOT implemented:
- "No per-operator kill/survival reporting is exposed via CLI"
- "collect_stat() and calculate_summary_stats() do not use source_by_key"

What IS specified:
- "The spec SHOULD guarantee that source_by_key is accessible to plugins via mutmut_post_run"
- "The spec MUST NOT promise any built-in CLI reporting command"

This is the anti-pattern of a spec: describing what something doesn't do without specifying what it does. The code shows `source_by_key` IS populated and persisted. Whether it is a stable public API for plugins is left as an open question. A public field that exists in the code but has no spec contract is worse than no field — it invites plugin authors to depend on it without any guarantee.

**Required:** The spec must explicitly state one of:
- `source_file_mutation_data.source_by_key` is a STABLE public API accessible in `mutmut_post_run`; plugins MAY read it, and the dict MUST contain an entry for every key in `exit_code_by_key`, OR
- `source_by_key` is an INTERNAL implementation detail; plugins MUST NOT read it directly; no stability guarantee exists

The current "open question" treatment is not acceptable in a spec intended for external plugin authors.

---

## Meta File Backward Compat Not Decided

The spec documents the L3 problem clearly:
> "The spec MUST either accept the incompatibility explicitly or mandate a migration path."

Then the draft does neither. Listing three fix options (a/b/c) and reporting that none are implemented is a bug report, not a spec contract. The draft author has correctly identified what the spec must decide, then deferred the decision.

**Specific gap:** The draft says the `.meta` format MUST include `source_by_key`. But if old mutmut `assert not meta` fires when reading new files, then the MUST on writing `source_by_key` is directly incompatible with the backward compat requirement. The spec cannot mandate both writing the field and supporting old readers without choosing one of options (a), (b), or (c).

**Required:** Force the decision and remove the conditional language. The spec cannot be finalized while this is "unresolved."

---

## Attribution Failure Silently Misrepresented As Success

The spec says: "If `__mutmut_source__` is absent or unreadable via `getattr`, the core MUST fall back to `source='builtin'`."

The M5 failure mode is NOT a `getattr` failure. The sequence is:
1. Plugin calls `func.__mutmut_source__ = "my-plugin"` — **this line silently fails** for C extensions and `functools.partial`
2. Core calls `getattr(operator, "__mutmut_source__", "builtin")` — **this succeeds and returns `"builtin"`**

The core's contract ("fall back if getattr fails") is technically satisfied. But the plugin's intent was violated without any signal. The plugin author CANNOT verify attribution was set, because both the set and the get succeed — they just don't agree.

The spec's current language frames this as a handled edge case. It is not. It is a silent correctness hole for an entire class of operators (any C extension or wrapped callable). The spec must either:
- State this is an explicit **Known Limitation** and that `source` attribution is unreliable for non-pure-Python callables, OR
- Mandate the dict-registry alternative (M5 fix) and prohibit the attribute-stamping protocol

---

## `source_by_name` vs `source_by_key` Key Space Unspecified

The spec describes two maps with different key formats:
- `source_by_name` in `mutate_file_contents` return value: keys are mangled trampoline names (local short form, e.g., `"MyClass.__init___mutmut_0"`)
- `source_by_key` in `.meta` persistence: keys are fully-qualified mutant names (e.g., `"my_module.MyClass.__init___mutmut_0"`)

The conversion happens in `__main__.py` via `get_mutant_name(filename, mutant_name)`. The spec never defines:
- Who is responsible for the conversion
- What the exact conversion algorithm is (strip `src.` prefix? replace `os.sep` with `.`? strip `.py`?)
- Whether the two maps are guaranteed to be consistent

Two conforming implementations of `mutate_file_contents` could use different key formats for `source_by_name` and produce inconsistent `source_by_key` entries when converted.

---

## `source` Field Immutability Claim Is Factually Wrong

The spec states: "`source` MUST be immutable after `Mutation` construction — it is part of the frozen dataclass."

The actual code:
```python
@dataclass
class Mutation:
    original_node: cst.CSTNode
    mutated_node: cst.CSTNode
    contained_by_top_level_function: cst.CSTNode | None
    source: str = "builtin"
```

There is no `frozen=True`. This is a plain mutable dataclass. `mutation.source = "other"` is valid Python and succeeds. The spec states an invariant that the implementation does NOT enforce. Either:
- The spec is wrong and the immutability claim must be removed, OR
- The implementation needs `frozen=True` (but this requires checking whether any code assigns to `original_node`, `mutated_node`, or `contained_by_top_level_function` after construction)

---

## `mutmut_mutations_created` Filter Timing Unverified

The spec says the hook MUST be called "after all mutations are created for a file and the filter hook has run." Looking at the code flow in `mutate_file_contents`:

```python
module, mutations = create_mutations(code, ...)
mutated_code, mutant_names, source_by_name = combine_mutations_to_source(module, mutations)
if mutant_names:
    get_plugin_manager().hook.mutmut_mutations_created(...)
```

The `mutmut_filter_mutations` hook is not called anywhere in `mutate_file_contents`. If filtering happens OUTSIDE `mutate_file_contents` (e.g., in the caller), then `source_by_mutant_name` passed to `mutmut_mutations_created` reflects PRE-filter mutations — names that may not exist in the final mutant file. The spec's guarantee "after filter hook has run" is unverifiable from this code path alone.

The spec must explicitly state whether `source_by_mutant_name` reflects pre-filter or post-filter mutations, and the implementation must be verified to match.

---

## Verdict

The spec delta is thorough in identifying problems but makes no decisions. Six of its seven open questions are blockers that prevent finalizing any MUST contract. The three critical issues:

1. **API shape (C2)**: The 3-tuple vs NamedTuple decision must be made before ANY MUST statement about return types can stand. Remove all conditional MUST language.
2. **`"builtin"` semantic overloading**: Either reserve it for core only or explicitly disclaim per-operator reporting accuracy.
3. **Meta format backward compat (L3)**: Choose option a, b, or c. Document the version break explicitly if choosing incompatibility.

The spec also contains one factually incorrect invariant (immutability claim) that needs correction regardless of other decisions.

Until these are resolved, this spec delta describes the problem space — it does not define a behavioral contract.
