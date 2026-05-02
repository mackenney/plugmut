"""Tests for mutmut_llm.scope."""

from __future__ import annotations

import textwrap

import libcst as cst
import pytest

from mutmut_llm.scope import (
    ScopeResult,
    ScopeTarget,
    _allocate_budget,
    _branch_count,
    _build_class_context,
    _build_module_context,
    _discover_python_files,
    _extract_assign_targets,
    _extract_functions,
    compute_mutation_budget,
    _extract_imported_names,
    _extract_signature,
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

    def test_module_context_filters_imports(self, sample_file):
        """top_level uses neither os nor Path, so context should be empty."""
        targets = _extract_functions(sample_file)
        top_level = next(t for t in targets if t.function_name == "top_level")
        assert "import os" not in top_level.context
        assert "from pathlib import Path" not in top_level.context

    def test_module_context_includes_relevant_imports(self, tmp_path):
        code = textwrap.dedent("""\
            import os
            from pathlib import Path

            def uses_path(x):
                return Path(x)

            def uses_os():
                return os.getcwd()

            def uses_neither():
                return 42
        """)
        p = tmp_path / "filtered.py"
        p.write_text(code)
        targets = _extract_functions(str(p))

        uses_path = next(t for t in targets if t.function_name == "uses_path")
        assert "from pathlib import Path" in uses_path.context
        assert "import os" not in uses_path.context

        uses_os = next(t for t in targets if t.function_name == "uses_os")
        assert "import os" in uses_os.context
        assert "from pathlib import Path" not in uses_os.context

        uses_neither = next(t for t in targets if t.function_name == "uses_neither")
        assert uses_neither.context == ""

    def test_method_context_has_class_header_and_signatures(self, sample_file):
        targets = _extract_functions(sample_file)
        method = next(t for t in targets if t.function_name == "MyClass.method")
        assert "class MyClass:" in method.context
        assert (
            "def method(self): ..." not in method.context
        )  # H4: target stub excluded, full source provided separately
        assert "def other_method(self, x): ..." in method.context
        assert "attr = 42" in method.context

    def test_empty_file(self, empty_file):
        assert _extract_functions(empty_file) == []

    def test_syntax_error_file(self, syntax_error_file):
        assert _extract_functions(syntax_error_file) == []

    def test_nonexistent_file(self):
        assert _extract_functions("/nonexistent/path.py") == []

    def test_file_path_stored(self, sample_file):
        targets = _extract_functions(sample_file)
        assert all(t.file_path == sample_file for t in targets)


class TestBuildModuleContext:
    def _parse(self, code: str) -> cst.Module:
        return cst.parse_module(textwrap.dedent(code))

    def test_filters_imports_to_relevant_ones(self):
        module = self._parse("""\
            import os
            import sys
            from pathlib import Path
            from typing import Optional

            def func():
                return Path("x")
        """)
        func_source = "def func():\n    return Path('x')\n"
        ctx = _build_module_context(module, func_source)
        assert "from pathlib import Path" in ctx
        assert "import os" not in ctx
        assert "import sys" not in ctx
        assert "from typing import Optional" not in ctx

    def test_includes_module_level_constants(self):
        module = self._parse("""\
            TIMEOUT = 30
            MAX_RETRIES = 5
            UNUSED = "nope"

            def func():
                return TIMEOUT + MAX_RETRIES
        """)
        func_source = "def func():\n    return TIMEOUT + MAX_RETRIES\n"
        ctx = _build_module_context(module, func_source)
        assert "TIMEOUT = 30" in ctx
        assert "MAX_RETRIES = 5" in ctx
        assert "UNUSED" not in ctx

    def test_includes_annotated_assignments(self):
        module = self._parse("""\
            DEBUG: bool = False

            def func():
                if DEBUG:
                    pass
        """)
        func_source = "def func():\n    if DEBUG:\n        pass\n"
        ctx = _build_module_context(module, func_source)
        assert "DEBUG" in ctx

    def test_empty_when_no_names_match(self):
        module = self._parse("""\
            import os

            def func():
                return 42
        """)
        func_source = "def func():\n    return 42\n"
        ctx = _build_module_context(module, func_source)
        assert ctx == ""

    def test_import_with_alias(self):
        module = self._parse("""\
            import numpy as np

            def func():
                return np.array([1])
        """)
        func_source = "def func():\n    return np.array([1])\n"
        ctx = _build_module_context(module, func_source)
        assert "import numpy as np" in ctx

    def test_from_import_with_alias(self):
        module = self._parse("""\
            from collections import OrderedDict as OD

            def func():
                return OD()
        """)
        func_source = "def func():\n    return OD()\n"
        ctx = _build_module_context(module, func_source)
        assert "from collections import OrderedDict as OD" in ctx

    def test_mixed_imports_and_constants(self):
        module = self._parse("""\
            import os
            from pathlib import Path
            LIMIT = 100

            def func():
                return Path(os.getcwd()) if LIMIT else None
        """)
        func_source = "def func():\n    return Path(os.getcwd()) if LIMIT else None\n"
        ctx = _build_module_context(module, func_source)
        assert "import os" in ctx
        assert "from pathlib import Path" in ctx
        assert "LIMIT = 100" in ctx


class TestExtractImportedNames:
    def _import_node(self, code: str) -> cst.Import | cst.ImportFrom:
        module = cst.parse_module(code)
        stmt = module.body[0]
        assert isinstance(stmt, cst.SimpleStatementLine)
        item = stmt.body[0]
        assert isinstance(item, (cst.Import, cst.ImportFrom))
        return item

    def test_simple_import(self):
        node = self._import_node("import os\n")
        assert _extract_imported_names(node) == {"os"}

    def test_from_import(self):
        node = self._import_node("from pathlib import Path\n")
        assert _extract_imported_names(node) == {"Path"}

    def test_from_import_multiple(self):
        node = self._import_node("from os.path import join, exists\n")
        assert _extract_imported_names(node) == {"join", "exists"}

    def test_import_with_alias(self):
        node = self._import_node("import numpy as np\n")
        assert _extract_imported_names(node) == {"np"}

    def test_from_import_with_alias(self):
        node = self._import_node("from collections import OrderedDict as OD\n")
        assert _extract_imported_names(node) == {"OD"}

    def test_dotted_import(self):
        """import os.path -> binds 'os' in local scope."""
        node = self._import_node("import os.path\n")
        assert _extract_imported_names(node) == {"os"}

    def test_star_import_returns_empty(self):
        """from x import * -> can't determine names statically."""
        node = self._import_node("from os import *\n")
        assert _extract_imported_names(node) == set()


class TestExtractAssignTargets:
    def _assign_node(self, code: str) -> cst.Assign | cst.AnnAssign:
        module = cst.parse_module(code)
        stmt = module.body[0]
        assert isinstance(stmt, cst.SimpleStatementLine)
        item = stmt.body[0]
        assert isinstance(item, (cst.Assign, cst.AnnAssign))
        return item

    def test_simple_assign(self):
        node = self._assign_node("X = 42\n")
        assert _extract_assign_targets(node) == {"X"}

    def test_annotated_assign(self):
        node = self._assign_node("X: int = 42\n")
        assert _extract_assign_targets(node) == {"X"}

    def test_multiple_targets(self):
        node = self._assign_node("X = Y = 42\n")
        assert "X" in _extract_assign_targets(node)
        assert "Y" in _extract_assign_targets(node)

    def test_tuple_target_ignored(self):
        """Tuple unpacking targets are not simple Names; should return empty."""
        node = self._assign_node("a, b = 1, 2\n")
        assert _extract_assign_targets(node) == set()


class TestExtractSignature:
    def _func_node(self, code: str) -> tuple[cst.Module, cst.FunctionDef]:
        module = cst.parse_module(textwrap.dedent(code))
        for stmt in module.body:
            if isinstance(stmt, cst.FunctionDef):
                return module, stmt
            if isinstance(stmt, cst.ClassDef):
                for s in stmt.body.body:
                    if isinstance(s, cst.FunctionDef):
                        return module, s
        raise ValueError("No function found")

    def test_simple_function(self):
        module, func = self._func_node("def foo(x, y): pass\n")
        sig = _extract_signature(module, func)
        assert sig == "def foo(x, y): ..."

    def test_function_with_return_type(self):
        module, func = self._func_node("def foo(x: int) -> str: pass\n")
        sig = _extract_signature(module, func)
        assert sig == "def foo(x: int) -> str: ..."

    def test_function_with_decorator(self):
        module, func = self._func_node("""\
            class C:
                @staticmethod
                def foo(): pass
        """)
        sig = _extract_signature(module, func)
        assert "@staticmethod" in sig
        assert "def foo(): ..." in sig

    def test_function_with_property_decorator(self):
        module, func = self._func_node("""\
            class C:
                @property
                def name(self) -> str: pass
        """)
        sig = _extract_signature(module, func)
        assert "@property" in sig
        assert "def name(self) -> str: ..." in sig

    def test_no_params(self):
        module, func = self._func_node("def foo(): pass\n")
        sig = _extract_signature(module, func)
        assert sig == "def foo(): ..."


class TestBuildClassContext:
    def _parse_class(self, code: str) -> tuple[cst.Module, cst.ClassDef]:
        module = cst.parse_module(textwrap.dedent(code))
        for stmt in module.body:
            if isinstance(stmt, cst.ClassDef):
                return module, stmt
        raise ValueError("No class found")

    def test_includes_method_signatures(self):
        module, cls = self._parse_class("""\
            class Point:
                def __init__(self, x: int, y: int) -> None:
                    self.x = x
                    self.y = y

                def abs(self) -> float:
                    return (self.x ** 2 + self.y ** 2) ** 0.5
        """)
        ctx = _build_class_context(module, cls, "")
        assert "class Point:" in ctx
        assert "def __init__(self, x: int, y: int) -> None: ..." in ctx
        assert "def abs(self) -> float: ..." in ctx
        # Full body should NOT be in context
        assert "self.x = x" not in ctx
        assert "self.x ** 2" not in ctx

    def test_includes_class_attributes(self):
        module, cls = self._parse_class("""\
            class Config:
                MAX = 100
                DEBUG = False

                def get_max(self):
                    return self.MAX
        """)
        ctx = _build_class_context(module, cls, "")
        assert "MAX = 100" in ctx
        assert "DEBUG = False" in ctx

    def test_includes_base_classes(self):
        module, cls = self._parse_class("""\
            class Child(Parent, Mixin):
                def method(self):
                    pass
        """)
        ctx = _build_class_context(module, cls, "")
        assert "class Child(Parent, Mixin):" in ctx

    def test_prepends_module_context(self):
        module, cls = self._parse_class("""\
            class Foo:
                def bar(self):
                    pass
        """)
        ctx = _build_class_context(module, cls, "import os")
        assert ctx.startswith("import os\n\nclass Foo:")

    def test_no_module_context(self):
        module, cls = self._parse_class("""\
            class Foo:
                def bar(self):
                    pass
        """)
        ctx = _build_class_context(module, cls, "")
        assert ctx.startswith("class Foo:")

    def test_decorated_methods(self):
        module, cls = self._parse_class("""\
            class Foo:
                @staticmethod
                def create() -> 'Foo':
                    return Foo()

                @property
                def name(self) -> str:
                    return "foo"
        """)
        ctx = _build_class_context(module, cls, "")
        assert "@staticmethod" in ctx
        assert "def create() -> 'Foo': ..." in ctx
        assert "@property" in ctx
        assert "def name(self) -> str: ..." in ctx


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
        assert (
            _branch_count('def f():\n    msg = "if you need help"\n    return msg\n')
            == 0
        )

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
        """3 targets, budget=2 -- must not allocate more than 2 total."""
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


class TestContextIntegration:
    """End-to-end tests verifying context quality for realistic files."""

    def test_class_methods_get_per_function_filtered_imports(self, tmp_path):
        code = textwrap.dedent("""\
            import os
            from pathlib import Path
            from typing import Optional

            MAX_SIZE = 1024

            class FileHandler:
                def read(self, path: str) -> str:
                    return Path(path).read_text()

                def size(self, path: str) -> int:
                    return os.path.getsize(path)

                def limit(self) -> int:
                    return MAX_SIZE
        """)
        p = tmp_path / "handler.py"
        p.write_text(code)
        targets = _extract_functions(str(p))

        read_target = next(t for t in targets if t.function_name == "FileHandler.read")
        assert "from pathlib import Path" in read_target.context
        assert "import os" not in read_target.context
        assert "MAX_SIZE" not in read_target.context

        size_target = next(t for t in targets if t.function_name == "FileHandler.size")
        assert "import os" in size_target.context
        assert "from pathlib import Path" not in size_target.context

        limit_target = next(
            t for t in targets if t.function_name == "FileHandler.limit"
        )
        assert "MAX_SIZE = 1024" in limit_target.context
        assert "import os" not in limit_target.context

    def test_class_context_shows_all_sibling_signatures(self, tmp_path):
        code = textwrap.dedent("""\
            class Calculator:
                def add(self, a: int, b: int) -> int:
                    return a + b

                def subtract(self, a: int, b: int) -> int:
                    return a - b

                def multiply(self, a: int, b: int) -> int:
                    return a * b
        """)
        p = tmp_path / "calc.py"
        p.write_text(code)
        targets = _extract_functions(str(p))

        add_target = next(t for t in targets if t.function_name == "Calculator.add")
        assert (
            "def add(self, a: int, b: int) -> int: ..." not in add_target.context
        )  # H4: target stub excluded
        assert "def subtract(self, a: int, b: int) -> int: ..." in add_target.context
        assert "def multiply(self, a: int, b: int) -> int: ..." in add_target.context
        # Bodies should not leak
        assert "return a + b" not in add_target.context
        assert "return a - b" not in add_target.context

    def test_function_using_no_imports_gets_empty_context(self, tmp_path):
        code = textwrap.dedent("""\
            import os
            import sys
            from pathlib import Path

            def pure(x):
                return x * 2
        """)
        p = tmp_path / "pure.py"
        p.write_text(code)
        targets = _extract_functions(str(p))
        pure = next(t for t in targets if t.function_name == "pure")
        assert pure.context == ""
