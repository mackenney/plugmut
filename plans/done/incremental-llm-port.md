# Incremental LLM Feature Port Plan

Port features from `~/pr/mutmut/` to `mutmut2/` in small, reviewable, well-tested steps.

**Guiding principles:**
- Each step is a self-contained PR that compiles, passes tests, and delivers value
- Aggressive simplification: ship the 20% that delivers 80% of value
- No step depends on unmerged previous steps (linear chain)
- Every submodule patch gets a conflict-resolution doc

---

## Progress

| Step | Status | Tests | Notes |
|------|--------|-------|-------|
| 1. Whole-function mutations | **Done** | 5 core + 14 extras | Landed in earlier commits |
| 2. Additional hookspecs | **Done** | 10 | 6 hooks, 4 call sites patched |
| 3. Config + cache | **Done** | 38 (18 config + 20 cache) | `mutmut-llm/` package created |
| 4. Prompts + validation | **Done** | 53 (26 prompts + 27 validation) | ~85 LOC, no security.py needed |
| 5. LLM operator + pipeline + CLI | **Done** | 59 (13 operators + 14 scope + 13 pipeline + 8 plugin + 11 integration) | ~280 LOC, deep mode only |
| 6. Storage + reporting (merged 6+7) | **Done** | 49 (11 storage + 16 reporting + 22 plugin) | JSON files, no SQLite, no submodule patch |
| 7. PR/targeted scope | Pending | — | |
| 8. Dedup + static equivalence | Pending | — | |

**Total tests passing:** 517 (193 core + 127 extras + 198 llm)

---

## Step 1: Whole-function mutation support + function body deletion operator

**What:** Patch `file_mutation.py` so operators can replace entire FunctionDef nodes (not just sub-nodes), and ship a deterministic operator that exercises this path immediately.

**Why first:** Prerequisite for the LLM operator and for function-level deterministic mutations. `deep_replace()` uses object identity (`is`) to locate nodes. In `function_trampoline_arrangement()`, `function.with_changes(name=...)` creates a **new CST object** — so `mutant.original_node is mutated_method_base` is `False` and the replacement silently fails. Expression-level LLM constraints don't solve this: the LLM naturally produces complete function bodies, and forcing micro-level targeting makes prompts fragile and cache schema awkward.

**Deterministic use case — function body deletion:**

The classic "remove method body" mutation (PITest, MutPy IOD). Replaces the entire function body with `pass` (or `return None` for typed returns). This is one of the most effective single mutation operators — research (Untch 2009) showed statement deletion alone achieves ~92% mutation testing effectiveness.

This operator genuinely requires whole-function access: the function body is `cst.IndentedBlock`, but `IndentedBlock` is used everywhere (if/for/while/class/try bodies). Operators receive only the node with no parent context, so registering against `IndentedBlock` would mutate every block in the program. Registering against `FunctionDef` is the only clean path.

```python
def operator_function_deletion(node: cst.FunctionDef) -> Iterable[cst.FunctionDef]:
    pass_body = cst.IndentedBlock(body=[cst.SimpleStatementLine(body=[cst.Pass()])])
    yield node.with_changes(body=pass_body)
```

**Scope:**
- Patch `mutmut/src/mutmut/file_mutation.py`: ~14 lines in `function_trampoline_arrangement()`
- Add `mutmut-extras/src/mutmut_extras/operators/function_deletion.py`: ~15 LOC
- Add `mutmut/tests/test_whole_function_mutation.py`: 5 tests (direct trampoline, regression guard, multiple mutations, mixed sub+whole, end-to-end)
- Add `mutmut-extras/tests/test_function_deletion.py`: unit + integration tests
- Update e2e project to cover function deletion mutations
- Add `conflict-resolution/whole-function-mutations.md`

**Change detail (submodule patch):**
```python
# Before: always uses deep_replace
mutated_method_result = deep_replace(mutated_method_base, mutant.original_node, mutant.mutated_node)

# After: identity check for whole-function mutations
if mutant.original_node is function:
    mutated_method = mutant.mutated_node.with_changes(name=cst.Name(mutant_name))
else:
    mutated_method = function.with_changes(name=cst.Name(mutant_name))
    mutated_method = deep_replace(mutated_method, mutant.original_node, mutant.mutated_node)
```

**Why this ordering matters:** Shipping the deterministic operator alongside the patch means the whole-function code path is immediately exercised by real tests with predictable output — no LLM variability. This builds confidence in the patch before it's used for LLM mutations in Step 5.

**Simplification vs old repo:** Keep return signature as 2-tuple — skip `mutant.source` tracking for now (add with storage in Step 6).

---

## Step 2: Additional hookspecs (minimal set) — DONE

**What:** Add lifecycle hooks to the submodule's plugin system.

**Why:** The LLM pipeline needs hooks for configuration, CLI commands, and mutation filtering. Without these, the plugin can only register operators — it can't initialize config, add CLI commands, or filter bad mutations.

**Hooks added (6 of the old repo's 9 additional hooks):**

| Hook | Signature | Call site |
|------|-----------|-----------|
| `mutmut_configure` | `(config: object)` | `__main__.py:ensure_config_loaded()` |
| `mutmut_register_commands` | `(cli_group: object)` | `__main__.py:_register_plugin_commands()` (module-level) |
| `mutmut_filter_mutations` | `(filename: str, mutations: list) -> list \| None` | `file_mutation.py:create_mutations()` |
| `mutmut_post_test` | `(mutant_name, exit_code, status, duration)` | `__main__.py:SourceFileMutationData.register_result()` |
| `mutmut_post_run` | `(source_file_mutation_data: Sequence)` | `__main__.py:_run()` end |
| `mutmut_mutations_created` | `(filename: str, source_by_mutant_name: dict)` | `file_mutation.py:mutate_file_contents()` |

**Deferred:**
- `mutmut_pre_test` — not needed until storage (Step 6)
- `mutmut_select_tests` — optimization, not needed
- `mutmut_skip_node` — optimization, not needed

**Delivered:**
- Patched `mutmut/src/mutmut/hookspecs.py`: 6 hook specs added
- Patched `mutmut/src/mutmut/file_mutation.py`: `create_mutations()` gained `filename` kwarg, calls `mutmut_filter_mutations`; `mutate_file_contents()` calls `mutmut_mutations_created`
- Patched `mutmut/src/mutmut/__main__.py`: 4 hook call sites (configure, register_commands, post_test, post_run)
- Added `mutmut/tests/test_hookspecs.py`: 10 tests
- Added `conflict-resolution/additional-hookspecs.md`

**Simplification vs old repo:** 6 hooks instead of 10. No changes to `plugin_manager.py` needed (hookspecs auto-register via `add_hookspecs`).

---

## Step 3: mutmut-llm package scaffold + config + cache — DONE

**What:** Create the `mutmut-llm/` package with configuration loading and file-based mutation cache.

**Why:** Foundation for all LLM features. Config reads API key and model settings. Cache stores/retrieves LLM-generated mutations on disk so the expensive API calls happen once.

**Cache isolation:** The cache is 100% plugin-internal. `cache.py` imports zero mutmut modules (stdlib only: `hashlib`, `json`, `pathlib`). `operators.py` reads from cache internally and yields CST nodes through the standard `mutmut_register_operators` hook. Mutmut core never sees, touches, or knows about the cache. Zero complexity leaks to the host.

**Delivered:**
- `mutmut-llm/pyproject.toml`: package metadata, deps (mutmut, pluggy, anthropic), entry point `mutmut_llm.plugin`
- `mutmut-llm/src/mutmut_llm/__init__.py`
- `mutmut-llm/src/mutmut_llm/plugin.py`: stub entry point (auto-discovered by pluggy)
- `mutmut-llm/src/mutmut_llm/config.py` (~80 LOC): `LLMConfig` dataclass, `load_config()` with explicit `pyproject_path` and `env` params for testability. No singleton.
- `mutmut-llm/src/mutmut_llm/cache.py` (~110 LOC): `CacheEntry`/`CachedMutation` dataclasses, `write_cache_entry()`, `read_cache_entry()`, `list_cache_entries()`, `clear_cache()`, `source_hash()`. Cache in `.mutmut-cache/llm/`.
- `mutmut-llm/tests/test_config.py`: 18 tests (defaults, env var, pyproject.toml, find_pyproject, read_toml_section, priority)
- `mutmut-llm/tests/test_cache.py`: 20 tests (source_hash, write/read round-trip, hash keying, missing entries, list, clear, serialization)
- Updated workspace `pyproject.toml` to include `mutmut-llm` as workspace member

**Simplification vs old repo:**
- No model pricing table (defer to reporting step)
- No unknown-model validation warnings
- No singleton caching pattern — `load_config()` takes explicit params, returns fresh instance
- `CachedMutation` has 2 fields (not 3): dropped `mutation_type` (unnecessary indirection)
- ~190 LOC total vs ~250 in old repo

---

## Step 4: Prompts + validation (lightweight)

**What:** LLM prompt templates, response parsing, and lightweight mutation validation.

**Why:** Before we can call the LLM, we need to know what to ask and how to parse the response. Before we can use the response, we need to validate it's syntactically correct and doesn't introduce new dependencies.

**Security strategy — prompt-first, not scan-first:**

The old repo had 37 regex patterns + a CST visitor (~250 LOC) for post-hoc security scanning. For v1 we replace most of that with a layered approach:

1. **Prompt constraints** (free, first line of defense): The system prompt explicitly forbids dangerous operations: "Only modify control flow, return values, conditions, and arithmetic. Never introduce calls to `os`, `subprocess`, `eval`, `exec`, `pickle`, `socket`, `requests`, or any I/O. Only use functions and methods already present in the original code."
2. **Import validation** (~20 LOC, mechanical guarantee): Reject any mutation that adds imports not in the original source. This structurally blocks the most dangerous categories — you can't call `subprocess.run()` if you can't import `subprocess`.
3. **Syntax validation** (already needed): `libcst.parse_module()` catches malformed LLM output.

The remaining gap — original code already imports `os` and LLM adds `os.system("bad")` — is low-risk: mutations run in a test environment with the test suite as the safety net. If real-world usage reveals prompt-bypassing patterns, a regex scanner can be added as a future step (see Deferred section).

**Scope:**
- `mutmut-llm/src/mutmut_llm/prompts.py` (~90 LOC): `build_system_prompt()`, `build_user_prompt()`, `parse_llm_response()`. JSON output format. System prompt includes explicit security constraints. Strip equivalence detection prompts (defer to Step 9).
- `mutmut-llm/src/mutmut_llm/validation.py` (~30 LOC): 2-stage pipeline: (1) syntax check via `libcst.parse_module()`, (2) import guard — extract imports from original and mutated, reject if mutated introduces new ones.
- Tests for each module: prompt construction, JSON parsing with malformed input, import validation edge cases

**Simplification vs old repo:**
- ~120 LOC total vs ~420 LOC (71% reduction)
- No `security.py` module at all — prompt constraints + import guard replace 37 regex patterns
- No CST visitor for aliased imports
- No equivalence prompts

---

## Step 5: LLM operator + generation pipeline + `mutmut generate`

**What:** The core LLM mutation feature: generate mutations via API call, cache them, replay during test runs.

**Why:** This is the primary differentiator. After this step, users can run `mutmut generate` to pre-generate LLM mutations, then `mutmut run` picks them up automatically.

**Scope:**
- `mutmut-llm/src/mutmut_llm/operators.py` (~90 LOC): `operator_llm(node: cst.FunctionDef)` reads from cache, yields mutated FunctionDef nodes. Lazy in-memory index.
- `mutmut-llm/src/mutmut_llm/scope.py` (~80 LOC): **Deep mode only** — walk `paths_to_mutate`, extract all functions via libcst. Uniform budget allocation (equal per function). No git integration, no PR mode.
- `mutmut-llm/src/mutmut_llm/pipeline.py` (~100 LOC): `run_generation()` orchestrator. For each function: build prompt → call API → parse response → validate → cache. Uses anthropic SDK.
- `mutmut-llm/src/mutmut_llm/plugin.py` (~40 LOC): `mutmut_register_operators` + `mutmut_configure` + `mutmut_register_commands` (generate command only).
- CLI: `mutmut generate [--budget N]` (deep mode, all functions)
- Tests: mock API calls, test operator cache lookup, test pipeline orchestration
- E2E test with `@pytest.mark.e2e_live` for real API calls

**Simplification vs old repo:**
- Deep mode only (no PR/targeted scope) — ~80 LOC vs ~360 LOC for scope.py
- No cost tracking display
- No truncation detection warnings
- Minimal CLI flags (just `--budget`)
- ~310 LOC total vs ~580 in old repo

---

## Step 6: Storage + result tracking + reporting (merged with old Step 7)

**What:** JSON-file storage for LLM mutation run history, per-mutant results, and terminal reporting. Matches core mutmut's JSON-in-`mutants/` pattern.

**Why:** Without persistence, you lose all run data when the process exits. Storage enables: "which LLM mutations survived?", "what's my kill rate over time?". Reporting is tightly coupled — it reads from storage — so they ship together.

**Design decisions:**
- **JSON files, not SQLite.** Core mutmut uses JSON `.meta` files in `mutants/`. The LLM plugin follows suit: JSON files in `.mutmut-cache/llm/runs/`. No new dependency, consistent with the existing cache pattern.
- **No `mutmut_pre_test` hook.** Dropped — `mutmut_post_test` already provides `mutant_name`, `status`, and `duration`. The plugin knows which mutants are LLM-generated from its own cache (keyed by function source hash). No submodule patch needed.
- **LLM vs builtin tracking** via `mutmut_mutations_created` hook (already exists). Plugin matches mutant names against its cache index to tag them.

**Scope:**
- `mutmut-llm/src/mutmut_llm/storage.py` (~80 LOC):
  - `RunResult` dataclass: `run_id`, `started_at`, `completed_at`, `results: list[MutantResult]`
  - `MutantResult` dataclass: `mutant_name`, `status`, `duration`, `is_llm`
  - `save_run()`, `load_run()`, `list_runs()`, `load_latest_run()`
  - Storage dir: `.mutmut-cache/llm/runs/{run_id}.json`
- `mutmut-llm/src/mutmut_llm/reporting.py` (~60 LOC):
  - Terminal table: Status, Mutant, File, Function, Type (builtin/llm)
  - Summary line: total, killed, survived, kill rate, LLM vs builtin breakdown
- Update `plugin.py`:
  - `mutmut_mutations_created` hookimpl: record which mutant names are LLM-generated
  - `mutmut_post_test` hookimpl: accumulate per-mutant results
  - `mutmut_post_run` hookimpl: finalize and save run to JSON
  - `mutmut llm-status` CLI command: cache entry count, last run stats, config summary
- Tests: storage round-trip, run lifecycle, reporting format, integration with plugin hooks

**Simplification vs old repo:**
- JSON files instead of SQLite — zero new dependencies
- No `mutmut_pre_test` submodule patch — zero submodule changes
- 4 fields per mutant result instead of 12
- 1 report format instead of 4 (defer JUnit, Stryker, GitHub)
- ~140 LOC vs ~530 in old repo (storage + reporting combined)

---

## Step 7: PR and targeted scope modes

**What:** Git-aware mutation scope for CI workflows.

**Why:** `mutmut generate --scope pr` is the killer CI feature — only generate LLM mutations for changed code, saving API budget.

**Scope:**
- Extend `scope.py`: add `scope_pr()` (git diff vs base branch, extract changed functions) and `scope_targeted()` (explicit file:function specs)
- Priority-based budget allocation (complexity proxy)
- CLI flags: `--scope pr|targeted|deep`, `--targets`, `--base-branch`
- Tests: mock git output, test budget allocation

**Simplification vs old repo:** Port as-is from old repo — this was well-implemented there. ~200 LOC addition.

---

## Step 8: Deduplication + static equivalence detection

**What:** Remove duplicate and equivalent mutations before testing.

**Why:** LLMs sometimes generate mutations identical to builtins or to each other. Testing duplicates wastes time.

**Scope:**
- `mutmut-llm/src/mutmut_llm/dedup.py` (~140 LOC): AST normalization, per-function grouping, builtin priority
- `mutmut-llm/src/mutmut_llm/equivalence.py` (~150 LOC): Static checks only — identical AST, identity operations, dead code, commutative swaps. No behavioral or LLM-based detection.
- Wire into `mutmut_filter_mutations` hook
- Tests for each detection method

**Simplification vs old repo:**
- Static equivalence only (no behavioral, no LLM-based) — ~150 LOC vs ~416
- Total: ~290 LOC vs ~557 in old repo

---

## Deferred (not in initial port)

These can be added later based on real usage data:

| Feature | Why defer |
|---------|-----------|
| Regex security scanner (37 patterns + CST visitor) | Prompt constraints + import guard cover realistic threats; add if prompt bypasses observed |
| LLM-based equivalence detection | Expensive, low signal until we have usage data |
| Behavioral equivalence (stubborn mutants) | Needs multiple runs of history |
| JUnit/Stryker/GitHub reporting | Integration formats — terminal is enough to start |
| Cost tracking & model pricing | Nice-to-have display feature |
| `mutmut_select_tests` hook | Optimization for large test suites |
| `mutmut_skip_node` hook | Optimization for noisy nodes |

---

## LOC per step

| Step | New LOC | Submodule patch | Tests | Status |
|------|---------|----------------|-------|--------|
| 1. Whole-function mutations + function deletion | ~30 | Yes | 5 + 14 | **Done** |
| 2. Additional hookspecs | ~50 | Yes | 10 | **Done** |
| 3. Config + cache | ~190 | No | 38 | **Done** |
| 4. Prompts + validation | ~85 | No | 53 | **Done** |
| 5. LLM operator + pipeline + CLI | ~280 | No | 59 | **Done** |
| 6. Storage + reporting (merged) | ~160 | No | 49 | **Done** |
| 7. PR/targeted scope | ~200 | No | ~100 | Pending |
| 8. Dedup + static equivalence | ~290 | No | ~150 | Pending |
| **Total** | **~1,195** | | **~716+** | 6/8 done |

Old repo had ~2,500+ LOC for equivalent features. This is a **46% reduction**.

---

## Dependency chain

```
Step 1 (whole-function) ─── prerequisite for Step 5
Step 2 (hookspecs) ──────── prerequisite for Steps 5, 6, 7
Step 3 (config + cache) ─── prerequisite for Steps 4, 5
Step 4 (validation) ──────── prerequisite for Step 5
Step 5 (LLM core) ────────── prerequisite for Steps 6, 7, 8

Steps 1-4 can be developed in parallel (no cross-dependencies).
Steps 6-8 can be developed in any order after Step 5.
```
