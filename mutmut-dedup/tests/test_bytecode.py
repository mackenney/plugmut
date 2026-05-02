from __future__ import annotations

import sys

import pytest

from mutmut_dedup.bytecode import bytecode_signature, group_by_bytecode, is_equivalent


class TestBytecodeSignatureBasics:
    def test_simple_function_produces_signature(self):
        sig = bytecode_signature("def f(): return 1\n")
        assert sig is not None

    def test_same_source_identical_signature(self):
        source = "def f(): return 1\n"
        assert bytecode_signature(source) == bytecode_signature(source)

    def test_different_source_different_signature(self):
        sig1 = bytecode_signature("def f(): return 1\n")
        sig2 = bytecode_signature("def f(): return 2\n")
        assert sig1 != sig2

    def test_syntax_error_returns_none(self):
        assert bytecode_signature("def f(:\n") is None

    def test_signature_excludes_line_numbers(self):
        sig1 = bytecode_signature("def f(): return 1\n")
        sig2 = bytecode_signature("\ndef f(): return 1\n")
        assert sig1 == sig2

    def test_nested_function_captures_inner(self):
        source = "def f():\n def g(): return 1\n return g\n"
        sig = bytecode_signature(source)
        assert sig is not None
        # Signature must contain a nested tuple for the inner code object.
        # co_consts is element [1]; at least one entry is a recursive tuple (from inner CodeType).
        co_consts = sig[1]
        assert any(isinstance(c, tuple) for c in co_consts)

    def test_lambda_different_bodies_differ(self):
        sig1 = bytecode_signature("f = lambda x: x + 1\n")
        sig2 = bytecode_signature("f = lambda x: x + 2\n")
        assert sig1 != sig2

    def test_empty_function_produces_signature(self):
        sig = bytecode_signature("def f(): pass\n")
        assert sig is not None


class TestCPythonOptimizerBehavior:
    """Empirical tests documenting what CPython's peephole optimizer folds.

    On CPython 3.13+, constant arithmetic (e.g., `2 * 3` → `6`) and bool
    short-circuit (`True and x` → `x`) are folded to identical bytecode
    signatures. On earlier versions these pairs are NOT folded — the optimizer
    emits the same opcodes but retains original literals in co_consts, making
    signatures differ. Each parametrize case carries an `expected` bool
    reflecting the known behavior for the running CPython version.
    """

    @pytest.mark.parametrize(
        "name, original, mutated, expected",
        [
            pytest.param(
                "constant_folding",
                "def f(): return 2 * 3\n",
                "def f(): return 6\n",
                # CPython 3.13+ folds constant arithmetic into identical bytecode.
                True,
                id="constant-folding",
            ),
            pytest.param(
                "bool_short_circuit",
                "def f(x): return True and x\n",
                "def f(x): return x\n",
                # CPython 3.13+ elides the True operand at the bytecode level.
                True,
                id="bool-short-circuit",
            ),
            pytest.param(
                "double_negation",
                "def f(x): return not not x\n",
                "def f(x): return x\n",
                False,
                id="double-negation",
            ),
            pytest.param(
                "identity_add",
                "def f(x): return x + 0\n",
                "def f(x): return x\n",
                False,
                id="identity-add-variable",
            ),
            pytest.param(
                "identity_mul",
                "def f(x): return x * 1\n",
                "def f(x): return x\n",
                False,
                id="identity-mul-variable",
            ),
            pytest.param(
                "dead_branch",
                "def f(x):\n if True:\n  return x\n",
                "def f(x):\n return x\n",
                False,
                id="dead-branch",
            ),
        ],
    )
    def test_optimizer_pair_not_equivalent(
        self, name: str, original: str, mutated: str, expected: bool
    ):
        result = is_equivalent(original, mutated)
        assert result is expected, (
            f"CPython {sys.version_info[:2]} produced is_equivalent={result} for '{name}'; ",
            f"expected {expected}. Update this test if optimizer behavior changed.",
        )


class TestIsEquivalent:
    def test_identical_source_is_equivalent(self):
        source = "x = 42\n"
        assert is_equivalent(source, source) is True

    def test_different_semantics_not_equivalent(self):
        assert is_equivalent("x = 1\n", "x = 2\n") is False

    def test_original_syntax_error_returns_false(self):
        assert is_equivalent("def f(:\n", "x = 1\n") is False

    def test_mutated_syntax_error_returns_false(self):
        assert is_equivalent("x = 1\n", "def f(:\n") is False

    def test_both_syntax_error_returns_false(self):
        assert is_equivalent("def f(:\n", "def g(:\n") is False

    def test_line_number_only_difference_is_equivalent(self):
        # Confirmed: different leading newlines produce identical signatures
        assert is_equivalent("def f(): return 1\n", "\ndef f(): return 1\n") is True


class TestGroupByBytecode:
    def test_all_different_sources(self):
        sources = ["x = 1\n", "x = 2\n", "x = 3\n"]
        groups = group_by_bytecode(sources)
        assert all(len(indices) == 1 for indices in groups.values())
        assert sum(len(v) for v in groups.values()) == 3

    def test_two_identical_sources_grouped(self):
        sources = ["x = 1\n", "x = 1\n"]
        groups = group_by_bytecode(sources)
        assert len(groups) == 1
        assert list(groups.values()) == [[0, 1]]

    def test_syntax_error_excluded(self):
        sources = ["x = 1\n", "def f(:\n"]
        groups = group_by_bytecode(sources)
        assert len(groups) == 1
        assert list(groups.values()) == [[0]]

    def test_mixed_sources(self):
        sources = [
            "x = 1\n",  # 0 - unique
            "x = 1\n",  # 1 - duplicate of 0
            "x = 2\n",  # 2 - unique
            "def f(:\n",  # 3 - syntax error, excluded
        ]
        groups = group_by_bytecode(sources)

        sig_x1 = bytecode_signature("x = 1\n")
        sig_x2 = bytecode_signature("x = 2\n")
        assert sig_x1 is not None
        assert sig_x2 is not None
        assert groups[sig_x1] == [0, 1]
        assert groups[sig_x2] == [2]
        assert len(groups) == 2
