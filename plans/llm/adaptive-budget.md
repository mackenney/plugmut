# Adaptive Mutation Budget per Function Complexity

Scale the number of LLM mutations requested per function based on its complexity, instead of using a uniform count.

## Problem

Currently every function gets `max_mutations_per_function` (default 5) regardless of size. This leads to:
- **Over-budgeting simple functions:** `Point.__init__` (2 lines: `self.x = x; self.y = y`) forced to produce 5 mutations. Result: 3+ are weak/equivalent padding.
- **Under-budgeting complex functions:** A 33-line function with branches, loops, and data structures gets the same 5 mutations as a one-liner.

## Design

### Complexity signal: source lines

Use effective source lines (non-blank, non-comment, non-docstring) as the primary complexity signal. Simple, no external dependencies, already available from the function source.

```python
def compute_mutation_budget(source: str, min_budget: int = 2, max_budget: int = 10) -> int:
    """Scale mutation budget by function complexity."""
    lines = [l for l in source.strip().splitlines() if l.strip() and not l.strip().startswith('#')]
    # Subtract the def line itself
    effective = max(1, len(lines) - 1)
    return min(max_budget, max(min_budget, effective // 3))
```

| Effective lines | Budget |
|----------------|--------|
| 1-5 | 2 |
| 6-8 | 2 |
| 9-11 | 3 |
| 12-14 | 4 |
| 15-17 | 5 |
| 18-29 | 6-9 |
| 30+ | 10 |

### Secondary signal: branching complexity

Count `if`, `elif`, `else`, `for`, `while`, `try`, `except` keywords for a rough cyclomatic complexity proxy. Add 1 to budget per 3 branches found.

```python
import re
BRANCH_RE = re.compile(r'\b(if|elif|else|for|while|try|except|with)\b')

def _branch_count(source: str) -> int:
    return len(BRANCH_RE.findall(source))

def compute_mutation_budget(source: str, min_budget: int = 2, max_budget: int = 10) -> int:
    lines = [l for l in source.strip().splitlines() if l.strip() and not l.strip().startswith('#')]
    effective = max(1, len(lines) - 1)
    base = effective // 3
    branch_bonus = _branch_count(source) // 3
    return min(max_budget, max(min_budget, base + branch_bonus))
```

## Integration Points

### In scope.py: `_allocate_budget`

Currently uniform:
```python
per_function = min(max_per_function, max(1, total_budget // len(targets)))
```

Change to per-function computation:
```python
def _allocate_budget(targets, total_budget, max_per_function):
    raw = {
        f"{t.file_path}::{t.function_name}": compute_mutation_budget(
            t.source, min_budget=2, max_budget=max_per_function
        )
        for t in targets
    }
    # Scale down proportionally if total exceeds budget
    total_raw = sum(raw.values())
    if total_raw > total_budget:
        scale = total_budget / total_raw
        raw = {k: max(1, int(v * scale)) for k, v in raw.items()}
    return raw
```

### In config.py: new fields

```python
@dataclass
class LLMConfig:
    # ... existing fields ...
    min_mutations_per_function: int = 2
    max_mutations_per_function: int = 10
```

### In pipeline.py: pass through

The budget_per_target dict already flows from scope → pipeline → API call. No changes needed in `_generate_mutations` or `_call_llm_and_validate` — they already read from `budget_per_target`.

## Steps

### Step 1: Add `compute_mutation_budget()` to scope.py

Pure function, no dependencies. Include both line-count and branch-count logic.

### Step 2: Update `_allocate_budget`

Replace uniform allocation with per-function budgets. Add proportional scaling when total exceeds API call budget.

### Step 3: Update config

Add `min_mutations_per_function` (default 2) to `LLMConfig`. Update `load_config` to read from pyproject.toml.

### Step 4: Test

Unit test `compute_mutation_budget` with functions of varying complexity:
- 1-line function → budget 2
- 10-line function → budget 3-4
- 30-line function with branches → budget 8-10

Integration test: run `mutmut generate --dry-run` on e2e projects, verify budgets are non-uniform and correlate with complexity.

### Step 5: Measure impact

Re-run the dedup metrics test. Compare WEAK/EQUIVALENT rate for simple functions (expect decrease due to lower budget) and EXCELLENT rate for complex functions (expect increase due to higher budget).
