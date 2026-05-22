"""Prompt templates and response parsing for LLM mutation generation."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterable
    from collections.abc import Sequence

    import libcst as cst

    OperatorList = Sequence[tuple[type[cst.CSTNode], Callable[..., Iterable[cst.CSTNode]]]]

_CODE_BLOCK_RE = re.compile(r"```(?:\w*)\s*\n?(.*?)\n?```", re.DOTALL)

log = logging.getLogger(__name__)

_HARDCODED_EXCLUSIONS = """\
  * Arithmetic operator swaps (+↔-, *↔/, //↔/, **↔*)
  * Comparison operator swaps (==↔!=, <↔>, <=↔>=, is↔is not)
  * Boolean literal flips (True↔False)
  * Logical operator swaps (and↔or)
  * Unary operator changes (+x↔-x)
  * Keyword mutations (break↔continue, return x↔return None)
  * String and number constant mutations"""

SYSTEM_PROMPT_TEMPLATE = """\
You are a mutation testing expert. Given a Python function, generate subtle \
code mutations that a weak test suite might fail to detect.

Rules:
- Each mutation must be syntactically valid Python.
- Each mutation must change observable behavior (no equivalent mutants).
- Prefer mutations that exploit missing test coverage.
- Focus on: boundary conditions, logic errors, wrong API usage, state bugs.
- Do NOT generate these trivial mutations (already handled by rule-based operators):
{exclusion_list}
- Include the COMPLETE mutated function definition (including `def` line and full body).
- NEVER return the original code unchanged.

- Lines containing `# pragma: no mutate` must NOT be modified.
- Never move, remove, or modify pragma comments.
- Each mutation must be semantically distinct from the others. Do not generate multiple variations of the same idea.

Safety constraints:
- Only modify control flow, return values, conditions, and arithmetic.
- Never introduce calls to os, subprocess, eval, exec, pickle, socket, \
requests, or any I/O not already in the original code.
- Only use functions and methods already present in the original code.

Examples of GOOD mutations (the kind you should generate):

Input:
def clamp(x, lo, hi):
    return max(lo, min(x, hi))

Output:
[
  {{"mutated_code": "def clamp(x, lo, hi):\\n    return max(lo, min(x, lo))", "description": "Use lo instead of hi in inner min — clamp always returns lo for values above lo"}},
  {{"mutated_code": "def clamp(x, lo, hi):\\n    return max(hi, min(x, lo))", "description": "Swap lo/hi in outer max — returns hi instead of clamped value when x < lo"}}
]

Examples of BAD mutations (do NOT generate these):
- `return sorted(items)` → `return list(sorted(items))` — equivalent, sorted() already returns list
- `x = 5` → `tmp = 5; x = tmp` — equivalent, intermediate variable changes nothing
- `self.data[:]` instead of `self.data` — equivalent for most types
- `str(name)` when name is already a str — equivalent, no behavior change

Output a JSON array:
[{{"mutated_code": "def func(...):\\n    ...", "description": "what changed and why it might survive"}}]

Output ONLY the JSON array, no other text.\
"""


def _describe_operator(node_type: type, fn: object) -> str:
    """Extract a human-readable description from an operator callable.

    Uses the function docstring's first line if available,
    falls back to deriving a description from the function name and node type.
    """
    doc = getattr(fn, "__doc__", None)
    if doc:
        first_line = doc.strip().split("\n")[0].strip()
        if first_line:
            return first_line

    name = getattr(fn, "__name__", "unknown")
    readable_name = name.replace("operator_", "").replace("_", " ")
    target = getattr(node_type, "__name__", str(node_type))
    return f"{readable_name} (targets {target} nodes)"


def build_exclusion_list(operator_lists: list[OperatorList] | None = None) -> str:
    """Build the exclusion list from registered mutation operators.

    When *operator_lists* is ``None``, queries the plugin manager for all
    registered operators (both core and plugin). Pass an explicit list in
    tests to avoid depending on plugin registration state.
    """
    if operator_lists is None:
        operator_lists = _get_registered_operators()

    if not operator_lists:
        return _HARDCODED_EXCLUSIONS

    seen: set[str] = set()
    lines: list[str] = []
    for operators in operator_lists:
        for node_type, fn in operators:
            desc = _describe_operator(node_type, fn)
            if desc not in seen:
                seen.add(desc)
                lines.append(f"  * {desc}")

    return "\n".join(lines) if lines else _HARDCODED_EXCLUSIONS


def _get_registered_operators() -> list[OperatorList]:
    """Query the plugin manager for all registered operators.

    Returns an empty list if the plugin system is unavailable, letting the
    caller fall back to hardcoded exclusions.
    """
    try:
        from mutmut.plugin_manager import get_plugin_manager
    except ImportError:
        log.debug("mutmut plugin manager unavailable; using hardcoded exclusions")
        return []
    try:
        pm = get_plugin_manager()
        return pm.hook.mutmut_register_operators()
    except Exception:
        log.warning(
            "Error querying registered operators; falling back to hardcoded exclusions",
            exc_info=True,
        )
        return []


def build_system_prompt(operator_lists: list[OperatorList] | None = None) -> str:
    """Build the full system prompt with a dynamic exclusion list.

    Queries registered operators (core + plugins) and injects their
    descriptions into the prompt so the LLM avoids generating redundant
    mutations already covered by rule-based operators.
    """
    exclusion_list = build_exclusion_list(operator_lists)
    return SYSTEM_PROMPT_TEMPLATE.format(exclusion_list=exclusion_list)


def build_system_with_context(context: str = "", ttl: str = "5m", system_prompt: str | None = None) -> list[dict]:
    """Build system blocks with cache_control on the last block.

    Combines the system prompt with file-level context so the entire
    prefix is cached across calls to functions in the same file.

    *system_prompt* overrides the default; pass the return value of
    ``build_system_prompt()`` to use a dynamically-built prompt.
    If omitted, calls ``build_system_prompt()`` at call time so plugins
    registered after module import are included.
    """
    prompt = system_prompt if system_prompt is not None else build_system_prompt()

    cache_control: dict = {"type": "ephemeral"}
    if ttl == "1h":
        cache_control["ttl"] = "1h"

    context = (context or "").strip()

    blocks: list[dict] = [{"type": "text", "text": prompt}]
    if context:
        blocks.append(
            {
                "type": "text",
                "text": f"File context (imports, class headers):\n```python\n{context}\n```",
                "cache_control": cache_control,
            }
        )
    else:
        blocks[-1]["cache_control"] = cache_control
    return blocks


def build_user_prompt(
    function_source: str,
    max_mutations: int = 5,
) -> str:
    """Build the user message for mutation generation."""
    parts = [f"Function to mutate:\n```python\n{function_source}\n```"]
    parts.append(f"\nGenerate up to {max_mutations} subtle mutations.")
    return "\n".join(parts)


def parse_llm_response(response_text: str) -> list[dict]:
    """Parse LLM response into list of mutation dicts.

    Handles raw JSON, markdown code blocks, and bare JSON arrays in prose.
    Returns only dicts that contain a ``mutated_code`` key.
    """
    text = response_text.strip()
    if not text:
        return []

    # Fast path: entire text is valid JSON.
    result = _try_parse(text)
    if result is not None:
        return result

    # Try each markdown code block.
    for block in _CODE_BLOCK_RE.findall(text):
        result = _try_parse(block.strip())
        if result is not None:
            return result

    # Fallback: bare JSON array embedded in prose.
    bracket_match = re.search(r"\[.*]", text, re.DOTALL)
    if bracket_match:
        result = _try_parse(bracket_match.group(0))
        if result is not None:
            return result

    return []


def _try_parse(text: str) -> list[dict] | None:
    """Attempt JSON parse and validate structure. Returns None on failure."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    valid = [m for m in data if isinstance(m, dict) and "mutated_code" in m]
    return valid if valid else None
