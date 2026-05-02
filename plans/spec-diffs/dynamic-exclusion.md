# Spec Delta: Dynamic Exclusion List (mutmut-llm)

> These contracts would need to be added to `mutmut-llm/SPEC.md` if this branch were merged.
> RFC 2119 keywords apply.
> Items marked ⚠️ MERGE-BLOCKED are contracts the branch currently violates; they
> become effective only after the referenced bug is fixed.

---

## Overview

This feature replaces a hardcoded exclusion string in the LLM system prompt with a
dynamically-assembled list derived from all registered mutation operators.
The key behavioral properties are: construction timing (after plugin registration,
before first API call), graceful fallback when no operators are available, and
injection safety when operator docstrings contain special characters.

---

## Timing Contract

- The exclusion list MUST be constructed after all plugins have registered and before
  the first LLM API call of the run.
- The exclusion list MUST NOT be constructed during module import.
- `build_exclusion_list()` or `build_system_prompt()` MUST NOT be called at module
  scope in a way that could affect the effective system prompt used by the generation
  pipeline. A module-level precomputed value MAY exist as a backward-compatibility
  alias but MUST NOT be consulted by the generation pipeline.
- Callers MUST invoke `build_system_prompt()` once per generation run and pass the
  result explicitly to downstream functions. Relying on a cached module-level constant
  as an implicit default violates the timing contract.

---

## Exclusion List Construction Contract

- `build_exclusion_list(operator_lists)` MUST accept an explicit list of operator
  lists. When provided, it MUST NOT consult the plugin manager.
- `build_exclusion_list(operator_lists=None)` MUST query the plugin manager for all
  registered operators via the `mutmut_register_operators` hook.
- For each `(node_type, callable)` pair yielded by operator lists, the function MUST
  produce at most one bullet line in the output. Duplicate descriptions (see
  Deduplication Contract) are suppressed.
- When at least one unique description is produced, the output MUST consist of each
  unique description formatted as `  * {description}`, one per line, in alphabetical
  order by description string.
- When no descriptions are produced (all inputs empty, all operators yield only
  duplicates, etc.), the output MUST be the hardcoded fallback exclusion string.
- The output MUST be a single string ready for inline substitution into the system
  prompt exclusion section.

---

## Operator Description Extraction Contract

- For each `(node_type, callable)` operator pair, the description MUST be the first
  non-empty line of the callable's `__doc__`, if available.
  - "First non-empty line" means: `doc.strip().split("\n")[0].strip()` where `doc`
    is the raw docstring. Leading blank lines in the docstring are therefore ignored.
- When `__doc__` is absent, empty, or whitespace-only, the description MUST be derived
  as: `"{readable_name} (targets {NodeType} nodes)"`, where `readable_name` is the
  callable's `__name__` with any `operator_` prefix stripped and underscores replaced
  with spaces.
- When `__name__` is also absent, `readable_name` MUST be `"unknown"`.
- Description extraction MUST NOT raise. Any attribute access that raises MUST be
  caught and the result MUST fall back to the name-based form.

---

## Deduplication Contract

- Deduplication is applied to the raw description string before formatting.
- Two descriptions are considered duplicates if and only if they are identical strings
  under case-sensitive exact comparison.
- Deduplication MUST apply across all operators regardless of which plugin provided
  them. "From different operators" and "from the same operator appearing in multiple
  lists" are treated identically.
- When two operators are deduplicated, the surviving entry gives no indication that
  multiple operators shared that description. This is an accepted consequence:
  per-operator attribution is not part of the exclusion list contract.

---

## Fallback Contract

The hardcoded fallback is returned in the following cases:

1. `operator_lists=None` and the plugin manager is unavailable (import fails).
2. `operator_lists=None` and the plugin manager returns an empty result.
3. `operator_lists` is an empty container (`[]`, or any falsy value after the
   `None`-query branch).
4. `operator_lists` contains only empty sublists (`[[]]`, `[[], []]`, etc.) — the
   operator iteration loop yields no descriptions.

The hardcoded fallback MUST cover at minimum: arithmetic operator swaps, comparison
operator swaps, boolean literal flips, logical operator swaps, unary operator changes,
keyword mutations, string and number constant mutations. The fallback MUST NOT be an
empty string.

---

## Plugin Integration Contract

- `build_exclusion_list()` MUST invoke `pm.hook.mutmut_register_operators()` to
  collect operators from all registered plugins.
- Operators returned by multiple plugins MUST all be included, subject to
  deduplication by description.
- When the plugin manager module cannot be imported (`ImportError`), the function
  MUST fall back to hardcoded exclusions and MUST NOT raise. This SHOULD be logged
  at DEBUG level.
- When the plugin manager is available but a hook call raises (e.g., `TypeError` from
  a malformed implementation), the function MUST log at WARNING level and proceed as
  if that plugin returned no operators. It MUST NOT silently swallow the exception
  without logging.

---

## System Prompt Construction Contract

- `build_system_prompt(operator_lists)` MUST produce a complete, valid system prompt
  string by substituting the constructed exclusion list into the prompt template.
- The JSON examples embedded in the prompt template MUST be preserved verbatim in the
  output (i.e., `{{` / `}}` escapes in the template MUST produce literal `{` / `}` in
  the output).
- ⚠️ MERGE-BLOCKED (BUG-3): The substitution MUST NOT raise when operator docstrings
  contain literal brace characters (`{`, `}`, `{foo}`, `{0:d}`, etc.). The fix
  requires replacing `.format(exclusion_list=exclusion_list)` with a targeted string
  replacement that does not interpret the substituted value as a format template.

---

## `build_system_with_context` Contract

`build_system_with_context` assembles the multi-block structure required for Anthropic
prompt caching.

- The function MUST accept an explicit `system_prompt` argument.
- When `system_prompt` is `None`, the function MUST NOT silently use a module-level
  constant built at import time. It MUST call `build_system_prompt()` at invocation
  time. Callers SHOULD always pass an explicit `system_prompt` to ensure the timing
  contract is met; relying on the `None` default is SHOULD NOT.
- The function MUST return a list of at least one Anthropic content block containing
  the system prompt text.
- When non-empty context is provided, the function MUST include it as a subsequent
  block. Cache control MUST be applied to the last block in the list, so that the
  longest possible prefix is cached across calls to functions in the same file.
- The TTL parameter governs cache lifetime. Supported values and their semantics are
  an implementation detail of the Anthropic API layer; the spec requires only that
  the function accepts and passes through the TTL to the cache control block.

---

## LLM Guidance Semantics

The exclusion list is guidance to the LLM, not a hard enforcement mechanism.

- The exclusion list SHOULD reduce the frequency with which the LLM generates mutation
  types already covered by rule-based operators. It does NOT guarantee the LLM will
  never generate such mutations.
- Consumers MUST NOT assume that mutations in the exclusion list will be absent from
  the LLM's output. The exclusion list is best-effort guidance only.
- Dedup filtering (from `mutmut-dedup`) remains the reliable mechanism for removing
  equivalent mutations after generation. The exclusion list reduces waste; dedup
  eliminates it when it occurs.

---

## Ordering Contract

The exclusion list MUST present descriptions in ascending alphabetical order (Unicode
code-point order, case-sensitive). Rationale: a deterministic order ensures the
assembled system prompt is identical across runs with the same operator set, which
maximizes Anthropic prompt-cache hit rates. Plugin registration order MUST NOT affect
the output string.

---

## Known Bugs in Branch Implementation

### BUG-1 (HIGH) — Import-time `SYSTEM_PROMPT` used as default in `build_system_with_context`

`SYSTEM_PROMPT = build_system_prompt()` executes at module import time (`prompts.py`
line 153). `build_system_with_context` falls back to this constant when called without
an explicit `system_prompt`. Any caller that omits `system_prompt=` will silently use
the stale import-time exclusion list even if plugins were registered after import.
The pipeline avoids this by passing the argument explicitly, but the default is
latently wrong and a trap for third-party integrations.

*Reference: wave2-review-findings.md H3*

### BUG-2 (MEDIUM) — `except Exception` swallows real plugin errors

`_get_registered_operators` catches `Exception` broadly. A `TypeError` from a
malformed hook implementation, an `AttributeError` from a bad plugin, or any other
runtime error is silently downgraded to an empty operator list and logged at DEBUG.
Plugin authors will not see failures. The catch should be scoped: `ImportError` for
the plugin manager import step only; actual hook call errors should be caught
separately and logged at WARNING.

*Reference: wave2-review-findings.md M2*

### BUG-3 (MEDIUM) ⚠️ BLOCKS SECURITY MUST — Brace literals in docstrings crash prompt construction

`SYSTEM_PROMPT_TEMPLATE.format(exclusion_list=exclusion_list)` interprets the injected
value as a format template. A docstring like `"Swap {a} and {b} in binary expressions"`
causes `KeyError: 'a'`. Fix: replace `.format()` with
`.replace("{exclusion_list}", exclusion_list)` so the injected value is treated as a
literal string.

*Reference: wave2-review-findings.md M7*

### BUG-4 (LOW) — `_describe_operator` does not guard against property-raising `__doc__`

`getattr(fn, "__doc__", None)` only catches `AttributeError`. A descriptor or property
that raises any other exception on access will propagate. Should wrap in
`try/except Exception`.

*Reference: wave2-review-findings.md L1*

### INCONSISTENCY-1 — Dynamic list quality degrades silently when operators lack docstrings

With 1 of 20 mutmut-extras operators providing a docstring at time of branch
implementation, the dynamic exclusion list produces mechanical fallbacks
(`"return none (targets Return nodes)"`) that are less informative to the LLM than the
original hardcoded exclusions. The dynamic mechanism may produce a worse exclusion
list than the hardcoded one for the current operator corpus, with no signal to the
user.

---

## Open Questions

1. **Quality floor for operator descriptions.** With 19/20 operators producing
   mechanical fallback descriptions, is the dynamic exclusion list net-positive for
   LLM guidance? Should the spec require that registered operators expose meaningful
   descriptions? This would require either a documentation standard or a new hookspec
   that operators satisfy a description-quality contract.

2. **Caching contract for `build_system_prompt()` across a run.** The pipeline calls
   it once per run and reuses the result. Should the spec mandate this ("MUST be called
   at most once per run, not once per target"), or leave caching to the caller? The
   current behavior is already specified via the timing contract (one call before the
   per-target loop); this question is whether the spec should also bound calls from
   above.
