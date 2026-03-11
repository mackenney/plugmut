"""Adversarial tests for Quick Wins implementation.

Targets: pragma validation edge cases, temperature config, system prompt quality,
integration gaps, and backwards compatibility.
"""

from __future__ import annotations

import json
import textwrap
from unittest.mock import MagicMock

import pytest

from mutmut_llm.config import LLMConfig, load_config
from mutmut_llm.pipeline import _call_llm_and_validate
from mutmut_llm.prompts import SYSTEM_PROMPT
from mutmut_llm.scope import ScopeTarget
from mutmut_llm.validation import validate_mutation, validate_pragmas


def _make_mock_response(
    mutations: list[dict], stop_reason: str = "end_turn"
) -> MagicMock:
    text_block = MagicMock()
    text_block.text = json.dumps(mutations)
    response = MagicMock()
    response.content = [text_block]
    response.stop_reason = stop_reason
    response.usage = MagicMock(input_tokens=100, output_tokens=200)
    return response


class TestPragmaEdgeCases:
    """validate_pragmas uses exact string match on '# pragma: no mutate'.
    Test what slips through and what falsely rejects.
    """

    def test_extra_spaces_before_hash(self):
        """Pragma with different leading whitespace — still detected because
        the full line is compared, and leading spaces are part of the line."""
        original = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        mutated = "def f():\n    x = 2  # pragma: no mutate\n    return x"
        result = validate_pragmas(mutated, original)
        assert result is not None, "Should reject: pragma line value changed"

    def test_no_space_after_hash(self):
        """'#pragma: no mutate' (no space after #) must be detected."""
        original = "def f():\n    x = 1  #pragma: no mutate\n    return x"
        mutated = "def f():\n    x = 2  #pragma: no mutate\n    return x"
        result = validate_pragmas(mutated, original)
        assert result is not None, (
            "Should reject: '#pragma: no mutate' (no space) must be recognized as a pragma"
        )

    def test_case_insensitive_pragma(self):
        """'# PRAGMA: NO MUTATE' or '# Pragma: No Mutate' must be detected."""
        original = "def f():\n    x = 1  # PRAGMA: NO MUTATE\n    return x"
        mutated = "def f():\n    x = 2  # PRAGMA: NO MUTATE\n    return x"
        result = validate_pragmas(mutated, original)
        assert result is not None, (
            "Should reject: uppercase '# PRAGMA: NO MUTATE' must be recognized"
        )

    def test_mutation_inserts_line_before_pragma(self):
        """BUG: If mutation adds a line before the pragma, the pragma shifts down
        and the positional check (idx comparison) fails to protect it."""
        original = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        mutated = "def f():\n    y = 0\n    x = 1  # pragma: no mutate\n    return x"
        result = validate_pragmas(mutated, original)
        # Pragma was at original index 1, but in mutated it's at index 2.
        # The check looks at mutated_lines[1] which is now "    y = 0" — mismatch!
        # This correctly rejects, but for the WRONG REASON: it thinks the pragma
        # line was modified, when really a line was inserted before it.
        assert result is not None, "Should reject when line inserted before pragma"

    def test_mutation_deletes_line_before_pragma(self):
        """BUG: Deleting a line before the pragma shifts it up. The positional
        check may now compare against the wrong line."""
        original = "def f():\n    y = 0\n    x = 1  # pragma: no mutate\n    return x"
        mutated = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        result = validate_pragmas(mutated, original)
        # Pragma at original index 2. mutated_lines[2] = "    return x" != pragma line.
        assert result is not None, "Should reject when line deleted before pragma"

    def test_pragma_in_multiline_string_is_data(self):
        """GAP: A multiline string containing 'pragma: no mutate' as data is
        treated as a real pragma, preventing valid mutations of surrounding code."""
        original = textwrap.dedent("""\
            def f():
                msg = '''
                # pragma: no mutate
                '''
                return msg + "hello"
        """)
        mutated = textwrap.dedent("""\
            def f():
                msg = '''
                # pragma: no mutate
                '''
                return msg + "world"
        """)
        result = validate_pragmas(mutated, original)
        # The pragma-in-string is detected as a real pragma. Since line 2 matches,
        # this passes. But if the mutation changed that line, it would be falsely
        # rejected. This is a false-positive risk for string content changes.
        assert result is None, (
            "Should pass: pragma in string data, code changed elsewhere"
        )

    def test_mutated_code_shorter_than_pragma_index(self):
        """When mutation makes function shorter, pragma index is out of bounds."""
        original = "def f():\n    a = 1\n    b = 2\n    c = 3  # pragma: no mutate\n    return a + b + c"
        mutated = "def f():\n    return 0"
        result = validate_pragmas(mutated, original)
        assert result is not None, "Should reject: pragma line is gone"

    def test_multiple_pragmas_only_first_checked(self):
        """If one pragma passes but another is violated, should still reject."""
        original = "x = 1  # pragma: no mutate\ny = 2  # pragma: no mutate\nz = 3"
        mutated = "x = 1  # pragma: no mutate\ny = 999  # pragma: no mutate\nz = 3"
        result = validate_pragmas(mutated, original)
        assert result is not None, "Should reject: second pragma line modified"

    def test_pragma_with_trailing_comment(self):
        """Pragma followed by additional comment text."""
        original = "def f():\n    x = 1  # pragma: no mutate -- keep this constant\n    return x"
        mutated = "def f():\n    x = 2  # pragma: no mutate -- keep this constant\n    return x"
        result = validate_pragmas(mutated, original)
        assert result is not None, "Should reject: pragma line modified"


class TestTemperatureConfig:
    def test_default_temperature(self):
        config = LLMConfig()
        assert config.temperature == 0.6

    def test_temperature_from_toml(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text("[tool.mutmut.llm]\ntemperature = 0.9\n")
        config = load_config(pyproject_path=toml, env={})
        assert config.temperature == 0.9

    def test_temperature_zero_from_toml(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text("[tool.mutmut.llm]\ntemperature = 0.0\n")
        config = load_config(pyproject_path=toml, env={})
        assert config.temperature == 0.0

    def test_missing_temperature_defaults(self, tmp_path):
        """Backwards compat: config without temperature key uses default 0.6."""
        toml = tmp_path / "pyproject.toml"
        toml.write_text('[tool.mutmut.llm]\nmodel = "claude-sonnet-4-6"\n')
        config = load_config(pyproject_path=toml, env={})
        assert config.temperature == 0.6

    def test_out_of_range_temperature_raises(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text("[tool.mutmut.llm]\ntemperature = 2.0\n")
        with pytest.raises(ValueError, match="temperature must be in"):
            load_config(pyproject_path=toml, env={})

    def test_negative_temperature_raises(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text("[tool.mutmut.llm]\ntemperature = -0.5\n")
        with pytest.raises(ValueError, match="temperature must be in"):
            load_config(pyproject_path=toml, env={})

    def test_temperature_string_coerced(self, tmp_path):
        """TOML parser returns float for 0.5 but string for "0.5" in a string field.
        Test that float() coercion works when TOML type is correct."""
        toml = tmp_path / "pyproject.toml"
        toml.write_text("[tool.mutmut.llm]\ntemperature = 0.5\n")
        config = load_config(pyproject_path=toml, env={})
        assert isinstance(config.temperature, float)
        assert config.temperature == 0.5


class TestSystemPromptQuality:
    def test_few_shot_good_example_is_valid_json(self):
        """The good mutation example in the prompt must be parseable JSON."""
        # Extract the JSON array from the "Output:" section after the good example
        idx = SYSTEM_PROMPT.index("Examples of GOOD mutations")
        output_idx = SYSTEM_PROMPT.index("Output:\n", idx)
        # Find the JSON array between "Output:\n" and "Examples of BAD"
        bad_idx = SYSTEM_PROMPT.index("Examples of BAD")
        json_text = SYSTEM_PROMPT[output_idx + len("Output:\n") : bad_idx].strip()
        parsed = json.loads(json_text)
        assert isinstance(parsed, list)
        assert len(parsed) >= 1
        for entry in parsed:
            assert "mutated_code" in entry
            assert "description" in entry

    def test_few_shot_good_examples_are_syntactically_valid_python(self):
        """Each mutated_code in good examples must be valid Python."""
        idx = SYSTEM_PROMPT.index("Examples of GOOD mutations")
        output_idx = SYSTEM_PROMPT.index("Output:\n", idx)
        bad_idx = SYSTEM_PROMPT.index("Examples of BAD")
        json_text = SYSTEM_PROMPT[output_idx + len("Output:\n") : bad_idx].strip()
        parsed = json.loads(json_text)
        import ast

        for entry in parsed:
            code = entry["mutated_code"]
            try:
                ast.parse(code)
            except SyntaxError:
                pytest.fail(f"Few-shot good example is not valid Python: {code!r}")

    def test_few_shot_good_examples_are_actual_mutations(self):
        """Good examples must differ from the input function."""
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
        """Bad examples should explicitly mention 'equivalent'."""
        idx = SYSTEM_PROMPT.index("Examples of BAD mutations")
        bad_section = SYSTEM_PROMPT[idx:]
        assert bad_section.count("equivalent") >= 3, (
            "Bad examples should clearly explain WHY each is bad (equivalence)"
        )

    def test_dedup_instruction_present_and_clear(self):
        assert "semantically distinct" in SYSTEM_PROMPT
        assert (
            "do not generate multiple variations of the same idea"
            in SYSTEM_PROMPT.lower()
            or "Do not generate multiple variations of the same idea" in SYSTEM_PROMPT
        )


class TestPragmaIntegration:
    """Test that validate_pragmas is properly wired into the pipeline."""

    def test_pragma_rejection_in_pipeline(self):
        """Pragma violations should be caught in _call_llm_and_validate."""
        original = (
            "def f(x):\n    CONST = 42  # pragma: no mutate\n    return x + CONST"
        )
        target = ScopeTarget(file_path="test.py", function_name="f", source=original)
        mutations = [
            {
                "mutated_code": "def f(x):\n    CONST = 99  # pragma: no mutate\n    return x + CONST",
                "description": "change constant",
            }
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)

        config = LLMConfig(api_key="test-key")
        result = _call_llm_and_validate(mock_client, config, target, max_mutations=3)
        assert len(result.mutations) == 0, (
            "Pragma-violating mutation should be rejected"
        )

    def test_valid_mutation_with_pragma_passes_pipeline(self):
        """Mutations that don't touch pragma lines should pass."""
        original = (
            "def f(x):\n    CONST = 42  # pragma: no mutate\n    return x + CONST"
        )
        target = ScopeTarget(file_path="test.py", function_name="f", source=original)
        mutations = [
            {
                "mutated_code": "def f(x):\n    CONST = 42  # pragma: no mutate\n    return x - CONST",
                "description": "change operator",
            }
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)

        config = LLMConfig(api_key="test-key")
        result = _call_llm_and_validate(mock_client, config, target, max_mutations=3)
        assert len(result.mutations) == 1, "Mutation not touching pragma should pass"

    def test_pragma_check_runs_after_syntax_and_import_checks(self):
        """Syntax errors should be caught before pragma check (short-circuit)."""
        original = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        mutated = "def f(\n    broken"
        result = validate_mutation(mutated, original)
        assert "Syntax error" in result, "Syntax check should run first"

    def test_pragma_check_order_with_imports(self):
        """Import errors should be caught before pragma check."""
        original = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        mutated = "import os\ndef f():\n    x = 999  # pragma: no mutate\n    return os.getcwd()"
        result = validate_mutation(mutated, original)
        assert "import" in result.lower(), "Import check should run before pragma check"


class TestBackwardsCompat:
    def test_llmconfig_no_temperature_arg(self):
        """LLMConfig() without temperature kwarg should work (default 0.6)."""
        config = LLMConfig(api_key="key", model="claude-sonnet-4-6")
        assert config.temperature == 0.6

    def test_load_config_empty_toml(self, tmp_path):
        """Empty [tool.mutmut.llm] section should use all defaults."""
        toml = tmp_path / "pyproject.toml"
        toml.write_text("[tool.mutmut.llm]\n")
        config = load_config(pyproject_path=toml, env={})
        assert config.temperature == 0.6
        assert config.model == "claude-sonnet-4-6"
        assert config.max_mutations_per_function == 5
        assert config.max_tokens == 4096
        assert config.enabled is True

    def test_load_config_no_toml_file(self, tmp_path):
        """No pyproject.toml at all — all defaults."""
        config = load_config(pyproject_path=None, env={})
        assert config.temperature == 0.6

    def test_old_config_keys_still_work(self, tmp_path):
        """All pre-existing config keys remain functional alongside temperature."""
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            textwrap.dedent("""\
            [tool.mutmut.llm]
            model = "claude-haiku-4-5"
            max_mutations_per_function = 10
            max_tokens = 8192
            enabled = false
            temperature = 0.3
        """)
        )
        config = load_config(pyproject_path=toml, env={})
        assert config.model == "claude-haiku-4-5"
        assert config.max_mutations_per_function == 10
        assert config.max_tokens == 8192
        assert config.enabled is False
        assert config.temperature == 0.3


class TestPragmaValidateEdgeCasesDeep:
    """Deeper edge cases for the positional line comparison approach."""

    def test_empty_original(self):
        """No pragmas in empty original."""
        assert validate_pragmas("def f(): pass", "") is None

    def test_empty_mutated(self):
        """Original has pragma, mutated is empty — should reject."""
        original = "x = 1  # pragma: no mutate"
        result = validate_pragmas("", original)
        assert result is not None

    def test_identical_code(self):
        """Identical code with pragmas should pass."""
        code = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        assert validate_pragmas(code, code) is None

    def test_pragma_on_def_line(self):
        """Pragma on the def line itself."""
        original = "def f():  # pragma: no mutate\n    return 1"
        mutated = "def g():  # pragma: no mutate\n    return 1"
        result = validate_pragmas(mutated, original)
        assert result is not None, "Renaming function with pragma should be rejected"

    def test_windows_line_endings(self):
        """BUG RISK: Windows \\r\\n line endings may cause splitlines mismatch."""
        original = "def f():\r\n    x = 1  # pragma: no mutate\r\n    return x"
        mutated = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        # splitlines() handles both, but the lines won't match due to trailing \r
        # in original but not mutated. This depends on splitlines() behavior.
        orig_lines = original.splitlines()
        mut_lines = mutated.splitlines()
        # Python's splitlines strips \r\n to just the content, so this should match
        assert orig_lines[1] == mut_lines[1], "splitlines should normalize line endings"
        result = validate_pragmas(mutated, original)
        assert result is None, "Should pass: same content, different line endings"

    def test_tab_vs_spaces_in_pragma_line(self):
        """If LLM converts tabs to spaces, pragma line won't match."""
        original = "def f():\n\tx = 1  # pragma: no mutate\n\treturn x"
        mutated = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        result = validate_pragmas(mutated, original)
        # Tab != 4 spaces, so the pragma line is "modified"
        assert result is not None, (
            "Tab-to-space conversion should be detected as modification"
        )
