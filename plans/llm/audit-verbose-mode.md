# Implementation Plan: LLM Audit / Verbose Mode

## Goal

Add `-v`/`--verbose` (0–3) and `--audit-log PATH` options to `mutmut generate`, exposing progressively detailed insight into prompts, validation decisions, caching, and retries — with a machine-readable NDJSON audit log for offline analysis.

---

## Wave 1 — Core data structures and helpers (no behavior change)

### Step 1.1 — `AuditEvent` dataclass and `AuditContext` coordinator

**File:** `mutmut-llm/src/mutmut_llm/audit.py` (new)

Create the event bus that threads through the pipeline.

```python
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ValidationDetail:
    index: int
    description: str
    passed: bool
    syntax: str        # "OK" or error
    imports: str       # "OK" or "new imports: X"
    pragmas: str       # "OK" or error


@dataclass
class BackoffEvent:
    attempt: int
    delay: float
    error_type: str
    error_message: str


@dataclass
class SystemBlock:
    index: int
    text: str
    has_cache_control: bool
    token_estimate: int


@dataclass
class CallAuditRecord:
    """One record per API call, written to audit log as NDJSON."""
    function_name: str
    file_path: str
    source_hash: str
    model: str
    attempt_number: int
    system_prompt_blocks: list[SystemBlock]
    user_prompt: str
    raw_response: str
    stop_reason: str
    parsed_mutations: list[dict]
    valid_mutations: list[dict]
    rejected_mutations: list[dict]   # each has "reason" key
    validation_details: list[ValidationDetail]
    usage: dict       # {input, output, cache_creation, cache_read}
    cost_usd: float
    duration_seconds: float
    backoff_events: list[BackoffEvent]


class AuditContext:
    """Thread-safe coordinator for verbose output and audit logging.

    Passed through the pipeline; each layer calls emit methods
    without knowing the output format.
    """

    def __init__(self, verbosity: int = 0, audit_log_path: Path | None = None) -> None:
        self.verbosity = verbosity
        self._audit_log_path = audit_log_path
        self._lock: asyncio.Lock | None = None  # lazy init in async context
        self._file = None

    async def _ensure_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def open(self) -> None:
        if self._audit_log_path:
            self._file = open(self._audit_log_path, "w")

    async def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None

    async def write_record(self, record: CallAuditRecord) -> None:
        if self._file is None:
            return
        lock = await self._ensure_lock()
        async with lock:
            line = json.dumps(_record_to_dict(record), default=str)
            self._file.write(line + "\n")
            self._file.flush()

    # Verbosity-guarded print helpers (sync, called from sync contexts too)
    def v1(self, msg: str) -> None:
        if self.verbosity >= 1:
            _echo(msg)

    def v2(self, msg: str) -> None:
        if self.verbosity >= 2:
            _echo(msg)

    def v3(self, msg: str) -> None:
        if self.verbosity >= 3:
            _echo(msg)


def _echo(msg: str) -> None:
    import click
    click.echo(msg)


def _record_to_dict(r: CallAuditRecord) -> dict:
    return {
        "function_name": r.function_name,
        "file_path": r.file_path,
        "source_hash": r.source_hash,
        "model": r.model,
        "attempt_number": r.attempt_number,
        "system_prompt_blocks": [
            {"text": b.text, "has_cache_control": b.has_cache_control, "token_estimate": b.token_estimate}
            for b in r.system_prompt_blocks
        ],
        "user_prompt": r.user_prompt,
        "raw_response": r.raw_response,
        "stop_reason": r.stop_reason,
        "parsed_mutations": r.parsed_mutations,
        "valid_mutations": r.valid_mutations,
        "rejected_mutations": r.rejected_mutations,
        "validation_details": [
            {"index": v.index, "description": v.description, "passed": v.passed,
             "syntax": v.syntax, "imports": v.imports, "pragmas": v.pragmas}
            for v in r.validation_details
        ],
        "usage": r.usage,
        "cost_usd": r.cost_usd,
        "duration_seconds": r.duration_seconds,
        "backoff_events": [
            {"attempt": b.attempt, "delay": b.delay, "error_type": b.error_type}
            for b in r.backoff_events
        ],
    }


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English/code."""
    return max(1, len(text) // 4)
```

**Acceptance:**
- `uv run --package mutmut-llm python -c "from mutmut_llm.audit import AuditContext, CallAuditRecord; print('OK')"`
- Unit tests in Step 1.2 pass

### Step 1.2 — Tests for `audit.py`

**File:** `mutmut-llm/tests/test_audit.py` (new)

Tests:
- `AuditContext(verbosity=0)` — `v1`/`v2`/`v3` produce no output (capsys)
- `AuditContext(verbosity=2)` — `v1` and `v2` print, `v3` does not
- `write_record` with no audit log path is a no-op
- `write_record` with a path writes valid NDJSON (parse each line with `json.loads`)
- `estimate_tokens` returns reasonable values (e.g., 100-char string → ~25 tokens)
- Concurrent `write_record` calls don't interleave (asyncio test: 10 tasks writing simultaneously, verify line count)

**Acceptance:** `uv run --package mutmut-llm pytest tests/test_audit.py -v`

### Step 1.3 — `format_system_blocks_debug` helper in `prompts.py`

**File:** `mutmut-llm/src/mutmut_llm/prompts.py`

Add a function that formats system blocks for `-vvv` display:

```python
def format_system_blocks_debug(blocks: list[dict]) -> str:
    """Format system blocks with cache_control annotations for verbose output."""
    from mutmut_llm.audit import estimate_tokens

    parts: list[str] = []
    for i, block in enumerate(blocks):
        text = block.get("text", "")
        tokens = estimate_tokens(text)
        cc = block.get("cache_control")
        if cc:
            cc_str = f"{cc.get('type', '?')}"
            ttl = cc.get("ttl")
            if ttl:
                cc_str += f"/{ttl}"
        else:
            cc_str = "NONE"

        label = "SYSTEM PROMPT" if i == 0 else f"CONTEXT (block {i})"
        parts.append(f"╔══ {label} (~{tokens} tokens, cache_control: {cc_str}) ══╗")
        parts.append(text)
        parts.append(f"╚══ END {label.split(' (')[0]} ══╝")

        if cc and tokens < 1024:
            parts.append(
                f"⚠ WARNING: cache_control on block {i} (~{tokens} tokens) — "
                "Anthropic requires ≥1024 tokens for caching to activate. "
                "Consider moving cache_control to a larger block or combining blocks."
            )

    return "\n".join(parts)
```

**Acceptance:**
- Existing `test_prompts.py` tests still pass
- New test: `format_system_blocks_debug` with 2-block input returns string containing `╔══ SYSTEM PROMPT`, `╔══ CONTEXT`, both `cache_control` annotations, and the warning when context block is small

### Step 1.4 — Tests for `format_system_blocks_debug`

**File:** `mutmut-llm/tests/test_prompts.py` — append new test class

```python
class TestFormatSystemBlocksDebug:
    def test_single_block_no_context(self):
        blocks = build_system_with_context("")
        output = format_system_blocks_debug(blocks)
        assert "SYSTEM PROMPT" in output
        assert "cache_control: ephemeral" in output

    def test_two_blocks_with_context(self):
        blocks = build_system_with_context("import os\nimport sys")
        output = format_system_blocks_debug(blocks)
        assert "SYSTEM PROMPT" in output
        assert "CONTEXT" in output
        assert "cache_control: NONE" in output  # block 0
        assert "cache_control: ephemeral" in output  # block 1

    def test_small_context_triggers_warning(self):
        blocks = build_system_with_context("import os")
        output = format_system_blocks_debug(blocks)
        assert "WARNING" in output
        assert "1024" in output

    def test_ttl_shown(self):
        blocks = build_system_with_context("ctx", ttl="1h")
        output = format_system_blocks_debug(blocks)
        assert "ephemeral/1h" in output
```

**Acceptance:** `uv run --package mutmut-llm pytest tests/test_prompts.py::TestFormatSystemBlocksDebug -v`

---

## Wave 2 — Validation transparency (individual validators return structured data)

### Step 2.1 — Extend `validate_mutation` to return structured results

**File:** `mutmut-llm/src/mutmut_llm/validation.py`

Add `validate_mutation_detailed` alongside existing `validate_mutation` (keep backward compat):

```python
@dataclass
class ValidationResult:
    syntax: str | None = None    # None = OK, str = error
    imports: str | None = None
    pragmas: str | None = None

    @property
    def passed(self) -> bool:
        return self.syntax is None and self.imports is None and self.pragmas is None

    @property
    def first_error(self) -> str | None:
        return self.syntax or self.imports or self.pragmas

    def summary(self) -> str:
        parts = []
        parts.append(f"syntax:{'OK' if self.syntax is None else self.syntax}")
        parts.append(f"imports:{'OK' if self.imports is None else self.imports}")
        parts.append(f"pragmas:{'OK' if self.pragmas is None else self.pragmas}")
        return ", ".join(parts)


def validate_mutation_detailed(mutated_code: str, original_code: str) -> ValidationResult:
    """Run all validators and return structured result instead of first-error string."""
    result = ValidationResult()
    result.syntax = validate_syntax(mutated_code)
    if result.syntax is None:
        result.imports = validate_imports(mutated_code, original_code)
        result.pragmas = validate_pragmas(mutated_code, original_code)
    return result
```

The existing `validate_mutation` stays unchanged (returns `str | None`).

**Acceptance:**
- Existing `test_validation.py` tests still pass
- New tests for `validate_mutation_detailed` added (Step 2.2)

### Step 2.2 — Tests for `ValidationResult` and `validate_mutation_detailed`

**File:** `mutmut-llm/tests/test_validation.py` — append new test class

Tests:
- Valid code → `.passed == True`, `.summary()` contains `"syntax:OK, imports:OK, pragmas:OK"`
- Syntax error → `.passed == False`, `.syntax` is truthy, `.imports` and `.pragmas` are `None` (skipped)
- New import → `.passed == False`, `.imports` contains "New imports"
- Pragma violation → `.passed == False`, `.pragmas` is truthy
- `first_error` returns the first non-None field

**Acceptance:** `uv run --package mutmut-llm pytest tests/test_validation.py -v`

---

## Wave 3 — Thread `AuditContext` through the pipeline

### Step 3.1 — Update `_call_llm_and_validate_async` to accept and use `AuditContext`

**File:** `mutmut-llm/src/mutmut_llm/pipeline.py`

Changes:
1. Add `audit: AuditContext | None = None` parameter to `_call_llm_and_validate_async`
2. Import `AuditContext`, `CallAuditRecord`, `SystemBlock`, `ValidationDetail`, `estimate_tokens` from `mutmut_llm.audit`
3. Import `validate_mutation_detailed` from `mutmut_llm.validation`
4. Import `format_system_blocks_debug` from `mutmut_llm.prompts`
5. Capture timing: `t0 = time.monotonic()` before API call, `duration = time.monotonic() - t0` after
6. After API call, before validation loop:
   - At verbosity ≥ 3: print system block debug, user prompt, raw response, stop_reason
   - At verbosity ≥ 2: print cache status (cache_creation vs cache_read tokens, activation warning)
7. Replace validation loop to use `validate_mutation_detailed`:
   ```python
   validation_details: list[ValidationDetail] = []
   valid: list[dict] = []
   rejected: list[dict] = []
   for i, m in enumerate(mutations):
       vr = validate_mutation_detailed(m["mutated_code"], target.source)
       desc = m.get("description", "")
       vd = ValidationDetail(
           index=i, description=desc, passed=vr.passed,
           syntax="OK" if vr.syntax is None else vr.syntax,
           imports="OK" if vr.imports is None else vr.imports,
           pragmas="OK" if vr.pragmas is None else vr.pragmas,
       )
       validation_details.append(vd)
       if vr.passed:
           valid.append(m)
           if audit and audit.verbosity >= 2:
               audit.v2(f"  ✓ [{i}] {desc}  [{vr.summary()}]")
       else:
           rejected.append({**m, "reason": vr.first_error})
           if audit and audit.verbosity >= 2:
               audit.v2(f"  ✗ [{i}] {desc}  [{vr.summary()}]")
           else:
               click.echo(f"    Rejected: {vr.first_error}")
   ```
   Note: when `audit` is None or `verbosity < 2`, preserve the existing `click.echo(f"    Rejected: {err}")` behavior.
8. Build `CallAuditRecord` and call `await audit.write_record(record)` if audit is present
9. At verbosity ≥ 1, print per-function summary line:
   ```
   fibonacci (claude-sonnet-4-6): 100+200 tokens, $0.0012, 3/5 mutations valid, cache:miss
   ```

Signature becomes:
```python
async def _call_llm_and_validate_async(
    client,
    config: LLMConfig,
    target: ScopeTarget,
    max_mutations: int,
    audit: AuditContext | None = None,
) -> GenerationResult:
```

**Critical constraint — zero cost at level 0:** Guard all string formatting behind `if audit and audit.verbosity >= N` checks. When `audit is None`, no `ValidationDetail` objects, no `CallAuditRecord`, no `format_system_blocks_debug` call.

**Acceptance:**
- Existing tests in `test_pipeline.py::TestCallLlmAndValidateAsync` still pass (they don't pass `audit`)
- New tests (Step 3.3) verify verbose output at each level

### Step 3.2 — Update `_call_llm_async` to thread `AuditContext` and emit retry events

**File:** `mutmut-llm/src/mutmut_llm/pipeline.py`

Changes:
1. Add `audit: AuditContext | None = None` parameter
2. Pass `audit` through to `_call_llm_and_validate_async`
3. On retry events, emit via `audit.v1()`:
   ```python
   if audit:
       audit.v1(f"  ⚠ Attempt {attempt + 1}/{config.max_retries} for {target.function_name} ({type(exc).__name__}, backoff {backoff_delay:.1f}s)")
   ```
4. Collect `BackoffEvent` instances when `audit` is not None, pass to `_call_llm_and_validate_async` context (or accumulate in the audit record at the wrapper level)

Signature becomes:
```python
async def _call_llm_async(
    client,
    config: LLMConfig,
    target: ScopeTarget,
    max_mutations: int,
    semaphore: TrackedSemaphore,
    cancel_event: asyncio.Event,
    audit: AuditContext | None = None,
) -> GenerationResult:
```

**Acceptance:** Existing async tests still pass. Retry test verifies warning message emitted at v1.

### Step 3.3 — Update `_generate_mutations_async` to create/pass `AuditContext`

**File:** `mutmut-llm/src/mutmut_llm/pipeline.py`

Changes:
1. Add `verbosity: int = 0` and `audit_log: Path | None = None` parameters
2. Create `AuditContext(verbosity, audit_log)` at function entry
3. Call `await audit.open()` before the work loop and `await audit.close()` in a `finally` block
4. Pass `audit` to each `_call_llm_async` task
5. At verbosity ≥ 1, before the work loop, print scope resolution summary (R3):
   ```
   Scope: 42 functions discovered, 38 queued (4 cached)
   Budget: 5 mutations/function, 20 API calls max
   Processing order: a.py::foo, a.py::bar, b.py::baz, ...
   ```
6. At verbosity ≥ 1, after the work loop, print enhanced summary with token breakdown:
   ```
   Tokens: 12,400 input, 3,200 output, 800 cache_write, 9,000 cache_read
   ```
7. At verbosity ≥ 3, print per-function full prompt dump (R5) — this is already handled inside `_call_llm_and_validate_async`

Signature becomes:
```python
async def _generate_mutations_async(
    config: LLMConfig,
    targets: list[ScopeTarget],
    budget_per_target: dict[str, int],
    total_budget: int,
    base_dir: Path | None,
    verbosity: int = 0,
    audit_log: Path | None = None,
) -> int:
```

### Step 3.4 — Update `run_generation` to accept and forward verbose params

**File:** `mutmut-llm/src/mutmut_llm/pipeline.py`

Change signature:
```python
def run_generation(
    config: LLMConfig,
    paths: list[str],
    budget: int,
    dry_run: bool = False,
    base_dir: Path | None = None,
    verbosity: int = 0,
    audit_log: Path | None = None,
) -> int:
```

Forward `verbosity` and `audit_log` to `_generate_mutations_async`.

Also update `_generate_mutations` (sync wrapper) if it remains.

**Acceptance:**
- All existing `test_pipeline.py` tests pass (default `verbosity=0`, `audit_log=None`)
- `run_generation(..., verbosity=0)` produces identical output to current behavior

### Step 3.5 — Pipeline verbose output tests

**File:** `mutmut-llm/tests/test_pipeline.py` — new test class `TestVerboseOutput`

Tests (using `capsys` and mock client):
1. `verbosity=0` — output matches current behavior exactly (regression test)
2. `verbosity=1` — output contains per-function summary (tokens, cost, model), scope summary, and no prompt dumps
3. `verbosity=2` — output contains validation `✓`/`✗` lines with bracketed detail
4. `verbosity=3` — output contains `╔══ SYSTEM PROMPT`, `╔══ USER PROMPT`, `╔══ RAW RESPONSE`
5. `verbosity=1` with retry — output contains `⚠ Attempt` line
6. `verbosity=2` with small context block — output contains `WARNING` about <1024 tokens

Tests for audit log:
7. `audit_log=tmp_path / "audit.ndjson"` — file created, each line is valid JSON, correct field set
8. `audit_log` without `verbosity` — log file written but no extra console output
9. Concurrent API calls — audit log has correct line count (one per call)

**Acceptance:** `uv run --package mutmut-llm pytest tests/test_pipeline.py::TestVerboseOutput -v`

---

## Wave 4 — CLI integration and sync wrapper

### Step 4.1 — Add `--verbose` and `--audit-log` to `generate` command

**File:** `mutmut-llm/src/mutmut_llm/plugin.py`

Changes to `mutmut_register_commands`:
```python
@cli_group.command()
@click.option("--budget", type=int, default=20, help="Max API calls.")
@click.option("--dry-run", is_flag=True, help="Show functions without calling LLM.")
@click.option("--paths", multiple=True, help="Paths to scan (overrides mutmut config).")
@click.option("-v", "--verbose", count=True, help="Verbosity level (0-3, repeat for more).")
@click.option("--audit-log", type=click.Path(dir_okay=False), default=None, help="Write NDJSON audit log to PATH.")
def generate(budget: int, dry_run: bool, paths: tuple[str, ...], verbose: int, audit_log: str | None) -> None:
    """Generate LLM mutations for functions in scope."""
    from pathlib import Path as P
    from mutmut_llm.pipeline import run_generation

    config = _llm_config or load_config()
    scan_paths = list(paths) if paths else (_mutmut_paths or ["src"])
    run_generation(
        config=config,
        paths=scan_paths,
        budget=budget,
        dry_run=dry_run,
        verbosity=min(verbose, 3),
        audit_log=P(audit_log) if audit_log else None,
    )
```

**Acceptance:**
- `mutmut generate --help` shows `-v`/`--verbose` and `--audit-log`
- Existing `test_plugin.py` tests still pass
- New CLI-level test: invoke `generate` with `-v` via Click test runner

### Step 4.2 — Update `_call_llm_and_validate` (sync version) for consistency

**File:** `mutmut-llm/src/mutmut_llm/pipeline.py`

The sync `_call_llm_and_validate` is used in tests. Add `audit: AuditContext | None = None` param for symmetry, but keep it optional with default `None`. When `audit is None`, behavior is identical to current.

**Acceptance:** Existing sync tests still pass.

### Step 4.3 — Plugin audit for mutant classification (R7)

**File:** `mutmut-llm/src/mutmut_llm/plugin.py`

Changes to `mutmut_mutations_created`:
1. Import the global `AuditContext` or check a module-level verbosity flag
2. At verbosity ≥ 2, after classifying LLM mutants, print per-function breakdown:
   ```
   fibonacci: 3 builtin, 2 LLM
   ```
3. At verbosity ≥ 3, print first 500 chars of `source_by_mutant_name` dict

**Design decision:** Since `mutmut_mutations_created` is a hook called by mutmut core (not during `generate`), the verbosity setting needs to be stored at module level. Add `_verbosity: int = 0` module global, set from `mutmut_configure` or from the `generate` command. This is acceptable because:
- The plugin is single-process
- `mutmut_configure` runs before any hooks
- The global is reset by `_reset_plugin_state` in tests

```python
_verbosity: int = 0

@hookimpl
def mutmut_mutations_created(filename: str, source_by_mutant_name: dict[str, str]) -> None:
    # ... existing logic ...
    
    if _verbosity >= 2:
        for func_name, mutant_names in mutants_by_func.items():
            llm_count = llm_counts.get(func_name, 0)
            builtin_count = len(mutant_names) - llm_count
            click.echo(f"  {func_name}: {builtin_count} builtin, {llm_count} LLM")

    if _verbosity >= 3:
        truncated = str(source_by_mutant_name)[:500]
        click.echo(f"  source_by_mutant_name: {truncated}...")
```

**Acceptance:**
- At `_verbosity=0`, no extra output from `mutmut_mutations_created`
- At `_verbosity=2`, per-function breakdown printed
- Test via monkeypatch setting `_verbosity` and calling hook directly

### Step 4.4 — CLI and plugin tests

**File:** `mutmut-llm/tests/test_plugin.py` — append tests

Tests:
- Click test runner: `generate -v` sets `verbose=1`
- Click test runner: `generate -vvv` sets `verbose=3`
- Click test runner: `generate --audit-log /tmp/test.ndjson` passes path
- `mutmut_mutations_created` at verbosity 2 prints counts
- `mutmut_mutations_created` at verbosity 0 prints nothing extra

**Acceptance:** `uv run --package mutmut-llm pytest tests/test_plugin.py -v`

---

## Wave 5 — Cache status display at v1 and prompt caching bug warning

### Step 5.1 — Cache status in per-function v1 output

**File:** `mutmut-llm/src/mutmut_llm/pipeline.py`

In `_call_llm_and_validate_async`, after getting the response usage:
```python
if audit and audit.verbosity >= 1:
    cache_status = "hit" if cache_read_tokens > 0 else "miss"
    audit.v1(
        f"  {target.function_name} ({config.model}): "
        f"{input_tokens}+{output_tokens} tokens, "
        f"{format_cost(cost_usd)}, "
        f"{len(valid)}/{len(mutations)} valid, "
        f"cache:{cache_status}"
    )
```

### Step 5.2 — Prompt caching bug warning at v2+

In `_call_llm_and_validate_async`, after printing system blocks at v3 or validating at v2, add a cache activation check:

```python
if audit and audit.verbosity >= 2:
    if cache_creation_tokens == 0 and cache_read_tokens == 0:
        for i, block in enumerate(system_blocks):
            if "cache_control" in block:
                tokens = estimate_tokens(block["text"])
                if tokens < 1024:
                    audit.v2(
                        f"  ⚠ CACHE NOT ACTIVE: block {i} has cache_control but "
                        f"~{tokens} tokens (min 1024). Move cache_control to "
                        "the system prompt block or combine blocks."
                    )
```

**Acceptance:** Test at v2 with a small context block verifies the warning appears.

---

## Files to Modify

| File | Changes |
|------|---------|
| `mutmut-llm/src/mutmut_llm/audit.py` | **NEW** — `AuditContext`, `CallAuditRecord`, dataclasses, NDJSON writer |
| `mutmut-llm/src/mutmut_llm/prompts.py` | Add `format_system_blocks_debug()` |
| `mutmut-llm/src/mutmut_llm/validation.py` | Add `ValidationResult` dataclass, `validate_mutation_detailed()` |
| `mutmut-llm/src/mutmut_llm/pipeline.py` | Thread `AuditContext` through `run_generation` → `_generate_mutations_async` → `_call_llm_async` → `_call_llm_and_validate_async`; add verbose output at each level; structured validation; scope summary; token breakdown |
| `mutmut-llm/src/mutmut_llm/plugin.py` | Add `--verbose`/`--audit-log` CLI options; module-level `_verbosity`; R7 plugin audit in `mutmut_mutations_created` |

## New Files

| File | Purpose |
|------|---------|
| `mutmut-llm/src/mutmut_llm/audit.py` | Core audit infrastructure |
| `mutmut-llm/tests/test_audit.py` | Tests for `AuditContext`, NDJSON writer |

## Modified Test Files

| File | Changes |
|------|---------|
| `mutmut-llm/tests/test_prompts.py` | `TestFormatSystemBlocksDebug` class |
| `mutmut-llm/tests/test_validation.py` | `TestValidationResult` and `TestValidateMutationDetailed` classes |
| `mutmut-llm/tests/test_pipeline.py` | `TestVerboseOutput` class (v0–v3 output, audit log, retries) |
| `mutmut-llm/tests/test_plugin.py` | CLI option tests, R7 hook output tests |
| `mutmut-llm/tests/conftest.py` | Add `_verbosity` to `_reset_plugin_state` monkeypatch |

---

## Dependencies

```
Wave 1 (Steps 1.1–1.4): independent
Wave 2 (Steps 2.1–2.2): independent, parallel with Wave 1
Wave 3 (Steps 3.1–3.5): depends on Wave 1 + Wave 2
Wave 4 (Steps 4.1–4.4): depends on Wave 3 (Step 3.4 specifically)
Wave 5 (Steps 5.1–5.2): depends on Wave 3
```

Within waves:
- 1.1 → 1.2 (tests need the module)
- 1.3 → 1.4
- 2.1 → 2.2
- 3.1 → 3.2 → 3.3 → 3.4 → 3.5
- 4.1 depends on 3.4; 4.3 is independent of 4.1

---

## Risks

1. **Async file I/O in audit log**: `open()`/`write()` are blocking. For the expected volume (tens to low-hundreds of records), this is fine. If it becomes a bottleneck, switch to `aiofiles` or an `asyncio.Queue` + writer task. Keep this as a documented future optimization, not a launch blocker.

2. **Test pollution from module-level `_verbosity`**: Mitigated by `_reset_plugin_state` in `conftest.py`. Must remember to add `_verbosity` to the monkeypatch list.

3. **Backward compatibility of `run_generation` signature**: All new params have defaults. Existing callers (the `generate` command in `plugin.py`) are updated in the same wave. The sync `_generate_mutations` wrapper must also be updated.

4. **`_call_llm_and_validate` sync version divergence**: The sync version is used in `TestCallLlmAndValidate`. It must mirror the async version's validation logic changes (using `validate_mutation_detailed` when audit is present). Alternatively, keep the sync version simple (no audit support) and only add audit to the async path — the sync path is only used in unit tests, not production.

5. **`estimate_tokens` accuracy**: The `len(text) // 4` heuristic is rough. Anthropic's actual tokenizer (tiktoken-compatible) would be more accurate but adds a dependency. The heuristic is sufficient for the warning threshold (1024 tokens ≈ 4096 chars) and display purposes.

6. **Output interleaving with tqdm**: At verbosity ≥ 1, verbose output interleaves with the tqdm progress bar. Use `tqdm.write()` instead of `click.echo()` when tqdm is active, or disable tqdm at verbosity ≥ 1 and replace with plain-text progress. **Recommended approach**: At verbosity ≥ 1, disable the tqdm bar (set `disable=True`) and rely on per-function verbose lines as progress indication. This avoids the interleaving problem entirely.

7. **No `mutmut/` changes required**: All additions are in `mutmut-llm/`. The `mutmut_mutations_created` hook already provides the `source_by_mutant_name` dict needed for R7. No upstream patches needed.

---

## Reviewer Checklist (per step)

- [ ] No new output at `verbosity=0` (regression)
- [ ] All string formatting guarded by `if verbosity >= N` or `if audit and audit.verbosity >= N`
- [ ] No `dict` or `dataclass` allocation in the hot path when `audit is None`
- [ ] `asyncio.Lock` used for audit log writes, not `threading.Lock`
- [ ] Existing tests pass without modification (backward compat)
- [ ] New tests use `capsys` for output verification, not string matching on stderr
- [ ] `format_cost` used for all cost display (consistency)
- [ ] No imports from `mutmut/` submodule added (plugin isolation)
