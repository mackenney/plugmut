"""Tests for mutmut_llm.prompts."""

from __future__ import annotations

import json
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from mutmut_llm.prompts import SYSTEM_PROMPT_TEMPLATE
from mutmut_llm.prompts import _HARDCODED_EXCLUSIONS
from mutmut_llm.prompts import _describe_operator
from mutmut_llm.prompts import build_exclusion_list
from mutmut_llm.prompts import build_system_prompt
from mutmut_llm.prompts import build_system_with_context
from mutmut_llm.prompts import build_user_prompt
from mutmut_llm.prompts import parse_llm_response

# Call at module level so all tests share the same snapshot; deterministic because
# operator registry state is stable within a test session.
SYSTEM_PROMPT = build_system_prompt()

class TestSystemPrompt:
    def test_mentions_json_output(self):
        assert "JSON array" in SYSTEM_PROMPT

    def test_mentions_mutated_code_key(self):
        assert "mutated_code" in SYSTEM_PROMPT

    def test_mentions_safety_constraints(self):
        for keyword in ("subprocess", "eval", "exec", "pickle", "os"):
            assert keyword in SYSTEM_PROMPT

    def test_forbids_trivial_mutations(self):
        assert "Do NOT generate" in SYSTEM_PROMPT
        assert "rule-based operators" in SYSTEM_PROMPT

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


class TestSystemPromptFewShot:
    """Validate that few-shot examples in the system prompt are well-formed."""

    def test_good_example_is_valid_json(self):
        idx = SYSTEM_PROMPT.index("Examples of GOOD mutations")
        output_idx = SYSTEM_PROMPT.index("Output:\n", idx)
        bad_idx = SYSTEM_PROMPT.index("Examples of BAD")
        json_text = SYSTEM_PROMPT[output_idx + len("Output:\n") : bad_idx].strip()
        parsed = json.loads(json_text)
        assert isinstance(parsed, list)
        assert len(parsed) >= 1
        for entry in parsed:
            assert "mutated_code" in entry
            assert "description" in entry

    def test_good_examples_are_syntactically_valid_python(self):
        import ast

        idx = SYSTEM_PROMPT.index("Examples of GOOD mutations")
        output_idx = SYSTEM_PROMPT.index("Output:\n", idx)
        bad_idx = SYSTEM_PROMPT.index("Examples of BAD")
        json_text = SYSTEM_PROMPT[output_idx + len("Output:\n") : bad_idx].strip()
        parsed = json.loads(json_text)
        for entry in parsed:
            code = entry["mutated_code"]
            try:
                ast.parse(code)
            except SyntaxError:
                pytest.fail(f"Few-shot good example is not valid Python: {code!r}")

    def test_good_examples_are_actual_mutations(self):
        original = "def clamp(x, lo, hi):\n    return max(lo, min(x, hi))"
        idx = SYSTEM_PROMPT.index("Examples of GOOD mutations")
        output_idx = SYSTEM_PROMPT.index("Output:\n", idx)
        bad_idx = SYSTEM_PROMPT.index("Examples of BAD")
        json_text = SYSTEM_PROMPT[output_idx + len("Output:\n") : bad_idx].strip()
        parsed = json.loads(json_text)
        for entry in parsed:
            assert entry["mutated_code"] != original, (
                "Good example is identical to input"
            )

    def test_bad_examples_describe_equivalence(self):
        idx = SYSTEM_PROMPT.index("Examples of BAD mutations")
        bad_section = SYSTEM_PROMPT[idx:]
        assert bad_section.count("equivalent") >= 3, (
            "Bad examples should clearly explain WHY each is bad (equivalence)"
        )


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

    def test_no_context_in_user_prompt(self):
        prompt = build_user_prompt(self.SAMPLE_FUNC)
        assert "File context" not in prompt


class TestSystemBlockStructure:
    """Verify system blocks match Anthropic's expected content-block schema."""

    def test_block_has_required_keys_with_context(self):
        blocks = build_system_with_context("import os")
        for block in blocks:
            assert "type" in block
            assert "text" in block
            assert block["type"] == "text"

    def test_block_has_required_keys_without_context(self):
        blocks = build_system_with_context("")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"
        assert "text" in blocks[0]
        assert "cache_control" in blocks[0]

    def test_cache_control_only_on_last_block(self):
        blocks = build_system_with_context("import os")
        assert "cache_control" not in blocks[0]
        assert "cache_control" in blocks[-1]

    def test_cache_control_shape(self):
        blocks = build_system_with_context("ctx")
        cc = blocks[-1]["cache_control"]
        assert "type" in cc
        assert cc["type"] == "ephemeral"

    def test_no_extra_keys_in_blocks(self):
        """Anthropic API rejects unknown keys in content blocks."""
        blocks = build_system_with_context("ctx")
        allowed_keys = {"type", "text", "cache_control"}
        for block in blocks:
            assert set(block.keys()) <= allowed_keys

    def test_none_context_produces_single_block(self):
        """None is falsy like empty string — should not crash."""
        blocks = build_system_with_context(None)  # type: ignore[arg-type]
        assert len(blocks) == 1
        assert "cache_control" in blocks[0]

    def test_whitespace_only_context_treated_as_empty(self):
        """Whitespace-only context is stripped and treated as no context."""
        blocks = build_system_with_context("   ")
        assert len(blocks) == 1
        assert "cache_control" in blocks[0]


class TestBuildSystemWithContext:
    def test_empty_context_single_block(self):
        blocks = build_system_with_context("")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"
        assert "mutation testing expert" in blocks[0]["text"]
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}

    def test_with_context_two_blocks(self):
        blocks = build_system_with_context("import foo")
        assert len(blocks) == 2
        assert "mutation testing expert" in blocks[0]["text"]
        assert "cache_control" not in blocks[0]
        assert "import foo" in blocks[1]["text"]
        assert blocks[1]["cache_control"] == {"type": "ephemeral"}

    def test_ttl_default_no_ttl_key(self):
        blocks = build_system_with_context("import foo")
        assert "ttl" not in blocks[1]["cache_control"]

    def test_ttl_1h_included(self):
        blocks = build_system_with_context("import foo", ttl="1h")
        assert blocks[1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    def test_ttl_1h_empty_context(self):
        blocks = build_system_with_context("", ttl="1h")
        assert blocks[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    def test_system_prompt_text_used_by_default(self):
        blocks = build_system_with_context("ctx")
        assert blocks[0]["text"] == SYSTEM_PROMPT

    def test_custom_system_prompt_override(self):
        custom = "You are a custom prompt."
        blocks = build_system_with_context("ctx", system_prompt=custom)
        assert blocks[0]["text"] == custom

    def test_unknown_ttl_no_ttl_key(self):
        """TTL validation is in LLMConfig; build_system_with_context trusts callers."""
        blocks = build_system_with_context("ctx", ttl="5m")
        assert "ttl" not in blocks[-1]["cache_control"]


class TestDescribeOperator:
    """Test _describe_operator extraction logic."""

    def test_uses_docstring_first_line(self):
        def operator_example():
            """Mutate X by doing Y. Example: `a` -> `b`."""

        result = _describe_operator(type("FakeNode", (), {}), operator_example)
        assert result == "Mutate X by doing Y. Example: `a` -> `b`."

    def test_multiline_docstring_uses_first_line_only(self):
        def operator_multi():
            """First line summary.

            Extended description that should be ignored.
            """

        result = _describe_operator(type("FakeNode", (), {}), operator_multi)
        assert result == "First line summary."

    def test_no_docstring_falls_back_to_name(self):
        def operator_swap_args():
            pass

        NodeType = type("BinaryOperation", (), {})
        result = _describe_operator(NodeType, operator_swap_args)
        assert result == "swap args (targets BinaryOperation nodes)"

    def test_empty_docstring_falls_back_to_name(self):
        fn = MagicMock()
        fn.__doc__ = ""
        fn.__name__ = "operator_return_none"
        NodeType = type("ReturnStatement", (), {})
        result = _describe_operator(NodeType, fn)
        assert result == "return none (targets ReturnStatement nodes)"

    def test_whitespace_only_docstring_falls_back(self):
        fn = MagicMock()
        fn.__doc__ = "   \n   "
        fn.__name__ = "operator_test"
        NodeType = type("Node", (), {})
        result = _describe_operator(NodeType, fn)
        assert result == "test (targets Node nodes)"


class TestBuildExclusionList:
    """Test build_exclusion_list with explicit operator lists."""

    def _make_operator(self, name: str, doc: str | None = None):
        fn = lambda node: []  # noqa: E731
        fn.__name__ = name
        fn.__doc__ = doc
        return fn

    def test_empty_operator_lists_returns_hardcoded(self):
        result = build_exclusion_list(operator_lists=[])
        assert result == _HARDCODED_EXCLUSIONS

    def test_none_queries_plugin_manager(self):
        """When operator_lists is None, it tries to query the plugin manager."""
        mock_ops = [
            [(type("Node", (), {}), self._make_operator("operator_foo", "Do foo."))]
        ]
        with patch(
            "mutmut_llm.prompts._get_registered_operators", return_value=mock_ops
        ):
            result = build_exclusion_list(operator_lists=None)
        assert "Do foo." in result

    def test_single_operator_with_docstring(self):
        fn = self._make_operator(
            "operator_return_none", "Mutate return to return None."
        )
        ops = [[(type("Node", (), {}), fn)]]
        result = build_exclusion_list(operator_lists=ops)
        assert "  * Mutate return to return None." in result

    def test_single_operator_without_docstring(self):
        fn = self._make_operator("operator_swap_args", None)
        NodeType = type("BinaryOp", (), {})
        ops = [[(NodeType, fn)]]
        result = build_exclusion_list(operator_lists=ops)
        assert "  * swap args (targets BinaryOp nodes)" in result

    def test_multiple_operator_lists_combined(self):
        fn1 = self._make_operator("operator_a", "Does A.")
        fn2 = self._make_operator("operator_b", "Does B.")
        ops = [
            [(type("N1", (), {}), fn1)],
            [(type("N2", (), {}), fn2)],
        ]
        result = build_exclusion_list(operator_lists=ops)
        assert "Does A." in result
        assert "Does B." in result

    def test_deduplicates_identical_descriptions(self):
        fn1 = self._make_operator("operator_x", "Same description.")
        fn2 = self._make_operator("operator_y", "Same description.")
        ops = [[(type("N", (), {}), fn1), (type("N", (), {}), fn2)]]
        result = build_exclusion_list(operator_lists=ops)
        assert result.count("Same description.") == 1

    def test_mixed_docstring_and_fallback(self):
        fn_with_doc = self._make_operator("operator_a", "Has a docstring.")
        fn_no_doc = self._make_operator("operator_boundary_check", None)
        NodeType = type("Compare", (), {})
        ops = [[(NodeType, fn_with_doc), (NodeType, fn_no_doc)]]
        result = build_exclusion_list(operator_lists=ops)
        assert "Has a docstring." in result
        assert "boundary check (targets Compare nodes)" in result

    def test_each_line_starts_with_bullet(self):
        fn1 = self._make_operator("operator_a", "Does A.")
        fn2 = self._make_operator("operator_b", "Does B.")
        ops = [[(type("N", (), {}), fn1), (type("N", (), {}), fn2)]]
        result = build_exclusion_list(operator_lists=ops)
        for line in result.split("\n"):
            assert line.startswith("  * "), f"Line missing bullet prefix: {line!r}"


class TestBuildSystemPrompt:
    """Test build_system_prompt integration."""

    def _make_operator(self, name: str, doc: str | None = None):
        fn = lambda node: []  # noqa: E731
        fn.__name__ = name
        fn.__doc__ = doc
        return fn

    def test_with_operators_includes_descriptions(self):
        fn = self._make_operator("operator_foo", "Mutate foo to bar.")
        ops = [[(type("Node", (), {}), fn)]]
        prompt = build_system_prompt(operator_lists=ops)
        assert "Mutate foo to bar." in prompt
        assert "mutation testing expert" in prompt

    def test_with_empty_operators_uses_hardcoded(self):
        prompt = build_system_prompt(operator_lists=[])
        assert "Arithmetic operator swaps" in prompt

    def test_template_braces_in_examples_preserved(self):
        """Double braces in template must render as single braces in output."""
        fn = self._make_operator("operator_x", "X.")
        ops = [[(type("N", (), {}), fn)]]
        prompt = build_system_prompt(operator_lists=ops)
        assert '"mutated_code"' in prompt
        assert "{{" not in prompt

    def test_is_valid_template(self):
        """SYSTEM_PROMPT_TEMPLATE has exactly one placeholder: {exclusion_list}."""
        result = SYSTEM_PROMPT_TEMPLATE.format(exclusion_list="PLACEHOLDER")
        assert "PLACEHOLDER" in result
        assert "{exclusion_list}" not in result


class TestGetRegisteredOperators:
    """Test _get_registered_operators fallback behavior."""

    def test_returns_empty_on_import_error(self):
        import sys

        from mutmut_llm.prompts import _get_registered_operators

        with patch.dict(sys.modules, {"mutmut.plugin_manager": None}):
            result = _get_registered_operators()
            assert result == []

    def test_returns_operators_when_available(self):
        from mutmut_llm.prompts import _get_registered_operators

        mock_pm = MagicMock()
        mock_pm.hook.mutmut_register_operators.return_value = [
            [(type("Node", (), {}), lambda n: [])]
        ]
        with patch("mutmut.plugin_manager.get_plugin_manager", return_value=mock_pm):
            result = _get_registered_operators()
            assert len(result) == 1


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
