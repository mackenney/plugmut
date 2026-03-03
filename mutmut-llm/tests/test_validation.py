"""Tests for mutmut_llm.validation."""

from __future__ import annotations

from mutmut_llm.validation import (
    _extract_imports,
    validate_imports,
    validate_mutation,
    validate_syntax,
)


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
        mutated = "import os\nimport subprocess\nfrom pathlib import Path\n\ndef f():\n    return subprocess.run(['ls'])"
        result = validate_imports(mutated, self.ORIGINAL)
        assert result is not None
        assert "subprocess" in result

    def test_new_from_import_rejected(self):
        mutated = "import os\nfrom pathlib import Path\nfrom sys import argv\n\ndef f():\n    return argv"
        result = validate_imports(mutated, self.ORIGINAL)
        assert result is not None
        assert "sys" in result

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

    def test_import_inside_function_not_captured(self):
        # Only top-level imports are captured (SimpleStatementLine at module level)
        code = "def f():\n    import os\n    return os.getcwd()"
        assert _extract_imports(code) == set()

    def test_multiple_names_in_single_import(self):
        assert _extract_imports("import os, sys") == {"os", "sys"}
