# plugmut

UV workspace extending [mutmut](https://github.com/boxed/mutmut) with additional mutation operators via its pluggy hook system. The `mutmut/` submodule is a fork of upstream mutmut, published as `plugmut` on PyPI. Plugins live in this repo.

## Structure

- `mutmut/` — Git submodule ([mackenney/mutmut](https://github.com/mackenney/mutmut) fork). Published as `plugmut`. Patched sparingly; every patch has a conflict-resolution guide.
- `plugmut-extras/` — Plugin package (`plugmut-extras`) with 19 additional mutation operators.
- `plugmut-llm/` — Plugin package (`plugmut-llm`) for LLM-powered mutation generation (Claude by default; additional backends can be added).
- `plugmut-dedup/` — Plugin package (`plugmut-dedup`) for structural and bytecode deduplication.
- `conflict-resolution/` — Guides for resolving conflicts when syncing upstream changes.

## Setup

```bash
git clone --recurse-submodules https://github.com/mackenney/plugmut
uv sync
```

Or via `just`:

```bash
just sync
```

## Development

```bash
just test         # run all tests
just check        # lint + format-check (matches upstream ruff config)
just fix          # ruff check --fix + format in-place
```

Direct `uv` commands:

```bash
uv run --package plugmut pytest mutmut/tests/         # core tests
uv run --package plugmut-extras pytest                 # extras unit tests
uv run --package plugmut-llm pytest                    # llm unit tests
uv run --package plugmut-dedup pytest                  # dedup unit tests
uv run --package plugmut pytest mutmut/tests/e2e/     # e2e tests
```

## Adding an operator

1. Create `plugmut-extras/src/mutmut_extras/operators/your_operator.py`
2. Export an `operators` list of `(cst_node_type, callable)` tuples
3. Import and spread into the list in `plugmut-extras/src/mutmut_extras/plugin.py`
4. Add unit tests and update the e2e project if needed
