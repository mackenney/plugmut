"""Tests for mutmut_llm.operators."""

from __future__ import annotations

from pathlib import Path

import libcst as cst
import pytest

from mutmut_llm.cache import CacheEntry, CachedMutation, source_hash, write_cache_entry
from mutmut_llm.operators import _parse_mutation, _reset_cache_index, operator_llm


@pytest.fixture(autouse=True)
def _clean_cache_index():
    """Reset the in-memory cache index before each test."""
    _reset_cache_index()
    yield
    _reset_cache_index()


def _make_func_node(source: str) -> cst.FunctionDef:
    """Parse a function source string into a FunctionDef node."""
    module = cst.parse_module(source)
    for stmt in module.body:
        if isinstance(stmt, cst.FunctionDef):
            return stmt
    raise ValueError(f"No FunctionDef found in: {source}")


def _write_test_cache(
    func_source: str,
    mutations: list[dict],
    base_dir: Path,
    file_path: str = "test.py",
    func_name: str = "f",
) -> None:
    """Helper to write a cache entry for testing."""
    entry = CacheEntry(
        function_name=func_name,
        file_path=file_path,
        source_hash=source_hash(func_source),
        mutations=[
            CachedMutation(mutated_code=m["code"], description=m.get("desc", ""))
            for m in mutations
        ],
        model="test",
    )
    write_cache_entry(entry, base_dir=base_dir)


class TestOperatorLlm:
    """Test the operator_llm function (reads from cache, yields FunctionDef nodes)."""

    def test_cache_hit_yields_mutations(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        func_source = "def f(x):\n    return x + 1\n"
        mutated = "def f(x):\n    return x - 1\n"
        _write_test_cache(func_source, [{"code": mutated}], tmp_path, func_name="f")

        node = _make_func_node(func_source)
        results = list(operator_llm(node))
        assert len(results) == 1
        assert isinstance(results[0], cst.FunctionDef)
        assert results[0].name.value == "f"

    def test_cache_miss_yields_nothing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        node = _make_func_node("def g():\n    return 42\n")
        results = list(operator_llm(node))
        assert results == []

    def test_multiple_mutations(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        func_source = "def f(x):\n    return x + 1\n"
        mutations = [
            {"code": "def f(x):\n    return x - 1\n"},
            {"code": "def f(x):\n    return x * 2\n"},
            {"code": "def f(x):\n    return 0\n"},
        ]
        _write_test_cache(func_source, mutations, tmp_path, func_name="f")

        node = _make_func_node(func_source)
        results = list(operator_llm(node))
        assert len(results) == 3

    def test_invalid_syntax_skipped(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        func_source = "def f(x):\n    return x\n"
        mutations = [
            {"code": "def f(x broken syntax"},
            {"code": "def f(x):\n    return -x\n"},
        ]
        _write_test_cache(func_source, mutations, tmp_path, func_name="f")

        node = _make_func_node(func_source)
        with pytest.warns(UserWarning, match="invalid syntax"):
            results = list(operator_llm(node))
        assert len(results) == 1

    def test_wrong_function_name_skipped(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        func_source = "def f(x):\n    return x\n"
        mutations = [{"code": "def g(x):\n    return -x\n"}]
        _write_test_cache(func_source, mutations, tmp_path, func_name="f")

        node = _make_func_node(func_source)
        with pytest.warns(UserWarning, match="doesn't contain expected"):
            results = list(operator_llm(node))
        assert results == []

    def test_source_hash_based_lookup(self, tmp_path, monkeypatch):
        """Cache lookup uses source_hash, not function name — avoids bare vs qualified name mismatch."""
        monkeypatch.chdir(tmp_path)

        func_source = "def bar(self):\n    return 1\n"
        mutated = "def bar(self):\n    return 2\n"

        # Cache stores qualified name "Foo.bar" (as scope.py would produce)
        entry = CacheEntry(
            function_name="Foo.bar",
            file_path="test.py",
            source_hash=source_hash(func_source),
            mutations=[CachedMutation(mutated_code=mutated, description="")],
            model="test",
        )
        write_cache_entry(entry, base_dir=tmp_path)

        # Operator sees bare name "bar" (from CST node)
        node = _make_func_node(func_source)
        assert node.name.value == "bar"

        results = list(operator_llm(node))
        assert len(results) == 1

    def test_cache_index_is_lazy(self, tmp_path, monkeypatch):
        """Index is built once and reused across calls."""
        monkeypatch.chdir(tmp_path)

        func_source = "def f():\n    return 1\n"
        _write_test_cache(
            func_source, [{"code": "def f():\n    return 2\n"}], tmp_path, func_name="f"
        )

        node = _make_func_node(func_source)
        # First call builds index
        r1 = list(operator_llm(node))
        # Write a new cache entry after index was built
        func2 = "def g():\n    return 1\n"
        _write_test_cache(
            func2, [{"code": "def g():\n    return 2\n"}], tmp_path, func_name="g"
        )

        # Second call still uses old index (won't find g)
        node2 = _make_func_node(func2)
        r2 = list(operator_llm(node2))
        assert len(r1) == 1
        assert len(r2) == 0  # not found because index was cached


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
