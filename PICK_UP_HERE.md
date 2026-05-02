# Pick Up Here — Publication Readiness Assessment

_Last updated: 2026-04-21_

## Packages

| Package | Purpose | Test status |
|---|---|---|
| `mutmut/` | Core submodule (patched from upstream) | — |
| `mutmut-extras/` | 19 extra mutation operators | ✅ 188 passed |
| `mutmut-llm/` | LLM-powered operator (async, cached, costed) | ✅ 448 passed, 21 skipped |
| `mutmut-dedup/` | Structural + bytecode TCE deduplication | ⚠️ 2 failing |

---

## What's fully merged and working

### mutmut-extras — all 19 operators live

`return_none`, `exception_handler`, `ternary`, `assert_true`, `slice_removal`, `void_call_removal`, `yield_mutation`, `comprehension_filter`, `super_call_deletion`, `fstring_mutation`, `function_deletion`, `default_param_mutation`, `reverse_iteration`, `startswith_endswith_swap`, `strip_to_partial`, `operand_swap`, `remove_boundary_offset`, `exception_type_broadening`, `exception_control_flow`

### mutmut-llm — complete

- Async parallel generation with `asyncio.Semaphore` + configurable concurrency
- Anthropic prompt caching (`cache_control` on system prompt blocks)
- Token cost tracking + per-run reporting
- Multi-model cache (composite keys: model + prompt version)
- Atomic cache writes
- Validation pipeline (syntax, import, pragma checks)
- Retry/backoff + SIGINT graceful cancellation

### mutmut-dedup — complete

- Phase 1: structural normalization (parse → unparse to canonical form, compare)
- Phase 2: bytecode TCE (compile + compare `co_code` / `co_consts` / `co_names`)

---

## Issues to fix before publishing

### 1. Two failing dedup tests (quick fix)

`test_bytecode.py::TestCPythonOptimizerBehavior::test_optimizer_pair_not_equivalent[constant-folding]`
`test_bytecode.py::TestCPythonOptimizerBehavior::test_optimizer_pair_not_equivalent[bool-short-circuit]`

CPython 3.13 folds both cases, but the tests assert it doesn't. The tests even include a comment: _"If a future CPython version changes optimizer behavior, flip to True."_ — that moment has arrived. Flip the assertions to `True` and update the message.

### 2. Five unmerged wave-2 features (worktrees, reviewed, need fixes then merge)

Implemented in `.claude/worktrees/`, reviewed in `wave2-review-findings.md`, unmerged due to issues found. The two "clean" features (cache GC `agent-a58ce4a1`, async parallel `agent-aaf84c48`) are already merged (0 commits ahead of main).

| Worktree | Feature | Plan file | Blocking issues |
|---|---|---|---|
| `agent-a28bdd9d` | Context quality improvement | `plans/llm/context-improvement.md` | C3 (submodule pointer wrong — reset to `0431bc7`), H1 (regex import filter → libcst Name visitor), H2 (regex branch count → AST node count), H4 (target method appears twice in class context), M3 (O(n×m) import/constant recomputation per method) |
| `agent-a225536b` | Adaptive budget per function | `plans/llm/adaptive-budget.md` | H2 (same regex branch count → AST), M1 (no validation when `min > max` in config), M6 (default `max_mutations_per_function` silently doubled from 5 to 10) |
| `agent-a8b9d9a9` | Hook filter composition | `plans/upstream/hook-filter-composition.md` | C1 (manual `get_hookimpls()` iteration bypasses pluggy arg subsetting — plugins that don't accept `filename` crash with `TypeError`) |
| `agent-a9c42fae` | Dynamic exclusion list | `plans/llm/dynamic-exclusion-list.md` | H3 (`SYSTEM_PROMPT` built at import time before plugins register), M2 (bare `except Exception` swallows plugin errors), M7 (`.format()` on template vulnerable to `{foo}` in operator docstrings) |
| `agent-afcf9355` | Mutation source tracking | `plans/core/mutation-source-tracking.md` | C2 (breaking API: `mutate_file_contents` returns 3-tuple, all callers unpacking 2-tuple break), M5 (`__mutmut_source__` attribute stamping fails on C extensions and `functools.partial`) |

Full issue details, root causes, and suggested fixes are in `wave2-review-findings.md`.

**Merge order (once fixes applied):**

```
1. agent-a225536b  (adaptive budget)          — no submodule changes
2. agent-a9c42fae  (dynamic exclusion)        — auto-merges with above
3. agent-a8b9d9a9  (hook filter)              — touches file_mutation.py
4. agent-afcf9355  (source tracking)          — touches file_mutation.py, merge after hook filter
5. agent-a28bdd9d  (context quality)          — mutmut-llm only, discard submodule pointer
```

### 3. README.md is sparse

Only covers `mutmut-extras`. Does not mention `mutmut-llm` or `mutmut-dedup` at all. Needs:
- Overview of all three packages and what they do
- Setup and usage for each
- Configuration reference for `mutmut-llm` (API key, model, concurrency, budget, etc.)
- How the plugins interact (extras + dedup + llm can all be installed together)

### 4. No PyPI metadata in any pyproject.toml

All three packages have bare `[project]` sections. Before publishing to PyPI, each needs:
- `authors`
- `license`
- `urls` (repository, homepage)
- `classifiers` (Development Status, Programming Language, License, Topic)
- `keywords`
- Proper version strategy (all at `0.1.0` now — decide: independent per-package versioning vs coordinated)

---

## Planned but not yet implemented

### plans/llm/

- **`audit-verbose-mode.md`** — `-v`/`--verbose` (0–3) + `--audit-log PATH` NDJSON output with prompt, validation decisions, caching hits, retry events. Full design in the plan file including `AuditEvent` dataclass and `AuditContext` coordinator. _Not started._

- **`cache-garbage-collection.md`** — Prune orphaned cache entries from renamed/moved/deleted functions. Cache entries accumulate forever; every source edit leaves a stale file. Plan covers three orphan scenarios and a GC algorithm. _Not started._

- **`context-improvement.md`** — Filter imports to only those referenced in the target function; add class sibling method signatures; add module-level constants used by the function. Partial implementation in worktree `agent-a28bdd9d` but blocked on fixing H1/H2 (regex → AST/libcst) before merge.

- **`dynamic-exclusion-list.md`** — Build the LLM's "do NOT generate these" exclusion list dynamically from registered operators' docstrings, rather than hardcoding 7 categories. Partial implementation in worktree `agent-a9c42fae` but blocked on H3/M2/M7 before merge.

- **`adaptive-budget.md`** — Scale LLM mutation count by function complexity (effective source lines + branch count). Partial implementation in worktree `agent-a225536b` but blocked on H2/M1/M6 before merge.

### plans/extras/

- **`isinstance-type-reduction.md`** — Remove one type at a time from `isinstance` type tuples. **Explicitly deferred**: blocked on a core change to `MutationVisitor.on_visit` to allow operators to see `Call` nodes that are in `NEVER_MUTATE_FUNCTION_CALLS`. The required change is small but touches a critical hot path. Revisit if there's demand.

- **`plan-exploratory-mutations.md`** — 6 lower-priority patterns: `statement_reorder`, `swap_dict_key_value`, `drop_defensive_copy`, `keyword_bool_arg_negate`, `remove_chained_method_call`, `exception_chaining_suppression`. All explicitly lower priority than the already-shipped operators. Plus 6 patterns from literature (decorator deletion, zero/one iteration loops, conditional→true/false, regex mutation, variable replacement). _Not started; need equivalent mutant rate experiments first._

### plans/core/

- **`mutation-source-tracking.md`** — Add `Mutation.source` field to attribute each mutant to its generating operator/plugin. Enables per-operator kill/survival reporting. Partial implementation in worktree `agent-afcf9355` with breaking API issue (C2) — needs `NamedTuple` or dataclass result object instead of raw 3-tuple.

### plans/upstream/

- **`hook-filter-composition.md`** — Chain `mutmut_filter_mutations` hook results so each plugin filters the previous plugin's output (currently last-result-wins, silently discarding earlier filters). Partial implementation in worktree `agent-a8b9d9a9` with pluggy arg subsetting bug (C1).

### plans/dedup/

- **`deterministic-mutant-dedup.md`** — Research survey (TCE, AST normalization, operator subsumption). Fully superseded by the implemented Phase 1 + Phase 2 in `mutmut-dedup`. No further action needed unless Phase 3 (static subsumption rules) is desired.

- **`exploration-dedup-strategies.md`** — Background research. Archived reference only.

---

## Suggested publish sequence

1. **Fix dedup tests** — flip 2 assertions, update messages (15 min)
2. **Fix + merge the 5 unmerged wave-2 features** — per the issue list and merge order above (largest effort)
3. **Write README.md** — cover all three packages with setup, usage, and config reference
4. **Add PyPI metadata** to all three `pyproject.toml` files
5. **Publish** `mutmut-extras` first (no external API dependencies, zero config required)
6. **Publish** `mutmut-dedup` second (standalone, no API key)
7. **Publish** `mutmut-llm` last (requires Anthropic key, most complex setup)
