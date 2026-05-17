# Changelog

All notable changes to mutmut-llm will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-05-17

### Added
- Initial release with LLM-powered mutation generation
- Anthropic Claude integration with prompt caching (5-minute and 1-hour TTL options)
- Async generation with configurable concurrency (`min_concurrency`, `max_concurrency`)
- Exponential backoff retry with jitter for transient API errors
- Error classification: RETRY, SKIP, and STOP actions for different failure modes
- Persistent JSON cache under `.mutmut-cache/llm/` with source-hash-based invalidation
- Two-phase design: explicit `generate` phase writes cache; operator phase reads it without API calls
- Per-model cache entries — multiple models coexist for the same function
- Three-stage validation pipeline for generated mutations: syntax, import guard, pragma guard
- `generate` CLI command to invoke LLM generation with budget control and dry-run support
- `llm-status` CLI command to report cache contents and cumulative cost
- Configuration via `[tool.mutmut.llm]` section in `pyproject.toml`
- Plugin integration via `mutmut_configure`, `mutmut_register_operators`, `mutmut_mutations_created`, `mutmut_post_test`, and `mutmut_post_run` hooks
- Per-run result storage under `.mutmut-cache/llm/runs/` with cost and token totals
- POSIX write-safety via advisory file locking to prevent partial cache writes
- SIGINT cancellation: first interrupt sets cancel event; second interrupt forces immediate exit
