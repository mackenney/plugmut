# plugmut

> **⚠️ Experimental — not ready for production use.**
> This repo is a personal research project. APIs, hook contracts, and package names may change
> without notice. Do not depend on any published package from this repo in production code.

A close fork of [mutmut](https://github.com/boxed/mutmut) extended with a [pluggy](https://pluggy.readthedocs.io/) hook system. The rationale: mutmut's mutation engine is solid and battle-tested, but its operator set and pipeline are fixed. By adding pluggy hooks at the right lifecycle points — operator registration, mutation filtering, post-test reporting — the core can stay close to upstream while plugins add operators, deduplication, LLM-based generation, and custom reporting without touching the fork.

## Structure

- `mutmut/` — Git submodule ([mackenney/mutmut](https://github.com/mackenney/mutmut) fork). Published as `plugmut`. Patched sparingly; every patch has a conflict-resolution guide.
- `plugmut-extras/` — Plugin package with 19 additional mutation operators.
- `plugmut-llm/` — Plugin package for LLM-powered mutation generation (Claude by default).
- `plugmut-dedup/` — Plugin package for structural and bytecode deduplication.
- `conflict-resolution/` — Guides for resolving conflicts when syncing upstream changes.

## Setup

```bash
git clone --recurse-submodules https://github.com/mackenney/plugmut
just sync
```

## Development

```bash
just test         # run all tests
just check        # lint + format-check
just fix          # ruff check --fix + format in-place
```

## Adding an operator

1. Create `plugmut-extras/src/mutmut_extras/operators/your_operator.py`
2. Export an `operators` list of `(cst_node_type, callable)` tuples
3. Import and spread into the list in `plugmut-extras/src/mutmut_extras/plugin.py`
4. Add unit tests and update the e2e project if needed
