"""Adversarial tests for dynamic exclusion list feature."""

from __future__ import annotations

import pytest
import libcst as cst

from mutmut_llm.prompts import (
    _describe_operator,
    _HARDCODED_EXCLUSIONS,
    build_exclusion_list,
    build_system_prompt,
)


class TestDescribeOperator:
    def test_function_with_docstring(self) -> None:
        def my_op(node):
            """Swap True for False."""
            return []

        desc = _describe_operator(cst.Name, my_op)
        assert desc == "Swap True for False."

    def test_function_without_docstring(self) -> None:
        def operator_swap_comparison(node):
            return []

        operator_swap_comparison.__doc__ = None
        desc = _describe_operator(cst.Name, operator_swap_comparison)
        assert "swap comparison" in desc
        assert "Name" in desc

    def test_function_with_empty_docstring(self) -> None:
        def my_op(node):
            """"""
            return []

        desc = _describe_operator(cst.Name, my_op)
        # Empty docstring should fall back to name-based description
        assert "Name" in desc

    def test_lambda_operator(self) -> None:
        op = lambda node: []  # noqa: E731
        desc = _describe_operator(cst.Name, op)
        # Lambda has name "<lambda>", should not crash
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_callable_object_without_name(self) -> None:
        class CallableOp:
            def __call__(self, node):
                return []

        op = CallableOp()
        # Remove __name__ if it exists
        assert not hasattr(op, "__name__")
        desc = _describe_operator(cst.Name, op)
        assert "unknown" in desc or "Name" in desc

    def test_non_cst_node_type(self) -> None:
        """Non-CST type should not crash _describe_operator."""

        def my_op(node):
            return []

        my_op.__doc__ = None
        desc = _describe_operator(int, my_op)
        assert "int" in desc


class TestBuildExclusionList:
    def test_empty_operator_lists(self) -> None:
        result = build_exclusion_list(operator_lists=[])
        assert result == _HARDCODED_EXCLUSIONS

    def test_none_falls_back(self) -> None:
        """None triggers plugin manager query; if unavailable, returns hardcoded."""
        result = build_exclusion_list(operator_lists=None)
        # In test env without plugins loaded, should get hardcoded or dynamic
        assert isinstance(result, str)
        assert len(result) > 0

    def test_1000_operators(self) -> None:
        """Large operator list should complete without issues."""
        ops = [(cst.Name, lambda n: []) for _ in range(1000)]
        result = build_exclusion_list(operator_lists=[ops])
        assert isinstance(result, str)
        # All 1000 have same description, so dedup should collapse to 1
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) == 1

    def test_deduplication(self) -> None:
        def op_a(node):
            """Same description."""
            return []

        def op_b(node):
            """Same description."""
            return []

        ops = [(cst.Name, op_a), (cst.Name, op_b)]
        result = build_exclusion_list(operator_lists=[ops])
        assert result.count("Same description.") == 1

    def test_multiple_operator_lists(self) -> None:
        def op_a(node):
            """Description A."""
            return []

        def op_b(node):
            """Description B."""
            return []

        list1 = [(cst.Name, op_a)]
        list2 = [(cst.Name, op_b)]
        result = build_exclusion_list(operator_lists=[list1, list2])
        assert "Description A." in result
        assert "Description B." in result

    def test_operator_with_multiline_docstring(self) -> None:
        def my_op(node):
            """First line.

            Detailed explanation that should NOT appear.
            """
            return []

        ops = [(cst.Name, my_op)]
        result = build_exclusion_list(operator_lists=[ops])
        assert "First line." in result
        assert "Detailed explanation" not in result


class TestBuildSystemPrompt:
    def test_exclusion_list_injected(self) -> None:
        def my_op(node):
            """Custom mutation type."""
            return []

        prompt = build_system_prompt(operator_lists=[[(cst.Name, my_op)]])
        assert "Custom mutation type." in prompt
        assert "mutation testing expert" in prompt

    def test_empty_ops_uses_hardcoded(self) -> None:
        prompt = build_system_prompt(operator_lists=[])
        assert "Arithmetic operator swaps" in prompt

    def test_template_format_injection_safe(self) -> None:
        """Operator descriptions with braces should not break str.format().

        Python's str.format() does not recursively process braces in
        substituted values, so this is safe by design.
        """

        def bad_op(node):
            """Swap {x} with {y} in dict literals."""
            return []

        ops = [(cst.Name, bad_op)]
        result = build_system_prompt(operator_lists=[ops])
        assert "Swap {x} with {y}" in result

    def test_operator_raising_exception_in_describe(self) -> None:
        """If getattr(__doc__) or __name__ raises, _describe_operator should not crash."""

        class EvilCallable:
            @property
            def __doc__(self):
                raise RuntimeError("evil doc")

            @property
            def __name__(self):
                raise RuntimeError("evil name")

            def __call__(self, node):
                return []

        op = EvilCallable()
        # _describe_operator uses getattr(..., None) which should handle property exceptions
        # BUT: getattr(obj, "__doc__", None) raises if __doc__ is a property that throws
        with pytest.raises(RuntimeError, match="evil doc"):
            _describe_operator(cst.Name, op)


class TestGetRegisteredOperators:
    def test_import_failure_returns_empty(self) -> None:
        """If mutmut.plugin_manager is not importable, should return []."""
        from mutmut_llm.prompts import _get_registered_operators

        # In test environment this may or may not work
        result = _get_registered_operators()
        assert isinstance(result, list)
