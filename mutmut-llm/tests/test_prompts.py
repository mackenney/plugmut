"""Tests for mutmut_llm.prompts."""

from __future__ import annotations

import json

from mutmut_llm.prompts import SYSTEM_PROMPT, build_user_prompt, parse_llm_response


class TestSystemPrompt:
    def test_mentions_json_output(self):
        assert "JSON array" in SYSTEM_PROMPT

    def test_mentions_mutated_code_key(self):
        assert "mutated_code" in SYSTEM_PROMPT

    def test_mentions_safety_constraints(self):
        for keyword in ("subprocess", "eval", "exec", "pickle", "os"):
            assert keyword in SYSTEM_PROMPT

    def test_forbids_trivial_mutations(self):
        for keyword in ("Arithmetic", "Comparison", "Boolean"):
            assert keyword in SYSTEM_PROMPT

    def test_contains_pragma_instruction(self):
        assert "pragma: no mutate" in SYSTEM_PROMPT
        assert "Never move, remove, or modify pragma comments" in SYSTEM_PROMPT

    def test_contains_dedup_instruction(self):
        assert "semantically distinct" in SYSTEM_PROMPT

    def test_contains_few_shot_good_examples(self):
        assert "Examples of GOOD mutations" in SYSTEM_PROMPT
        assert "def clamp" in SYSTEM_PROMPT

    def test_contains_few_shot_bad_examples(self):
        assert "Examples of BAD mutations" in SYSTEM_PROMPT
        assert "equivalent" in SYSTEM_PROMPT

    def test_prompt_word_count_reasonable(self):
        word_count = len(SYSTEM_PROMPT.split())
        assert word_count < 600, f"System prompt too long: {word_count} words"


class TestBuildUserPrompt:
    SAMPLE_FUNC = "def add(a, b):\n    return a + b"

    def test_contains_function_source(self):
        prompt = build_user_prompt(self.SAMPLE_FUNC)
        assert self.SAMPLE_FUNC in prompt

    def test_default_max_mutations(self):
        prompt = build_user_prompt(self.SAMPLE_FUNC)
        assert "up to 5" in prompt

    def test_custom_max_mutations(self):
        prompt = build_user_prompt(self.SAMPLE_FUNC, max_mutations=3)
        assert "up to 3" in prompt

    def test_without_context(self):
        prompt = build_user_prompt(self.SAMPLE_FUNC)
        assert "File context" not in prompt

    def test_with_context(self):
        ctx = "import math"
        prompt = build_user_prompt(self.SAMPLE_FUNC, context=ctx)
        assert "File context" in prompt
        assert ctx in prompt

    def test_empty_context_is_omitted(self):
        prompt = build_user_prompt(self.SAMPLE_FUNC, context="")
        assert "File context" not in prompt


class TestParseLlmResponse:
    """Test various response formats the LLM might produce."""

    VALID_MUTATION = {
        "mutated_code": "def add(a, b):\n    return a - b",
        "description": "swap + to -",
    }

    def test_raw_json_array(self):
        text = json.dumps([self.VALID_MUTATION])
        result = parse_llm_response(text)
        assert len(result) == 1
        assert result[0]["mutated_code"] == self.VALID_MUTATION["mutated_code"]

    def test_json_in_code_block(self):
        text = f"Here are mutations:\n```json\n{json.dumps([self.VALID_MUTATION])}\n```"
        result = parse_llm_response(text)
        assert len(result) == 1

    def test_json_in_unmarked_code_block(self):
        text = f"```\n{json.dumps([self.VALID_MUTATION])}\n```"
        result = parse_llm_response(text)
        assert len(result) == 1

    def test_bare_array_in_prose(self):
        text = (
            f"Sure, here you go: {json.dumps([self.VALID_MUTATION])} Hope that helps!"
        )
        result = parse_llm_response(text)
        assert len(result) == 1

    def test_multiple_mutations(self):
        mutations = [
            {"mutated_code": "def f(): return 1", "description": "a"},
            {"mutated_code": "def f(): return 2", "description": "b"},
            {"mutated_code": "def f(): return 3", "description": "c"},
        ]
        result = parse_llm_response(json.dumps(mutations))
        assert len(result) == 3

    def test_empty_string(self):
        assert parse_llm_response("") == []

    def test_whitespace_only(self):
        assert parse_llm_response("   \n  ") == []

    def test_invalid_json(self):
        assert parse_llm_response("this is not json at all") == []

    def test_json_object_not_array(self):
        assert parse_llm_response('{"mutated_code": "x"}') == []

    def test_array_without_mutated_code_key(self):
        assert parse_llm_response('[{"code": "x", "desc": "y"}]') == []

    def test_mixed_valid_invalid_entries(self):
        data = [
            {"mutated_code": "def f(): pass", "description": "ok"},
            {"no_code": "bad"},
            42,
            {"mutated_code": "def g(): pass"},
        ]
        result = parse_llm_response(json.dumps(data))
        assert len(result) == 2
        assert all("mutated_code" in m for m in result)

    def test_truncated_json(self):
        text = '[{"mutated_code": "def f(): pass", "description": "trunc'
        assert parse_llm_response(text) == []

    def test_multiple_code_blocks_first_invalid(self):
        """If first code block is not JSON, try subsequent ones."""
        good = json.dumps([self.VALID_MUTATION])
        text = f"```python\ndef example(): pass\n```\n\n```json\n{good}\n```"
        result = parse_llm_response(text)
        assert len(result) == 1

    def test_preserves_extra_keys(self):
        """Extra keys in mutation dicts are kept (forward-compat)."""
        mutation = {**self.VALID_MUTATION, "confidence": 0.9}
        result = parse_llm_response(json.dumps([mutation]))
        assert result[0]["confidence"] == 0.9

    def test_empty_array(self):
        assert parse_llm_response("[]") == []

    def test_nested_code_in_mutated_code(self):
        """Mutation code containing backticks shouldn't break parsing."""
        mutation = {
            "mutated_code": 'def f():\n    x = "```"\n    return x',
            "description": "backtick string",
        }
        text = json.dumps([mutation])
        result = parse_llm_response(text)
        assert len(result) == 1
