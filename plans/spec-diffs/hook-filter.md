# Spec Delta: Hook Filter Composition (`mutmut_filter_mutations`)

> Describes the behavioral contract changes required in `mutmut/SPEC.md` if branch
> `worktree-agent-a8b9d9a9` is merged.
>
> Branch commit: `c39852e Fix hook filter composition: chain mutmut_filter_mutations results`
>
> RFC 2119 keywords apply throughout: MUST, MUST NOT, SHOULD, SHOULD NOT, MAY.

---

## Summary of Change

The `mutmut_filter_mutations` hook changes from **last-result-wins** composition to
**chained** composition. Under the old semantics, pluggy fanned out the original
mutations list to all plugins simultaneously; the last non-None return value won and
earlier plugins' results were silently discarded. Under the new semantics, each plugin
receives the output of the previous plugin, so the full chain of filters is applied
in sequence.

---

## Accumulator Model

The caller MUST maintain an **accumulator** — a mutable reference to the working
mutations list — throughout the filter chain. The accumulator:

- MUST be initialized to the mutations list provided at the call site.
- MUST be replaced by a plugin's return value whenever that value is not `None`.
- MUST remain unchanged when a plugin returns `None`.
- MUST be the value returned to the caller after the last plugin has been called.

This is the complete state model. All subsequent invariants are consequences of it.

---

## Composition Invariants

- MUST: When N ≥ 1 plugins implement `mutmut_filter_mutations`, they MUST be called
  sequentially. Plugin K+1 MUST receive the accumulator's value after plugin K has
  been processed, not the original mutations list from the call site.
- MUST: A plugin returning `None` MUST be treated as "no opinion." The accumulator
  is passed to the next plugin unchanged.
- MUST: A plugin returning `[]` MUST replace the accumulator with an empty list.
  Subsequent plugins MUST be called with an empty list. An empty list is not a
  short-circuit signal; it is an explicit "remove all" decision, and the chain
  continues.
- MUST: When no plugins implement `mutmut_filter_mutations` (N = 0), the hook MUST
  return the original mutations list unchanged. No filtering occurs.
- MUST: The hook MUST be called even when the mutations list provided at the call
  site is empty. Plugins MUST receive `[]` in this case; they MUST NOT be skipped.
- MUST: A plugin's return value MUST be either a `list` or `None`. Returning any
  other type (tuple, generator, set, etc.) is undefined behavior. The spec does not
  guarantee how the caller handles such a return; implementations MAY reject it or
  coerce it, but MUST NOT silently corrupt the accumulator.

---

## Execution Order

Plugins are sorted into three tiers before the chain executes:

1. Plugins marked `@hookimpl(tryfirst=True)` — execute first.
2. Plugins with no ordering hint — execute second, in plugin registration order (FIFO).
3. Plugins marked `@hookimpl(trylast=True)` — execute last.

Invariants:

- MUST: A `tryfirst` plugin MUST be called before any regular-priority plugin and
  before any `trylast` plugin.
- MUST: A `trylast` plugin MUST be called after any regular-priority plugin and
  after any `tryfirst` plugin.
- MUST: Among plugins within the same tier (e.g., two `tryfirst` plugins, or two
  regular plugins), execution order MUST follow plugin registration order (FIFO —
  the order in which plugins were registered with the plugin manager).
- MUST NOT: A plugin MUST NOT declare both `tryfirst=True` and `trylast=True`
  simultaneously. If a plugin violates this, its position in the execution order
  is implementation-defined and MUST NOT be relied upon.
- MUST NOT: Implementations using `@hookimpl(wrapper=True)` on `mutmut_filter_mutations`
  MUST NOT be used. The filter chain bypasses pluggy's normal calling machinery;
  wrapper hooks are silently ignored. The hookspec MUST document this prohibition.

---

## Return Value Disambiguation

| Plugin return | Meaning | Effect on accumulator | Next plugin receives |
|---|---|---|---|
| `None` | No opinion / passthrough | Unchanged | Same list as this plugin received |
| `[]` | Remove all mutations | Replaced with `[]` | `[]` |
| `[m1, ...]` | Use exactly this list | Replaced with `[m1, ...]` | `[m1, ...]` |

The **terminal case**: after the last plugin is processed, the caller MUST return the
accumulator's current value — not the last plugin's raw return value. If the last
plugin returned `None`, the caller MUST return the accumulator (which may be the
original list or the output of an earlier plugin), not `None`.

---

## Argument Subsetting Contract

The hookspec for `mutmut_filter_mutations` accepts two parameters: `filename` and
`mutations`. Plugin implementations MAY declare only a subset of these in their
signature. The caller MUST honor arg subsetting:

- MUST NOT: The caller MUST NOT pass a keyword argument that is absent from a
  plugin's declared signature.
- MUST: A plugin that declares only `(self, mutations)` MUST receive only
  `mutations`. A plugin that declares only `(self, filename)` MUST receive only
  `filename`.
- MUST: A plugin that declares only `(self, filename)` and omits `mutations`
  receives no mutation list. Such a plugin is unable to perform useful filtering
  and SHOULD return `None`. Returning `[]` from such a plugin would remove all
  mutations without having examined them; this is permitted but strongly discouraged.

**Pre-merge requirement:** The branch implementation calls
`impl.function(filename=filename, mutations=mutations)` unconditionally, bypassing
arg subsetting. This violates the invariant above and is a regression from pluggy's
native fan-out behavior, which does perform arg subsetting. This MUST be fixed before
merge. The correct implementation inspects each plugin's signature and passes only the
parameters it declares. See C1 in `plans/wave2-review-findings.md`.

---

## Exception Behavior

- MUST: If a plugin raises an exception, the exception MUST propagate to the
  `mutmut_filter_mutations` call site uncaught.
- MUST: When a plugin raises, the accumulator at that point MUST be discarded. The
  caller MUST treat the exception as a complete failure of the filter chain, not a
  partial result. The partially-accumulated list MUST NOT be used as the return value.
- MUST NOT: The caller MUST NOT catch or suppress filter exceptions.

---

## Hookspec Accuracy

The hookspec for `mutmut_filter_mutations` MUST accurately reflect the composition
semantics. Since pluggy's fan-out machinery is no longer used:

- The hookspec MUST NOT declare `firstresult=True` (the result is not the first
  non-None return — it is the accumulator after the full chain).
- The hookspec SHOULD document in its docstring that plugins are called sequentially
  with the previous plugin's output, not in parallel with the original input.
- The hookspec MUST document that `@hookimpl(wrapper=True)` is prohibited for this
  hook.

---

## Backward Compatibility

### Compatible cases (single-plugin systems)

A system with exactly one filter plugin observes **identical behavior** under both
old and new semantics: the single plugin's return value (or None passthrough)
determines the final list in both cases.

### Breaking cases (multi-plugin systems)

A system with two or more plugins that both return non-None observes **different
behavior**:

- Old (last-wins): plugin B's result wins regardless of what plugin A returned.
  Plugin A's filtering is discarded if plugin B also returns non-None.
- New (chained): plugin B receives only what plugin A passed through. Plugin B
  can only reduce the list further, not restore mutations that plugin A removed.

### Migration requirement

Existing plugins that return non-None in a multi-plugin deployment MUST be audited
before being deployed under the new semantics. The semantics change is silent —
no error is raised; the behavior simply differs. Plugin authors relying on last-wins
behavior (e.g., a plugin intended to "override" earlier filters by returning a
complete list) must verify their intent is preserved under chained composition.

### Single-to-multi upgrade path

If a previously-single-plugin deployment adds a second plugin, the second plugin
will now filter the first plugin's output, not the original mutations list. Both
plugins must be reviewed for correctness under chained semantics at the point the
second plugin is introduced.

---

## Pre-Merge Requirements

The following issues MUST be resolved before this branch can be merged:

1. **C1 — Arg subsetting bug**: Fix `impl.function(filename=..., mutations=...)` to
   inspect each plugin's signature and pass only declared parameters. Without this
   fix, any plugin omitting `filename` from its signature will crash with `TypeError`.

2. **C3 — Submodule pointer**: The branch records submodule pointer `f644cda`, which
   is not locally available and lacks the workspace's local patches. The chaining
   patch MUST be applied atop the locally-patched commit (`0431bc7`) and the submodule
   pointer updated accordingly. The implementation referenced by the recorded pointer
   does not exist in the working tree.

---

## Bugs and Inconsistencies Remaining in Branch

**B3 (MEDIUM):** The sort key `(h.trylast, not h.tryfirst)` relies on pluggy's
`HookImpl` exposing `.tryfirst` and `.trylast` as direct attributes. This is correct
for pluggy 1.x but is an undocumented internal layout. If pluggy changes its
`HookImpl` structure, the sort silently produces the wrong order with no error. The
existing test (`test_filter_ordering_tryfirst_trylast`) tests only a two-plugin case
and does not cover the three-tier (tryfirst > regular > trylast) scenario.

**B5 (LOW):** `@hookimpl(wrapper=True)` on `mutmut_filter_mutations` silently does
nothing under the new implementation. The spec prohibits this (see Execution Order
section), but the implementation does not validate or warn. Violating plugins fail
silently.

---

## Open Questions

All critical open questions from the draft have been resolved above. The following
minor questions remain:

1. **Three-tier ordering test coverage.** The spec mandates `tryfirst > regular > trylast`
   ordering but the existing tests do not cover a three-plugin case with one of each tier.
   Whether this gap requires a test before merge is an implementation decision, not a
   spec question.

2. **pluggy version pinning.** The `HookImpl` attribute access (B3) depends on pluggy
   internals. Whether to add an assertion or pin a minimum pluggy version is a
   packaging decision outside this spec's scope.
