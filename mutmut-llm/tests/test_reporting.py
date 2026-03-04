"""Tests for mutmut_llm.reporting."""

from __future__ import annotations

from mutmut_llm.reporting import (
    format_mutant_name,
    format_run_summary,
    format_run_table,
)
from mutmut_llm.storage import MutantResult, RunResult


def _result(name: str, status: str = "killed", is_llm: bool = False) -> MutantResult:
    return MutantResult(mutant_name=name, status=status, duration=0.5, is_llm=is_llm)


class TestFormatMutantName:
    def test_standard_name(self):
        file_path, function, mutant_id = format_mutant_name(
            "src.mypackage.module.x_func__mutmut_3"
        )
        assert file_path == "src/mypackage/module.py"
        assert function == "func"
        assert mutant_id == "3"

    def test_nested_class_method(self):
        file_path, function, mutant_id = format_mutant_name(
            "src.pkg.mod.x\u01c1MyClass\u01c1method__mutmut_1"
        )
        assert file_path == "src/pkg/mod.py"
        assert function == "MyClass.method"
        assert mutant_id == "1"

    def test_no_mutmut_separator(self):
        file_path, function, mutant_id = format_mutant_name("some.module.x_func")
        assert file_path == "some/module.py"
        assert function == "func"
        assert mutant_id == "?"

    def test_single_part_name(self):
        file_path, function, mutant_id = format_mutant_name("func__mutmut_5")
        assert file_path == "?"
        assert function == "func"
        assert mutant_id == "5"

    def test_class_with_module_prefix(self):
        file_path, function, mutant_id = format_mutant_name(
            "mod.sub.x\u01c1Cls\u01c1do_thing__mutmut_7"
        )
        assert file_path == "mod/sub.py"
        assert function == "Cls.do_thing"
        assert mutant_id == "7"


class TestFormatRunSummary:
    def test_basic_kill_rate(self):
        run = RunResult(
            run_id="r1",
            started_at="2026-01-01T00:00:00+00:00",
            results=[
                _result("a__mutmut_1", "killed"),
                _result("a__mutmut_2", "survived"),
            ],
        )
        summary = format_run_summary(run)
        assert "Total: 2" in summary
        assert "Killed: 1" in summary
        assert "Survived: 1" in summary
        assert "Kill rate: 50.0%" in summary

    def test_all_killed_100_percent(self):
        run = RunResult(
            run_id="r2",
            started_at="2026-01-01T00:00:00+00:00",
            results=[
                _result("a__mutmut_1", "killed"),
                _result("b__mutmut_2", "killed"),
            ],
        )
        assert "Kill rate: 100.0%" in format_run_summary(run)

    def test_empty_results(self):
        run = RunResult(run_id="r3", started_at="2026-01-01T00:00:00+00:00")
        summary = format_run_summary(run)
        assert "Total: 0" in summary
        assert "Kill rate: 0.0%" in summary

    def test_includes_timeout_when_present(self):
        run = RunResult(
            run_id="r4",
            started_at="2026-01-01T00:00:00+00:00",
            results=[_result("a__mutmut_1", "timeout")],
        )
        assert "Timeout: 1" in format_run_summary(run)

    def test_no_timeout_in_summary_when_zero(self):
        run = RunResult(
            run_id="r5",
            started_at="2026-01-01T00:00:00+00:00",
            results=[_result("a__mutmut_1", "killed")],
        )
        assert "Timeout" not in format_run_summary(run)

    def test_llm_builtin_breakdown(self):
        run = RunResult(
            run_id="r6",
            started_at="2026-01-01T00:00:00+00:00",
            results=[
                _result("a__mutmut_1", "killed", is_llm=True),
                _result("b__mutmut_2", "killed", is_llm=True),
                _result("c__mutmut_3", "killed", is_llm=False),
            ],
        )
        summary = format_run_summary(run)
        assert "LLM: 2" in summary
        assert "Builtin: 1" in summary


class TestFormatRunTable:
    def test_empty_results(self):
        run = RunResult(run_id="r1", started_at="2026-01-01T00:00:00+00:00")
        assert format_run_table(run) == "No results."

    def test_header_present(self):
        run = RunResult(
            run_id="r2",
            started_at="2026-01-01T00:00:00+00:00",
            results=[_result("mod.func__mutmut_1", "killed")],
        )
        table = format_run_table(run)
        assert "Status" in table
        assert "Type" in table
        assert "File" in table
        assert "Function" in table
        assert "Mutant" in table

    def test_survived_sorted_first(self):
        run = RunResult(
            run_id="r3",
            started_at="2026-01-01T00:00:00+00:00",
            results=[
                _result("mod.a__mutmut_1", "killed"),
                _result("mod.b__mutmut_2", "survived"),
                _result("mod.c__mutmut_3", "killed"),
            ],
        )
        table = format_run_table(run)
        lines = table.strip().split("\n")
        # Skip header (2 lines), first data line should be survived
        data_lines = [
            l
            for l in lines[2:]
            if l.strip() and not l.startswith("-") and "Total:" not in l
        ]
        assert data_lines[0].startswith("survived")

    def test_table_includes_summary(self):
        run = RunResult(
            run_id="r4",
            started_at="2026-01-01T00:00:00+00:00",
            results=[_result("mod.func__mutmut_1", "killed")],
        )
        table = format_run_table(run)
        assert "Kill rate:" in table

    def test_type_label_llm(self):
        run = RunResult(
            run_id="r5",
            started_at="2026-01-01T00:00:00+00:00",
            results=[_result("mod.func__mutmut_1", "killed", is_llm=True)],
        )
        table = format_run_table(run)
        assert "llm" in table

    def test_type_label_builtin(self):
        run = RunResult(
            run_id="r6",
            started_at="2026-01-01T00:00:00+00:00",
            results=[_result("mod.func__mutmut_1", "killed", is_llm=False)],
        )
        table = format_run_table(run)
        assert "builtin" in table
