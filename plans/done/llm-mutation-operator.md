# LLM Mutation Operator

## Context

The original project goal is LLM-powered mutation testing. The plugin system is now in place (`mutmut-extras` registers operators via pluggy). The reference implementation at `~/pr/mutmut/` had a full LLM pipeline: `prompts.py`, `pipeline.py`, `cache.py`, `config.py`, `operators.py`.

LLM mutations are fundamentally different from syntactic mutations. Syntactic operators apply mechanical transformations (`+` to `-`, `True` to `False`). LLM operators understand code semantics and can produce mutations like:

- Swapping a sorting algorithm implementation (bubble sort for the correct merge sort).
- Introducing off-by-one errors in loop bounds that match real bug patterns.
- Changing data flow (returning a copy instead of a reference, or vice versa).
- Altering business logic in ways that are syntactically valid but semantically wrong.

## Why It Matters

- Syntactic mutations have diminishing returns — most are trivially killed by basic tests. The surviving ones are often equivalent mutants, not gaps in the test suite.
- LLM mutations target the semantic gap: code that passes tests but would fail under real-world edge cases.
- This is the differentiating feature that justifies the project's existence.

## Benefits

- Higher-quality mutations that test real-world failure modes.
- Finds test gaps that syntactic mutation cannot reach.
- Mutations are human-readable — surviving LLM mutants produce actionable feedback ("your tests don't verify the sort order" vs "your tests don't catch `<` changing to `<=`").
- Cache-based approach means LLM costs are one-time per function, amortized across runs.

## Implementation Recommendation

**Prerequisite:** [whole-function-mutations.md](./whole-function-mutations.md) must be implemented first. LLM mutations replace entire function bodies.

### Architecture: Generate-then-run

Separate mutation generation (LLM API calls, expensive, slow) from mutation testing (run tests, fast, repeatable). This means:

1. **`mutmut generate`** — CLI command that calls LLM API, populates cache. Run once or when code changes.
2. **`mutmut run`** — existing command, reads from cache via the operator. No API calls during testing.

This decoupling is critical: LLM API calls are slow (seconds per function), non-deterministic, and costly. Test runs should be fast and reproducible.

### Module structure (in `mutmut-extras`)

```
mutmut-extras/src/mutmut_extras/llm/
    __init__.py
    config.py      — configuration loading
    prompts.py     — prompt templates and response parsing
    cache.py       — JSON file cache management
    operators.py   — pluggy operator that reads from cache
    pipeline.py    — generation pipeline (API calls + cache writes)
```

### 1. `config.py` — Configuration

Load from `pyproject.toml` and environment variables:

```toml
[tool.mutmut.llm]
model = "claude-sonnet-4-20250514"
provider = "anthropic"
cache_dir = ".mutmut-llm-cache"
max_mutations_per_function = 3
```

```python
@dataclass
class LLMConfig:
    model: str = "claude-sonnet-4-20250514"
    provider: str = "anthropic"
    api_key: str = ""  # from ANTHROPIC_API_KEY env var
    cache_dir: Path = Path(".mutmut-llm-cache")
    max_mutations_per_function: int = 3

def load_config() -> LLMConfig:
    # Read pyproject.toml [tool.mutmut.llm], overlay env vars
    ...
```

### 2. `prompts.py` — Prompt engineering

Two-part prompt:

**System prompt:** You are a mutation testing expert. Given a Python function, generate mutated versions that introduce subtle, realistic bugs. Each mutation should change the function's behavior in a way that a good test suite would catch.

**User prompt:** Contains the function source, its module context (imports, class if method), and constraints (preserve signature, return valid Python, describe the mutation).

**Response parsing:** Extract code blocks from LLM response, validate they parse as valid Python, wrap in CST nodes.

```python
def build_mutation_prompt(function_source: str, module_context: str) -> tuple[str, str]:
    """Return (system_prompt, user_prompt)."""
    ...

def parse_mutation_response(response: str) -> list[dict]:
    """Extract mutations from LLM response.
    Returns list of {"code": str, "description": str}.
    """
    ...
```

### 3. `cache.py` — Persistent cache

Cache keyed by function identity (module path + qualified name + content hash):

```
.mutmut-llm-cache/
    module__path__to__file/
        function_name__abc123.json
```

Each JSON file:

```json
{
    "function_name": "calculate_total",
    "module": "src/billing/calculator.py",
    "content_hash": "abc123",
    "original_source": "def calculate_total(items): ...",
    "mutations": [
        {
            "mutated_source": "def calculate_total(items): ...",
            "description": "Off-by-one in loop bound",
            "generated_at": "2026-03-03T10:00:00Z",
            "model": "claude-sonnet-4-20250514"
        }
    ]
}
```

Content hash invalidation: if the function source changes, the cache entry is stale and `mutmut generate` will regenerate.

```python
class MutationCache:
    def __init__(self, cache_dir: Path): ...
    def get(self, module: str, function_name: str, source_hash: str) -> list[dict] | None: ...
    def put(self, module: str, function_name: str, source_hash: str, mutations: list[dict]): ...
    def is_stale(self, module: str, function_name: str, current_hash: str) -> bool: ...
```

### 4. `operators.py` — Plugin operator

Reads from cache, yields whole-function mutations:

```python
def operator_llm(node, context=None, **kwargs):
    """Yield whole-function mutations from LLM cache."""
    if not isinstance(node, cst.FunctionDef):
        return

    cache = MutationCache(config.cache_dir)
    function_source = module.code_for_node(node)
    source_hash = hashlib.sha256(function_source.encode()).hexdigest()[:12]

    cached = cache.get(context.module, node.name.value, source_hash)
    if not cached:
        return

    for mutation in cached:
        mutated_node = cst.parse_statement(mutation["mutated_source"])
        yield node, mutated_node

operator_llm.__mutmut_source__ = "llm"
```

Registered via pluggy:

```python
@hookimpl
def mutmut_register_operators():
    return [(cst.FunctionDef, operator_llm)]
```

### 5. `pipeline.py` — Generation command

Walks the project source, extracts functions, calls LLM API, populates cache:

```python
def generate_mutations(source_dir: Path, config: LLMConfig):
    for py_file in source_dir.rglob("*.py"):
        module = cst.parse_module(py_file.read_text())
        for function in extract_functions(module):
            source_hash = hash_function(function)
            if not cache.is_stale(py_file, function.name, source_hash):
                continue

            prompt = build_mutation_prompt(function, module_context)
            response = call_llm(config, prompt)
            mutations = parse_mutation_response(response)
            cache.put(py_file, function.name, source_hash, mutations)
```

Exposed as `mutmut generate` via the `mutmut_register_commands` hook (see [additional-hookspecs.md](./additional-hookspecs.md)).

### Rollout strategy

1. Implement with hardcoded cache files first — manually create `.mutmut-llm-cache/` entries, verify the operator reads them and mutations flow through the pipeline.
2. Add `pipeline.py` with LLM API integration.
3. Add `mutmut generate` CLI command.
4. Add cache invalidation and incremental regeneration.

The reference implementation's `prompts.py` and `cache.py` are solid starting points for steps 2-3.
