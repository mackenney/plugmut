# mutmut-extras SPEC.md — Final Revision Summary

**Output:** `mutmut-extras/SPEC.md`
**Critique addressed:** `mutmut-extras/SPEC.md.critique`

## Critique Resolution

| Category | Issues found | Resolution |
|---|---|---|
| Critical contradictions (CON-1, IC-1, IC-3, BA-1) | 4 | All resolved |
| High (UI-1, IL-1, IC-2) | 3 | All resolved |
| Medium IL / IC issues | ~10 | All resolved |
| Low issues | ~5 | All resolved |

## Critical Resolutions

**CON-1 — Syntax guarantee vs exception_control_flow:**
The invariant is now scoped to libcst-parseability only. `ast.parse` compatibility is
explicitly NOT guaranteed for scope-unaware operators. The Non-Goals section calls this out
up front.

**IC-1 / BSO-1 — reverse_iteration fires on async for:**
Verified by reading the implementation (`cst.For`, no `asynchronous` guard). The false
non-goal ("Does not handle async for") is removed. Bug B4 added with HIGH severity and a
one-line fix. The trigger description now explicitly states it fires on both sync and async
for loops.

**IC-3 — default_param_mutation Case 3 dead code:**
Case 3 completely removed from the live trigger/output contract. The operator now only
documents Cases 1 and 2 as live. Case 3 is referenced exclusively in the Bugs section (B1).

**BA-1 — exception_type_broadening single-element tuple:**
Verified by reading implementation (`if len(elements) < 2: return`). "Yields nothing"
committed as the definitive contract. Open Question about this removed.

## Implementation Leakage Removed

- `.with_changes()` / `.with_deep_changes()` API call → "input node MUST be unchanged"
- `isinstance(node, declared_type)` → "type matches declared type in registration tuple"
- `MaybeSentinel.DEFAULT` → "serializes without trailing colon"
- `node.with_changes(body=node.orelse, ...)` → "true-branch and false-branch exchanged"
- `cst.SimpleString("'XX'")` → "string literal `'XX'`"

## Ordering Contract Clarified

The general invariant now says "same ordered sequence" (not "same set"). Per-operator
ordering is contractual for ternary and exception_control_flow. Cross-operator registration
order is NOT part of the package contract to callers.

## New Bug Added

**B4: reverse_iteration fires on async for loops (HIGH)**
`cst.For` in libcst covers both sync and async for. No guard on `node.asynchronous`.
Fix: `if node.asynchronous is not None: return`.

## Open Questions (5, reduced from 6)

1. comprehension_filter multi-clause: one-shot removal vs per-clause?
2. remove_boundary_offset: `1 - expr` intentionally excluded?
3. yield 0 sentinel: always `0` or configurable?
4. strip_to_partial: lstrip/rstrip are non-targets — intentional?
5. super_call_deletion: should deeper chaining be matched?

## Bugs Documented (4)

- B1: default_param_mutation Case 3 dead code (Medium)
- B2: void_call_removal + super_call_deletion duplicate mutations (Low)
- B3: exception_control_flow docstring claims filtering that doesn't happen (Low)
- B4: reverse_iteration fires on async for (High) ← NEW
