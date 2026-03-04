"""JSON-based storage for mutation run results.

Follows the same .mutmut-cache/llm/ directory as the LLM mutation cache,
with run results stored under a ``runs/`` subdirectory.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from pathlib import Path
from uuid import uuid4


@dataclass
class MutantResult:
    mutant_name: str
    status: str
    duration: float
    is_llm: bool


@dataclass
class RunResult:
    run_id: str
    started_at: str
    completed_at: str | None = None
    results: list[MutantResult] = field(default_factory=list)
    total_llm_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0


def _runs_dir(cache_root: Path | None = None) -> Path:
    root = cache_root or Path(".mutmut-cache/llm")
    return root / "runs"


def save_run(run: RunResult, cache_root: Path | None = None) -> Path:
    """Save a run result to JSON file. Returns the path written."""
    d = _runs_dir(cache_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{run.run_id}.json"
    path.write_text(json.dumps(asdict(run), indent=2))
    return path


def _run_from_dict(data: dict) -> RunResult:
    """Deserialize a RunResult from a dict, tolerating missing cost fields."""
    results = [MutantResult(**r) for r in data.get("results", [])]
    return RunResult(
        run_id=data["run_id"],
        started_at=data["started_at"],
        completed_at=data.get("completed_at"),
        results=results,
        total_llm_cost_usd=data.get("total_llm_cost_usd", 0.0),
        total_input_tokens=data.get("total_input_tokens", 0),
        total_output_tokens=data.get("total_output_tokens", 0),
    )


def load_run(run_id: str, cache_root: Path | None = None) -> RunResult | None:
    """Load a run by ID. Returns None if not found."""
    path = _runs_dir(cache_root) / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return _run_from_dict(data)
    except (json.JSONDecodeError, KeyError):
        return None


def list_runs(cache_root: Path | None = None) -> list[RunResult]:
    """List all runs, sorted by started_at (newest first)."""
    d = _runs_dir(cache_root)
    if not d.exists():
        return []
    runs = []
    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            runs.append(_run_from_dict(data))
        except (json.JSONDecodeError, KeyError):
            continue
    runs.sort(key=lambda r: r.started_at, reverse=True)
    return runs


def load_latest_run(cache_root: Path | None = None) -> RunResult | None:
    """Load the most recent run. Returns None if no runs exist."""
    runs = list_runs(cache_root)
    return runs[0] if runs else None


def new_run() -> RunResult:
    """Create a new RunResult with a fresh ID and current timestamp."""
    return RunResult(
        run_id=uuid4().hex[:12],
        started_at=datetime.now(timezone.utc).isoformat(),
    )
