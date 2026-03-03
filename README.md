# mutmut2

UV workspace extending [mutmut](https://github.com/boxed/mutmut) with additional mutation operators via its pluggy hook system.

## Structure

- `mutmut/` — Git submodule tracking upstream mutmut. Patched sparingly; every patch has a conflict-resolution guide.
- `mutmut-extras/` — Plugin package with additional mutation operators (ternary, return-none, slice-removal, exception-handler, assert-true).
- `conflict-resolution/` — Guides for resolving conflicts when syncing upstream changes.
- `plans/` — Implementation plans for future work.

## Setup

```bash
git clone --recurse-submodules <repo-url>
uv sync
```

## Testing

```bash
uv run --package mutmut pytest mutmut/tests/         # core tests
uv run --package mutmut-extras pytest                 # extras unit tests
uv run --package mutmut-extras pytest mutmut-extras/tests/e2e/  # extras e2e tests
```

## Adding an operator

1. Create `mutmut-extras/src/mutmut_extras/operators/your_operator.py`
2. Export an `operators` list of `(cst_node_type, callable)` tuples
3. Import and spread into the list in `mutmut-extras/src/mutmut_extras/plugin.py`
4. Add unit tests and update the e2e project if needed
