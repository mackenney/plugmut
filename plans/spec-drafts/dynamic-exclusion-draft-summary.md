# Spec Delta Draft: Dynamic Exclusion List — Summary

**Draft written to:** `plans/spec-diffs/dynamic-exclusion.draft.md`
**Branch:** `worktree-agent-a9c42fae`
**Package affected:** `mutmut-llm`

## Contracts Captured

- Exclusion list construction: build from registered operators via plugin manager; fall back to hardcoded when none available
- Operator description extraction: docstring first line → name-based fallback; errors MUST NOT propagate
- System prompt construction: substitution MUST NOT fail on docstring brace literals
- Timing: MUST build at generation-run time, NOT import time
- Plugin integration: all registered plugins included, deduplication by description string
- Fallback: hardcoded exclusions used when plugin manager unavailable or returns empty

## Open Questions (5)

1. Should plugin introspection errors propagate or silently fall back?
2. Is exclusion list ordering defined/deterministic?
3. Is caching of `build_system_prompt()` across a run contractual?
4. Should `build_system_with_context` require explicit `system_prompt` (eliminating stale default)?
5. Quality floor for operator descriptions — should operators be required to have docstrings?

## Bugs Found

| ID | Severity | Description |
|---|---|---|
| BUG-1 | HIGH | Import-time `SYSTEM_PROMPT` constant used as fallback in `build_system_with_context` — stale when plugins register after import |
| BUG-2 | MEDIUM | `except Exception` in `_get_registered_operators` silently swallows plugin errors |
| BUG-3 | MEDIUM | `.format(exclusion_list=...)` raises `KeyError` if any operator docstring contains `{identifier}` |
| BUG-4 | LOW | `_describe_operator` doesn't guard against property-raising `__doc__` |
| INC-1 | — | With 1/20 operators having docstrings, dynamic list may be less informative than the hardcoded fallback it replaces |
| INC-2 | — | Template not validated at definition time; future edits to template could silently break `build_system_prompt()` |
