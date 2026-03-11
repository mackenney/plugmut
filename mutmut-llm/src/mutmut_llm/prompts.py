"""Prompt templates and response parsing for LLM mutation generation."""

from __future__ import annotations

import json
import re

_CODE_BLOCK_RE = re.compile(r"```(?:\w*)\s*\n?(.*?)\n?```", re.DOTALL)

SYSTEM_PROMPT = """\
You are a mutation testing expert. Given a Python function, generate subtle \
code mutations that a weak test suite might fail to detect.

Rules:
- Each mutation must be syntactically valid Python.
- Each mutation must change observable behavior (no equivalent mutants).
- Prefer mutations that exploit missing test coverage.
- Focus on: boundary conditions, logic errors, wrong API usage, state bugs.
- Do NOT generate these trivial mutations (already handled by rule-based operators):
  * Arithmetic operator swaps (+↔-, *↔/, //↔/, **↔*)
  * Comparison operator swaps (==↔!=, <↔>, <=↔>=, is↔is not)
  * Boolean literal flips (True↔False)
  * Logical operator swaps (and↔or)
  * Unary operator changes (+x↔-x)
  * Keyword mutations (break↔continue, return x↔return None)
  * String and number constant mutations
- Include the COMPLETE mutated function definition (including `def` line and full body).
- NEVER return the original code unchanged.

Safety constraints:
- Only modify control flow, return values, conditions, and arithmetic.
- Never introduce calls to os, subprocess, eval, exec, pickle, socket, \
requests, or any I/O not already in the original code.
- Only use functions and methods already present in the original code.

Output a JSON array:
[{"mutated_code": "def func(...):\\n    ...", "description": "what changed and why it might survive"}]

Output ONLY the JSON array, no other text.\
"""


def build_system_with_context(context: str = "", ttl: str = "5m") -> list[dict]:
    """Build system blocks with cache_control on the last block.

    Combines SYSTEM_PROMPT with file-level context so the entire
    prefix is cached across calls to functions in the same file.
    """
    cache_control: dict = {"type": "ephemeral"}
    if ttl == "1h":
        cache_control["ttl"] = "1h"

    context = (context or "").strip()

    blocks: list[dict] = [{"type": "text", "text": SYSTEM_PROMPT}]
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
    context: str = "",
) -> str:
    """Build the user message for mutation generation.

    The *context* parameter is accepted for backward compatibility but
    ignored — file context is now included in the system blocks via
    ``build_system_with_context`` for prompt caching.
    """
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
