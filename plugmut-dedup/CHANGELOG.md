# Changelog

All notable changes to mutmut-dedup will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.1] - 2026-05-17

### Added
- Initial release with two-phase mutation deduplication
- Phase 1: Structural normalization — removes mutations with identical AST structure after stripping whitespace, quote style, comments, and type annotations
- Phase 2: Bytecode equivalence checking — removes mutations that compile to identical bytecode as the original function or as another retained mutation at the same site
- First-wins retention: the first occurrence of equivalent mutations is kept; subsequent occurrences are discarded
- Conservative Phase 2 fallback: keeps mutations when equivalence cannot be determined (serialization errors, compile errors, orphaned nodes)
- Plugin integration via `mutmut_filter_mutations` hook, registered to run after all other filter hooks
- CPython-version-aware bytecode signature including `co_exceptiontable` on Python ≥ 3.11
- Module-level mutations pass through Phase 2 unchanged (Phase 1 still applies)
- Annotation stripping in Phase 1 normalization covers function argument annotations, return annotations, annotated assignments, and annotation-only statements
