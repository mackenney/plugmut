"""Tests for mutmut_llm.scope."""

from __future__ import annotations


import pytest

from mutmut_llm.scope import (
    ScopeResult,
    ScopeTarget,
    _allocate_budget,
    _branch_count,
    _discover_python_files,
    _extract_functions,
    compute_mutation_budget,
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


SIMPLE_FUNC = "def f(x):\n    return x + 1\n"

MEDIUM_FUNC = """\
def process(data):
    result = []
    for item in data:
        if item > 0:
            result.append(item * 2)
        elif item == 0:
            result.append(0)
        else:
            result.append(-item)
    return result
"""

COMPLEX_FUNC = """\
def transform(records, config):
    output = []
    seen = set()
    for record in records:
        if record.id in seen:
            continue
        seen.add(record.id)
        if config.validate:
            try:
                record.validate()
            except ValidationError:
                if config.strict:
                    raise
                continue
        if record.type == "A":
            output.append(handle_a(record))
        elif record.type == "B":
            output.append(handle_b(record))
        else:
            output.append(handle_default(record))
        if config.limit and len(output) >= config.limit:
            break
    for hook in config.post_hooks:
        output = hook(output)
    if config.sort:
        output.sort(key=lambda r: r.priority)
    return output
"""


class TestBranchCount:
    def test_no_branches(self):
        assert _branch_count("x = 1\ny = 2\n") == 0

    def test_single_if(self):
        assert _branch_count("if x:\n    pass\n") == 1

    def test_if_elif_else(self):
        # AST: `elif` is a nested ast.If in orelse; `else` is orelse list, not a node.
        # So if/elif/else = 2 ast.If nodes, not 3.
        assert (
            _branch_count("if x:\n    pass\nelif y:\n    pass\nelse:\n    pass\n") == 2
        )

    def test_keywords_in_strings_not_counted(self):
        # Regression: regex-based counting incorrectly counted 'if' inside strings.
        assert _branch_count('def f():\n    msg = "if you need help"\n    return msg\n') == 0

    def test_for_and_while(self):
        assert _branch_count("for x in y:\n    while z:\n        pass\n") == 2

    def test_try_except_with(self):
        assert (
            _branch_count("try:\n    with open(f):\n        pass\nexcept:\n    pass\n")
            == 3
        )

    def test_complex_function(self):
        count = _branch_count(COMPLEX_FUNC)
        assert count >= 10


class TestComputeMutationBudget:
    def test_empty_source_returns_min(self):
        assert compute_mutation_budget("") == 2

    def test_one_liner_returns_min(self):
        assert compute_mutation_budget(SIMPLE_FUNC) == 2

    def test_medium_function(self):
        budget = compute_mutation_budget(MEDIUM_FUNC)
        assert 3 <= budget <= 5

    def test_complex_function_gets_high_budget(self):
        budget = compute_mutation_budget(COMPLEX_FUNC)
        assert budget >= 7

    def test_min_budget_respected(self):
        assert compute_mutation_budget("", min_budget=4) == 4

    def test_max_budget_respected(self):
        assert compute_mutation_budget(COMPLEX_FUNC, max_budget=5) == 5

    def test_comments_excluded_from_line_count(self):
        source = "def f():\n    # comment 1\n    # comment 2\n    return 1\n"
        budget_with_comments = compute_mutation_budget(source)
        source_no_comments = "def f():\n    return 1\n"
        budget_without = compute_mutation_budget(source_no_comments)
        assert budget_with_comments == budget_without

    def test_blank_lines_excluded(self):
        source = "def f():\n\n\n    return 1\n\n"
        assert compute_mutation_budget(source) == 2

    def test_branches_increase_budget(self):
        no_branches = "def f():\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    e = 5\n    f = 6\n    return a\n"
        with_branches = "def f():\n    if a:\n        b = 1\n    elif c:\n        d = 2\n    else:\n        e = 3\n    return e\n"
        budget_plain = compute_mutation_budget(no_branches)
        budget_branchy = compute_mutation_budget(with_branches)
        assert budget_branchy >= budget_plain


class TestAllocateBudget:
    def test_empty_targets(self):
        assert _allocate_budget([], 10, 5) == {}

    def test_zero_budget(self):
        targets = [ScopeTarget(file_path="f.py", function_name="f", source="")]
        assert _allocate_budget(targets, 0, 5) == {}

    def test_simple_functions_get_min_budget(self):
        targets = [
            ScopeTarget(file_path="f.py", function_name="a", source=SIMPLE_FUNC),
            ScopeTarget(file_path="f.py", function_name="b", source=SIMPLE_FUNC),
        ]
        alloc = _allocate_budget(targets, 20, 10)
        assert alloc["f.py::a"] == 2
        assert alloc["f.py::b"] == 2

    def test_complex_function_gets_more_than_simple(self):
        targets = [
            ScopeTarget(file_path="f.py", function_name="simple", source=SIMPLE_FUNC),
            ScopeTarget(file_path="f.py", function_name="complex", source=COMPLEX_FUNC),
        ]
        alloc = _allocate_budget(targets, 50, 10)
        assert alloc["f.py::complex"] > alloc["f.py::simple"]

    def test_capped_at_max_per_function(self):
        targets = [
            ScopeTarget(file_path="f.py", function_name="a", source=COMPLEX_FUNC)
        ]
        alloc = _allocate_budget(targets, 100, 3)
        assert alloc["f.py::a"] == 3

    def test_budget_less_than_targets(self):
        targets = [
            ScopeTarget(file_path="f.py", function_name="a", source=SIMPLE_FUNC),
            ScopeTarget(file_path="f.py", function_name="b", source=SIMPLE_FUNC),
            ScopeTarget(file_path="f.py", function_name="c", source=SIMPLE_FUNC),
        ]
        alloc = _allocate_budget(targets, 1, 5)
        assert sum(alloc.values()) <= 1

    def test_total_never_exceeds_budget(self):
        targets = [
            ScopeTarget(file_path="f.py", function_name="a", source=SIMPLE_FUNC),
            ScopeTarget(file_path="f.py", function_name="b", source=MEDIUM_FUNC),
            ScopeTarget(file_path="f.py", function_name="c", source=COMPLEX_FUNC),
        ]
        alloc = _allocate_budget(targets, 5, 10)
        assert sum(alloc.values()) <= 5

    def test_file_qualified_keys_no_collision(self):
        targets = [
            ScopeTarget(file_path="a.py", function_name="helper", source=SIMPLE_FUNC),
            ScopeTarget(file_path="b.py", function_name="helper", source=SIMPLE_FUNC),
        ]
        alloc = _allocate_budget(targets, 10, 5)
        assert len(alloc) == 2
        assert "a.py::helper" in alloc
        assert "b.py::helper" in alloc

    def test_min_per_function_parameter(self):
        targets = [ScopeTarget(file_path="f.py", function_name="a", source=SIMPLE_FUNC)]
        alloc = _allocate_budget(targets, 100, 10, min_per_function=5)
        assert alloc["f.py::a"] >= 5

    def test_scaling_preserves_relative_order(self):
        targets = [
            ScopeTarget(file_path="f.py", function_name="simple", source=SIMPLE_FUNC),
            ScopeTarget(file_path="f.py", function_name="complex", source=COMPLEX_FUNC),
        ]
        alloc = _allocate_budget(targets, 5, 10)
        assert alloc["f.py::complex"] >= alloc["f.py::simple"]

    def test_large_budget_no_scaling(self):
        targets = [
            ScopeTarget(file_path="f.py", function_name="a", source=MEDIUM_FUNC),
        ]
        raw = compute_mutation_budget(MEDIUM_FUNC, min_budget=2, max_budget=10)
        alloc = _allocate_budget(targets, 100, 10)
        assert alloc["f.py::a"] == raw


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


class TestSortStability:
    def test_same_file_preserves_order(self):
        """Multiple functions in the same file should maintain original order after sort."""
        targets = [
            ScopeTarget(
                file_path="same.py",
                function_name="z_func",
                source="def z_func(): pass\n",
            ),
            ScopeTarget(
                file_path="same.py",
                function_name="a_func",
                source="def a_func(): pass\n",
            ),
            ScopeTarget(
                file_path="same.py",
                function_name="m_func",
                source="def m_func(): pass\n",
            ),
        ]
        sorted_targets = sorted(targets, key=lambda t: t.file_path)
        assert [t.function_name for t in sorted_targets] == [
            "z_func",
            "a_func",
            "m_func",
        ]

    def test_sort_groups_by_file_for_caching(self):
        """Functions from same file should be grouped together for cache locality."""
        targets = [
            ScopeTarget(
                file_path="b.py", function_name="b1", source="def b1(): pass\n"
            ),
            ScopeTarget(
                file_path="a.py", function_name="a1", source="def a1(): pass\n"
            ),
            ScopeTarget(
                file_path="b.py", function_name="b2", source="def b2(): pass\n"
            ),
            ScopeTarget(
                file_path="a.py", function_name="a2", source="def a2(): pass\n"
            ),
        ]
        sorted_targets = sorted(targets, key=lambda t: t.file_path)
        file_order = [t.file_path for t in sorted_targets]
        assert file_order == ["a.py", "a.py", "b.py", "b.py"]
        a_funcs = [t.function_name for t in sorted_targets if t.file_path == "a.py"]
        assert a_funcs == ["a1", "a2"]
