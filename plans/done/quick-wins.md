# Quick Wins: LLM Prompt & Pipeline Improvements

Three small changes to `mutmut-llm` that improve mutation quality with minimal code.

## 1. Set temperature to 0.6

**File:** `mutmut-llm/src/mutmut_llm/pipeline.py`, `_call_llm_and_validate`

Currently temperature is unset (Anthropic default = 1.0). Too high for structured JSON output — causes malformed JSON, hallucinated syntax, equivalent mutants from creative but meaningless changes.

**Change:** Add `temperature=0.6` to the `client.messages.create()` call.

Optionally expose as `LLMConfig.temperature` in config.py + pyproject.toml section.

## 2. Add `pragma: no mutate` awareness

**Problem:** The LLM mutated `pragma: no mutate` lines in the audit (both `Point.ignored` and `function_with_pragma`). One mutation (#48) adversarially moved the pragma comment to bypass exclusion.

**Two-layer fix:**

### 2a. Strip pragmas from function source before prompting

In `scope.py`, `_extract_functions`: after extracting `source = module.code_for_node(stmt)`, strip lines containing `# pragma: no mutate` or mark them. Alternatively, add a note in the user prompt.

Simpler approach — add to the system prompt:
```
- Lines containing `# pragma: no mutate` must NOT be modified.
- Never move, remove, or modify pragma comments.
```

### 2b. Post-validation pragma check

In `validation.py`, add `validate_pragmas(mutated_code, original_code)`:
- Extract lines with `# pragma: no mutate` from original
- Verify those lines are unchanged in the mutated code
- Reject if any pragma-marked line was modified or if pragmas were moved

## 3. Add few-shot examples to system prompt

**File:** `mutmut-llm/src/mutmut_llm/prompts.py`, `SYSTEM_PROMPT`

Append 2 examples after the rules section:

```
Examples of GOOD mutations (the kind you should generate):

Input:
def clamp(x, lo, hi):
    return max(lo, min(x, hi))

Output:
[
  {"mutated_code": "def clamp(x, lo, hi):\\n    return max(lo, min(x, lo))", "description": "Use lo instead of hi in inner min — clamp always returns lo for values above lo"},
  {"mutated_code": "def clamp(x, lo, hi):\\n    return min(hi, max(x, lo))", "description": "Swap max/min nesting — inverts clamping logic"}
]

Examples of BAD mutations (do NOT generate these):
- `return sorted(items)` → `return list(sorted(items))` — equivalent, sorted() already returns list
- `x = 5` → `tmp = 5; x = tmp` — equivalent, intermediate variable changes nothing
- `self.data[:]` instead of `self.data` — equivalent for most types
- `str(name)` when name is already a str — equivalent, no behavior change
```

## 4. Add dedup instruction to system prompt

Append to rules:
```
- Each mutation must be semantically distinct from the others. Do not generate multiple variations of the same idea.
```

## Steps

### Step 1: Update system prompt
Add few-shot examples, negative examples, pragma instruction, and dedup instruction to `SYSTEM_PROMPT` in `prompts.py`.

### Step 2: Set temperature
Add `temperature=0.6` to `client.messages.create()` in `pipeline.py`. Optionally add `temperature` field to `LLMConfig`.

### Step 3: Add pragma validation
Add `validate_pragmas()` to `validation.py`. Wire it into `validate_mutation()`.

### Step 4: Test
- Run `mutmut generate` on `my_lib` with the changes.
- Compare mutation quality before/after using the dedup metrics test.
- Verify pragma-marked lines are no longer mutated.
- Verify JSON parse failures decrease (temperature effect).

### Step 5: Update dedup metrics test
Re-run `test_dedup_metrics.py` with all 3 configurations to measure improvement.
