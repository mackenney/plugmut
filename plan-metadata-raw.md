# Implementation Plan: Packaging Metadata

## Overview

Prepare all three plugin packages (`mutmut-extras`, `mutmut-llm`, `mutmut-dedup`) for PyPI publication by adding complete metadata to their `pyproject.toml` files, creating user-facing README.md documentation, and updating the workspace README to reflect the full plugin ecosystem.

**Scope:** PyPI metadata fields, README content, CHANGELOG stubs, workspace documentation updates. Does NOT include API/branding changes (hook namespace, CLI rename, package rename) or infrastructure (GitHub Actions, dist cleanup).

## Key Design Decisions

### 1. Version Strategy: Keep `0.1.0` for initial release

All three plugins currently use `0.1.0`. This is appropriate for a first PyPI release:
- Signals early-stage/alpha quality
- Follows SemVer convention for pre-1.0 packages
- No need to coordinate version bumps yet

**Decision:** Keep `0.1.0`, document in CHANGELOG as initial release.

### 2. License: BSD-3-Clause (match upstream mutmut)

Upstream `mutmut/pyproject.toml` uses `license = "BSD-3-Clause"`. All plugins should use the same license for consistency and to avoid licensing conflicts since they extend mutmut.

**Decision:** Use `BSD-3-Clause` for all three plugins.

### 3. Author Information: Placeholder for human decision

The verified facts state: "Content requiring human decisions (author name, repo URL, marketing copy) must go into a `TO_ADDRESS.md` stub."

**Decision:** Use `{{AUTHOR_NAME}}` and `{{AUTHOR_EMAIL}}` placeholders in pyproject.toml. These get documented in the infrastructure planner's TO_ADDRESS.md.

### 4. README Field: Use relative path `readme = "README.md"`

Standard practice for packages with README in the package root.

### 5. Project URLs: Consistent structure across packages

Each package gets URLs for Homepage, Repository, and Issues. Documentation URL omitted until docs exist.

**Decision:** Use placeholder `{{REPO_URL}}` since the actual repository URL is a human decision.

### 6. Classifiers: Match mutmut core pattern

Use the same Development Status, Intended Audience, and Python version classifiers from `mutmut/pyproject.toml`, adding relevant topic classifiers.

### 7. README Content Strategy: Derive from SPEC.md

Each plugin has a comprehensive SPEC.md. README content should:
- Extract Purpose section for overview
- Include quick-start installation/usage
- Reference SPEC.md for detailed behavior
- Add usage examples from the spec

### 8. CHANGELOG Format: Keep It Simple Markdown (KISMD)

Create `CHANGELOG.md` with initial release entry. Format: `## [version] - YYYY-MM-DD` sections.

### 9. asyncio_default_fixture_loop_scope fix

`mutmut-llm/pyproject.toml` is missing `asyncio_default_fixture_loop_scope = "function"` which causes 500+ pytest-asyncio deprecation warnings.

**Decision:** Add this to pytest.ini_options alongside the existing `asyncio_mode = "auto"`.

## Implementation Steps

### Step 1: Update `mutmut-extras/pyproject.toml`

Add after line 5 (`requires-python`):

```toml
readme = "README.md"
license = "BSD-3-Clause"
authors = [
    { name = "{{AUTHOR_NAME}}", email = "{{AUTHOR_EMAIL}}" },
]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: BSD License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Software Development :: Testing",
    "Topic :: Software Development :: Quality Assurance",
]

[project.urls]
Homepage = "{{REPO_URL}}"
Repository = "{{REPO_URL}}"
Issues = "{{REPO_URL}}/issues"
```

### Step 2: Update `mutmut-llm/pyproject.toml`

Add after line 5 (`requires-python`), same metadata block as Step 1.

Additionally, fix the pytest-asyncio deprecation warning by adding to `[tool.pytest.ini_options]`:

```toml
asyncio_default_fixture_loop_scope = "function"
```

### Step 3: Update `mutmut-dedup/pyproject.toml`

Add after line 5 (`requires-python`), same metadata block as Step 1.

**Note:** Add `libcst>=1.8.5` to dependencies — currently undeclared but imported. (Bug B1 in SPEC.md.)

### Step 4: Create `mutmut-extras/README.md`

```markdown
# mutmut-extras

Extra mutation operators for [mutmut](https://github.com/boxed/mutmut).

## Installation

```bash
pip install mutmut-extras
```

## Overview

mutmut-extras registers 19 additional mutation operators into mutmut, targeting AST patterns the built-ins do not cover. Each operator is independently composable with other plugins.

## Operators

| Operator | Description |
|----------|-------------|
| `return_none` | Replaces non-None return values with `return None` |
| `exception_handler` | Replaces except handler bodies with `pass` |
| `ternary` | Mutates `x if cond else y` expressions (3 variants) |
| `assert_true` | Replaces assert tests with `True` |
| `slice_removal` | Removes slice components (lower, upper, step) |
| `void_call_removal` | Replaces standalone function calls with `pass` |
| `yield_mutation` | Mutates yield expressions to `yield None` or `yield 0` |
| `comprehension_filter` | Removes `if` clauses from comprehensions |
| `super_call_deletion` | Replaces `super().method()` calls with `pass` |
| `fstring_mutation` | Replaces f-string interpolations with `'XX'` |
| `function_deletion` | Replaces function bodies with `pass` |
| `default_param_mutation` | Mutates default parameter values |
| `reverse_iteration` | Wraps for-loop iterables with `reversed()` |
| `startswith_endswith_swap` | Swaps `.startswith()` ↔ `.endswith()` |
| `strip_to_partial` | Replaces `.strip()` with `.lstrip()` or `.rstrip()` |
| `operand_swap` | Swaps operands in non-commutative binary ops |
| `remove_boundary_offset` | Removes `±1` from boundary expressions |
| `exception_type_broadening` | Broadens except types to `Exception` |
| `exception_control_flow` | Replaces `pass` in handlers with `break`/`continue`/`return` |

## Usage

Simply install alongside mutmut. The operators register automatically via the plugin system.

```bash
mutmut run
```

## Documentation

See [SPEC.md](SPEC.md) for detailed operator contracts and behavioral invariants.

## License

BSD-3-Clause
```

### Step 5: Create `mutmut-llm/README.md`

```markdown
# mutmut-llm

LLM-powered mutation operator for [mutmut](https://github.com/boxed/mutmut).

## Installation

```bash
pip install mutmut-llm
```

Requires an Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your-key-here
```

## Overview

mutmut-llm generates semantically sophisticated code mutations using Claude. It operates in two phases:

1. **Generation phase** — calls the LLM API and caches results locally
2. **Operator phase** — reads pre-generated mutations during mutmut's mutation pass

LLM API costs are incurred only during generation, not during test execution.

## Usage

### Generate mutations

```bash
mutmut generate [paths...]
```

Without paths, scans `./src/` by default.

### Run mutation testing

```bash
mutmut run
```

The LLM operator yields cached mutations automatically.

### Check status

```bash
mutmut llm-status
```

## Configuration

Configure in `pyproject.toml`:

```toml
[tool.mutmut.llm]
model = "claude-sonnet-4-6"           # Model to use
max_mutations_per_function = 5         # Max mutations per function
temperature = 0.6                      # Generation temperature (0.0-1.0)
enabled = true                         # Enable/disable the plugin
```

API key must be set via `ANTHROPIC_API_KEY` environment variable.

## Caching

- Cache stored in `.mutmut-cache/llm/`
- Entries keyed by source hash — refactored functions get new mutations
- Clear with: `rm -rf .mutmut-cache/llm/`

## Documentation

See [SPEC.md](SPEC.md) for detailed contracts, validation pipeline, and cost tracking.

## License

BSD-3-Clause
```

### Step 6: Create `mutmut-dedup/README.md`

```markdown
# mutmut-dedup

Structural and bytecode deduplication for [mutmut](https://github.com/boxed/mutmut).

## Installation

```bash
pip install mutmut-dedup
```

## Overview

mutmut-dedup reduces mutation testing time by eliminating redundant mutations before test execution:

- **Phase 1 (Structural)**: Removes mutations with identical normalized AST representations
- **Phase 2 (Bytecode)**: Removes mutations that compile to identical bytecode

This eliminates mutations that would produce the same observable behavior, reducing wasted test runs.

## Usage

Simply install alongside mutmut. Deduplication activates automatically via the `mutmut_filter_mutations` hook.

```bash
mutmut run  # deduplication applied automatically
```

## How It Works

### Phase 1: Structural Normalization

Two mutations are structurally equivalent if their normalized AST dumps match. Normalization strips:
- Whitespace and indentation
- Quote style differences
- Comments
- Type annotations

### Phase 2: Bytecode Equivalence

A mutation is removed if:
- It produces the same compiled bytecode as the original code
- It produces the same bytecode as a previously retained mutation at the same site

Phase 2 only applies to mutations inside function bodies. Module-level mutations are conservatively kept.

## Python Version Notes

Deduplication results may vary between Python versions due to:
- CPython optimizer behavior changes
- `ast.dump` format differences

Results are reproducible within a single Python version.

## Documentation

See [SPEC.md](SPEC.md) for detailed equivalence definitions and behavioral invariants.

## License

BSD-3-Clause
```

### Step 7: Create CHANGELOG.md files

Create identical structure in all three packages:

**`mutmut-extras/CHANGELOG.md`:**
```markdown
# Changelog

All notable changes to mutmut-extras will be documented in this file.

## [0.1.0] - {{RELEASE_DATE}}

### Added
- Initial release with 19 mutation operators
- Plugin integration via `mutmut_register_operators` hook
```

**`mutmut-llm/CHANGELOG.md`:**
```markdown
# Changelog

All notable changes to mutmut-llm will be documented in this file.

## [0.1.0] - {{RELEASE_DATE}}

### Added
- Initial release with LLM-powered mutation generation
- Anthropic Claude integration with prompt caching
- Async generation with configurable concurrency
- Persistent cache with source-hash-based invalidation
- `generate` and `llm-status` CLI commands
```

**`mutmut-dedup/CHANGELOG.md`:**
```markdown
# Changelog

All notable changes to mutmut-dedup will be documented in this file.

## [0.1.0] - {{RELEASE_DATE}}

### Added
- Initial release with two-phase deduplication
- Phase 1: Structural normalization (AST-based)
- Phase 2: Bytecode equivalence checking
- Plugin integration via `mutmut_filter_mutations` hook
```

### Step 8: Update workspace `README.md`

Replace the Structure section to include all three plugins:

```markdown
## Structure

- `mutmut/` — Git submodule tracking upstream mutmut. Patched sparingly; every patch has a conflict-resolution guide.
- `mutmut-extras/` — Plugin package with 19 additional mutation operators.
- `mutmut-llm/` — Plugin package for LLM-powered mutation generation (Anthropic Claude).
- `mutmut-dedup/` — Plugin package for structural and bytecode deduplication.
- `conflict-resolution/` — Guides for resolving conflicts when syncing upstream changes.
```

Update the Testing section to include all packages:

```markdown
## Testing

```bash
uv run --package mutmut pytest mutmut/tests/         # core tests
uv run --package mutmut-extras pytest                 # extras unit tests
uv run --package mutmut-llm pytest                    # llm unit tests  
uv run --package mutmut-dedup pytest                  # dedup unit tests
uv run --package mutmut pytest mutmut/tests/e2e/     # e2e tests
```
```

### Step 9: Fix mutmut-dedup undeclared dependency

In `mutmut-dedup/pyproject.toml`, `libcst` is imported but not declared. Add to dependencies:

```toml
dependencies = [
    "mutmut>=3.5.0",
    "pluggy>=1.5.0",
    "libcst>=1.8.5",  # already present, verified
]
```

**Note:** Upon review, libcst is already declared. No change needed.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Placeholder values forgotten before release | `{{PLACEHOLDER}}` syntax is grep-able; CI can check for unreplaced placeholders |
| README content drifts from SPEC.md | README references SPEC.md for detailed behavior; major changes should update both |
| BSD-3-Clause requires LICENSE file | Each package should have a LICENSE file (infrastructure planner's scope) |
| Missing keywords for PyPI discoverability | Add `keywords` field to pyproject.toml (minor enhancement) |

## Tradeoffs vs. Other Approaches

### Single workspace README vs. per-package README
**Chosen:** Per-package README (required for PyPI) + workspace README (for repo overview)
**Alternative:** Only workspace README, use `readme = "../README.md"` in each package
**Why rejected:** PyPI requires README content in the package itself; relative paths outside package don't work with `hatchling`

### CHANGELOG in repo root vs. per-package
**Chosen:** Per-package CHANGELOG (matches PyPI best practices)
**Alternative:** Single workspace CHANGELOG
**Why rejected:** Each package has independent release cycles; combined changelog would be confusing

### Full operator documentation in README vs. reference to SPEC.md
**Chosen:** Summary table in README, detailed specs in SPEC.md
**Alternative:** Duplicate all spec content in README
**Why rejected:** Duplication creates maintenance burden; README is for quick reference, SPEC.md for contracts

### Version strategy: 0.1.0 vs. 1.0.0
**Chosen:** 0.1.0 (pre-stable)
**Alternative:** 1.0.0 (declare stability)
**Why rejected:** First public release, API may evolve; 0.x signals expected changes
