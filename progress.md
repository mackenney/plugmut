# Progress

## Status
In Progress

## Completed Steps
- step-01: Library class with validation gate
- step-02: GenerationTarget / discovery (prior)
- step-03: Generator protocol in generators/base.py (prior)
- step-04: AnthropicGenerator extracted from pipeline.py (d65f1d1)

## Files Changed (step-04)
- `mutmut-llm/src/mutmut_llm/generators/anthropic.py` — full implementation (ErrorAction, classify_error, TrackedSemaphore, _sigint_handler, _compute_concurrency, _compute_backoff, GenerationResult, _call_llm_and_validate_async, _call_llm_async, AnthropicGenerator)
- `mutmut-llm/src/mutmut_llm/pipeline.py` — re-exports moved symbols; keeps _generate_mutations_async + backward compat functions
- `mutmut-llm/tests/generators/test_anthropic.py` — 13 new tests

## Notes
- 6 pre-existing test failures (test_plugin.py::TestMultiModelIndex and e2e flaky test) not caused by this step
