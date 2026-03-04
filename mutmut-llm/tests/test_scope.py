"""Tests for mutmut_llm.scope."""

from __future__ import annotations


import pytest

from mutmut_llm.scope import (
    ScopeResult,
    ScopeTarget,
    _allocate_budget,
    _discover_python_files,
    _extract_functions,
    resolve_scope_deep,
)


@pytest.fixture
def sample_file(tmp_path):
    """Create a sample Python file with functions."""
    code = """\
import os
from pathlib import Path


def top_level(x):
    return x + 1


def another(y, z):
    return y * z


class MyClass:
    attr = 42

    def method(self):
        return self.attr

    def other_method(self, x):
        return x * 2
"""
    p = tmp_path / "sample.py"
    p.write_text(code)
    return str(p)


@pytest.fixture
def empty_file(tmp_path):
    p = tmp_path / "empty.py"
    p.write_text("")
    return str(p)


@pytest.fixture
def syntax_error_file(tmp_path):
    p = tmp_path / "bad.py"
    p.write_text("def broken(\n")
    return str(p)


class TestExtractFunctions:
    def test_extracts_top_level_functions(self, sample_file):
        targets = _extract_functions(sample_file)
        names = [t.function_name for t in targets]
        assert "top_level" in names
        assert "another" in names

    def test_extracts_class_methods_with_qualified_names(self, sample_file):
        targets = _extract_functions(sample_file)
        names = [t.function_name for t in targets]
        assert "MyClass.method" in names
        assert "MyClass.other_method" in names

    def test_total_function_count(self, sample_file):
        targets = _extract_functions(sample_file)
        assert len(targets) == 4

    def test_source_is_function_code(self, sample_file):
        targets = _extract_functions(sample_file)
        top_level = next(t for t in targets if t.function_name == "top_level")
        assert "def top_level(x):" in top_level.source
        assert "return x + 1" in top_level.source

    def test_module_context_has_imports(self, sample_file):
        targets = _extract_functions(sample_file)
        top_level = next(t for t in targets if t.function_name == "top_level")
        assert "import os" in top_level.context
        assert "from pathlib import Path" in top_level.context

    def test_method_context_has_class_header(self, sample_file):
        targets = _extract_functions(sample_file)
        method = next(t for t in targets if t.function_name == "MyClass.method")
        assert "class MyClass:" in method.context
        assert "import os" in method.context

    def test_empty_file(self, empty_file):
        assert _extract_functions(empty_file) == []

    def test_syntax_error_file(self, syntax_error_file):
        assert _extract_functions(syntax_error_file) == []

    def test_nonexistent_file(self):
        assert _extract_functions("/nonexistent/path.py") == []

    def test_file_path_stored(self, sample_file):
        targets = _extract_functions(sample_file)
        assert all(t.file_path == sample_file for t in targets)


class TestDiscoverPythonFiles:
    def test_single_file(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("x = 1")
        assert _discover_python_files([str(f)]) == [str(f)]

    def test_directory(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1")
        (tmp_path / "b.py").write_text("y = 2")
        (tmp_path / "c.txt").write_text("not python")
        result = _discover_python_files([str(tmp_path)])
        assert len(result) == 2
        assert all(r.endswith(".py") for r in result)

    def test_nested_directory(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "mod.py").write_text("z = 3")
        result = _discover_python_files([str(tmp_path)])
        assert any("mod.py" in r for r in result)

    def test_nonexistent_path(self):
        assert _discover_python_files(["/nonexistent"]) == []

    def test_non_python_file_ignored(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text("{}")
        assert _discover_python_files([str(f)]) == []

    def test_mixed_files_and_dirs(self, tmp_path):
        f = tmp_path / "standalone.py"
        f.write_text("x = 1")
        sub = tmp_path / "pkg"
        sub.mkdir()
        (sub / "mod.py").write_text("y = 2")
        result = _discover_python_files([str(f), str(sub)])
        assert len(result) == 2


class TestAllocateBudget:
    def test_empty_targets(self):
        assert _allocate_budget([], 10, 5) == {}

    def test_zero_budget(self):
        targets = [ScopeTarget(file_path="f.py", function_name="f", source="")]
        assert _allocate_budget(targets, 0, 5) == {}

    def test_uniform_allocation(self):
        targets = [
            ScopeTarget(file_path="f.py", function_name="a", source=""),
            ScopeTarget(file_path="f.py", function_name="b", source=""),
        ]
        alloc = _allocate_budget(targets, 10, 5)
        assert alloc["f.py::a"] == 5
        assert alloc["f.py::b"] == 5

    def test_capped_at_max_per_function(self):
        targets = [ScopeTarget(file_path="f.py", function_name="a", source="")]
        alloc = _allocate_budget(targets, 100, 3)
        assert alloc["f.py::a"] == 3

    def test_budget_less_than_targets(self):
        targets = [
            ScopeTarget(file_path="f.py", function_name="a", source=""),
            ScopeTarget(file_path="f.py", function_name="b", source=""),
            ScopeTarget(file_path="f.py", function_name="c", source=""),
        ]
        alloc = _allocate_budget(targets, 1, 5)
        assert sum(alloc.values()) <= 1

    def test_total_never_exceeds_budget(self):
        """3 targets, budget=2 — must not allocate more than 2 total."""
        targets = [
            ScopeTarget(file_path="f.py", function_name="a", source=""),
            ScopeTarget(file_path="f.py", function_name="b", source=""),
            ScopeTarget(file_path="f.py", function_name="c", source=""),
        ]
        alloc = _allocate_budget(targets, 2, 5)
        assert sum(alloc.values()) <= 2
        assert all(v >= 1 for v in alloc.values())

    def test_file_qualified_keys_no_collision(self):
        """Same function_name in different files must get separate allocations."""
        targets = [
            ScopeTarget(file_path="a.py", function_name="helper", source=""),
            ScopeTarget(file_path="b.py", function_name="helper", source=""),
        ]
        alloc = _allocate_budget(targets, 10, 5)
        assert len(alloc) == 2
        assert "a.py::helper" in alloc
        assert "b.py::helper" in alloc


class TestResolveScopeDeep:
    def test_finds_functions_in_file(self, sample_file):
        result = resolve_scope_deep([sample_file], budget=20)
        assert isinstance(result, ScopeResult)
        assert result.mode == "deep"
        assert len(result.targets) == 4

    def test_empty_paths(self, tmp_path):
        result = resolve_scope_deep([], budget=20)
        assert result.targets == []

    def test_budget_allocation_populated(self, sample_file):
        result = resolve_scope_deep([sample_file], budget=20)
        assert len(result.budget_per_target) == len(result.targets)
        assert all(v > 0 for v in result.budget_per_target.values())

    def test_directory_path(self, tmp_path):
        (tmp_path / "mod.py").write_text("def hello():\n    return 'hi'\n")
        result = resolve_scope_deep([str(tmp_path)], budget=10)
        assert len(result.targets) == 1
        assert result.targets[0].function_name == "hello"
