# E2E Cache Enrichment Plan

## Current state

`TestOperatorIntegration._prepopulate_cache` writes a single `CacheEntry`:
- **Function:** `fibonacci` only
- **Mutations:** 1 — changes `return 1` to `return 0` in the `n == 1` base case
- **Kill status:** killed by `test_fibonacci_base_cases` (`fibonacci(1) == 1`)

No entry exists for `is_palindrome`. Every cached mutation is killed. Only one mutation type (boundary value change) is represented.

## Gaps

| Gap | Impact |
|-----|--------|
| No `is_palindrome` cache entry | Operator integration only covers 1 of 2 functions in the e2e project |
| No surviving mutations | Cannot verify that the test harness correctly reports survivors (exit code 0) |
| Single mutation type | No coverage of logic inversion, off-by-one, operator removal, or early return mutations |
| Single mutation per entry | Does not exercise the multi-mutation iteration path in `operator_llm` |
| No precise count assertion | `test_llm_mutations_appear_in_results` only checks `> 0`, never validates expected mutation count |
| No description variety | All descriptions are the same style; no coverage of edge cases in `CachedMutation.description` |

## Mutations to add

### fibonacci — additional mutations

All mutations below use the original source as baseline:

```python
def fibonacci(n):
    """Return the nth Fibonacci number."""
    if n <= 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
```

#### 1. Off-by-one in range (SURVIVES)

Change `range(2, n + 1)` to `range(2, n)`. This makes `fibonacci(2)` return 0 instead of 1. But the test suite never asserts `fibonacci(2)`, so this mutation **survives**.

```python
def fibonacci(n):
    """Return the nth Fibonacci number."""
    if n <= 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n):
        a, b = b, a + b
    return b
```

Description: `"off-by-one: range(2, n) instead of range(2, n + 1)"`

**Wait — need to verify.** `fibonacci(5)` is asserted as 5. With `range(2, n)` = `range(2, 5)`, that runs iterations for `_ in {2,3,4}` (3 iterations). Original `range(2, 6)` runs 4 iterations. So `fibonacci(5)` would return 3 instead of 5. **Killed.** This would not survive.

Better surviving mutation: change `n <= 0` to `n < 0`. The test asserts `fibonacci(0) == 0`, and `n < 0` still returns 0 for n=0 via the `n == 1` branch falling through to the loop with `range(2, 1)` which is empty, returning `b = 1`. That gives `fibonacci(0) = 1` — **killed** by the test.

Alternative surviving mutation: change the initial assignment `a, b = 0, 1` to `a, b = 1, 1`. Then:
- `fibonacci(0)` → 0 (base case, unchanged) ✓
- `fibonacci(1)` → 1 (base case, unchanged) ✓
- `fibonacci(5)` with `a,b = 1,1`: iterations yield `(1,2), (2,3), (3,5), (5,8)` → returns 8, not 5. **Killed.**

Finding a surviving fibonacci mutation is hard because the tests cover base cases and two further values. Instead, focus surviving mutations on `is_palindrome` where test gaps are obvious.

#### Mutation fib-2: Logic inversion — swap `<=` to `<` (KILLED)

```python
def fibonacci(n):
    """Return the nth Fibonacci number."""
    if n < 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
```

`fibonacci(0)` would enter the loop with `range(2, 1)` → empty → return `b = 1`. Test expects 0. **Killed.**

Description: `"boundary: n < 0 instead of n <= 0"`

#### Mutation fib-3: Early return — return `a` instead of `b` (KILLED)

```python
def fibonacci(n):
    """Return the nth Fibonacci number."""
    if n <= 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return a
```

`fibonacci(5)`: after iterations, `a` would be 3 instead of 5. **Killed.**

Description: `"return wrong accumulator: return a instead of b"`

### is_palindrome — new cache entry

Original source:

```python
def is_palindrome(s):
    """Check if a string is a palindrome (case-insensitive)."""
    cleaned = s.lower().strip()
    return cleaned == cleaned[::-1]
```

#### Mutation pal-1: Remove `.strip()` (SURVIVES)

```python
def is_palindrome(s):
    """Check if a string is a palindrome (case-insensitive)."""
    cleaned = s.lower()
    return cleaned == cleaned[::-1]
```

No test passes a string with leading/trailing whitespace. **Survives.**

Description: `"remove strip() call — no whitespace handling"`

#### Mutation pal-2: Remove `.lower()` (KILLED)

```python
def is_palindrome(s):
    """Check if a string is a palindrome (case-insensitive)."""
    cleaned = s.strip()
    return cleaned == cleaned[::-1]
```

`is_palindrome("Madam")` → `"Madam" != "madaM"` → False. Test expects True. **Killed.**

Description: `"remove lower() — case-sensitive comparison"`

#### Mutation pal-3: Negate return value (KILLED)

```python
def is_palindrome(s):
    """Check if a string is a palindrome (case-insensitive)."""
    cleaned = s.lower().strip()
    return cleaned != cleaned[::-1]
```

`is_palindrome("racecar")` → False. Test expects True. **Killed.**

Description: `"logic inversion: != instead of =="`

#### Mutation pal-4: Always return True (SURVIVES partially — but killed by `test_is_palindrome_false`)

```python
def is_palindrome(s):
    """Check if a string is a palindrome (case-insensitive)."""
    cleaned = s.lower().strip()
    return True
```

`is_palindrome("hello")` → True. Test expects `not is_palindrome("hello")`. **Killed.**

#### Mutation pal-5: Use `startswith` instead of full comparison (SURVIVES)

```python
def is_palindrome(s):
    """Check if a string is a palindrome (case-insensitive)."""
    cleaned = s.lower().strip()
    half = len(cleaned) // 2
    return cleaned[:half] == cleaned[:half][::-1]
```

Wait, this is a different algorithm but would give wrong results for some inputs. Too complex. Keep mutations simple.

Better surviving mutation — **reverse only half** (subtly wrong):

Actually the simplest surviving mutation for `is_palindrome` is pal-1 (remove `.strip()`). That is sufficient.

## Final mutations for `_prepopulate_cache`

### fibonacci entry (3 mutations)

```python
mutations=[
    CachedMutation(
        mutated_code='''\
def fibonacci(n):
    """Return the nth Fibonacci number."""
    if n <= 0:
        return 0
    if n == 1:
        return 0
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
''',
        description="change fib(1) base case from 1 to 0",
    ),
    CachedMutation(
        mutated_code='''\
def fibonacci(n):
    """Return the nth Fibonacci number."""
    if n < 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
''',
        description="boundary: n < 0 instead of n <= 0",
    ),
    CachedMutation(
        mutated_code='''\
def fibonacci(n):
    """Return the nth Fibonacci number."""
    if n <= 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return a
''',
        description="return wrong accumulator: return a instead of b",
    ),
]
```

**Expected outcomes:** All 3 killed.

### is_palindrome entry (3 mutations)

```python
# Extract is_palindrome source the same way as fibonacci
for stmt in module.body:
    if isinstance(stmt, cst.FunctionDef) and stmt.name.value == "is_palindrome":
        pal_source = module.code_for_node(stmt)
        break

mutations=[
    CachedMutation(
        mutated_code='''\
def is_palindrome(s):
    """Check if a string is a palindrome (case-insensitive)."""
    cleaned = s.lower()
    return cleaned == cleaned[::-1]
''',
        description="remove strip() call — no whitespace handling",
    ),
    CachedMutation(
        mutated_code='''\
def is_palindrome(s):
    """Check if a string is a palindrome (case-insensitive)."""
    cleaned = s.strip()
    return cleaned == cleaned[::-1]
''',
        description="remove lower() — case-sensitive comparison",
    ),
    CachedMutation(
        mutated_code='''\
def is_palindrome(s):
    """Check if a string is a palindrome (case-insensitive)."""
    cleaned = s.lower().strip()
    return cleaned != cleaned[::-1]
''',
        description="logic inversion: != instead of ==",
    ),
]
```

**Expected outcomes:**
- pal-1 (remove strip): **SURVIVES** (exit code 0) — no test uses whitespace input
- pal-2 (remove lower): **KILLED** — `is_palindrome("Madam")` fails
- pal-3 (negate): **KILLED** — `is_palindrome("racecar")` fails

## New test assertions to add

### 1. `test_llm_mutations_cover_both_functions`

```python
def test_llm_mutations_cover_both_functions(self):
    """Cache entries exist for both fibonacci and is_palindrome."""
    self._prepopulate_cache()
    results = self._run_mutmut()

    fib_mutations = {k: v for k, v in results.items() if "fibonacci" in k}
    pal_mutations = {k: v for k, v in results.items() if "is_palindrome" in k}
    assert fib_mutations, f"No fibonacci mutations. Keys: {sorted(results.keys())}"
    assert pal_mutations, f"No is_palindrome mutations. Keys: {sorted(results.keys())}"
```

### 2. `test_surviving_mutation_detected`

```python
def test_surviving_mutation_detected(self):
    """At least one LLM mutation should survive (exit code 0)."""
    self._prepopulate_cache()
    results = self._run_mutmut()

    survivors = {k: v for k, v in results.items() if v == 0}
    assert survivors, (
        f"Expected at least one surviving mutation (the strip-removal). "
        f"Results: {results}"
    )
```

### 3. `test_llm_mutation_count`

```python
def test_llm_mutation_count(self):
    """Total LLM mutations injected matches cache contents (6 total)."""
    self._prepopulate_cache()
    results = self._run_mutmut()

    # Filter to LLM-sourced mutations by checking for the "llm" prefix in keys.
    # If key format doesn't distinguish, at minimum assert total exceeds
    # baseline by the number of cached mutations.
    # 3 fibonacci + 3 is_palindrome = 6 LLM mutations added on top of builtins.
    llm_keys = {k for k in results if "llm" in k.lower()}
    if llm_keys:
        assert len(llm_keys) == 6, f"Expected 6 LLM mutations, got {len(llm_keys)}: {llm_keys}"
```

Note: the exact key format depends on how mutmut names mutations from the LLM operator. The assertion may need adjustment based on the actual key format. An alternative is to compare against a baseline run (already tested in `test_more_mutations_than_builtins_alone`) and assert the difference equals 6.

### 4. `test_killed_and_survived_counts`

```python
def test_killed_and_survived_counts(self):
    """Verify expected kill/survive split for LLM mutations."""
    self._prepopulate_cache()
    results = self._run_mutmut()

    killed = {k for k, v in results.items() if v == 1}
    survived = {k for k, v in results.items() if v == 0}

    # At minimum: 5 killed LLM mutations + builtins, 1+ survivor
    assert len(killed) >= 5, f"Expected ≥5 killed, got {len(killed)}"
    assert len(survived) >= 1, f"Expected ≥1 survivor, got {len(survived)}"
```

## Implementation checklist

1. Refactor `_prepopulate_cache` to extract both `fibonacci` and `is_palindrome` source from the e2e module
2. Write fibonacci `CacheEntry` with 3 mutations (all killed)
3. Write is_palindrome `CacheEntry` with 3 mutations (1 survives, 2 killed)
4. Add `test_llm_mutations_cover_both_functions`
5. Add `test_surviving_mutation_detected`
6. Add `test_llm_mutation_count` (adjust key-matching logic after inspecting actual mutmut output format)
7. Add `test_killed_and_survived_counts`
8. Run the e2e suite and verify: `uv run --package mutmut-llm pytest mutmut-llm/tests/e2e/ -v`
9. Confirm the strip-removal mutation actually survives — if not, find another test-gap mutation
