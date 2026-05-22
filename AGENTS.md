# plugmut workspace

UV workspace extending [mutmut](https://github.com/boxed/mutmut) with additional mutation operators. The fork is published as `plugmut`; plugins live here as `plugmut-extras`, `plugmut-llm`, and `plugmut-dedup`.

## Core principles

1. **Minimal changes to `mutmut/`.** The submodule should stay as close to upstream as possible. All new functionality goes in plugin packages (`plugmut-extras/`, future packages). Only patch `mutmut/` when there is no plugin-based alternative.
2. **Extend via plugins, not forks.** Mutmut's pluggy hook system (`mutmut_register_operators`, `mutmut_filter_mutations`, etc.) is the primary extension mechanism. If a hook is missing upstream, prefer proposing it upstream over patching locally.
3. **Every `mutmut/` patch requires a conflict-resolution guide.** No exceptions. Before merging any change to the submodule, create a file in `conflict-resolution/` explaining what changed, why it couldn't be done via plugin, and how to resolve if upstream touches the same code.

## Workspace layout

- `mutmut/` — Git submodule tracking upstream mutmut. Published as `plugmut`. Patch sparingly.
- `plugmut-extras/` — Plugin package providing extra mutation operators (entry point: `mutmut_extras.plugin`).
- `plugmut-llm/` — Plugin package for LLM-powered mutation generation (Claude by default; additional backends can be added).
- `plugmut-dedup/` — Plugin package for structural + bytecode deduplication of mutations.
- `conflict-resolution/` — Guides for resolving conflicts when syncing upstream changes to `mutmut/`.

## Commands

```bash
uv sync                                                  # install all
uv run --package plugmut pytest mutmut/tests/            # core tests
uv run --package plugmut-extras pytest                   # extras tests
uv run --package plugmut-llm pytest                      # llm tests
uv run --package plugmut-dedup pytest                    # dedup tests
uv run --package plugmut pytest mutmut/tests/e2e/        # e2e tests
```

Or use `just` (see Justfile for all targets):

```bash
just sync        # install all
just test        # run all tests
just check       # lint + format-check
just fix         # ruff check --fix + format in-place
```

## Updating mutmut from upstream

1. Pull upstream changes into the `mutmut/` submodule
2. Check `conflict-resolution/` for every file — each describes a local patch that may conflict
3. Run the full test suite to verify
4. Commit the updated submodule pointer

**When adding new patches to `mutmut/`**, always create a corresponding file in `conflict-resolution/` documenting what changed, why, and how to resolve if upstream touches the same code.

## Plugin isolation

Core mutmut tests run with `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD=1` (via `mutmut/tests/conftest.py`) to prevent `plugmut-extras` from injecting mutations into the core test expectations. See `conflict-resolution/plugin-autoload-isolation.md`.

## Planning and progress files

`plans/`, `PROGRESS.md`, `PICK_UP_HERE.md`, and similar agent-generated artifacts are gitignored. These files are fine to create and commit while a feature is in flight, but **must be removed from git before a final merge commit**:

```bash
git rm -r plans/          # if staged
rm -rf plans/             # if untracked
git rm PROGRESS.md PICK_UP_HERE.md 2>/dev/null || true
```

The same applies to spec drafts (`SPEC.md.draft*`, `SPEC.md.critique*`) and `.agent/` tooling directories — create freely during development, clean up before merging.

## Style rules

These apply to `plugmut-extras/`, `plugmut-llm/`, `plugmut-dedup/`, and any other non-submodule code in this workspace.

### Comments

- No "what" comments. Code should be self-documenting through clear naming and structure.
- Comments exist to explain **why** — rationale, constraints, non-obvious trade-offs, or references to external context (issues, specs, upstream behavior).
- Delete comments that restate what the code does. If code needs a "what" comment to be understood, refactor the code instead.

**Bad:**
```python
# Set the timeout to 30
timeout = 30

# Loop through all mutations
for m in mutations:
```

**Good:**
```python
# Upstream uses 30s as the fork child CPU limit (RLIMIT_CPU)
timeout = 30

# Plugins may return empty lists; extend handles both cases
for m in mutations:
```

### General

- Python 3.10+ minimum
- Use `libcst` for AST manipulation (matches upstream)
- Use `pluggy` for plugin hooks
- Keep mutation operators pure: `(node) -> list[node]`, no side effects
- Tests use `pytest`; e2e tests use `inline-snapshot` for result snapshots
- Follow the ruff config from the workspace `pyproject.toml` (mirrors `mutmut/pyproject.toml`: line-length 120, isort force-single-line)
