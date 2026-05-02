# Spec Delta: Hook Filter Composition (mutmut core)

> Describes behavioral contract changes required in `mutmut/SPEC.md` if branch
> `worktree-agent-a8b9d9a9` (hook filter composition) is merged.
>
> Branch commit: `c39852e Fix hook filter composition: chain mutmut_filter_mutations results`
> Core submodule pointer changed: `22e26fb` → `f644cda` (see Bug section — `f644cda` not locally available)

---

## Changed Behavioral Contracts

### mutmut_filter_mutations composition semantics

**Current (must be replaced):**

> The `mutmut_filter_mutations` hook uses last-result-wins composition. Pluggy fans out
> the original mutations list to every registered plugin simultaneously. The final mutation
> list is the return value of the last plugin that returned a non-None result. Earlier
> plugins' filter results are silently discarded if a later plugin also returns a non-None
> value.

**Proposed (what the branch specifies):**

> The `mutmut_filter_mutations` hook uses chained composition. Plugins are called
> sequentially in defined order. Each plugin receives as its `mutations` argument the output
> of the previous plugin, not the original mutations list. The final mutation list is the
> output of the last plugin in the chain.

This is a breaking semantic change: any system that relied on later plugins overriding
earlier ones (last-wins) will now find that later plugins only see what earlier plugins
left behind.

---

## Composition Semantics

The proposed protocol, stated as invariants:

- MUST: When N ≥ 2 plugins implement `mutmut_filter_mutations`, plugin K+1 MUST receive
  the list returned by plugin K (after None substitution), not the list originally passed
  to the hook call site.
- MUST: A plugin returning `None` MUST be treated as a passthrough — the current
  accumulated mutations list is passed unchanged to the next plugin.
- MUST: A plugin returning `[]` (empty list) MUST be treated as an explicit "remove all"
  decision. The next plugin receives `[]`.
- MUST: The hook is called even when the incoming mutations list is empty. A plugin MUST
  receive `[]` (not be skipped) if no mutations were generated.
- MUST NOT: The caller MUST NOT substitute an empty list for a plugin's explicit `None` return.
  `None` and `[]` have distinct semantics.
- MUST: If a plugin raises an exception, it MUST propagate to the caller uncaught. The
  pipeline MUST NOT swallow filter exceptions.

---

## Ordering Guarantee

The branch defines this ordering for the filter chain:

1. Plugins marked `@hookimpl(tryfirst=True)` execute first.
2. Plugins with no ordering hint execute next (in pluggy registration order, stable).
3. Plugins marked `@hookimpl(trylast=True)` execute last.

**What the spec should say:**

- MUST: A plugin marked `tryfirst=True` MUST be called before any plugin without an
  ordering hint and before any plugin marked `trylast=True`.
- MUST: A plugin marked `trylast=True` MUST be called after any plugin without an
  ordering hint and after any plugin marked `tryfirst=True`.
- SHOULD: Relative execution order among plugins with the same ordering hint (both
  `tryfirst`, or both regular) is not guaranteed and SHOULD NOT be relied upon.
- MUST NOT: A single plugin MUST NOT declare both `tryfirst=True` and `trylast=True`.

The branch's sort key `(h.trylast, not h.tryfirst)` implements this correctly for
`HookImpl` objects (verified: pluggy exposes `tryfirst` and `trylast` directly on
`HookImpl`). However, the relative order of same-precedence regular plugins depends on
the order returned by `get_hookimpls()`, which preserves insertion order — this may
differ from pluggy's native hook calling order (which reverses insertion order). The spec
should explicitly state that same-precedence relative order is unspecified rather than
implying it follows registration order.

---

## Empty / Nil Handling

| Plugin return value | Meaning | Effect on next plugin |
|---|---|---|
| `None` | "No opinion / pass through" | Receives same list as this plugin |
| `[]` | "Remove all mutations" | Receives empty list |
| `[m1, m2, ...]` | "Use exactly this list" | Receives this list |

MUST: These three cases MUST be distinguishable and handled distinctly by the caller.
MUST NOT: The caller MUST NOT coerce `None` to `[]` or `[]` to `None`.

---

## Backward Compatibility Contract

- BREAKING: A single-plugin system where the plugin returns non-None observes identical
  behavior under both old and new semantics — its return value becomes the final list.
- BREAKING: A two-plugin system where both return non-None observes different behavior.
  Old: second plugin's result wins regardless of first. New: second plugin filters only
  what first plugin passed through.
- Plugins that return `None` unconditionally are fully backward-compatible — they behave
  identically under both semantics (passthrough in both cases).
- MAY: Existing plugins written for last-wins semantics that happen to return non-None MUST
  be reviewed before deployment in a multi-plugin configuration under chained semantics.
  The spec SHOULD document this migration requirement.

---

## Arg Subsetting Contract

**This section documents a KNOWN BUG in the branch (C1 from wave2-review-findings.md).**

The branch implementation calls `impl.function(filename=filename, mutations=mutations)`
directly, bypassing pluggy's argument normalization layer. Pluggy's hookspec mechanism
allows plugin implementors to declare only the parameters they care about:

```python
# This is valid per pluggy's arg subsetting contract:
@hookimpl
def mutmut_filter_mutations(self, mutations):  # omits filename
    return [m for m in mutations if ...]
```

Under the branch's implementation, such a plugin crashes with:
```
TypeError: mutmut_filter_mutations() got an unexpected keyword argument 'filename'
```

**What the spec SHOULD guarantee (correct behavior):**

- MUST: A filter plugin MAY declare only a subset of `(filename, mutations)` in its
  signature. The caller MUST NOT pass parameters that the plugin's signature does not
  declare.
- MUST: A filter plugin that omits `filename` MUST receive only `mutations`. A filter
  plugin that omits `mutations` is nonsensical (cannot filter without it) but MUST NOT
  crash the caller.

**What the branch currently guarantees (incorrect):**

- The branch's `impl.function(filename=..., mutations=...)` call requires plugins to
  accept both parameters. Single-parameter plugins crash. This violates pluggy's
  arg subsetting contract and is a regression from the current pluggy fan-out behavior,
  which does perform arg subsetting.

The fix from wave2-review-findings.md (C1) is correct:
```python
sig = inspect.signature(impl.function)
kwargs = {"filename": filename, "mutations": mutations}
accepted = {k: v for k, v in kwargs.items() if k in sig.parameters}
result = impl.function(**accepted)
```

---

## Open Questions

1. **Wrapper hook compatibility.** The branch bypasses pluggy's normal calling machinery,
   including wrappers (`@hookimpl(wrapper=True)`). Should the spec explicitly state that
   wrapper hooks are not supported for `mutmut_filter_mutations`? Or should the
   implementation be changed to preserve wrapper support?

2. **Same-precedence ordering.** The branch uses `get_hookimpls()` which returns plugins
   in insertion order. Pluggy's native fan-out reverses insertion order. Should the spec
   guarantee that same-precedence filter plugins execute in registration order (FIFO) or
   in reverse-registration order (LIFO, pluggy default)?

3. **Filter called with zero mutations.** The current implementation always calls the
   filter hook even when no mutations were generated. Is this intentional? A filter
   receiving an empty list and returning `None` is a no-op, but calling all registered
   filters for empty files wastes cycles. Should the spec guarantee hook invocation even
   for empty files, or permit skipping it?

4. **Self-consistency of `firstresult` hookspec.** The hookspec has no `firstresult=True`
   attribute. The branch's manual iteration bypasses this entirely. Should the hookspec
   be updated to reflect the new semantics, or should the hookspec stay as-is since the
   implementation no longer uses pluggy's fan-out at all?

---

## Bugs / Inconsistencies in Branch Implementation

### B1 (CRITICAL — same as C1 in wave2-review-findings.md)
`impl.function(filename=filename, mutations=mutations)` bypasses pluggy arg subsetting.
Plugins that omit `filename` from their signature crash with `TypeError`. This directly
contradicts pluggy's documented plugin contract and makes the new implementation a
regression from the old one.

**Evidence:** Confirmed in code review. The `inspect.signature` fix from the review
findings is the correct repair.

### B2 (HIGH) — Two tests fail in the worktree
`test_adversarial_filter.py::test_three_filters_pipeline` and
`test_filter_receives_chained_mutations_not_original` FAIL in the current worktree because
the submodule is checked out at commit `0431bc7` (the old implementation), not at
`f644cda` (the commit recorded in the branch) — `f644cda` is not locally available.
The tests were written to document the desired behavior, but the implementation they test
does not exist in the local working tree.

**Evidence:** Running `pytest mutmut/tests/test_adversarial_filter.py` from the worktree
produces 2 failures with `assert 7 <= 2` and `assert 5 == 0`, confirming the old
last-wins behavior is still active.

**Implication for merge:** The submodule pointer in this branch is broken (same class as
C3). The correct approach before merge: apply the `get_hookimpls()` reduce pattern to the
submodule at the currently-patched commit (`0431bc7`) and commit it, then update the
pointer.

### B3 (MEDIUM) — Sort key not tested for correctness against pluggy internals
The conflict-resolution doc's sort key `(h.trylast, not h.tryfirst)` is correct for
pluggy 1.x `HookImpl` objects (which expose `.tryfirst` and `.trylast` directly).
However, this relies on pluggy's internal attribute layout. If pluggy changes its
`HookImpl` structure, the sort silently produces wrong order with no error. A test
asserting the ordering for `tryfirst` > regular > `trylast` exists
(`test_filter_ordering_tryfirst_trylast`) but it only tests two plugins and does not test
a three-plugin case with regular in the middle.

### B4 (LOW) — Inconsistency between plan doc and conflict-resolution doc
`plans/upstream/hook-filter-composition.md` uses `h.hookimpl.tryfirst` (wrong — would
AttributeError in pluggy 1.x). The `conflict-resolution/hook-filter-composition.md` uses
`h.tryfirst` (correct). The plan doc should be updated to avoid confusion.

### B5 (LOW) — Wrapper hooks silently broken
The branch bypasses `pluggy`'s wrapper hook mechanism. Any plugin using
`@hookimpl(wrapper=True)` on `mutmut_filter_mutations` will have its wrapper body
skipped — the `yield`/return from the wrapper is never invoked. This fails silently (no
error; the filter just doesn't wrap). The spec should explicitly prohibit wrapper hooks
for this hookspec or the implementation should support them.
