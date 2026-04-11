# Prompt Caching Strategy — Fix Placement and Grow the System Prompt

## Problem statement

Anthropic's prompt cache is not activating. Two root causes:

1. **Wrong block.** `cache_control` sits on the *context block* (file imports, ~21 tokens) instead
   of the *system prompt block* (~621 tokens). When context is present, the large constant block
   gets no `cache_control` at all.

2. **System prompt too small.** Even with correct placement, the system prompt at ~621 tokens
   falls below Anthropic's minimum of **1024 tokens** for caching to activate. Any block smaller
   than 1024 tokens with `cache_control` is silently ignored.

Current `build_system_with_context` logic:

```python
blocks = [{"type": "text", "text": SYSTEM_PROMPT}]          # no cache_control
if context:
    blocks.append({..., "cache_control": cache_control})    # cache_control on ~21-token block
else:
    blocks[-1]["cache_control"] = cache_control             # only fires when context is empty
```

The consequence: `cache_creation_tokens` and `cache_read_tokens` are always 0 in practice,
meaning every API call re-sends the full system prompt and pays full input-token prices.

---

## Correct architecture

Prompt caching is a **prefix KV cache**. The `cache_control` marker says "cache everything up to
and including this block." The most stable prefix should always be cached first.

The three layers of a generation call, by stability:

```
[system: SYSTEM_PROMPT]     — identical across every call, ever        ← cache this first
[system: FILE_CONTEXT]      — identical across all functions in a file ← cache this second
[user:   FUNCTION_SOURCE]   — unique per call                          ← never cached
```

The correct block structure:

```python
# Block 0: system prompt — cache_control always present
{"type": "text", "text": SYSTEM_PROMPT, "cache_control": cc}

# Block 1: file context — cache_control present (stacks on top of block 0 cache)
{"type": "text", "text": f"File context:\n```python\n{context}\n```", "cache_control": cc}
```

With this layout:
- Every call benefits from the block-0 cache (same system prompt always).
- Calls within the same file additionally benefit from the block-0+1 cache.

For either cache to activate, the cached block must be ≥1024 tokens. Block 0 must therefore
exceed 1024 tokens. This drives the need to grow the system prompt.

---

## Part 1 — Fix `cache_control` placement (immediate, mechanical)

**Files changed:** `mutmut-llm/src/mutmut_llm/prompts.py`

Replace `build_system_with_context`:

```python
def build_system_with_context(context: str = "", ttl: str = "5m") -> list[dict]:
    """Build system blocks with cache_control on every block.

    Block 0: system prompt (always present, always cache_control).
    Block 1: file context (only when context is non-empty, also cache_control).

    Both blocks are marked so the deepest matching prefix is cached.
    Caching only activates when the cached block reaches ≥1024 tokens
    (Anthropic minimum). See plans/llm/prompt-caching-strategy.md.
    """
    cc: dict = {"type": "ephemeral"}
    if ttl == "1h":
        cc["ttl"] = "1h"

    blocks: list[dict] = [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": cc}
    ]

    if context.strip():
        blocks.append({
            "type": "text",
            "text": f"File context (imports, class headers):\n```python\n{context.strip()}\n```",
            "cache_control": cc,
        })

    return blocks
```

### Acceptance criteria

```bash
# Block 0 always has cache_control, regardless of context
uv run --package mutmut-llm python -c "
from mutmut_llm.prompts import build_system_with_context
b = build_system_with_context('')
assert 'cache_control' in b[0], 'block 0 must have cache_control'
assert len(b) == 1
print('AC1 PASS: no-context case — block 0 has cache_control')
"

# With context: both blocks have cache_control
uv run --package mutmut-llm python -c "
from mutmut_llm.prompts import build_system_with_context
b = build_system_with_context('import os\nimport sys')
assert 'cache_control' in b[0], 'block 0 must have cache_control'
assert 'cache_control' in b[1], 'block 1 must have cache_control'
assert len(b) == 2
print('AC2 PASS: context case — both blocks have cache_control')
"

# cache_control placement survives ttl=1h
uv run --package mutmut-llm python -c "
from mutmut_llm.prompts import build_system_with_context
b = build_system_with_context('import os', ttl='1h')
assert b[0]['cache_control'] == {'type': 'ephemeral', 'ttl': '1h'}
assert b[1]['cache_control'] == {'type': 'ephemeral', 'ttl': '1h'}
print('AC3 PASS: 1h TTL on both blocks')
"

# Full test suite still passes
uv run --package mutmut-llm pytest mutmut-llm/tests/ -q --tb=short 2>&1 | tail -4
```

### Existing test updates

`test_prompts.py` has tests that assert block count and `cache_control` presence.
Check whether any assert block 0 lacks `cache_control` when context is present — update those.

### Why this alone is not enough

Even with correct placement, the system prompt at ~621 tokens is below 1024. Caching will not
activate for the e2e test project or any project whose file context is small. Part 2 solves this.

---

## Part 2 — Grow the system prompt to ≥1024 tokens via DSPy optimization

### Goal

Produce a new `SYSTEM_PROMPT` that:
- Is ≥1024 tokens (so block-0 caching always activates)
- Is demonstrably higher quality than the current hand-written prompt (measurable: more mutations
  survive validation, more are non-trivial, better description quality)
- Fits within a fixed token budget (target: 1200–1600 tokens — enough to activate caching
  without inflating cost significantly)

### Why DSPy

The current prompt was written by hand. Expanding it by hand (adding more examples, more rules)
risks bloating it with irrelevant content or reinforcing existing biases. DSPy
(https://dspy.ai) treats prompts as learnable parameters and optimizes them against a metric.

DSPy's `MIPROv2` (or `BootstrapFewShot`) optimizer:
1. Takes a *signature* (input/output spec) and a *metric* (score function)
2. Generates candidate instruction variants and few-shot demonstrations
3. Evaluates each candidate against a held-out set
4. Returns the combination that maximises the metric

This gives us a principled way to find a high-quality, correctly-sized prompt without guessing.

### DSPy integration design

DSPy will be used as an **offline optimization tool**, not a runtime dependency. The workflow:

```
[offline]  run dspy optimizer → produces optimized SYSTEM_PROMPT string
[commit]   paste the optimized string into prompts.py as the new SYSTEM_PROMPT constant
[runtime]  mutmut-llm uses the constant — zero DSPy dependency at runtime
```

DSPy is added to a new `[dependency-groups] optimizer` section in `mutmut-llm/pyproject.toml`
so it is never pulled into production installs.

### Step 2.1 — DSPy exploration scaffold

**File:** `mutmut-llm/optimizer/` (new directory, not a package — scripts only)

```
mutmut-llm/optimizer/
├── README.md          # how to run the optimizer
├── signature.py       # DSPy signature for mutation generation
├── dataset.py         # collect training examples from real cached mutations
├── metric.py          # scoring function (quality + token budget)
├── optimize.py        # main script: run MIPROv2, emit optimized prompt
└── evaluate.py        # compare current prompt vs optimized prompt on held-out set
```

#### `signature.py`

```python
"""DSPy signature for LLM mutation generation."""
import dspy


class MutationGenerator(dspy.Signature):
    """Generate subtle code mutations that a weak test suite might fail to detect.

    Mutations must be syntactically valid Python, change observable behavior,
    and avoid trivial operator swaps already handled by rule-based operators.
    """

    function_source: str = dspy.InputField(
        desc="Complete Python function definition to mutate"
    )
    file_context: str = dspy.InputField(
        desc="File-level imports and class headers relevant to the function",
        default="",
    )
    max_mutations: int = dspy.InputField(
        desc="Maximum number of mutations to generate", default=5
    )
    mutations_json: str = dspy.OutputField(
        desc=(
            'JSON array of mutation objects: '
            '[{"mutated_code": "...", "description": "..."}]'
        )
    )
```

#### `dataset.py`

Collect training/validation examples from two sources:

1. **Real cache entries** — scrape `list_cache_entries()` from any project that has run
   `mutmut generate`. Each entry provides `(function_source, context, mutations)`.
2. **Synthetic curated set** — 20–30 hand-written (function, ideal_mutations) pairs covering
   representative patterns: boundary conditions, loop invariants, state bugs, wrong API usage.

The curated set must include at least:
- A function with a loop and an off-by-one boundary (like `fibonacci`)
- A function with a guard clause (`window <= 0`)
- A function with string manipulation (`is_palindrome`)
- A function with accumulator state (`moving_average`)
- A class method with self-mutation opportunities
- A function using external API with error handling

Split: 80% train / 20% validation.

```python
# dataset.py
from dataclasses import dataclass
from mutmut_llm.cache import list_cache_entries

@dataclass
class MutationExample:
    function_source: str
    context: str
    expected_mutations: list[dict]   # {"mutated_code": ..., "description": ..., "quality": 0-3}
    function_name: str
    difficulty: str   # "easy" | "medium" | "hard"

def load_from_cache() -> list[MutationExample]: ...
def load_curated() -> list[MutationExample]: ...
def train_val_split(examples, val_ratio=0.2) -> tuple[list, list]: ...
```

#### `metric.py`

The metric must capture *quality* without requiring human judges at runtime. Use a combination:

```python
def score_mutation_set(
    pred_json: str,
    example: MutationExample,
    original_prompt_tokens: int,
) -> float:
    """
    Score a predicted mutation set (0.0 – 1.0).

    Components:
      - validity_rate:    fraction of mutations that pass validate_mutation()         (weight 0.35)
      - non_trivial_rate: fraction that change structure beyond operator swaps         (weight 0.25)
      - coverage_proxy:   fraction of distinct AST node types mutated                 (weight 0.20)
      - description_quality: avg len(description) clipped to [50, 200] / 200          (weight 0.10)
      - token_budget_penalty: 0 if prompt ≥ 1024 tokens, else -0.5                   (weight 0.10)
    """
```

The `token_budget_penalty` term actively pushes the optimizer toward prompts that exceed 1024
tokens, directly tying the caching threshold into the quality objective.

#### `optimize.py`

```python
"""Run DSPy MIPROv2 to find the best system prompt.

Usage:
    uv run --with dspy-ai --package mutmut-llm python mutmut-llm/optimizer/optimize.py \
        --model claude-sonnet-4-6 \
        --max-demos 8 \
        --num-trials 30 \
        --output optimized_prompt.txt
"""
import dspy
from mutmut_llm.optimizer.signature import MutationGenerator
from mutmut_llm.optimizer.dataset import load_curated, train_val_split
from mutmut_llm.optimizer.metric import score_mutation_set

def main(model: str, max_demos: int, num_trials: int, output: str):
    lm = dspy.LM(model=f"anthropic/{model}", cache=True)
    dspy.configure(lm=lm)

    program = dspy.Predict(MutationGenerator)
    train, val = train_val_split(load_curated())

    metric = lambda example, pred, trace=None: score_mutation_set(
        pred.mutations_json, example, ...
    )

    optimizer = dspy.MIPROv2(metric=metric, num_candidates=num_trials, max_bootstrapped_demos=max_demos)
    optimized = optimizer.compile(program, trainset=train, valset=val)

    # Extract the optimized instruction string
    instruction = optimized.signature.instructions
    print(f"Optimized instruction ({len(instruction.split()) * 1.3:.0f} est. tokens):")
    print(instruction)

    with open(output, "w") as f:
        f.write(instruction)
```

#### `evaluate.py`

Side-by-side comparison of current prompt vs optimized prompt on the held-out validation set.
Outputs a Markdown table:

| Metric | Current | Optimized | Delta |
|--------|---------|-----------|-------|
| validity_rate | 0.82 | 0.91 | +0.09 |
| non_trivial_rate | 0.61 | 0.78 | +0.17 |
| avg_mutations | 3.1 | 4.4 | +1.3 |
| token_count | 621 | 1342 | +721 |
| cache_activates | NO | YES | ✓ |
| cost_per_call (est) | $0.0091 | $0.0033* | -64%* |

*Estimated after cache warm-up assuming 10-call batches from the same file.

### Step 2.2 — Run the optimizer and select a candidate

**This is an experimental, human-in-the-loop step.** The process:

1. Run `optimize.py` with `--num-trials 30` against the curated dataset.
2. Review the top 3 candidate prompts from the optimizer output:
   - Check they are coherent English instructions
   - Verify token count ≥ 1024 (run through `estimate_tokens`)
   - Run `evaluate.py` to compare against current prompt on validation set
3. Optionally hand-edit the winning candidate to fix any incoherent passages the optimizer
   introduced (DSPy-generated instructions can occasionally be verbose or redundant).
4. Run the winning prompt through the live API tests (`MUTMUT_LLM_E2E_LIVE=1`) and inspect
   the generated mutations manually for quality regression.

**Quality gate for accepting the new prompt:**
- `validity_rate` on validation set ≥ current prompt's rate
- `non_trivial_rate` ≥ current prompt's rate
- Token count in [1024, 2000] — activates caching without inflating cost
- All live API tests pass
- Spot-check: manually review 10 generated mutations and confirm they are non-trivial,
  semantically distinct, and well-described

### Step 2.3 — Commit the optimized prompt

**File:** `mutmut-llm/src/mutmut_llm/prompts.py`

Replace `SYSTEM_PROMPT` with the selected candidate. The constant should include a header comment:

```python
# This prompt was optimized using DSPy MIPROv2 (see mutmut-llm/optimizer/).
# Target: ≥1024 tokens to activate Anthropic prompt caching on block 0.
# Last optimized: <date>, validator score: <score>.
SYSTEM_PROMPT = """\
<optimized content here>
"""
```

Add a smoke test to `test_prompts.py` that fails if someone hand-edits the prompt below 1024
tokens:

```python
def test_system_prompt_meets_cache_threshold():
    from mutmut_llm.prompts import SYSTEM_PROMPT
    # Anthropic minimum for cache_control to activate
    tokens = len(SYSTEM_PROMPT) // 4  # conservative estimate
    assert tokens >= 1024, (
        f"SYSTEM_PROMPT is ~{tokens} tokens — below the Anthropic caching minimum of 1024. "
        "See plans/llm/prompt-caching-strategy.md for context."
    )
```

---

## Part 3 — Validate caching is active with real API calls

Once Part 1 and Part 2 are both merged, verify caching with a live call:

```bash
ANTHROPIC_API_KEY=<key> uv run --package mutmut-llm python -c "
import asyncio, anthropic, os
from mutmut_llm.prompts import build_system_with_context, build_user_prompt, SYSTEM_PROMPT
from mutmut_llm.audit import estimate_tokens

token_est = estimate_tokens(SYSTEM_PROMPT)
print(f'SYSTEM_PROMPT estimated tokens: {token_est}')
assert token_est >= 1024, f'System prompt too small: {token_est} tokens'

async def check():
    client = anthropic.AsyncAnthropic()

    context = 'from __future__ import annotations\nimport os\nimport sys\n'
    src = 'def add(a, b):\n    return a + b\n'
    sys_blocks = build_system_with_context(context)
    user_msg = build_user_prompt(src, 2)

    # Call 1: expect cache_creation > 0
    r1 = await client.messages.create(
        model='claude-sonnet-4-6', max_tokens=200, temperature=0,
        system=sys_blocks, messages=[{'role': 'user', 'content': user_msg}]
    )
    u1 = r1.usage
    print(f'Call 1: cache_create={getattr(u1, \"cache_creation_input_tokens\", 0)}  cache_read={getattr(u1, \"cache_read_input_tokens\", 0)}')
    assert getattr(u1, 'cache_creation_input_tokens', 0) > 0, 'Caching did not activate on call 1'

    # Call 2 (same prefix): expect cache_read > 0
    src2 = 'def sub(a, b):\n    return a - b\n'
    r2 = await client.messages.create(
        model='claude-sonnet-4-6', max_tokens=200, temperature=0,
        system=build_system_with_context(context),
        messages=[{'role': 'user', 'content': build_user_prompt(src2, 2)}]
    )
    u2 = r2.usage
    print(f'Call 2: cache_create={getattr(u2, \"cache_creation_input_tokens\", 0)}  cache_read={getattr(u2, \"cache_read_input_tokens\", 0)}')
    assert getattr(u2, 'cache_read_input_tokens', 0) > 0, 'Cache did not hit on call 2'

    print('PASS: prompt caching is active')

asyncio.run(check())
"
```

---

## Dependencies

### Part 1 → Part 2 → Part 3 (sequential)

- Part 1 (placement fix) is a standalone PR. Merge immediately.
- Part 2 (DSPy optimization) depends on Part 1 being merged so the optimized prompt lands
  in a system that will actually cache it.
- Part 3 (live validation) is a CI check / manual smoke test, runs after Part 2 is merged.

### DSPy dependency

DSPy is added to `pyproject.toml` as an optimizer-only dependency, never required at runtime:

```toml
[dependency-groups]
dev = [
    "ruff>=0.15.4",
    "pytest-asyncio>=0.24.0",
]
optimizer = [
    "dspy-ai>=2.5.0",
    "pandas>=2.0.0",     # for evaluate.py comparison tables
]
```

Install for optimizer work: `uv sync --group optimizer`

---

## Files changed

| File | Change |
|------|--------|
| `mutmut-llm/src/mutmut_llm/prompts.py` | Fix `build_system_with_context`; replace `SYSTEM_PROMPT` with optimized version |
| `mutmut-llm/tests/test_prompts.py` | Update block-placement assertions; add `test_system_prompt_meets_cache_threshold` |
| `mutmut-llm/pyproject.toml` | Add `optimizer` dependency group |
| `mutmut-llm/optimizer/README.md` | How-to for running the optimizer |
| `mutmut-llm/optimizer/signature.py` | DSPy signature |
| `mutmut-llm/optimizer/dataset.py` | Training/validation example loader |
| `mutmut-llm/optimizer/metric.py` | Composite quality + budget scoring function |
| `mutmut-llm/optimizer/optimize.py` | MIPROv2 optimization script |
| `mutmut-llm/optimizer/evaluate.py` | Before/after comparison script |

---

## Expected impact once complete

| Metric | Before | After |
|--------|--------|-------|
| `cache_creation_tokens` on first call | 0 | ~1200–1600 |
| `cache_read_tokens` on subsequent same-file calls | 0 | ~1200–1600 |
| Input cost per call (warm cache) | full price | ~10× cheaper on cached tokens |
| Mutation quality | baseline | ≥ baseline (enforced by metric gate) |
| Prompt token size | ~621 | 1024–2000 |
| Runtime dependency on DSPy | — | none (offline tool only) |
