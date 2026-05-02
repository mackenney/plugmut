# Additional Hookspecs

## Context

The mutmut plugin system currently exposes a single hookspec:

```python
# mutmut/src/mutmut/hookspecs.py
@hookspec
def mutmut_register_operators():
    """Return a list of (node_type, operator_function) tuples."""
```

The reference implementation had 10 hooks covering the full mutation lifecycle. Several are directly valuable for real plugin use cases that emerged during `mutmut-extras` development.

## Why It Matters

- **Filtering**: No way to post-process mutations (deduplicate, remove security-sensitive mutants, detect equivalent mutants) without modifying mutmut core.
- **Test lifecycle**: No hook for reacting to test results — plugins can't track per-mutant timing, store results externally, or trigger alerts.
- **CLI extensibility**: No way to add commands like `mutmut generate` (for LLM cache pre-population) or `mutmut report` (custom output formats).
- **Node-level control**: No way for plugins to skip specific nodes without modifying mutmut's skip logic.

## Benefits

- Enables mutation filtering: deduplication, security scanning, equivalent mutant detection.
- Enables custom test result tracking: external storage, timing analysis, custom reporting.
- Enables CLI extension: `mutmut generate`, `mutmut report`, plugin-specific commands.
- Enables fine-grained node skip logic without upstream changes.
- Each hook is independently useful — no all-or-nothing dependency.

## Implementation Recommendation

Add hooks incrementally, each gated on having a concrete consumer (no speculative hooks).

### Priority 1: `mutmut_filter_mutations`

**Hook:**
```python
@hookspec
def mutmut_filter_mutations(filename: str, mutations: list[Mutation]) -> list[Mutation]:
    """Filter or transform mutations after generation. Return filtered list."""
```

**Integration point:** After `MutationVisitor` produces mutations in `create_mutations()` (file_mutation.py), call `pm.hook.mutmut_filter_mutations(filename=filename, mutations=mutations)` and use the result.

**Use cases:**
- Deduplication: Remove mutations that produce identical diffs.
- Security: Strip mutations in authentication/authorization code paths.
- Equivalent mutant detection: Remove mutations that provably don't change behavior (e.g., `x + 0`, `x * 1`).

### Priority 2: `mutmut_post_test`

**Hook:**
```python
@hookspec
def mutmut_post_test(mutant_name: str, exit_code: int, status: str, duration: float):
    """Called after each mutant's test run completes."""
```

**Integration point:** After `_run()` in `__main__.py` processes each mutant's test result, invoke this hook.

**Use cases:**
- Custom reporting: Write results to database, JSON, or external service.
- Timing analysis: Track slow-to-kill mutants, identify test suite bottlenecks.
- Alerting: Notify on surviving mutants in critical code paths.

### Priority 3: `mutmut_register_commands`

**Hook:**
```python
@hookspec
def mutmut_register_commands(cli_group):
    """Register additional Click commands on the mutmut CLI group."""
```

**Integration point:** In `__main__.py` where the Click CLI group is defined, call this hook passing the group.

**Use cases:**
- `mutmut generate` — pre-populate LLM mutation cache.
- `mutmut report` — custom output formats (HTML, JSON, CI annotations).
- `mutmut operators` — list registered operators and their sources.

### Priority 4: `mutmut_skip_node`

**Hook:**
```python
@hookspec(firstresult=True)
def mutmut_skip_node(node: cst.CSTNode, context: Context) -> bool:
    """Return True to skip mutation of this node. First True wins."""
```

**Integration point:** In `MutationVisitor._create_mutations()`, before generating mutations for a node, check `pm.hook.mutmut_skip_node(node=node, context=context)`.

**Use cases:**
- Skip logging code, debug assertions, type-checking blocks.
- Skip based on comments/pragmas (e.g., `# mutmut: skip`).
- Skip based on complexity thresholds.

### General implementation notes

- Each hookspec goes in `mutmut/src/mutmut/hookspecs.py`.
- Each hook's `firstresult` setting depends on semantics: `filter_mutations` chains (all plugins filter), `skip_node` short-circuits (first True wins).
- Add corresponding `@hookimpl` examples in `mutmut-extras` to validate the interface.
- Document the hook contract (parameters, return type, when it's called) in docstrings.
