# plugmut

UV workspace extending [mutmut](https://github.com/boxed/mutmut) (forked as [mackenney/mutmut](https://github.com/mackenney/mutmut)) with additional mutation operators via its pluggy hook system. The core `mutmut/` submodule is published as `plugmut` on PyPI.
## Structure

- `mutmut/` — Git submodule tracking upstream mutmut. Published as `plugmut`. Patched sparingly; every patch has a conflict-resolution guide.
- `mutmut-extras/` — Plugin package (`plugmut-extras`) with 19 additional mutation operators.
- `mutmut-llm/` — Plugin package (`plugmut-llm`) for LLM-powered mutation generation (Anthropic Claude).
- `mutmut-dedup/` — Plugin package (`plugmut-dedup`) for structural and bytecode deduplication.
- `conflict-resolution/` — Guides for resolving conflicts when syncing upstream changes.

## Setup

```bash
git clone --recurse-submodules https://github.com/mackenney/plugmut
uv sync
```

## Testing

```bash
uv run --package plugmut pytest mutmut/tests/         # core tests
uv run --package plugmut-extras pytest                 # extras unit tests
uv run --package plugmut-llm pytest                    # llm unit tests
uv run --package plugmut-dedup pytest                  # dedup unit tests
uv run --package plugmut pytest mutmut/tests/e2e/     # e2e tests
```

## Adding an operator

1. Create `mutmut-extras/src/mutmut_extras/operators/your_operator.py`
2. Export an `operators` list of `(cst_node_type, callable)` tuples
3. Import and spread into the list in `mutmut-extras/src/mutmut_extras/plugin.py`
4. Add unit tests and update the e2e project if needed
