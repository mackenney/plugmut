# Spec Delta: Dynamic Exclusion List (mutmut-llm)

> These contracts would need to be added to `mutmut-llm/SPEC.md` if this branch were merged.
> RFC 2119 keywords apply.

---

## New Behavioral Contracts

### Exclusion List Construction

- `build_exclusion_list(operator_lists)` MUST accept an explicit list of operator lists; when provided, it MUST NOT consult the plugin manager.
- `build_exclusion_list(operator_lists=None)` MUST query the plugin manager for all registered operators via the `mutmut_register_operators` hook.
- When the resulting set of operator descriptions is non-empty, each description MUST appear as a bullet line prefixed with `  * `.
- Duplicate descriptions (same string from different operators) MUST be suppressed; each unique description MUST appear exactly once.
- The output MUST be a single string suitable for inline substitution into the system prompt exclusion section.

### Operator Description Extraction

- For each `(node_type, callable)` operator pair, the description MUST be the first non-empty line of the callable's `__doc__` if available.
- When `__doc__` is absent, empty, or whitespace-only, the description MUST be derived from the callable's `__name__` (stripping `operator_` prefix, replacing `_` with spaces) combined with the node type name: `"{name} (targets {NodeType} nodes)"`.
- Description extraction MUST NOT raise; any attribute access errors MUST be caught and fall back to the name-based form.

### System Prompt Construction

- `build_system_prompt(operator_lists)` MUST produce a complete, valid system prompt string by substituting the constructed exclusion list into the prompt template.
- The substitution MUST NOT fail when operator docstrings contain literal brace characters (`{` or `}`).
- The JSON examples embedded in the prompt template MUST be preserved verbatim in the output (not corrupted by string substitution).

---

## Timing Contract

The exclusion list MUST be built at **generation-run time**, not at module import time.

Rationale: plugins are registered after import. An import-time query will return only the operators known before any plugin has called `register()`, producing a stale, partial exclusion list.

The canonical call point is once per `run_generation()` invocation, before the per-target loop begins.

**MUST NOT** expose a module-level constant that is frozen at import time as the effective system prompt. Any such constant MUST be treated as a backward-compatibility alias only, and MUST NOT be used by the generation pipeline.

---

## Plugin Integration Contract

- The exclusion list builder MUST invoke `pm.hook.mutmut_register_operators()` to collect operators from all registered plugins.
- Operators returned by multiple plugins MUST all be included (subject to deduplication by description).
- When the plugin manager is unavailable (e.g., `mutmut` core not installed), the builder MUST fall back to hardcoded exclusions and MUST NOT raise.
- The fallback MUST be the complete hardcoded exclusion list, not an empty string.

---

## Fallback Contract

- When `operator_lists` is an empty list `[]`, the return value MUST be the hardcoded exclusions string.
- When `operator_lists=None` and the plugin manager returns no operators (empty result), the return value MUST be the hardcoded exclusions string.
- When `operator_lists=None` and plugin manager import fails, the return value MUST be the hardcoded exclusions string.
- The hardcoded fallback MUST cover at minimum: arithmetic operator swaps, comparison operator swaps, boolean literal flips, logical operator swaps, unary operator changes, keyword mutations, string and number constant mutations.

---

## Security Contract

- Operator docstring content MUST NOT be able to raise an exception during prompt construction.
- In particular: if a docstring contains `{identifier}` or `}` sequences, prompt construction MUST NOT raise `KeyError` or `ValueError`.
- The prompt template's JSON examples (which use `{{` and `}}` escapes) MUST survive the substitution step intact as `{` and `}` in the final output.

---

## Open Questions

1. **Should plugin errors propagate or be silently swallowed?**
   The current implementation catches `Exception` broadly and logs at DEBUG. This hides plugin bugs. Should real plugin errors (e.g., `TypeError` from a malformed hook implementation) propagate so the operator author sees them? The spec should declare whether failure-to-introspect is a silent fallback or a hard error.

2. **Is exclusion list ordering defined?**
   Plugin hook call order depends on registration order. The spec should state whether the exclusion list order is deterministic (e.g., sorted by description) or explicitly unspecified.

3. **What is the caching contract for `build_system_prompt()` across a generation run?**
   The pipeline currently calls it once and reuses the result. Should the spec guarantee this (one call per run, not per target), or leave it to the implementation?

4. **Should `build_system_with_context` always require an explicit `system_prompt` argument?**
   The `system_prompt=None` default falls back to the import-time `SYSTEM_PROMPT` constant. If the timing contract above is adopted (import-time = stale), this default is incorrect. The spec should define whether the default is acceptable or whether callers MUST always pass an explicit prompt.

5. **Quality floor for operator descriptions?**
   Currently 1 of 20 mutmut-extras operators has a docstring; the rest produce mechanical fallback descriptions like `"return none (targets Return nodes)"`. Should the spec require that registered operators expose meaningful descriptions? This would require a new hookspec or documentation standard.

---

## Bugs / Inconsistencies Found in Branch Implementation

### BUG-1 (HIGH): Import-time `SYSTEM_PROMPT` constant used as default in `build_system_with_context`

`SYSTEM_PROMPT = build_system_prompt()` executes at module import time (line 153 of `prompts.py`). `build_system_with_context` falls back to this constant when called without `system_prompt=`. Any external code calling `build_system_with_context(context=...)` directly — including tests and third-party integrations — will silently use the stale import-time exclusion list, even if plugins were registered after import. The pipeline itself avoids this by passing `system_prompt=system_prompt` explicitly, but the fallback path is latently wrong.

*Reference: wave2-review-findings.md H3*

### BUG-2 (MEDIUM): `except Exception` catches plugin errors, not just import failures

In `_get_registered_operators`, the `except Exception` block catches every exception including `TypeError` from a malformed plugin, `AttributeError` from a bad hook implementation, and `MemoryError`. All are silently downgraded to an empty operator list and logged at DEBUG. Plugin authors will not see errors from their operators. Should catch `ImportError` only for the `from mutmut.plugin_manager import get_plugin_manager` step; actual hook call errors should propagate or log at WARNING.

*Reference: wave2-review-findings.md M2*

### BUG-3 (MEDIUM): `.format(exclusion_list=exclusion_list)` vulnerable to brace literals in docstrings

`SYSTEM_PROMPT_TEMPLATE.format(exclusion_list=exclusion_list)` at line 148. If any operator docstring contains `{foo}` (e.g., a docstring like `"Swap {a} and {b} in binary expressions"`), Python's `.format()` raises `KeyError: 'foo'`. The template itself uses `{{`/`}}` escapes for JSON examples, so the template itself is safe — but the injected `exclusion_list` string is not pre-escaped. Fix: either escape braces in `exclusion_list` before injection (`exclusion_list.replace("{", "{{").replace("}", "}}")`), or replace `.format()` with a targeted `.replace("{exclusion_list}", exclusion_list)`.

*Reference: wave2-review-findings.md M7*

### BUG-4 (LOW): `_describe_operator` does not guard against property-raising `__doc__`

`getattr(fn, "__doc__", None)` is not safe against descriptors/properties that raise on access. `getattr(obj, attr, default)` only catches `AttributeError`, not arbitrary exceptions from a property getter. Should wrap in `try/except Exception`.

*Reference: wave2-review-findings.md L1*

### INCONSISTENCY-1: Exclusion list quality degrades silently as operators lack docstrings

Only 1 of 20 mutmut-extras operators has a docstring at the time of this branch. The remaining 19 produce fallback descriptions like `"return none (targets Return nodes)"` — which are less informative than the original hardcoded exclusions for the LLM. The dynamic mechanism may actually produce a WORSE exclusion list than the hardcoded one for the current operator corpus, without any signal to the user.

### INCONSISTENCY-2: `SYSTEM_PROMPT_TEMPLATE` uses `.format()` but template is not validated at definition time

The template contains `{exclusion_list}` as the only intended placeholder, but there is no assertion or test that verifies this at definition time. If the template is edited to add other content containing `{...}`, `build_system_prompt()` will start raising `KeyError` with no clear error message pointing at the template.
