"""LLM mutation experiment: discover new mutation patterns beyond deterministic operators.

Calls Claude API with sample functions, asking for mutations that avoid our existing
26 deterministic operators. Analyzes results to find recurring patterns that could
become new deterministic operators.

Usage:
    uv run python plans/llm_mutation_experiment.py
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load API key from the reference repo's .env
load_dotenv(Path.home() / "pr" / "mutmut" / ".env")

import anthropic
import libcst as cst

# ---------------------------------------------------------------------------
# Sample functions: each with "tight" and "loose" test descriptions
# ---------------------------------------------------------------------------

SAMPLE_FUNCTIONS: list[dict] = [
    {
        "name": "binary_search",
        "category": "algorithmic",
        "source": '''\
def binary_search(arr, target):
    """Return index of target in sorted arr, or -1 if not found."""
    low, high = 0, len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
''',
        "tight_tests": "Tests: empty array, single element found/not-found, first/last/middle element, duplicates, large arrays, target smaller/larger than all elements",
        "loose_tests": "Tests: finds element in [1,2,3,4,5], returns -1 for missing element",
    },
    {
        "name": "parse_config",
        "category": "data_transformation",
        "source": '''\
def parse_config(raw: str, defaults: dict | None = None) -> dict:
    """Parse KEY=VALUE config lines. Comments (#) and blank lines ignored."""
    result = dict(defaults) if defaults else {}
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid config line: {line!r}")
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"Empty key in line: {line!r}")
        result[key] = value
    return result
''',
        "tight_tests": "Tests: empty string, only comments, only blank lines, valid key=value pairs, defaults merging, override defaults, empty value, key with spaces, missing = raises ValueError, empty key raises ValueError, multiple = signs in value",
        "loose_tests": "Tests: parses 'a=1\\nb=2' correctly, empty string returns {}",
    },
    {
        "name": "retry_with_backoff",
        "category": "error_handling",
        "source": '''\
import time
import random

def retry_with_backoff(fn, max_retries=3, base_delay=1.0, jitter=True):
    """Call fn() with exponential backoff on failure. Returns result or raises last exception."""
    last_exception = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                if jitter:
                    delay *= random.uniform(0.5, 1.5)
                time.sleep(delay)
    raise last_exception
''',
        "tight_tests": "Tests: fn succeeds first try, fn fails then succeeds, all retries exhausted raises, delay increases exponentially, jitter=False gives exact delays, max_retries=1 no retry, base_delay affects timing",
        "loose_tests": "Tests: successful call returns value, failed call raises after retries",
    },
    {
        "name": "LRUCache",
        "category": "oop_stateful",
        "source": """\
from collections import OrderedDict

class LRUCache:
    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("Capacity must be positive")
        self._capacity = capacity
        self._cache: OrderedDict = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, key):
        if key in self._cache:
            self._hits += 1
            self._cache.move_to_end(key)
            return self._cache[key]
        self._misses += 1
        return None

    def put(self, key, value):
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        if len(self._cache) > self._capacity:
            self._cache.popitem(last=False)

    @property
    def hit_rate(self):
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total
""",
        "tight_tests": "Tests: get existing key, get missing key, put new key, put updates existing, eviction of LRU item, capacity=1, hit_rate calculation, hit_rate with no accesses, move_to_end on get, move_to_end on put update, capacity<=0 raises ValueError",
        "loose_tests": "Tests: put and get a value, get missing returns None",
    },
    {
        "name": "flatten_nested",
        "category": "recursive_collections",
        "source": '''\
def flatten_nested(data, max_depth=None, _current_depth=0):
    """Flatten nested lists/tuples. max_depth=None means unlimited."""
    result = []
    for item in data:
        is_nested = isinstance(item, (list, tuple))
        within_depth = max_depth is None or _current_depth < max_depth
        if is_nested and within_depth:
            result.extend(flatten_nested(item, max_depth, _current_depth + 1))
        else:
            result.append(item)
    return result
''',
        "tight_tests": "Tests: empty list, flat list unchanged, nested 2 levels, nested 3+ levels, mix of lists and tuples, max_depth=0 no flattening, max_depth=1 one level, non-iterable items preserved, deeply nested, strings not flattened",
        "loose_tests": "Tests: flattens [[1,2],[3,4]] to [1,2,3,4]",
    },
    {
        "name": "process_transactions",
        "category": "business_logic",
        "source": '''\
from decimal import Decimal

def process_transactions(transactions: list[dict]) -> dict:
    """Process list of {amount, type, category} transactions.
    Returns summary with totals per category and overall balance."""
    summary = {"income": Decimal("0"), "expense": Decimal("0"), "categories": {}}
    for txn in transactions:
        amount = Decimal(str(txn["amount"]))
        txn_type = txn["type"]
        category = txn.get("category", "uncategorized")

        if txn_type not in ("income", "expense"):
            raise ValueError(f"Unknown transaction type: {txn_type}")

        if amount < 0:
            raise ValueError(f"Negative amount: {amount}")

        summary[txn_type] += amount

        if category not in summary["categories"]:
            summary["categories"][category] = {"income": Decimal("0"), "expense": Decimal("0")}
        summary["categories"][category][txn_type] += amount

    summary["balance"] = summary["income"] - summary["expense"]
    return summary
''',
        "tight_tests": "Tests: empty list, single income, single expense, multiple mixed, category grouping, uncategorized default, negative amount raises, unknown type raises, balance calculation, Decimal precision, multiple categories",
        "loose_tests": "Tests: process one income transaction, empty list returns zeros",
    },
    {
        "name": "merge_sorted_streams",
        "category": "generator_iteration",
        "source": '''\
import heapq

def merge_sorted_streams(*iterables, key=None):
    """Merge multiple sorted iterables into a single sorted stream.
    Yields items lazily. Optional key function for comparison."""
    if key is None:
        yield from heapq.merge(*iterables)
    else:
        heap = []
        iterators = [iter(it) for it in iterables]
        for i, iterator in enumerate(iterators):
            try:
                item = next(iterator)
                heapq.heappush(heap, (key(item), i, item, iterator))
            except StopIteration:
                pass

        while heap:
            _, source_idx, item, iterator = heapq.heappop(heap)
            yield item
            try:
                next_item = next(iterator)
                heapq.heappush(heap, (key(next_item), source_idx, next_item, iterator))
            except StopIteration:
                pass
''',
        "tight_tests": "Tests: empty iterables, single iterable passthrough, two sorted lists, three sorted lists, with key function, empty mixed with non-empty, single element streams, duplicate values, already merged, generators as input",
        "loose_tests": "Tests: merges [1,3,5] and [2,4,6] correctly",
    },
    {
        "name": "validate_and_sanitize",
        "category": "string_processing",
        "source": '''\
import re

def validate_and_sanitize(email: str) -> str:
    """Validate and normalize an email address. Returns normalized form or raises ValueError."""
    email = email.strip()
    if not email:
        raise ValueError("Email cannot be empty")

    local, _, domain = email.rpartition("@")
    if not local or not domain:
        raise ValueError(f"Invalid email format: {email!r}")

    if ".." in local or ".." in domain:
        raise ValueError(f"Consecutive dots not allowed: {email!r}")

    if not re.match(r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+$", local):
        raise ValueError(f"Invalid characters in local part: {email!r}")

    if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$", domain):
        raise ValueError(f"Invalid domain: {domain!r}")

    return f"{local}@{domain.lower()}"
''',
        "tight_tests": "Tests: valid email normalized, uppercase domain lowered, whitespace stripped, empty raises, no @ raises, no local part raises, no domain raises, consecutive dots raises, invalid local chars raises, invalid domain raises, edge case valid chars",
        "loose_tests": "Tests: 'user@example.com' passes, empty string raises",
    },
]

# ---------------------------------------------------------------------------
# System prompt for the experiment — asks LLM to avoid our existing operators
# ---------------------------------------------------------------------------

EXPERIMENT_SYSTEM_PROMPT = """\
You are a mutation testing researcher. Your goal is to generate code mutations \
that CANNOT be produced by the following deterministic mutation operators. \
These operators are already implemented and we need mutations BEYOND them.

EXISTING OPERATORS (do NOT produce mutations that these can already generate):

Category: Arithmetic/Operator swaps
- +↔-, *↔/, //→/, %→/, **→*, <<↔>>, &↔|, ^→&, and↔or
- Augmented assignment operator swaps (+=↔-=, etc.)
- Augmented assignment to plain assignment (x += 1 → x = 1)
- Unary +↔- swap
- Remove unary not, remove ~

Category: Comparison
- <↔<=, >↔>=, ==↔!=

Category: Boolean/Keyword
- True↔False, is↔is not, in↔not in
- break→return, continue→break
- deepcopy→copy

Category: Literals
- Number increment (n → n+1)
- String: XX prefix/suffix, upper/lower case transforms
- Assignment: a=b → a=None, a=None → a=""

Category: Function calls
- Replace each arg with None
- Remove individual args (when >1)
- dict(key=val) → dict(keyXX=val)
- Swap symmetric string methods (lower↔upper, lstrip↔rstrip, find↔rfind, etc.)
- split↔rsplit (conditional)

Category: Lambda
- lambda: x → lambda: None (or lambda: 0)

Category: Return/Yield
- return x → return None
- yield x → yield None, bare yield → yield 0

Category: Control flow
- if-expression: collapse to true/false branch, swap branches
- Match: drop case clauses

Category: Exception handling
- Exception handler body → pass
- assert cond → assert True

Category: Collections
- Slice: remove lower/upper/step individually
- Comprehension: remove if-clause

Category: Calls
- Standalone call statement → pass (void call removal)
- super().method() → pass

Category: OOP/Parameters
- Default param: None→0, compound→None, non-builtin-name→None

Category: Iteration
- for x in items → for x in reversed(items)

Category: F-strings
- {expr} → {'XX'}

IMPORTANT CONSTRAINTS:
- Each mutation MUST be syntactically valid Python
- Each mutation MUST change observable behavior (no equivalent mutants)
- Focus on mutations that represent NOVEL PATTERNS not covered above
- Think about: semantic-level changes, API contract violations, boundary mutations, \
  state corruption, initialization errors, ordering bugs, type confusion, \
  resource management errors, concurrency mistakes
- Include the COMPLETE mutated function/class (with def/class line and full body)
- Tag each mutation with a descriptive pattern_name that could become a new operator

Output a JSON array:
[{
    "mutated_code": "def ...",
    "pattern_name": "short_snake_case_name_for_this_pattern",
    "description": "what changed and why it's not covered by existing operators",
    "category": "semantic|boundary|api_contract|state|resource|ordering|type_confusion|initialization|other"
}]

IMPORTANT: Output ONLY the JSON array. No markdown, no explanation outside the JSON.
"""

USER_PROMPT_TEMPLATE = """\
Function to mutate:
<source>
{source}
</source>

Test coverage context ({test_quality}):
{test_description}

Generate up to {max_mutations} novel mutations that our existing 26 deterministic \
operators CANNOT produce. Focus on patterns that could potentially become new \
deterministic operators (i.e., the pattern generalizes beyond this specific function).
"""

# ---------------------------------------------------------------------------
# Response parsing (adapted from mutmut-llm)
# ---------------------------------------------------------------------------

_CODE_BLOCK_RE = re.compile(r"```(?:\w*)\s*\n?(.*?)\n?```", re.DOTALL)


def parse_response(text: str) -> list[dict]:
    text = text.strip()
    try:
        return _validate(json.loads(text))
    except json.JSONDecodeError:
        pass

    for block in _CODE_BLOCK_RE.findall(text):
        try:
            return _validate(json.loads(block.strip()))
        except json.JSONDecodeError:
            continue

    bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket_match:
        try:
            return _validate(json.loads(bracket_match.group(0)))
        except json.JSONDecodeError:
            pass
    return []


def _validate(data: object) -> list[dict]:
    if isinstance(data, list):
        return [m for m in data if isinstance(m, dict) and "mutated_code" in m]
    return []


def validate_syntax(mutations: list[dict]) -> list[dict]:
    valid = []
    for m in mutations:
        try:
            cst.parse_module(m["mutated_code"])
            valid.append(m)
        except (cst.ParserSyntaxError, Exception):
            m["_syntax_error"] = True
            valid.append(m)  # keep for analysis but flag
    return valid


# ---------------------------------------------------------------------------
# API calling
# ---------------------------------------------------------------------------


def call_llm(
    client: anthropic.Anthropic,
    source: str,
    test_description: str,
    test_quality: str,
    max_mutations: int = 8,
    model: str = "claude-sonnet-4-6",
) -> tuple[list[dict], float]:
    user_prompt = USER_PROMPT_TEMPLATE.format(
        source=source,
        test_description=test_description,
        test_quality=test_quality,
        max_mutations=max_mutations,
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            system=[
                {
                    "type": "text",
                    "text": EXPERIMENT_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        print(f"  API error: {e}", file=sys.stderr)
        return [], 0.0

    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
    cache_create = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
    # Sonnet pricing
    cost = (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000
    # Cache discount: cached tokens cost 0.3/M instead of 3.0/M
    if cache_read:
        cost -= (cache_read * (3.0 - 0.3)) / 1_000_000

    mutations = parse_response(text)
    mutations = validate_syntax(mutations)

    print(
        f"    tokens: {input_tokens} in ({cache_read} cached, {cache_create} created) / {output_tokens} out | cost: ${cost:.4f}"
    )

    return mutations, cost


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@dataclass
class PatternStats:
    pattern_name: str
    count: int = 0
    categories: set = field(default_factory=set)
    descriptions: list = field(default_factory=list)
    functions_seen_in: set = field(default_factory=set)
    examples: list = field(default_factory=list)


def analyze_results(all_mutations: list[dict]) -> dict[str, PatternStats]:
    patterns: dict[str, PatternStats] = {}

    for m in all_mutations:
        name = m.get("pattern_name", "unknown")
        if name not in patterns:
            patterns[name] = PatternStats(pattern_name=name)
        p = patterns[name]
        p.count += 1
        p.categories.add(m.get("category", "other"))
        p.descriptions.append(m.get("description", ""))
        p.functions_seen_in.add(m.get("_function", "unknown"))
        if len(p.examples) < 2:
            p.examples.append(
                {
                    "function": m.get("_function", ""),
                    "code_snippet": m.get("mutated_code", "")[:300],
                }
            )

    return patterns


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print(
            "Error: ANTHROPIC_API_KEY not set. Check ~/pr/mutmut/.env", file=sys.stderr
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    all_mutations: list[dict] = []
    total_cost = 0.0
    results_by_function: dict[str, list[dict]] = {}

    print(
        f"Running mutation experiment on {len(SAMPLE_FUNCTIONS)} functions x 2 test qualities\n"
    )

    for func in SAMPLE_FUNCTIONS:
        func_name = func["name"]
        print(f"\n{'=' * 60}")
        print(f"Function: {func_name} ({func['category']})")

        for quality, test_desc in [
            ("loose", func["loose_tests"]),
            ("tight", func["tight_tests"]),
        ]:
            print(f"\n  [{quality} tests]")
            mutations, cost = call_llm(
                client=client,
                source=func["source"],
                test_description=test_desc,
                test_quality=quality,
                max_mutations=8,
            )
            total_cost += cost

            for m in mutations:
                m["_function"] = func_name
                m["_category"] = func["category"]
                m["_test_quality"] = quality

            key = f"{func_name}_{quality}"
            results_by_function[key] = mutations
            all_mutations.extend(mutations)
            print(f"    → {len(mutations)} mutations generated")

    # Analysis
    print(f"\n\n{'=' * 60}")
    print("RESULTS SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total mutations: {len(all_mutations)}")
    print(f"Total cost: ${total_cost:.4f}")

    valid_count = sum(1 for m in all_mutations if not m.get("_syntax_error"))
    print(f"Syntactically valid: {valid_count}/{len(all_mutations)}")

    patterns = analyze_results(all_mutations)
    sorted_patterns = sorted(patterns.values(), key=lambda p: p.count, reverse=True)

    print(f"\nUnique patterns discovered: {len(patterns)}")
    print("\n--- Patterns by frequency (potential new deterministic operators) ---\n")

    for p in sorted_patterns:
        generality = len(p.functions_seen_in)
        generalizable = (
            "GENERALIZABLE"
            if generality >= 3
            else "specific"
            if generality == 1
            else "moderate"
        )
        print(
            f"  [{p.count}x across {generality} functions] {p.pattern_name} ({generalizable})"
        )
        print(f"    Categories: {', '.join(p.categories)}")
        # Show first description as representative
        if p.descriptions:
            print(f"    Example: {p.descriptions[0][:120]}")
        print()

    # Save full results
    output_path = Path(__file__).parent / "llm_mutation_results.json"
    serializable = []
    for m in all_mutations:
        entry = {
            k: v
            for k, v in m.items()
            if not k.startswith("_")
            or k in ("_function", "_category", "_test_quality", "_syntax_error")
        }
        serializable.append(entry)

    # Save pattern analysis
    pattern_analysis = []
    for p in sorted_patterns:
        pattern_analysis.append(
            {
                "pattern_name": p.pattern_name,
                "count": p.count,
                "generality": len(p.functions_seen_in),
                "categories": sorted(p.categories),
                "functions_seen_in": sorted(p.functions_seen_in),
                "descriptions": p.descriptions[:3],
                "examples": p.examples,
            }
        )

    output = {
        "total_mutations": len(all_mutations),
        "total_cost_usd": round(total_cost, 4),
        "syntactically_valid": valid_count,
        "unique_patterns": len(patterns),
        "pattern_analysis": pattern_analysis,
        "all_mutations": serializable,
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nFull results saved to {output_path}")

    # Print the most promising patterns for new operators
    print(f"\n{'=' * 60}")
    print("TOP CANDIDATES FOR NEW DETERMINISTIC OPERATORS")
    print(f"{'=' * 60}\n")

    for p in sorted_patterns:
        if len(p.functions_seen_in) >= 2 and p.count >= 2:
            print(
                f"** {p.pattern_name} ** ({p.count}x, {len(p.functions_seen_in)} functions)"
            )
            for desc in p.descriptions[:3]:
                print(f"   - {desc[:150]}")
            if p.examples:
                print("   Example snippet:")
                print(f"   {p.examples[0]['code_snippet'][:200]}")
            print()


if __name__ == "__main__":
    main()
