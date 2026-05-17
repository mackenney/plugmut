"""Tests for mutmut_llm.operators."""

from __future__ import annotations

import json

import libcst as cst
import pytest

from mutmut_llm.library import Library, source_hash
from mutmut_llm.operators import (
    _parse_mutation,
    operator_llm,
    reset_library,
    set_library,
)


def _make_func_node(source: str) -> cst.FunctionDef:
    """Parse a function source string into a FunctionDef node."""
    module = cst.parse_module(source)
    for stmt in module.body:
        if isinstance(stmt, cst.FunctionDef):
            return stmt
    raise ValueError(f"No FunctionDef found in: {source}")


def _inject_entry(
    lib: Library, source: str, mutations: list[dict], model: str = "test"
) -> None:
    """Bypass Library validation and write a raw entry JSON directly to entries dir.

    Used to test operator_llm's handling of entries with invalid syntax or wrong names
    that Library.add() would normally reject.
    """
    src_h = source_hash(source)
    entries_dir = lib._entries_dir
    entries_dir.mkdir(parents=True, exist_ok=True)
    entry_data = {
        "function_name": "f",
        "file_path": "test.py",
        "source_hash": src_h,
        "model": model,
        "mutations": mutations,
    }
    (entries_dir / f"injected_{model}.json").write_text(json.dumps(entry_data))
    lib._index = None  # force index rebuild on next query


@pytest.fixture
def library(tmp_path):
    lib = Library(base_dir=tmp_path)
    set_library(lib)
    yield lib
    reset_library()


class TestOperatorLlm:
    """Test the operator_llm function (reads from library, yields FunctionDef nodes)."""

    def test_library_hit_yields_mutations(self, library):
        func_source = "def f(x):\n    return x + 1\n"
        mutated = "def f(x):\n    return x - 1\n"
        library.add(
            function_name="f",
            file_path="test.py",
            source=func_source,
            mutations=[{"mutated_code": mutated}],
            model="test",
        )

        node = _make_func_node(func_source)
        results = list(operator_llm(node))
        assert len(results) == 1
        assert isinstance(results[0], cst.FunctionDef)
        assert results[0].name.value == "f"

    def test_library_miss_yields_nothing(self, library):
        node = _make_func_node("def g():\n    return 42\n")
        results = list(operator_llm(node))
        assert results == []

    def test_no_library_yields_nothing(self):
        """When _library is None, operator_llm returns [] silently."""
        reset_library()
        node = _make_func_node("def h():\n    return 0\n")
        results = list(operator_llm(node))
        assert results == []

    def test_multiple_mutations(self, library):
        func_source = "def f(x):\n    return x + 1\n"
        mutations = [
            {"mutated_code": "def f(x):\n    return x - 1\n"},
            {"mutated_code": "def f(x):\n    return x * 2\n"},
            {"mutated_code": "def f(x):\n    return 0\n"},
        ]
        library.add(
            function_name="f",
            file_path="test.py",
            source=func_source,
            mutations=mutations,
            model="test",
        )

        node = _make_func_node(func_source)
        results = list(operator_llm(node))
        assert len(results) == 3

    def test_invalid_syntax_in_entry_skipped(self, library):
        """Mutations with invalid syntax stored in library are skipped with a warning."""
        func_source = "def f(x):\n    return x\n"
        _inject_entry(
            library,
            source=func_source,
            mutations=[
                {"mutated_code": "def f(x broken syntax"},
                {"mutated_code": "def f(x):\n    return -x\n"},
            ],
        )

        node = _make_func_node(func_source)
        with pytest.warns(UserWarning, match="invalid syntax"):
            results = list(operator_llm(node))
        assert len(results) == 1

    def test_wrong_function_name_in_entry_skipped(self, library):
        """Mutations containing a different function name are skipped with a warning."""
        func_source = "def f(x):\n    return x\n"
        _inject_entry(
            library,
            source=func_source,
            mutations=[{"mutated_code": "def g(x):\n    return -x\n"}],
        )

        node = _make_func_node(func_source)
        with pytest.warns(UserWarning, match="doesn't contain expected"):
            results = list(operator_llm(node))
        assert results == []

    def test_source_hash_based_lookup(self, library):
        """Library lookup uses source_hash — finds entry regardless of stored function_name."""
        func_source = "def bar(self):\n    return 1\n"
        mutated = "def bar(self):\n    return 2\n"

        # Store with qualified name "Foo.bar" (as scope analysis would produce)
        library.add(
            function_name="Foo.bar",
            file_path="test.py",
            source=func_source,
            mutations=[{"mutated_code": mutated}],
            model="test",
        )

        # Operator sees bare name "bar" from the CST node
        node = _make_func_node(func_source)
        assert node.name.value == "bar"

        results = list(operator_llm(node))
        assert len(results) == 1

    def test_query_returns_empty_for_unrelated_function(self, library):
        """Library with entries for f returns nothing for g (different source hash)."""
        func_f = "def f():\n    return 1\n"
        library.add(
            function_name="f",
            file_path="test.py",
            source=func_f,
            mutations=[{"mutated_code": "def f():\n    return 2\n"}],
            model="test",
        )

        node_g = _make_func_node("def g():\n    return 1\n")
        results = list(operator_llm(node_g))
        assert results == []


class TestParseMutation:
    def test_valid_function(self):
        code = "def f(x):\n    return x + 1"
        result = _parse_mutation(code, "f")
        assert result is not None
        assert isinstance(result, cst.FunctionDef)
        assert result.name.value == "f"

    def test_invalid_syntax(self):
        with pytest.warns(UserWarning, match="invalid syntax"):
            result = _parse_mutation("def f( broken", "f")
        assert result is None

    def test_wrong_name(self):
        with pytest.warns(UserWarning, match="doesn't contain expected"):
            result = _parse_mutation("def g():\n    pass", "f")
        assert result is None

    def test_multiple_functions_picks_correct(self):
        code = "def helper():\n    pass\n\ndef target():\n    return 1"
        result = _parse_mutation(code, "target")
        assert result is not None
        assert result.name.value == "target"

    def test_function_with_decorators(self):
        code = "@staticmethod\ndef f():\n    return 1"
        result = _parse_mutation(code, "f")
        assert result is not None

    def test_empty_string(self):
        # Empty string parses as empty module — no FunctionDef found
        with pytest.warns(UserWarning, match="doesn't contain expected"):
            result = _parse_mutation("", "f")
        assert result is None


class TestDeduplicationEdgeCases:
    """operator_llm deduplicates by exact mutated_code string."""

    def test_whitespace_only_difference_not_deduped(self, library):
        """Trailing newline difference = two separate mutations."""
        source = "def foo():\n    return 1\n"
        library.add(
            function_name="foo",
            file_path="a.py",
            source=source,
            mutations=[
                {
                    "mutated_code": "def foo():\n    return 2\n",
                    "description": "with newline",
                }
            ],
            model="model-a",
        )
        library.add(
            function_name="foo",
            file_path="a.py",
            source=source,
            mutations=[
                {
                    "mutated_code": "def foo():\n    return 2",
                    "description": "without newline",
                }
            ],
            model="model-b",
        )

        node = _make_func_node(source)
        results = list(operator_llm(node))
        assert len(results) == 2

    def test_identical_mutations_from_three_models_deduped(self, library):
        """Same mutation from 3 models yields exactly 1 result."""
        source = "def foo():\n    return 1\n"
        shared = "def foo():\n    return 2\n"

        for i in range(3):
            library.add(
                function_name="foo",
                file_path="a.py",
                source=source,
                mutations=[{"mutated_code": shared, "description": f"from model {i}"}],
                model=f"model-{i}",
            )

        node = _make_func_node(source)
        results = list(operator_llm(node))
        assert len(results) == 1
