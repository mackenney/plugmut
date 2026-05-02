# P1: Code Review — Deferred Findings

Deferred items from the P1 code review of mutmut-llm. Split from `__P1-review-findings.md` after all actionable work items were completed.

---

## Deferred items

| ID | Severity | Finding | Why defer |
|----|----------|---------|-----------|
| F2 | **MAJOR** | `mutmut_mutations_created` tail-slicing assumes LLM operator runs last. If another FunctionDef operator registers after LLM, the wrong mutants get tagged. | Works correctly with current operator set. Proper fix requires source-matching (compare mutated code against cache), which is a larger refactor touching the hook interface. Revisit when adding more FunctionDef operators. |
| F7/F8 | **MINOR** | CWD-dependent paths in `list_cache_entries()` and `save_run()` — no `base_dir` / `cache_root` passed. | Mutmut always runs from project root. No user-reported issues. Fix when adding `--project-root` CLI flag. |
| F10 | **MINOR** | `_cache_key` path sanitization: `a/b.py` → `a_b.py__...` collides with `a_b.py` → `a_b.py__...`. | Requires pathological file naming. Not worth the complexity of a different sanitization scheme. |
| F12 | **MINOR** | `_extract_functions` in scope.py only handles one level of class nesting. Nested classes' methods are invisible. | Uncommon Python pattern. Add when a user requests it. |
| F13 | **MINOR** | `parse_llm_response` fallback regex `\[.*]` is greedy — grabs from first `[` to last `]` in entire response. | Last-resort parse path. JSON fast-path and code-block extraction handle >99% of responses. |
| F14 | **MINOR** | Pipeline catches `except Exception` broadly on API calls. | Narrowing risks missing transport-layer errors. Current warning is sufficient. |
| F17 | **MINOR** | `validate_imports` returns empty set on parse failure (asymmetric — original failing = no guard). | Benign — `validate_syntax` runs first, so unparseable code is already rejected. |
| F18 | **MINOR** | No `encoding="utf-8"` on file I/O calls. | Add when Windows support becomes a goal. |

## Dismissed findings (from original review)

- "Prompt injection from malicious docstrings" — Theoretical. Requires attacker-controlled codebase.
- "Cache file path traversal" — `_cache_key` replaces `/` and `\`, traversal not possible.
- "source_hash truncated to 64 bits" — Fine for local file cache, not a security boundary.
- "Thread safety of globals" — mutmut is single-threaded.
- "Anthropic SDK `stop_reason` attribute may change" — Speculative.
- "E2E tests write to source tree" — No E2E tests exist in mutmut-llm yet.
- "`__import__()`, `exec()`, `eval()`, `importlib` bypass" — Deferred to "regex scanner" feature.
