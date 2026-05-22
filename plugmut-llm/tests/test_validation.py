"""Tests for mutmut_llm.validation."""

from __future__ import annotations

from mutmut_llm.validation import _extract_imports
from mutmut_llm.validation import _has_pragma
from mutmut_llm.validation import validate_imports
from mutmut_llm.validation import validate_mutation
from mutmut_llm.validation import validate_pragmas
from mutmut_llm.validation import validate_syntax


class TestValidateSyntax:
    def test_valid_function(self):
        assert validate_syntax("def f():\n    return 1") is None

    def test_valid_module(self):
        assert validate_syntax("import os\nx = 1") is None

    def test_invalid_syntax(self):
        result = validate_syntax("def f(\n    broken")
        assert result is not None
        assert "Syntax error" in result

    def test_empty_string(self):
        # Empty string is valid Python (empty module)
        assert validate_syntax("") is None

    def test_single_expression(self):
        assert validate_syntax("42") is None

    def test_incomplete_string(self):
        result = validate_syntax('x = "unterminated')
        assert result is not None


class TestValidateImports:
    ORIGINAL = "import os\nfrom pathlib import Path\n\ndef f():\n    return os.getcwd()"

    def test_same_imports_passes(self):
        mutated = "import os\nfrom pathlib import Path\n\ndef f():\n    return os.path.join('a', 'b')"
        assert validate_imports(mutated, self.ORIGINAL) is None

    def test_fewer_imports_passes(self):
        mutated = "import os\n\ndef f():\n    return os.getcwd()"
        assert validate_imports(mutated, self.ORIGINAL) is None

    def test_new_import_rejected(self):
        mutated = (
            "import os\nimport subprocess\nfrom pathlib import Path\n\ndef f():\n    return subprocess.run(['ls'])"
        )
        result = validate_imports(mutated, self.ORIGINAL)
        assert result is not None
        assert "subprocess" in result

    def test_new_from_import_rejected(self):
        mutated = "import os\nfrom pathlib import Path\nfrom sys import argv\n\ndef f():\n    return argv"
        result = validate_imports(mutated, self.ORIGINAL)
        assert result is not None
        assert "sys" in result

    def test_new_import_inside_function_rejected(self):
        original = "def f():\n    return 1"
        mutated = "def f():\n    import os\n    return os.getcwd()"
        result = validate_imports(mutated, original)
        assert result is not None
        assert "os" in result

    def test_no_imports_in_either(self):
        assert validate_imports("def f(): pass", "def g(): pass") is None

    def test_original_unparseable(self):
        # If original can't parse, original imports = empty set, so any import in mutated is "new"
        result = validate_imports("import os\ndef f(): pass", "def broken(\n")
        assert result is not None
        assert "os" in result

    def test_mutated_unparseable(self):
        # If mutated can't parse, mutated imports = empty set, so no new imports
        assert validate_imports("def broken(\n", self.ORIGINAL) is None


class TestValidateMutation:
    ORIGINAL = "def f(x):\n    return x + 1"

    def test_valid_mutation(self):
        mutated = "def f(x):\n    return x - 1"
        assert validate_mutation(mutated, self.ORIGINAL) is None

    def test_syntax_error_short_circuits(self):
        result = validate_mutation("def f(\n    broken", self.ORIGINAL)
        assert result is not None
        assert "Syntax error" in result

    def test_new_import_caught(self):
        mutated = "import sys\ndef f(x):\n    return sys.maxsize"
        result = validate_mutation(mutated, self.ORIGINAL)
        assert result is not None
        assert "sys" in result

    def test_both_stages_pass(self):
        mutated = "def f(x):\n    if x > 0:\n        return x\n    return -x"
        assert validate_mutation(mutated, self.ORIGINAL) is None

    def test_syntax_error_before_pragma_check(self):
        original = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        mutated = "def f(\n    broken"
        result = validate_mutation(mutated, original)
        assert result is not None, "Syntax check should return a message"
        assert "Syntax error" in result, "Syntax check should run first"

    def test_import_check_before_pragma_check(self):
        original = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        mutated = "import os\ndef f():\n    x = 999  # pragma: no mutate\n    return os.getcwd()"
        result = validate_mutation(mutated, original)
        assert result is not None, "Import check should return a message"
        assert "import" in result.lower(), "Import check should run before pragma check"


class TestExtractImports:
    def test_import_statement(self):
        assert _extract_imports("import os") == {"os"}

    def test_from_import(self):
        assert _extract_imports("from pathlib import Path") == {"pathlib"}

    def test_dotted_import(self):
        assert _extract_imports("import os.path") == {"os.path"}

    def test_dotted_from_import(self):
        assert _extract_imports("from os.path import join") == {"os.path"}

    def test_multiple_imports(self):
        code = "import os\nimport sys\nfrom pathlib import Path"
        assert _extract_imports(code) == {"os", "sys", "pathlib"}

    def test_import_star(self):
        # import star: `from foo import *` — module is "foo"
        assert _extract_imports("from foo import *") == {"foo"}

    def test_no_imports(self):
        assert _extract_imports("x = 1\ny = 2") == set()

    def test_unparseable_code(self):
        assert _extract_imports("def broken(\n") == set()

    def test_import_inside_function_captured(self):
        code = "def f():\n    import os\n    return os.getcwd()"
        assert _extract_imports(code) == {"os"}

    def test_from_import_inside_function_captured(self):
        code = "def f():\n    from subprocess import run\n    return run(['ls'])"
        assert _extract_imports(code) == {"subprocess"}

    def test_import_inside_nested_block_captured(self):
        code = "def f():\n    if True:\n        import sys\n    return sys.argv"
        assert _extract_imports(code) == {"sys"}

    def test_mixed_toplevel_and_nested_imports(self):
        code = "import os\ndef f():\n    import sys\n    return sys.argv"
        assert _extract_imports(code) == {"os", "sys"}

    def test_multiple_names_in_single_import(self):
        assert _extract_imports("import os, sys") == {"os", "sys"}


class TestValidatePragmas:
    ORIGINAL_WITH_PRAGMA = "def f(x):\n    ignored = 0  # pragma: no mutate\n    return x + 1"

    def test_pragma_line_preserved_passes(self):
        mutated = "def f(x):\n    ignored = 0  # pragma: no mutate\n    return x - 1"
        assert validate_pragmas(mutated, self.ORIGINAL_WITH_PRAGMA) is None

    def test_pragma_line_modified_rejected(self):
        mutated = "def f(x):\n    ignored = 999  # pragma: no mutate\n    return x + 1"
        result = validate_pragmas(mutated, self.ORIGINAL_WITH_PRAGMA)
        assert result is not None
        assert "Pragma-marked line modified" in result

    def test_pragma_line_removed_rejected(self):
        mutated = "def f(x):\n    return x + 1"
        result = validate_pragmas(mutated, self.ORIGINAL_WITH_PRAGMA)
        assert result is not None
        assert "Pragma-marked line modified" in result

    def test_no_pragmas_passes(self):
        original = "def f(x):\n    return x + 1"
        mutated = "def f(x):\n    return x - 1"
        assert validate_pragmas(mutated, original) is None

    def test_all_lines_have_pragma(self):
        original = "x = 1  # pragma: no mutate\ny = 2  # pragma: no mutate"
        mutated = "x = 1  # pragma: no mutate\ny = 2  # pragma: no mutate"
        assert validate_pragmas(mutated, original) is None

    def test_mixed_case_pragma_detected(self):
        original = "def f():\n    x = 1  # Pragma: No Mutate\n    return x"
        mutated = "def f():\n    x = 2  # Pragma: No Mutate\n    return x"
        result = validate_pragmas(mutated, original)
        assert result is not None

    def test_extra_spaces_in_pragma_detected(self):
        original = "def f():\n    x = 1  #  pragma:  no mutate\n    return x"
        mutated = "def f():\n    x = 2  #  pragma:  no mutate\n    return x"
        result = validate_pragmas(mutated, original)
        assert result is not None


class TestValidatePragmasPositional:
    """Edge cases where line insertion/deletion shifts pragma positions."""

    def test_mutation_inserts_line_before_pragma(self):
        original = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        mutated = "def f():\n    y = 0\n    x = 1  # pragma: no mutate\n    return x"
        result = validate_pragmas(mutated, original)
        assert result is not None, "Should reject when line inserted before pragma"

    def test_mutation_deletes_line_before_pragma(self):
        original = "def f():\n    y = 0\n    x = 1  # pragma: no mutate\n    return x"
        mutated = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        result = validate_pragmas(mutated, original)
        assert result is not None, "Should reject when line deleted before pragma"

    def test_multiple_pragmas_second_violated(self):
        original = "x = 1  # pragma: no mutate\ny = 2  # pragma: no mutate\nz = 3"
        mutated = "x = 1  # pragma: no mutate\ny = 999  # pragma: no mutate\nz = 3"
        result = validate_pragmas(mutated, original)
        assert result is not None, "Should reject: second pragma line modified"

    def test_pragma_in_multiline_string(self):
        import textwrap

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
        assert result is None, "Should pass: pragma in string data, code changed elsewhere"

    def test_mutated_code_shorter_than_pragma_index(self):
        original = "def f():\n    a = 1\n    b = 2\n    c = 3  # pragma: no mutate\n    return a + b + c"
        mutated = "def f():\n    return 0"
        result = validate_pragmas(mutated, original)
        assert result is not None, "Should reject: pragma line is gone"


class TestValidatePragmasBoundary:
    def test_empty_original(self):
        assert validate_pragmas("def f(): pass", "") is None

    def test_empty_mutated(self):
        original = "x = 1  # pragma: no mutate"
        result = validate_pragmas("", original)
        assert result is not None

    def test_identical_code(self):
        code = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        assert validate_pragmas(code, code) is None

    def test_pragma_on_def_line(self):
        original = "def f():  # pragma: no mutate\n    return 1"
        mutated = "def g():  # pragma: no mutate\n    return 1"
        result = validate_pragmas(mutated, original)
        assert result is not None, "Renaming function with pragma should be rejected"

    def test_windows_line_endings(self):
        original = "def f():\r\n    x = 1  # pragma: no mutate\r\n    return x"
        mutated = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        result = validate_pragmas(mutated, original)
        assert result is None, "Should pass: same content, different line endings"

    def test_tab_vs_spaces_in_pragma_line(self):
        original = "def f():\n\tx = 1  # pragma: no mutate\n\treturn x"
        mutated = "def f():\n    x = 1  # pragma: no mutate\n    return x"
        result = validate_pragmas(mutated, original)
        assert result is not None, "Tab-to-space conversion should be detected as modification"


class TestHasPragma:
    def test_standard_pragma(self):
        assert _has_pragma("    x = 1  # pragma: no mutate") is True

    def test_no_space_after_hash(self):
        assert _has_pragma("    x = 1  #pragma: no mutate") is True

    def test_uppercase(self):
        assert _has_pragma("    x = 1  # PRAGMA: NO MUTATE") is True

    def test_mixed_case(self):
        assert _has_pragma("    x = 1  # Pragma: No Mutate") is True

    def test_extra_spaces(self):
        assert _has_pragma("    x = 1  #  pragma:  no mutate") is True

    def test_no_pragma(self):
        assert _has_pragma("    x = 1") is False

    def test_no_comment(self):
        assert _has_pragma("x = 1") is False

    def test_pragma_with_trailing_text(self):
        assert _has_pragma("x = 1  # pragma: no mutate -- reason") is True
